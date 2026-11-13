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
SOURCES = {  # date -> (transcript json, ecapa cache); 10-06's raw transcript lives with its cache
    "2026-09-01": (W / "Troy School Board Meeting - 2026-09-01.transcript.json", W / "Troy School Board Meeting - 2026-09-01.ecapa.json"),
    "2026-09-22": (W / "Troy School Board Meeting - 2026-09-22.transcript.json", W / "Troy School Board Meeting - 2026-09-22.ecapa.json"),
    "2026-10-06": (REPO / "scratch/split-test/Troy School Board Meeting - 2026-10-06.transcript.json", REPO / "scratch/split-test/Troy School Board Meeting - 2026-10-06.ecapa.json"),
    "2026-10-20": (W / "Troy School Board Meeting - 2026-10-20.transcript.json", W / "Troy School Board Meeting - 2026-10-20.ecapa.json"),
}
SKIP = ("Speaker ", "Unidentified", "Public commenter", "Unknown")


def nv(v):
    v = np.asarray(v, dtype=float)
    return v / np.linalg.norm(v)


def hms(ms):
    ms //= 1000
    return f"{ms // 3600}:{ms % 3600 // 60:02d}:{ms % 60:02d}"


def load(date):
    tj, ej = SOURCES[date]
    U = json.load(open(tj))["utterances"]
    E = json.load(open(ej))["utts"]
    S = json.load(open(REPO / "transcription" / "examples" / date / "speakers.json"))
    who = namer(S["mapping"], S)
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
        lines.append(dict(date=date, st=u["start"], d=(u["end"] - u["start"]) / 1000, gt=n,
                          v=None if v is None else nv(v), text=u["text"]))
    return lines


def centroid(vs):
    m = np.mean(vs, 0)
    return m / np.linalg.norm(m)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--meetings", default=",".join(SOURCES))
    ap.add_argument("--min-ref-lines", type=int, default=4)
    a = ap.parse_args()
    dates = [d for d in a.meetings.split(",") if SOURCES[d][1].exists()]
    data = {d: load(d) for d in dates}
    print("meetings:", ", ".join(f"{d} ({len(data[d])} named lines)" for d in dates))

    grid = [(ab, mg) for ab in (0.40, 0.45, 0.50, 0.55, 0.60, 0.65) for mg in (0.05, 0.08, 0.10, 0.15, 0.20)]
    results = {v: {g: collections.Counter() for g in grid} for v in "AB"}
    confusions = collections.Counter()
    candidates = []
    for M in dates:
        lib = collections.defaultdict(list)
        for O in dates:
            if O == M:
                continue
            for ln in data[O]:
                if ln["v"] is not None and ln["d"] >= 5:
                    lib[ln["gt"]].append(ln["v"])
        REF = {n: centroid(vs) for n, vs in lib.items() if len(vs) >= a.min_ref_lines}
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
                    c = results[variant][(ab, mg)]
                    if inlib:
                        c["lib"] += 1
                        if conf:
                            c["named"] += 1
                            c["right"] += n1 == ln["gt"]
                    else:
                        c["guest"] += 1
                        c["guest_named"] += conf
                if variant == "B" and inlib and n1 != ln["gt"] and s1 >= 0.50 and s1 - s2 >= 0.10:
                    confusions[(ln["gt"], n1)] += 1
                    if ln["d"] >= 3 and s1 >= 0.60 and s1 - s2 >= 0.15:
                        candidates.append((M, hms(ln["st"]), ln["d"], ln["gt"], n1, round(s1, 2), round(s2, 2), ln["text"][:70]))

    for variant in "AB":
        print(f"\nVariant {variant} ({'library only' if variant == 'A' else 'library + 2 seeds per person'})")
        print("  abs  margin   coverage  precision  wrong/100 named  guest lines falsely named")
        for g in grid:
            c = results[variant][g]
            if not c["lib"]:
                continue
            cov = c["named"] / c["lib"]; prec = c["right"] / c["named"] if c["named"] else 0
            gf = c["guest_named"] / c["guest"] if c["guest"] else 0
            print(f"  {g[0]:.2f}  {g[1]:.2f}     {cov:6.1%}    {prec:6.1%}     {100 * (1 - prec):5.1f}            {gf:6.1%} ({c['guest_named']}/{c['guest']})")
    print("\nMost common confident confusions (settled -> voice says), variant B:")
    for (g, n), k in confusions.most_common(12):
        print(f"  {k:3d}  {g} -> {n}")
    print(f"\nCandidate errors in settled transcripts (>=3 s, voice >=0.60, margin >=0.15): {len(candidates)}")
    for c in sorted(candidates):
        print("  ", *c)
    return 0


if __name__ == "__main__":
    sys.exit(main())
