"""Second-pass attribution for 2026-11-10: score every line against one reference voice per
person (prior meetings' settled voices blended with this meeting's camera-confirmed turns), then
classify each line KEEP / MOVE / UNSURE / SHORT under a confidence rule."""
import json, sys, collections, numpy as np
sys.path.insert(0, "/Users/Alex/Downloads/tsd-boarddocs/transcription")
from transcribe_meeting import namer
R = "/Users/Alex/Downloads/tsd-boarddocs/"
W = R + "scratch/tsd-transcripts/Troy School Board Meeting - 2026-11-10"
def nv(v): v = np.array(v, dtype=float); return v / np.linalg.norm(v)
def hms(ms): ms //= 1000; return f"{ms//3600}:{ms%3600//60:02d}:{ms%60:02d}"
def ms(h): a = [int(x) for x in h.split(":")]; return (a[0]*3600 + a[1]*60 + a[2]) * 1000

# ---- prior-meeting references (settled specs) ----
prior = collections.defaultdict(list)
for tj, ej, sj in [(R+"scratch/tsd-transcripts/Troy School Board Meeting - 2026-10-20.transcript.json", R+"scratch/tsd-transcripts/Troy School Board Meeting - 2026-10-20.ecapa.json", R+"transcription/examples/2026-10-20/speakers.json"),
                   (R+"scratch/split-test/Troy School Board Meeting - 2026-10-06.transcript.json", R+"scratch/split-test/Troy School Board Meeting - 2026-10-06.ecapa.json", R+"transcription/examples/2026-10-06/speakers.json")]:
    U = json.load(open(tj))["utterances"]; E = json.load(open(ej))["utts"]; S = json.load(open(sj))
    who = namer(S["mapping"], S); cut = {int(x["start_ms"]) for x in S.get("utterance_splits") or []}
    for u in U:
        if u["end"] - u["start"] < 5000 or u["start"] in cut: continue
        v = E.get(str(u["start"]))
        if v is not None: prior[who(u)].append(nv(v))

# ---- this meeting ----
T = json.load(open(W + ".transcript.json")); U = T["utterances"]
E = json.load(open(W + ".ecapa.json"))["utts"]
S = json.load(open(R + "transcription/examples/2026-11-10/speakers.json"))
who = namer(S["mapping"], S)
byt = collections.defaultdict(list)
for u in U: byt[hms(u["start"])].append(u)
def at(h): return byt[h][0]

# camera/content-confirmed seed turns from this meeting
seeds = {
 "Vital Anne": ["0:38:38", "2:14:11", "2:21:28", "0:00:51"],
 "Emina Alic": ["2:17:30", "2:33:48", "3:09:10", "2:30:25", "1:19:26"],
 "Stephanie Zendler": ["0:43:46", "2:00:50", "1:32:04", "2:51:34", "2:59:48"],
 "Audra Melton": ["0:45:55", "2:50:02"],
 "Christine DiPilato": ["1:57:50"],
 "Dan Trudel": ["0:12:42", "0:27:59"],
 "Richard Machesky": ["1:42:21", "0:41:15", "3:05:57"],
}
# presenters: their own segment, lines >= 5 s
windows = {"Kyle Anderson": ("F", "0:03:00", "0:20:40"), "Keith McDonald": ("E", "0:21:00", "0:51:20"),
           "Sarah Smotherman": ("K", "1:03:00", "2:05:12"), "Jamie Evans": ("B", "1:09:00", "1:44:55"),
           "Hillary Pulliam": ("H", "1:12:00", "1:20:40"), "Erica Conklin": ("L", "1:22:00", "1:46:40"),
           "Christine DiPilato": ("J", "0:00:00", "3:14:00"), "Dan Trudel": ("C", "0:00:00", "3:14:00")}
cur = collections.defaultdict(list)
for n, hs in seeds.items():
    for h in hs:
        v = E.get(str(at(h)["start"]))
        if v is not None: cur[n].append(nv(v))
for n, (c, a, b) in windows.items():
    for u in U:
        if u["speaker"] == c and ms(a) <= u["start"] <= ms(b) and u["end"] - u["start"] >= 8000:
            v = E.get(str(u["start"]))
            if v is not None: cur[n].append(nv(v))
REF = {}
for n in set(cur) | {"Matt Haupt"}:
    parts = []
    if cur.get(n): m = np.mean(cur[n], 0); parts.append(m / np.linalg.norm(m))
    if prior.get(n) and len(prior[n]) >= 4: m = np.mean(prior[n], 0); parts.append(m / np.linalg.norm(m))
    if parts: m = np.mean(parts, 0); REF[n] = m / np.linalg.norm(m)
names = sorted(REF)

rows = []
for u in U:
    d = (u["end"] - u["start"]) / 1000; lab = who(u); v = E.get(str(u["start"]))
    if v is None or d < 1.5:
        rows.append(dict(t=hms(u["start"]), st=u["start"], cl=u["speaker"], lab=lab, d=d, cls="SHORT", best=None, s1=None, s2=None, n2=None, text=u["text"])); continue
    v = nv(v); sc = sorted(((float(REF[n] @ v), n) for n in names), reverse=True)
    (s1, n1), (s2, n2) = sc[0], sc[1]
    own = next((s for s, n in sc if n == lab), None)
    need_abs, need_m = (0.50, 0.10) if d >= 3 else (0.55, 0.15)
    if n1 == lab: cls = "KEEP" if (s1 >= 0.40 and s1 - s2 >= 0.05) else "UNSURE"
    elif s1 >= need_abs and s1 - (own if own is not None else -1) >= need_m and s1 - s2 >= 0.05: cls = "MOVE"
    else: cls = "UNSURE"
    rows.append(dict(t=hms(u["start"]), st=u["start"], cl=u["speaker"], lab=lab, d=d, cls=cls, best=n1, s1=round(s1, 2), s2=round(s2, 2), n2=n2, own=None if own is None else round(own, 2), text=u["text"]))
json.dump(rows, open("/private/tmp/claude-503/-Users-Alex/453f8a64-a3a6-4fb1-85b7-5aadc1cc098f/scratchpad/reattrib_rows.json", "w"))
c = collections.Counter(r["cls"] for r in rows); print("classes:", dict(c))
w = collections.Counter();
for r in rows: w[r["cls"]] += len(r["text"].split())
print("words by class:", dict(w))
print("refs:", {n: (len(cur.get(n, [])), len(prior.get(n, []))) for n in names})
print("\nby current label (KEEP/MOVE/UNSURE/SHORT):")
bl = collections.defaultdict(collections.Counter)
for r in rows: bl[r["lab"]][r["cls"]] += 1
for k in sorted(bl): print(f"  {k:20s} {dict(bl[k])}")
print("\nMOVE proposals:")
for r in rows:
    if r["cls"] == "MOVE": print(f"  {r['t']} {r['cl']} {r['d']:5.1f}s {r['lab'][:12]:12s} -> {r['best'][:14]:14s} {r['s1']:.2f} (own {r['own']}, 2nd {r['n2'].split()[-1]} {r['s2']:.2f})  {r['text'][:60]}")
