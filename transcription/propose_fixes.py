#!/usr/bin/env python3
"""Propose voice-based attribution fixes for meetings named by the automatic identifier.

Rules (back-tested in backtest_voice.py; the owner's confidence rule, docs/TRANSCRIPTION.md):
  1. REMAP a cluster when >= 60% of its scored lines (>= 8 lines of 4 s+) match one library voice
     that is not its current name, with a median score >= 0.55 (video-checked on 6 remaps,
     2026-11-13: all right; a 0.48 median was not trusted).
  2. A cluster named for a library person (trustee, cabinet) whose lines do not match that person
     (< 15% of scored lines, >= 8 lines) loses the name: "Unidentified speaker". Guest names the
     identifier read off the podium are left alone; nothing in the library can contradict them.
  3. Line level: a line of 3 s+ moves to another library voice only at >= 0.60 with a 0.15 margin.
Library: voices from hand-settled meetings only (transcription/examples/<date>/speakers.json).

    scratch/venv-voice/bin/python transcription/propose_fixes.py [DATE ...] [--write]

Without --write: a summary per meeting. With --write: transcription/examples/<date>/speakers.json
is created from the workdir spec plus the changes (overrides + reassign + a note), ready for
transcribe_meeting.py --transcript-id (offline) and the usual audit / upload / captions.
"""
from __future__ import annotations
import collections, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import backtest_voice as bv  # noqa: E402
from transcribe_meeting import namer  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
U_ = "Unidentified speaker"


def library(SRC):
    lib = collections.defaultdict(list)
    for d in SRC:
        if SRC[d][3] != "settled":
            continue
        for ln in bv.load(d, SRC[d]):
            if ln["v"] is not None and ln["d"] >= 5:
                lib[ln["gt"]].append(ln["v"])
    return {n: bv.centroid(v) for n, v in lib.items() if len(v) >= 6}


def self_medians(SRC):
    """Each library person's own lines scored against a library built without that meeting
    (leave-one-out over settled meetings): the person's typical same-voice score."""
    import numpy as np
    settled = [d for d in SRC if SRC[d][3] == "settled"]
    data = {d: bv.load(d, SRC[d]) for d in settled}
    sc = collections.defaultdict(list)
    for M in settled:
        lib = collections.defaultdict(list)
        for O in settled:
            if O != M:
                for ln in data[O]:
                    if ln["v"] is not None and ln["d"] >= 5:
                        lib[ln["gt"]].append(ln["v"])
        R = {n: bv.centroid(v) for n, v in lib.items() if len(v) >= 6}
        for ln in data[M]:
            if ln["v"] is not None and ln["d"] >= 4 and ln["gt"] in R:
                sc[ln["gt"]].append(float(R[ln["gt"]] @ ln["v"]))
    return {n: float(np.median(v)) for n, v in sc.items() if len(v) >= 8}


# Automatic targets: the board and the cabinet regulars. Anyone else (a guest who spoke at one
# settled meeting) is named only by a manual confirmation with video or content.
TARGETS = {"Vital Anne", "Emina Alic", "Matt Haupt", "Audra Melton", "Ayesha Potts", "Stephanie Zendler",
           "Nancy Philippart", "Richard Machesky", "Dan Trudel", "Christine DiPilato", "Kristine Griffor"}


