#!/usr/bin/env python3
"""Back-test voice-library attribution against hand-settled meetings (leave one meeting out).

For each settled meeting M, reference voices are built ONLY from the other meetings' settled
specs (lines of 5 s or more, resolved through the shared namer), every line of M is scored
against them, and the classifier's call is compared with M's settled speaker. Two variants:

  A  library only
  B  library blended with 2 seed turns per person from M itself (what camera-confirmed seeds
     give in practice; the seed lines are excluded from scoring)

Reports, per variant and threshold pair: coverage (share of library-person lines named),
precision (share of named lines that are right), and false names on guests (lines by people
not in the library that get confidently named as someone who is). Then lists confident
disagreements with the settled spec: candidate errors in the OLD transcripts, to be reviewed,
never applied blind.

    scratch/venv-voice/bin/python transcription/backtest_voice.py [--meetings 2026-09-01,...]

Needs each meeting's <transcript>.ecapa.json (split_cluster.py, or
transcription/examples/2026-11-10/ for the embed step). See docs/TRANSCRIPTION.md.
"""
from __future__ import annotations
import argparse, collections, json, sys
from pathlib import Path
import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "transcription"))
from transcribe_meeting import namer  # noqa: E402

W = REPO / "scratch" / "tsd-transcripts"
def discover():
    """date -> (transcript json, ecapa cache, spec, quality). quality 'settled' = a hand-checked spec
    in transcription/examples/<date>/; 'auto' = the identifier's mapping plus audit fixes, kept in
    the gitignored workdir. 10-06's raw transcript lives with its cache under scratch/split-test."""
    out = {}
    for tj in sorted(W.glob("Troy School Board Meeting - 20??-??-??.transcript.json")):
        d = tj.name.split(" - ")[-1].split(".")[0]
        ex = REPO / "transcription" / "examples" / d / "speakers.json"
        ws = tj.with_name(tj.name.replace(".transcript.json", ".speakers.json"))
        spec, q = (ex, "settled") if ex.exists() else ((ws, "auto") if ws.exists() else (None, None))
        if q == "settled" and json.load(open(ex)).get("_quality") == "voice-pass":
            spec, q = (ws if ws.exists() else ex), "auto"   # a propose_fixes.py proposal is not ground truth
        cache = tj.with_name(tj.name.replace(".transcript.json", ".ecapa.json"))
        if d == "2026-10-06":
            tj = REPO / "scratch/split-test/Troy School Board Meeting - 2026-10-06.transcript.json"
            cache = tj.with_name("Troy School Board Meeting - 2026-10-06.ecapa.json")
        if spec and cache.exists() and d != "2026-11-10":   # 11-10 is the meeting being worked on
            out[d] = (tj, cache, spec, q)
    return out


ALIASES = {"Dr. Richard Machesky": "Richard Machesky", "Vital Anne (President)": "Vital Anne",
           "Kris Griffor": "Kristine Griffor", "Hillary Colliam": "Hillary Pulliam",
           "Dr. David Recker": "David Recker", "Dr. Recker": "David Recker", "Mr. Butcher": "Thomas Butcher",
           "Mr. Pagel": "John Pagel"}
SKIP = ("Speaker ", "Unidentified", "Public commenter", "Unknown", "Trustee (", "Presenter", "Video",
        "Recognitions", "Student", "Staff ", "Guest", "Teacher presenter", "Curriculum presenter",
        "Technology staff", "Parent advisory", "AARC")


def nv(v):
    v = np.asarray(v, dtype=float)
    return v / np.linalg.norm(v)


def hms(ms):
    ms //= 1000
    return f"{ms // 3600}:{ms % 3600 // 60:02d}:{ms % 60:02d}"


def load(date, src):
    tj, ej, sp, q = src
    U = json.load(open(tj))["utterances"]
    E = json.load(open(ej))["utts"]
    S = json.load(open(sp))
    who0 = namer(S.get("mapping", {}), S)
    who = lambda u: ALIASES.get(who0(u), who0(u))
    cut = set()
    for x in S.get("utterance_splits") or []:
        cut |= {int(x["start_ms"]), int(x["at_ms"])}
    lines = []
    for u in U:
        if u["start"] in cut:
            continue
        n = who(u)
        if n.startswith(SKIP):
            continue
        v = E.get(str(u["start"]))
        lines.append(dict(date=date, q=q, st=u["start"], d=(u["end"] - u["start"]) / 1000, gt=n,
                          v=None if v is None else nv(v), text=u["text"]))
    return lines


