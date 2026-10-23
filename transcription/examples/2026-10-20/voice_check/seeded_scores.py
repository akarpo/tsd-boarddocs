import json, sys, numpy as np
import os
WD=os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../../../scratch/tsd-transcripts/')
T=json.load(open(WD+'Troy School Board Meeting - 2026-10-20.transcript.json'))['utterances']
E=json.load(open(WD+'Troy School Board Meeting - 2026-10-20.ecapa.json'))['utts']
n=lambda v: np.asarray(v)/np.linalg.norm(v)
V={int(k):n(v) for k,v in E.items()}
def sec(h):
    p=[int(x) for x in h.split(':')]; return (p[0]*3600+p[1]*60+p[2])*1000
def at(h):
    ms=sec(h); c=[u for u in T if ms<=u['start']<ms+1000]
    assert c, h; return max(c,key=lambda u:u['end']-u['start'])['start']
def hms(ms): s=ms//1000; return f"{s//3600}:{s%3600//60:02d}:{s%60:02d}"
SEEDS={
 'Vital Anne':['0:00:05','0:20:23','1:45:45','0:55:16'],
 'Richard Machesky':['0:01:10','1:44:02','1:45:22'],
 'Lindsay Keegan':['0:02:56','0:09:16','0:11:48'],
 'Audra Melton':['0:14:34','1:36:31'],
 'Stephanie Zendler':['0:17:45','1:32:00'],
 'Emina Alic':['1:15:14','1:42:32','1:12:29'],
 'Ayesha Potts':['1:34:52','1:17:24'],
 'Matt Haupt':['0:29:09','1:41:36','1:20:33'],
 'Dan Trudel':['1:14:03','1:15:48','1:21:11'],
 'I-presenter':['0:31:49','0:37:55'],
 'D-presenter':['0:44:56','0:59:47'],
 'Karpowitsch':['0:26:01'],
 'IAE rep':['1:24:03'],
 'Troy High rep':['1:27:01','1:29:34'],
 'TCCHS 1:25:33':['1:25:33'],
 'kid Nicholas':['0:02:29'], 'kid Audrey':['0:05:28'], 'kid Veeram':['0:08:34'], 'kid Dean':['0:09:32'], 'kid Remy':['0:04:37'],
}
C={k:n(np.mean([V[at(h)] for h in v],0)) for k,v in SEEDS.items()}
seedset={at(h) for v in SEEDS.values() for h in v}
if '--cent' in sys.argv:
    ks=list(C); print(' '*16+' '.join(f'{k[:6]:>6}' for k in ks))
    for a in ks: print(f'{a[:16]:16}'+' '.join(f'{C[a]@C[b]:6.2f}' for b in ks))
    sys.exit()
maxw=int(sys.argv[1]) if len(sys.argv)>1 else 25
for u in T:
    if u['start'] in seedset or len(u['text'].split())>maxw: continue
    v=V.get(u['start'])
    if v is None: print(f"{hms(u['start'])} {u['speaker']} [no emb] {u['text'][:70]}"); continue
    sc=sorted(((v@c,k) for k,c in C.items()),reverse=True)
    print(f"{hms(u['start'])} {u['speaker']} {(u['end']-u['start'])/1000:4.1f}s  {sc[0][1][:14]:14} {sc[0][0]:.2f} | {sc[1][1][:12]:12} {sc[1][0]:.2f}  {u['text'][:60]}")
