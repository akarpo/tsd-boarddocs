import json, numpy as np
import os
WD=os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../../../scratch/')
n=lambda v: np.asarray(v)/np.linalg.norm(v)
def cents(tpath, epath, spec_map, mind=8000):
    T=json.load(open(tpath))['utterances']; E={int(k):n(v) for k,v in json.load(open(epath))['utts'].items()}
    out={}
    for k,name in spec_map.items():
        vs=[E[u['start']] for u in T if u['speaker']==k and u['end']-u['start']>=mind and u['start'] in E]
        if vs: out[name]=(n(np.mean(vs,0)),len(vs))
    return out
a=cents(WD+'tsd-transcripts/Troy School Board Meeting - 2026-10-06.transcript.json', WD+'split-test/Troy School Board Meeting - 2026-10-06.ecapa.json',
        {'C':'1006 DiPilato','H':'1006 Griffor','D':'1006 Trudel','A':'1006 Anne','G':'1006 Alic','F':'1006 Haupt'})
b=cents(WD+'tsd-transcripts/Troy School Board Meeting - 2026-10-20.transcript.json', WD+'tsd-transcripts/Troy School Board Meeting - 2026-10-20.ecapa.json',
        {'I':'1020 I (elem)','D':'1020 D (mid/high)','N':'1020 Trudel','A':'1020 Anne','J':'1020 Alic','P':'1020 Haupt'})
print('n:',{k:v[1] for k,v in a.items()},{k:v[1] for k,v in b.items()})
print(' '*20+''.join(f'{k:>16}' for k in a))
for kb,(vb,_) in b.items(): print(f'{kb:20}'+''.join(f'{vb@va:16.2f}' for va,_ in a.values()))
