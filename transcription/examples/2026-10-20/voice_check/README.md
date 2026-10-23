# 2026-10-20 voice check — the scripts as run

Two session scripts, kept as the worked example for the check described in
docs/TRANSCRIPTION.md ("Two presenters whose names sound alike"). Run them with
`scratch/venv-voice/bin/python`; both read voiceprints that `split_cluster.py` cached
(`<transcript>.ecapa.json`) and compute nothing new.

1. `cross_meeting.py` — one centroid per settled cluster (turns of 8 s or more) for the
   last meeting and for this one, then every pair's cosine. This is the check that named
   the presenters: 10-20 cluster I against 10-06 Griffor 0.82 (DiPilato -0.01), cluster D
   against 10-06 DiPilato 0.63 (Griffor 0.01). Trudel, Anne, Alic and Haupt are the
   controls (0.69-0.79 to themselves). The 10-06 voiceprints were cached by the
   split-tool test under `scratch/split-test/`; `scratch/` is gitignored, so on another
   machine run `split_cluster.py` on the earlier meeting first.
2. `seeded_scores.py` — centroids seeded from evidence-anchored turns of this meeting
   (chair hand-offs, resolution readers, the presenters' long turns, the guests' own
   introductions), then every short line scored against them: `--cent` prints the
   centroid matrix, a number prints every line up to that many words with its two
   closest voices. The spec's `reassign` rows came from this listing, read with the
   same margins `split_cluster.py` uses (0.08; 0.15 under 3 s) plus context for lines
   too short to embed.

To reuse: change the transcript names, the cluster maps in `cross_meeting.py` and the
seed times in `seeded_scores.py`. Seeds are evidence, not guesses (TRANSCRIPTION.md).
