import json, sys, numpy as np
from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics import silhouette_score
E = json.load(open(sys.argv[1])); T = json.load(open(sys.argv[2]))["utterances"]
f = lambda t: "%d:%02d:%02d" % (t // 3600, t % 3600 // 60, t % 60)
U = E["utts"]; n = lambda v: v / np.linalg.norm(v)
X = {r["idx"]: n(np.array(r["emb"])) for r in U}
# centroids of the other clusters from their turns >= 3 s
cent = {}
for k in "ACDEFGH":
    vs = [X[r["idx"]] for r in U if r["speaker"] == k and r["end"] - r["start"] >= 3000]
    if vs: cent[k] = n(np.mean(vs, 0))
B = [r for r in U if r["speaker"] == "B" and r["end"] - r["start"] >= 2000]
M = np.array([X[r["idx"]] for r in B])
for k in (2, 3, 4, 5):
    lab = AgglomerativeClustering(n_clusters=k, metric="cosine", linkage="average").fit_predict(M)
    print(k, "silhouette %.3f" % silhouette_score(M, lab, metric="cosine"), np.bincount(lab))
k = int(sys.argv[3]) if len(sys.argv) > 3 else 4
lab = AgglomerativeClustering(n_clusters=k, metric="cosine", linkage="average").fit_predict(M)
sub = {c: n(M[lab == c].mean(0)) for c in set(lab)}
for c in sorted(sub): print("sub", c, "vs sinks", {s: round(float(sub[c] @ v), 2) for s, v in cent.items()})
for r, c in sorted(zip(B, lab), key=lambda z: z[0]["start"]):
    v = X[r["idx"]]; sink = max(cent, key=lambda s: v @ cent[s])
    print(f"{f(r['start']/1000)} {(r['end']-r['start'])/1000:4.0f}s sub{c}  own {v@sub[c]:.2f}  best-sink {sink} {v@cent[sink]:.2f} | {T[r['idx']]['text'][:70]}")