def centroid(vs):
    m = np.mean(vs, 0)
    return m / np.linalg.norm(m)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--meetings", help="comma-separated dates (default: every meeting with voiceprints)")
    ap.add_argument("--min-ref-lines", type=int, default=4)
    ap.add_argument("--candidates", help="write confident disagreements here as JSON")
    a = ap.parse_args()
    SRC = discover()
    dates = [d for d in (a.meetings.split(",") if a.meetings else SRC) if d in SRC]
    data = {d: load(d, SRC[d]) for d in dates}
    print(f"meetings: {len(dates)} ({sum(SRC[d][3] == 'settled' for d in dates)} settled), "
          f"{sum(len(v) for v in data.values())} named lines")

    grid = [(ab, mg) for ab in (0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70) for mg in (0.05, 0.10, 0.15)]
    results = {(v, q): {g: collections.Counter() for g in grid} for v in "AB" for q in ("settled", "auto")}
    # per-meeting centroids per person (>= 3 lines of 5 s), so one meeting's errors stay one vote
    permeet = collections.defaultdict(dict)
    for O in dates:
        byp = collections.defaultdict(list)
        for ln in data[O]:
            if ln["v"] is not None and ln["d"] >= 5:
                byp[ln["gt"]].append(ln["v"])
        for n, vs in byp.items():
            if len(vs) >= 3:
                permeet[n][O] = centroid(vs)
    dropped = collections.Counter()
    confusions = collections.Counter()
    candidates = []
    for M in dates:
        REF = {}
        for n, per in permeet.items():
            cs = {O: c for O, c in per.items() if O != M}
            if len(cs) < 2:
                continue
            keep = []
            for O, c in cs.items():   # drop a meeting whose centroid disagrees with the others'
                rest = centroid([x for P, x in cs.items() if P != O])
                if float(c @ rest) >= 0.45:
                    keep.append(c)
                else:
                    dropped[(n, O)] += 1
            if len(keep) >= 2:
                REF[n] = centroid(keep)
        # variant B seeds: each library person's 2 longest lines in M
        byp = collections.defaultdict(list)
        for ln in data[M]:
            if ln["v"] is not None and ln["gt"] in REF:
                byp[ln["gt"]].append(ln)
        seeds, REFB = set(), dict(REF)
        for n, ls in byp.items():
            top = sorted(ls, key=lambda x: -x["d"])[:2]
            if top and top[0]["d"] >= 5:
                seeds |= {x["st"] for x in top}
                REFB[n] = centroid([REF[n], centroid([x["v"] for x in top])])
        for variant, refs in (("A", REF), ("B", REFB)):
            names = list(refs)
            for ln in data[M]:
                if ln["v"] is None or ln["d"] < 1.5 or (variant == "B" and ln["st"] in seeds):
                    continue
                sc = sorted(((float(refs[n] @ ln["v"]), n) for n in names), reverse=True)
                (s1, n1), (s2, _) = sc[0], sc[1]
                inlib = ln["gt"] in refs
                for (ab, mg) in grid:
                    need_ab, need_mg = (ab, mg) if ln["d"] >= 3 else (ab + 0.05, mg + 0.05)
                    conf = s1 >= need_ab and s1 - s2 >= need_mg
                    c = results[(variant, ln["q"])][(ab, mg)]
                    if inlib:
                        c["lib"] += 1
                        if conf:
                            c["named"] += 1
                            c["right"] += n1 == ln["gt"]
                    else:
                        c["guest"] += 1
                        c["guest_named"] += conf
                if variant == "B" and n1 != ln["gt"] and s1 >= 0.60 and s1 - s2 >= 0.15 and ln["d"] >= 3:
                    confusions[(ln["gt"], n1)] += 1
                    own = next((s for s, n in sc if n == ln["gt"]), None)
                    candidates.append(dict(date=M, q=ln["q"], t=hms(ln["st"]), st=ln["st"], d=ln["d"], gt=ln["gt"],
                                           voice=n1, s1=round(s1, 2), s2=round(s2, 2),
                                           own=None if own is None else round(own, 2), inlib=inlib, text=ln["text"][:90]))

    for variant, q in [(v, q) for v in "AB" for q in ("settled", "auto")]:
        print(f"\nVariant {variant} ({'library only' if variant == 'A' else 'library + 2 seeds per person'}), {q} meetings")
        print("  abs  margin   coverage  precision  wrong/100 named  guest lines falsely named")
        for g in grid:
            c = results[(variant, q)][g]
            if not c["lib"]:
                continue
            cov = c["named"] / c["lib"]; prec = c["right"] / c["named"] if c["named"] else 0
            gf = c["guest_named"] / c["guest"] if c["guest"] else 0
            print(f"  {g[0]:.2f}  {g[1]:.2f}     {cov:6.1%}    {prec:6.1%}     {100 * (1 - prec):5.1f}            {gf:6.1%} ({c['guest_named']}/{c['guest']})")
    print("\nMost common confident confusions (settled -> voice says), variant B:")
    for (g, n), k in confusions.most_common(12):
        print(f"  {k:3d}  {g} -> {n}")
    if dropped:
        print("\nMeeting centroids dropped as outliers (person, meeting):", dict(dropped))
    print(f"\nConfident disagreements (>=3 s, voice >=0.60, margin >=0.15): {len(candidates)} "
          f"({sum(c['q'] == 'settled' for c in candidates)} in settled meetings)")
    for c in sorted(candidates, key=lambda c: (c["date"], c["st"]))[:60]:
        print(f"   {c['date']} {c['t']} {c['d']:5.1f}s {c['gt'][:18]:18s} -> {c['voice'][:18]:18s} {c['s1']} (own {c['own']})  {c['text'][:50]}")
    if a.candidates:
        json.dump(candidates, open(a.candidates, "w"), indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