def propose(M, src, REF, SELF=None):
    SELF = SELF or {}
    unreliable = {n for n, m in SELF.items() if m < 0.50}      # e.g. Potts: her own lines score 0.30
    unreliable |= {n for n in REF if n not in TARGETS}
    tj, ej, sp, q = src
    U = json.load(open(tj))["utterances"]; E = json.load(open(ej))["utts"]; S = json.load(open(sp))
    mp = dict(S.get("mapping", {})); mp.update(S.get("overrides") or {})
    who0 = namer(S.get("mapping", {}), S)
    cur = lambda u: bv.ALIASES.get(who0(u), who0(u))
    score = {}
    for u in U:
        v = E.get(str(u["start"]))
        if v is not None:
            v = bv.nv(v); score[u["start"]] = sorted(((float(REF[k] @ v), k) for k in REF), reverse=True)
    votes = collections.defaultdict(collections.Counter); tops = collections.defaultdict(lambda: collections.defaultdict(list))
    for u in U:
        sc = score.get(u["start"])
        if sc is None or u["end"] - u["start"] < 4000:
            continue
        (s1, k1), (s2, _) = sc[0], sc[1]
        votes[u["speaker"]][k1 if (s1 >= 0.40 and s1 - s2 >= 0.08) else "?"] += 1
        tops[u["speaker"]][k1].append(s1)
    # this meeting's typical same-voice score: median over clusters whose label its voice confirms
    import numpy as np
    ok = []
    for c in votes:
        n = bv.ALIASES.get(mp.get(c, ""), mp.get(c, ""))
        if n in REF and n not in unreliable and tops[c].get(n) and len(tops[c][n]) >= 8:
            m = float(np.median(tops[c][n]))
            if m >= 0.5:
                ok.append(m)
    typ = float(np.median(ok)) if ok else 0.65
    thr = lambda n: max(0.55, min(SELF.get(n, typ), typ) - 0.10)
    overrides, actions, held = {}, [], set()
    for c, vc in votes.items():
        tot = sum(vc.values()); name = bv.ALIASES.get(mp.get(c, f"Speaker {c}"), mp.get(c, f"Speaker {c}"))
        named = {k: x for k, x in vc.items() if k != "?"}
        top, k = max(named.items(), key=lambda x: x[1]) if named else ("?", 0)
        med = sorted(tops[c][top])[len(tops[c][top]) // 2] if tops[c].get(top) else 0
        if tot >= 8 and top != name and k / tot >= 0.60 and top not in unreliable and med >= thr(top):
            overrides[c] = top; actions.append(f"cluster {c}: {name} -> {top} ({k}/{tot} lines, median {med:.2f} >= {thr(top):.2f})")
            continue
        if tot >= 8 and top != name and k / tot >= 0.60 and top != "?":
            # Say which bar it missed: an unusable or non-target reference, or the score itself.
            # (It once printed "median 0.83 < 0.56" for a non-target, which reads as a bug.)
            why = (f"reference unusable (own lines {SELF[top]:.2f})" if top in SELF and SELF[top] < 0.50
                   else "not an automatic target" if top in unreliable
                   else f"median {med:.2f} < {thr(top):.2f}")
            actions.append(f"HELD cluster {c}: {name} -> {top}? ({k}/{tot}, median {med:.2f}; {why})")
            held.add((c, top))
        if tot >= 8 and name in REF and name not in unreliable and vc.get(name, 0) / tot < 0.15:
            overrides[c] = U_; actions.append(f"cluster {c}: {name} -> unidentified (voice matches {vc.get(name, 0)}/{tot}; top {top} {k})")
    S2 = json.loads(json.dumps(S)); S2.setdefault("overrides", {}).update(overrides)
    who1 = namer(S2.get("mapping", {}), S2)
    reassign = {int(ms): r["name"] for r in (S2.get("reassign") or []) for ms in r["start_ms"]}
    moved = 0
    for u in U:
        sc = score.get(u["start"])
        if sc is None or u["end"] - u["start"] < 3000 or u["start"] in reassign:
            continue
        (s1, k1), (s2, _) = sc[0], sc[1]
        now = bv.ALIASES.get(who1(u), who1(u))
        if (k1 != now and k1 not in unreliable and (u["speaker"], k1) not in held
                and s1 >= max(0.60, thr(k1)) and s1 - s2 >= 0.15):
            reassign[u["start"]] = k1; moved += 1
    if moved:
        actions.append(f"{moved} lines moved on voice (>= 0.60, margin 0.15)")
    g = collections.defaultdict(list)
    for ms, n in reassign.items():
        g[n].append(ms)
    S2["reassign"] = [{"name": n, "start_ms": sorted(v)} for n, v in sorted(g.items())]
    # before/after words per name
    who2 = namer(S2.get("mapping", {}), S2)
    before, after = collections.Counter(), collections.Counter()
    for u in U:
        w = len(u["text"].split())
        before[bv.ALIASES.get(who0(u), who0(u))] += w; after[bv.ALIASES.get(who2(u), who2(u))] += w
    return S2, actions, before, after, sum(before.values())


def main() -> int:
    write = "--write" in sys.argv
    SRC = bv.discover(); REF = library(SRC); SELF = self_medians(SRC)
    print("own-voice medians:", {n.split()[-1]: round(m, 2) for n, m in SELF.items()})
    dates = [a for a in sys.argv[1:] if not a.startswith("--")] or [d for d in SRC if SRC[d][3] == "auto"]
    total_changed = 0
    for M in dates:
        S2, actions, before, after, words = propose(M, SRC[M], REF, SELF)
        changed = sum(abs(after[n] - before[n]) for n in set(before) | set(after)) // 2
        total_changed += changed
        real = [x for x in actions if not x.startswith("HELD")]
        print(f"\n{M}: {len(real)} actions, ~{changed} of {words} words change speaker ({changed / max(words, 1):.1%})")
        for a in actions:
            print("   ", a)
        diffs = sorted(((after[n] - before[n], n) for n in set(before) | set(after) if after[n] != before[n]), key=lambda x: x[0])
        if diffs:
            print("    words:", ", ".join(f"{n.split()[-1]} {d:+d}" for d, n in diffs if abs(d) >= 30))
        conf = json.load(open(REPO / "transcription" / "voice_confirmations.json")).get(M, {})
        for c, (n, why) in conf.items():
            S2.setdefault("overrides", {})[c] = n; real.append(f"cluster {c} -> {n} (confirmed: {why})")
        if write and real:
            S2["_quality"] = "voice-pass"
            S2.setdefault("notes", []).append("VOICE-LIBRARY PASS (2026-11-13, transcription/propose_fixes.py): " + "; ".join(real))
            out = REPO / "transcription" / "examples" / M / "speakers.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            json.dump(S2, open(out, "w"), indent=2)
    print(f"\ntotal: ~{total_changed} words change speaker across {len(dates)} meetings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
