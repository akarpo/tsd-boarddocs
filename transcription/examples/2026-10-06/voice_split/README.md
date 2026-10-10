# Splitting cluster B (Zendler + Melton), 2026-10-06

The second meeting in five weeks where the diarizer put Stephanie Zendler and Audra Melton
in one cluster for the whole evening (the first was 2026-09-01, `../../2026-09-01/voice_split/`).
Same method; these scripts take their paths as arguments, which the 09-01 ones did not.

1. Frames first: one still from the middle of each cluster's longest turns
   (`ffmpeg -ss T -i tsd_2026-10-06.mp4 -frames:v 1`), read in subagents in batches of
   about seven. Name plates settled Anne, DiPilato and Melton; the Teams active-speaker
   label settled Alic and Haupt, who attended remotely.
2. `embed.py TRANSCRIPT.json AUDIO_16k.wav embs.json` — speechbrain ECAPA per utterance
   (>=0.8 s) and 4-s windows over B's turns longer than 8 s (~20 min on CPU).
3. `cluster_b.py` — unseeded agglomerative clustering. **It did not separate them**
   (76 of 85 turns in one group): on this room microphone the two voices are close
   enough that only a seeded comparison works.
4. `assign.py embs.json TRANSCRIPT.json` — the seeded split. Within-person cosine
   0.82-0.95, across 0.45-0.69. Two long turns change speaker mid-way (2:13:09 at
   2:15:11; 1:57:10 at 1:57:17). Results are in `../speakers.json`.

Environment: Python 3.9 venv with `speechbrain torch torchaudio soundfile numpy scipy
scikit-learn`; the model downloads from Hugging Face without a token.
