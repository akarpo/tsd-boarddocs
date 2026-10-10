# ECAPA embedding per utterance (>=0.8 s) for every cluster; long turns also get 4-s windows (hop 2 s).
import warnings; warnings.filterwarnings("ignore")
import json, sys, numpy as np, soundfile as sf, torch
from speechbrain.inference.speaker import EncoderClassifier
T, WAV, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
utts = json.load(open(T))["utterances"]
wav, sr = sf.read(WAV, dtype="float32"); assert sr == 16000
enc = EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb", savedir=OUT + ".model", run_opts={"device": "cpu"})
def emb(a, b):
    seg = torch.from_numpy(wav[a:b]).unsqueeze(0)
    with torch.no_grad(): return enc.encode_batch(seg).squeeze().numpy().tolist()
rows, wins = [], []
for i, u in enumerate(utts):
    s, e = int(u["start"] * 16), int(u["end"] * 16)
    if e - s < 12800: continue
    rows.append({"idx": i, "speaker": u["speaker"], "start": u["start"], "end": u["end"], "emb": emb(s, e)})
    if u["speaker"] == "B" and e - s > 8 * 16000:
        for a in range(s, e - 4 * 16000 + 1, 2 * 16000):
            wins.append({"idx": i, "t": a / 16000, "emb": emb(a, a + 4 * 16000)})
    if len(rows) % 100 == 0: print(len(rows), flush=True)
json.dump({"utts": rows, "wins": wins}, open(OUT, "w")); print("done", len(rows), "utts", len(wins), "windows")
