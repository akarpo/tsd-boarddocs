"""Seeded two-way split of cluster B (2026-10-06), as run in the session.

    python assign.py embs.json TRANSCRIPT.json

Seeds are turns where the camera is on the speaker (Melton 2:31:08, Zendler 2:45:56) plus
turns tied to them by the chair's hand-off ('Stephanie?' 0:58:44; Melton's follow-up after
'Audra has the answer' 0:51:58 / 0:57:43). Prints, per B turn, cosine to each centroid, a
label when the margin exceeds 0.08, and an M/Z string over the 4-s windows (hop 2 s) of
long turns; a run of one letter followed by a run of the other marks a mid-turn hand-off,
cut at the word boundary via `utterance_splits` in ../speakers.json. Also lists B turns
whose best match is a staff cluster (>=0.6 and >=0.15 above both trustees).
"""
import json, sys, numpy as np
E = json.load(open(sys.argv[1])); T = {u["start"]: u for u in json.load(open(sys.argv[2]))["utterances"]}
n = lambda v: v / np.linalg.norm(v); f = lambda t: "%d:%02d:%02d" % (t // 3600, t % 3600 // 60, t % 60)
h = lambda s: sum(int(x) * m for x, m in zip(s.split(":"), (3600, 60, 1)))
U = [dict(r, v=n(np.array(r["emb"]))) for r in E["utts"]]
B = [r for r in U if r["speaker"] == "B"]; near = lambda t: min(B, key=lambda r: abs(r["start"] / 1000 - t))
cent = {k: n(np.mean([r["v"] for r in U if r["speaker"] == k and r["end"] - r["start"] >= 3000], 0)) for k in "ACDEFGH"}
M = n(np.mean([near(h(t))["v"] for t in ("2:31:08", "0:51:58", "0:57:43")], 0))
Z = n(np.mean([near(h(t))["v"] for t in ("2:45:56", "0:58:44", "0:59:52", "1:56:41")], 0))
for r in sorted(B, key=lambda r: r["start"]):
    m, z = float(r["v"] @ M), float(r["v"] @ Z)
    lab = "MELTON" if m - z > 0.08 else "ZENDLER" if z - m > 0.08 else "??"
    w = [x for x in E["wins"] if x["idx"] == r["idx"]]
    seq = "".join("M" if (n(np.array(x["emb"])) @ M) - (n(np.array(x["emb"])) @ Z) > 0.05 else
                  "Z" if (n(np.array(x["emb"])) @ Z) - (n(np.array(x["emb"])) @ M) > 0.05 else "." for x in w)
    s = {k: float(r["v"] @ c) for k, c in cent.items()}; best = max(s, key=s.get)
    staff = f"  STAFF? {best} {s[best]:.2f}" if s[best] >= 0.6 and s[best] - max(m, z) >= 0.15 else ""
    print(f"{r['start']} {f(r['start']/1000)} {(r['end']-r['start'])/1000:4.0f}s M{m:.2f} Z{z:.2f} {lab:7} {seq}{staff} | {T[r['start']]['text'][:60]}")
