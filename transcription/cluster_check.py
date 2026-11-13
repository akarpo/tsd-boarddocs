#!/usr/bin/env python3
"""Per-cluster voice check for meetings whose speaker names came from the automatic identifier.

For each diarized cluster: which reference voice (built only from hand-settled meetings) do its
lines of 4 s or more match? A cluster whose current name disagrees with a clear majority is a
proposed REMAP; a cluster split between voices is MIXED (needs line-level work); one whose lines
match nobody in the library is a GUEST/UNKNOWN. Report only; nothing is written.

    scratch/venv-voice/bin/python transcription/cluster_check.py [DATE ...] [--abs 0.40] [--json OUT]
"""
from __future__ import annotations
import collections, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import backtest_voice as bv  # noqa: E402
from transcribe_meeting import namer  # noqa: E402


def main() -> int:
    argv = sys.argv[1:]
    opt = lambda k, d: (argv[argv.index(k) + 1] if k in argv else d)
    out_json = opt("--json", None); ABS = float(opt("--abs", "0.40"))
    vals = {out_json, opt("--abs", None)}
    args = [a for a in argv if not a.startswith("--") and a not in vals]
    SRC = bv.discover()
    settled = [d for d in SRC if SRC[d][3] == "settled"]
    lib = collections.defaultdict(list)
    for d in settled:
        for ln in bv.load(d, SRC[d]):
            if ln["v"] is not None and ln["d"] >= 5:
                lib[ln["gt"]].append(ln["v"])
    REF = {n: bv.centroid(v) for n, v in lib.items() if len(v) >= 6}
    targets = args or [d for d in SRC if SRC[d][3] == "auto"]
    report = []
    for M in targets:
        tj, ej, sp, q = SRC[M]
        U = json.load(open(tj))["utterances"]; E = json.load(open(ej))["utts"]; S = json.load(open(sp))
        mp = dict(S.get("mapping", {})); mp.update(S.get("overrides") or {})
        votes = collections.defaultdict(collections.Counter); n_lines = collections.Counter()
        for u in U:
            if u["end"] - u["start"] < 4000:
                continue
            v = E.get(str(u["start"]))
            if v is None:
                continue
            v = bv.nv(v); n_lines[u["speaker"]] += 1
            sc = sorted(((float(REF[k] @ v), k) for k in REF), reverse=True)
            (s1, k1), (s2, _) = sc[0], sc[1]
            votes[u["speaker"]][k1 if (s1 >= ABS and s1 - s2 >= 0.08) else "?"] += 1
        print(f"\n{M} ({q})")
        for c in sorted(votes, key=lambda c: -n_lines[c]):
            cur = bv.ALIASES.get(mp.get(c, f"Speaker {c}"), mp.get(c, f"Speaker {c}"))
            vc = votes[c]; tot = sum(vc.values()); named = {k: x for k, x in vc.items() if k != "?"}
            top, k = (max(named.items(), key=lambda x: x[1]) if named else ("?", 0))
            share = k / tot if tot else 0
            if tot < 3:
                verdict = "few"
            elif top == cur and share >= 0.5:
                verdict = "ok"
            elif share >= 0.6 and top != cur:
                verdict = "REMAP" if cur in REF or cur.startswith("Speaker") or True else "REMAP"
            elif len([x for x in named.values() if x >= 3]) >= 2:
                verdict = "MIXED"
            elif not named or share < 0.3:
                verdict = "guest/unknown" if cur not in REF else "UNCONFIRMED"
            else:
                verdict = "weak"
            if cur not in REF and top == "?":
                verdict = "guest" if verdict in ("guest/unknown", "few", "weak") else verdict
            print(f"  {c:3s} {cur[:22]:22s} lines>=4s {tot:3d}  voice: {dict(vc.most_common(3))}  -> {verdict}")
            report.append(dict(date=M, cluster=c, current=cur, lines=tot, votes=dict(vc), top=top, share=round(share, 2), verdict=verdict))
    if out_json:
        json.dump(report, open(out_json, "w"), indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
