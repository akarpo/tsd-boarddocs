# Meeting transcription — recording → named transcript → site

How a board-meeting recording becomes a speaker-attributed, proper-noun-accurate
transcript, wired into the site with a YouTube embed, agenda-item chapters, and
click-to-seek. Everything lives in `transcription/`; the worked example is the
July 22, 2026 regular meeting.

## The pipeline

```
TelVue / YouTube video
  │  yt-dlp (TelVue player page exposes an HLS master.m3u8)
  ▼
transcription/transcribe_meeting.py MEDIA --date YYYY-MM-DD --speakers speakers.json
  │  1. ffmpeg → 16 kHz mono 64 kbps MP3 (1.4 GB video → ~40 MB)
  │  2. POST /v2/upload
  │  3. POST /v2/transcript   speech_models + keyterms_prompt + speaker_labels
  │  4. poll until completed
  │  5. POST llm-gateway /v1/understanding  (speaker_identification, ≤10 names)
  ▼  writes <base>.transcript.json · .transcript.txt (or .transcript.attributed.txt) · .srt
transcription/upload_transcript.py JSON --date --name --youtube ID --speakers --anchors
  ▼  D1 tables: recordings · transcript_utts · transcript_anchors   (wrangler --remote)
site  /api/recording → meeting page: embed + chapter chips + searchable transcript,
      every line and chapter seeks the YouTube player (widget postMessage API)
```

## AssemblyAI specifics (verified against the live API, Aug 2026)

The docs and pricing pages lag the API — these were confirmed by probing:

- **Model**: send `speech_models: ["universal-3-5-pro", "universal-2"]` (priority
  order). The singular `speech_model` parameter returns HTTP 400 as deprecated.
  The response's `speech_model_used` reports what actually ran.
- **Proper nouns**: `keyterms_prompt` — up to 1,000 phrases, ≤6 words each.
  `word_boost` and Slam-1 are deprecated. Keyterms cost +$0.05/hr.
- **Diarization**: `speaker_labels: true` (+$0.02/hr) yields anonymous A/B/C…
  clusters. Speaker-count hints must be NESTED — `speaker_options:
  {min_speakers_expected, max_speakers_expected}` (top-level variants 400).
  **When clustering degenerates** (the 2026-06-01 workshop — a different room's
  mic chain — collapsed 3.4 hours into 2 clusters and the identifier labeled one
  "Unknown"), re-run with `--min-speakers 6 --max-speakers 25` and
  full-fidelity stereo audio instead of the 16 kHz mono downmix: that combination
  took June 1 from 2 unusable clusters to 9, all identified.
- **Speaker identification** (names, not letters): separate call, works on an
  already-completed transcript — `POST https://llm-gateway.assemblyai.com/v1/understanding`
  with `speech_understanding.request.speaker_identification =
  {speaker_type: "name", speakers: [{name, description}, …]}`. **Max 10 names
  per request.** Returns a `mapping` {letter → name} plus relabeled utterances.
- **Cost**: $0.21/hr base ⇒ an 85-minute meeting ≈ **$0.40** all-in.
- **Key**: `ASSEMBLYAI_API_KEY` via `tsd_secrets` (env var, else
  `tsd-secrets.env` outside the repo). Never committed.

## The proper-noun vocabulary

`scripts/proper_nouns.py --dataset dataset/summaries-full.jsonl --since 2025-01-01
--flat-out transcription/keyterms/TSD_keyterms_2025-2026.txt` regenerates the
361-term list (+ `.json` twin the transcriber loads): QA-curated rosters (board,
cabinet, all principals/APs from the 22 Jul 2026 packet, student board reps,
schools, programs, unions, acronyms) merged with firms auto-extracted from the
meeting-summary corpus. Ledger docs (check registers, P-card, ACH) are always
excluded as noise. (`dataset/` is gitignored — on a fresh checkout rebuild it
with `scripts/build_dataset.py`, or omit `--dataset` to pull summaries from D1.)

**Homophone caveat**: archival names can collide with current ones — the
2026-07-22 transcript wrote "Mr. Hauff" (Gary Hauff, trustee to 2024, since
June 2026 an Oakland Schools ISD board member) six times for trustee **Matt
Haupt**. Keep both for archival tapes, but expect to post-fix current-era
meetings.

## Speaker attribution: trust, but verify

The identifier is good, not infallible. On 2026-07-22 it mapped 6 of 9 clusters
correctly, left one unmapped, and guessed one wrong. Diarization itself has two
failure modes to check for:

- **One voice, two clusters** — the chair's 85 minutes split into A + B.
- **Two voices, one cluster** — the remote trustee (phone audio) and the podium
  public commenter shared cluster I; a few utterances of a second trustee rode
  along with an adjacent one (E).

`speakers.json` (see `transcription/examples/2026-07-22/`) is the reconciliation
record: `speakers[]` feeds the API (`description` strongly guides matching),
`mapping` stores the resolved result, `overrides` pins corrections, and
`splits` divides a two-person cluster at a timestamp. Once `mapping` is present,
both `transcribe_meeting.py` and `upload_transcript.py` use it directly — no
further identification calls, so re-runs are offline and deterministic.

Verification levers that settle disputes fast:

1. **Resolution reader = mover** — whoever reads "Be it therefore resolved…"
   just before "moved by X" is X.
2. **Absence windows** — speech while someone is confirmed absent/dropped rules
   them out ("Stephanie, did you have any questions? She's gone.").
3. **Content ownership** — facilities photos belong to M&O, budget scenarios to
   Business Services, personnel readings to Employee Services.

## Site integration

`upload_transcript.py` fills three D1 tables (created on first run):
`recordings` (meeting → YouTube id), `transcript_utts` (attributed utterances),
`transcript_anchors` (agenda-item chapters, hand-tuned from the transcript).
`--name` must match the meeting's `meeting_name` in the `chunks` table so the
meeting page finds it. Re-running replaces the meeting's rows.

The Worker serves `/api/recording?date=&name=`; the meeting page then shows the
YouTube embed (privacy-enhanced youtube-nocookie, `enablejsapi=1`), chapter
chips, and the transcript panel with live search/highlight. Clicking a chapter
or any transcript line seeks the player via the widget postMessage protocol —
no YouTube script is loaded.

## Adding a new meeting (checklist)

1. Download the video (TelVue player page → grep the `master.m3u8` → `yt-dlp`),
   upload to YouTube, note the video id.
2. `transcribe_meeting.py MEDIA --date …` (~$0.40). Draft `speakers.json` from
   the roll call; run with `--speakers`; verify with the levers above.
3. Hand-tune `anchors.json` from the transcript's transition lines
   ("That brings us to item…").
4. `upload_transcript.py … --youtube ID` (wrangler `--remote`).
5. Done — the meeting page picks it up on next load.
