# Meeting transcription — recording → named transcript → site

How a board-meeting recording becomes a speaker-attributed, proper-noun-accurate
transcript, wired into the site with a YouTube embed, agenda-item chapters, and
click-to-seek. Everything lives in `transcription/`; the worked example is the
July 22, 2026 regular meeting.

## The pipeline

```
TelVue / YouTube video
  │  yt-dlp (TelVue player page exposes an HLS master.m3u8)
  │
  ├─ transcription/upload_videos.py MP4 --title … --date … --name …
  │     └─ thumbnails.py: crest card found in the stream, else typeset  → thumbnails.set
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

## Before you transcribe: refresh the keyterm index

`run_meeting.sh` runs `scripts/keyterms_index.py --meeting <date> --add` ahead of
transcription, and the ordering is the entire point — vocabulary added afterwards
does nothing for the recording you just processed.

The index grows from each meeting's own packet and never evicts. That replaces
`proper_nouns.py`'s corpus-wide top-40 firms for this purpose, which failed the
2026-08-18 meeting three separate ways: the 40 cap is ours rather than the API's
(1,000 phrases allowed, 361 being sent), `_ORG` matches only names ending in a
corporate suffix so "L Mason Capitani" and "MI Works!" were invisible at any cap,
and ranking fifteen years of history buries the meeting about to be transcribed.

**The 1,000-phrase cap is shared, and the newest meeting has to win the ties.**
`--emit` keeps the curated list whole and gives the remaining slots to indexed terms,
most-recurrent first, then most recent; a term that misses the cut stays in the index
and returns if it recurs. The cap first bit on 2026-10-20 (314 curated + 866 indexed for
686 slots), and the tie-break then sorted dates ascending, so all 180 dropped terms came
from the packet about to be transcribed, among them the students' names the chair read
aloud from the National Merit resolution. Fixed the same day. Read the `NOTE:` line the
emit prints, and spot-check a few of the meeting's own names in the emitted file.

**Keyterms only help where a word is spoken.** That same meeting's winning bidder
appears throughout the packet and twice in 71 minutes of audio, so a fuller list
changed its transcript not at all. Count the term in an existing transcript before
assuming vocabulary is the problem.

## After you transcribe: name the leftover clusters

Speaker identification returns some clusters as bare letters. Run
`transcription/name_unknown_speakers.py --d1 <date>`; it reads the chair's
introduction out of the transcript, which is how public commenters get named at
all — they are never on the roster, since their names come off a sign-in sheet at
the meeting and the API caps at 10 names.

It is report-only. Verify, then `UPDATE transcript_utts` (check the predicate as a
`SELECT COUNT(*)` against a predicted number first), relabel the local
`.transcript.json` / `.attributed.txt` / `.srt`, and re-run `upload_captions.py`
so YouTube matches.

**Do not re-transcribe a good transcript to chase an improvement.** Speaker
identification is a separate, non-deterministic call: two runs of the same audio
for 2026-08-18 named 7 of 8 clusters and 5 of 8, the worse one losing 96
attributions. A re-run is only worth it against a defect you can name and measure.

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
  **When clustering degenerates**, escalate in two steps. The 2026-06-01
  workshop — a different room's mic chain — collapsed 3.4 hours into 2 clusters
  and the identifier labeled one "Unknown"; full-fidelity stereo audio instead of
  the 16 kHz mono downmix, plus `--min-speakers 6 --max-speakers 25`, took it to
  9 clusters, all identified. 2024-04-16 needed the second step: hi-fi at
  `--min-speakers 6` still merged 3,197 words of student and teacher remarks into
  one cluster, and raising the floor to `--min-speakers 14` split the meeting into
  30 clusters, 24 of them named. Set the floor from how many people the *minutes*
  say spoke, not from how many the first pass found.
  **Judge cluster count against duration**, not in absolute terms: 2024-03-19
  returned 4 clusters for a 2.5-hour meeting with 300 people in the room — above
  the ≤3 "degenerate" line, but plainly collapsed. Its re-run doubled it to 8.
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

- **One voice, two clusters** — the chair's 85 minutes split into A + B. When the
  identifier *names* both twins it marks them `Nancy Philippart - 1` / `- 2` and
  `clean_mapping()` merges them. **When it names one twin and leaves the other
  unlabelled there is no suffix to strip**, and the second twin ships as a bare
  `Speaker B` — which is what happened on 2026-05-19, where B was President Anne's
  own floor management ("Next up is Boulan Park Middle School"). An unnamed twin
  needs an explicit `overrides` entry; nothing automatic will catch it.
  The tell: a cluster with many turns but very few words each (≤6 words/line over
  12+ turns) that *alternates* with a named speaker instead of conversing with them.
  Read the content before merging — the same profile also fits a recognitions
  reader or a student, and on 2025-03-18 that cluster turned out to be a student
  introducing herself by name.
- **Two voices, one cluster** — the remote trustee (phone audio) and the podium
  public commenter shared cluster I; a few utterances of a second trustee rode
  along with an adjacent one (E).

**The identifier is a text model and loses to transcript evidence.** On 2026-09-01 it
named the trustee who says "Vital had similar feedback" as Vital Anne and left the
chair unmapped. Cheap levers settle most clusters: who speaks right before "what Nancy
said"; who answers when the chair says "Matt?"; who volunteers as delegate just before
the superintendent lists the delegates. Write the resolved `mapping` into the spec with
a note per name and run the transcriber offline — it skips the API when `mapping` is
present.

**A persona match needs the whole persona, and the video beats all of it.** The same
night's first pass put cluster F on Audra Melton from "on the board for the last year
and a half" and "I was a delegate last year", and recorded Emina Alic absent because
no cluster was left for her. The rest of F's persona said otherwise — a junior
daughter at Troy High, an 8th grader with a summer Algebra packet, a kindergartner
with classroom iPads, "in all of these years" — and Melton's earlier transcripts have
grown children and an Athens graduate. One frame grab settled it: the board room is
multi-camera and the director cuts to the speaker, so a frame from the middle of a
long turn shows the speaker *and the name plate* — `EMINA ALIC, Board Vice President`.
The "last year and a half" line was Alic addressing the newer trustees. Grab frames
before writing a mapping (`ffmpeg -ss H:MM:SS -i tsd_<date>.mp4 -frames:v 1 f.jpg`);
it costs nothing and it is the only lever that does not depend on reading the
transcript right.

**Two trustees, one cluster, interleaved all evening.** Melton was in the room the
whole time; the diarizer had merged her with Zendler into cluster E, and a time
`split` cannot separate voices that alternate. What worked: speaker embeddings
(speechbrain ECAPA-TDNN, `spkrec-ecapa-voxceleb`; resemblyzer's GE2E embeddings were
too coarse — every centroid within 0.9 of every other) for every utterance, seeded
from turns where the camera is on each speaker, with the other named voices as sinks
so turns the diarizer dropped into E (DiPilato, Philippart) come out too. A sliding
4-s window over long turns then shows where one person hands off to the other
mid-utterance; those are cut at the word boundary. The spec records the result as
`reassign` (name → utterance `start_ms` list) and `utterance_splits` (start_ms,
at_ms, after). The sub-second interjections are the least certain lines. The
scripts, with a README of the order they ran in, are kept as the worked example in
`transcription/examples/2026-09-01/voice_split/`; the spec they produced is beside them.

**It happened again on 2026-10-06** — the same two trustees, cluster B this time, 85
turns. Unseeded clustering of the embeddings did *not* separate them (76 turns in one
group); the seeded comparison did, with within-person cosine 0.82–0.95 against 0.45–0.69
across. Seeds came from name plates (Melton) and the chair's hand-off plus camera preset
(Zendler, "Stephanie?"). Two further lessons: check a merged cluster's turns against the
*staff* centroids too (two of B's lines were Crane's and Griffor's, at 0.80), and for
remote trustees the **Teams active-speaker label** in the broadcast's tile column is as
good as a name plate. The session scripts are kept in
`transcription/examples/2026-10-06/voice_split/`.

**`transcription/split_cluster.py` does this now** (2026-10-10). Give it the merged cluster and
one or more seed times per person, and it reports — or with `--write` merges into the spec —
the per-line split, mid-turn hand-offs, staff lines inside the cluster, and the person's lines
filed under other clusters:

```bash
# one-time: a venv with the voice model (scratch/ is gitignored)
python3 -m venv scratch/venv-voice
scratch/venv-voice/bin/pip install speechbrain torch torchaudio soundfile numpy scikit-learn

scratch/venv-voice/bin/python transcription/split_cluster.py 2026-10-06 --cluster B \
  --seed "Audra Melton=2:31:08,0:51:58,0:57:43" \
  --seed "Stephanie Zendler=2:45:56,0:58:44,0:59:52,1:56:41"          # report; add --write
```

- **Seeds are evidence, not guesses.** Take them from a name plate on camera, a lit Teams
  label, or the line answering the chair's "Stephanie?" — never from what a line says. A seed
  time means the line *labelled* with that second in the attributed transcript (labels are
  floored), else the line containing it (a time read off a frame).
- **Read the seed check first.** It prints the lowest same-person and highest
  different-person cosine. On the first test a seed landed on the neighbouring line (Melton's
  "that is it", which ends a fraction before Zendler's answer starts): same-person fell to 0.32
  and the tool printed SEEDS DO NOT SEPARATE. With the right seeds: 0.80 against 0.69.
- **What it decides and what it leaves.** A line moves to the closer seed only with a clear
  margin (0.08; 0.15 under 3 s), to a staff voice only when that is clearly closer (≥ 0.6 and
  0.15 above both seeds). Everything else is listed for review and keeps the cluster default.
  Context calls — the one-second "I don't think I have any" after "Ayesha?" — stay hand-made
  rows in the spec, and hand-made rows win over the tool's (they are tagged `_split_cluster`
  and replaced on each run).
- **A line whose start time is shared** with another utterance (the API does emit these) is
  never moved: `reassign` is keyed by start time and would move both.
- Voiceprints are cached as `<transcript>.ecapa.json`; the first run is ~15 minutes of CPU for a
  three-hour meeting, later runs take seconds.

Tested against the hand-made 2026-10-06 spec, from the raw (unsplit) transcript: the same two
hand-offs at the same words, the same two staff lines, the same four Melton lines under staff
clusters, and — merged with `--write` and re-attributed — 811 of 812 lines identical to what
was published; the one difference is a 1.8-s "Oh, I'm just lingering" the tool gives to Melton
(0.15 margin) and the hand pass had left with the cluster.

**A first name in a sentence about someone else is not evidence.** The same night,
"she's going to stick around as long as she can, but Dan is out of town on business
… she's got to take care of the kids" was the superintendent explaining why DiPilato
would leave early — her husband — and it was read as Trudel being remote. Trudel had
finished the superintendent's previous sentence from the table four seconds earlier.
Presence is proven by a person's own in-room turns; absence needs the chair's word or
the minutes, never an inference, and never before it reaches a public post. The chair's
word need not carry the name: on 2026-10-20 she said only "We have 6 of our 7 board
members present … she's not able to be here", and the other six each spoke in board
comments, which leaves one trustee on a seven-member roster.

**Two presenters whose names sound alike (2026-10-20).** Christine DiPilato and Kristine
Griffor are homophones, so the chair's "Thanks, Kristine" names either one, and the
identifier swapped them. Content decides first: Griffor (Assistant Superintendent,
Elementary) presents the elementary data and DiPilato (Secondary Instruction) middle and
high school. A **cross-meeting voiceprint check** confirms it when no frame can (that
night's presentation frames were all slides): a centroid per settled cluster of the last
meeting from its cached `.ecapa.json`, the same for the new one, and every pair's cosine.
Cluster I scored 0.82 against 10-06 Griffor and D 0.63 against 10-06 DiPilato, each about
0 against the other, while four control voices matched themselves at 0.69-0.79. The
scripts are in `transcription/examples/2026-10-20/voice_check/`.

**Guest clusters keep collecting after the guest leaves.** The diarizer gives a podium
guest, or a group of children, a cluster of their own and then files the evening's
one-word interjections there too, so mapping the cluster to the guest labels a vote's
"Yes." as a Schroeder student or as the public commenter. Close a guest cluster with a
time `split` at the moment the guest leaves (`after: "Unidentified speaker"`), then pin
the few later lines that context does identify (the chair's "supported by Mr. Haupt"
names the "Support." before it). The same night one student rep's nine lines sat in three
clusters (DiPilato's, Melton's and the Troy High rep's); the name plate on camera and one
voice (0.44-0.74 to her first line) brought them back together.

`speakers.json` (see `transcription/examples/2026-07-22/`) is the reconciliation
record: `speakers[]` feeds the API (`description` strongly guides matching),
`mapping` stores the resolved result, `overrides` pins corrections,
`splits` divides a two-person cluster at a timestamp, `reassign` pins individual
utterances by `start_ms` (interleaved voices), and `utterance_splits` cuts one
utterance at a word boundary where the speaker changes. Resolution order is
reassign > splits > overrides > mapping, in one shared resolver
(`transcribe_meeting.namer`) that the uploader and the audit gate both import.
Once `mapping` is present,
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

## Audit every meeting against the minutes

`transcription/audit_attribution.py TRANSCRIPT… [--absent NAME…] [--expect NAME…]`
is the gate a transcript passes before it goes on the site. It prints each
speaker's share of the spoken words and raises four flags: **DEGENERATE** (≤3
clusters), **UNATTRIBUTED** (>30% of words still on Speaker letters), **ABSENT**
(words attributed to someone the minutes record as absent) and **MISSING** (a
trustee recorded present who never speaks).

**Absence is not the same as non-attendance.** Trustees join remotely, and the
minutes say so in prose the roll-call line does not contain: "Mrs. Alic connected
via remote communications", "Dr. Philippart was not in attendance but connected to
the workshop remotely", "Mrs. Hammond participated via phone conference". Read the
whole attendance paragraph, not just the `present were` list — scoring 2025-10-07
off the list alone flagged Emina Alic as absent when she was participating. A real
absence reads the other way round: 2025-05-20's minutes say the vice president
presided "for President Philippart who was not in attendance", with no remote
language anywhere in the document.

ABSENT and MISSING are the ones worth building a wave around, because they are
checkable against a source outside the audio. Every meeting's minutes open with
a roll call — "In addition to Mr. Schmidt, present were Board members Alic,
Anne, Hauff, Haupt, and Wilson. Dr. Philippart was absent" — so pass that roll
call in and the audit will tell you when the identifier has put words in an
absent trustee's mouth. Better still, drop the absent members from that
meeting's candidate list before transcribing: on a night the vice president
chairs, leaving the usual chair among the candidates invites exactly the wrong
answer.

Fix what it finds with `overrides` / `splits` in the speakers spec, then re-run
`transcribe_meeting.py --transcript-id` — offline, no new charge.

## Names the identifier invents

The identifier will happily return names that were never in your candidate
list, mined from what it heard: presenters, student representatives, public
commenters. They are often right and are exactly the proper nouns that make an
archive searchable — but each one needs a source before it ships:

- **The minutes name the officials and the students** (presenters with titles,
  each student representative with their school), so most out-of-roster names
  can be confirmed and, where the STT mangled them, corrected there: `Macy
  Justice` → Maisie Justes, `Kris Bunch` → Chris Bunch, `Seo-Wee Kim` → Seowoo
  Kim.
- **The keyterms list can pull a name toward a district insider.** On
  2024-12-17 the Student Spotlight senior introduced himself on camera and the
  transcript wrote `Ryan Zawislak` — Zawislak being a district surname sitting
  in the vocabulary. The minutes name him Ryan Stasinski.
- **The minutes name no public commenters**, and neither should the transcript:
  the identifier read one commenter's name off the chair's uncertain announcement
  ("Mrs. Lauren Haroun … Anne Haroun?") and another as `Joseph Kolbe` when the
  man said "Joseph Colby Bernhardt". They ship as `Public commenter`.

## Era keyterms — build the vocabulary for the year you are transcribing

`transcription/era_keyterms.py --start 2024-01-01 --end 2024-06-30 --label 2024H1`
harvests that era's people out of its board minutes — attendance roll calls,
movers and supporters, presenters with titles, student representatives, and the
people the minutes name at the podium — and merges them with the base
vocabulary. Build one per six-month era and pass it with `--keyterms`.

This is not optional politeness to the older meetings. The committed 2025-26
list actively *misleads* an older transcript: it pulls unfamiliar names toward
the district names it contains. Two 2024 meetings produced `Ryan Zawislak` and
`Brian Zawislak` — Zawislak being a district surname in that list — where the
minutes say Ryan Stasinski and Brian Fahnestock. The era pass found Fahnestock,
and found `Katie Starn` where the chair had announced "Katie Skarn", turning two
speakers that had been demoted to `Public commenter` back into named teachers.

## Season coverage (as of 2026-10-23)

**48 recordings are on the site, and each has the "English (speaker-attributed)" caption
track on YouTube**: 46 board meetings (2024 and 2025 complete, 2026 through the
2026-10-20 regular) and the two League of Women Voters candidate forums (2024-09-25,
2026-09-24). Each new meeting is captioned as it is added
(`upload_captions.py --only <date>`). The 2026-09-25 audit pushed 15 tracks
after finding the owed list wrong in both directions; see "Audit before you push
captions" below.

- **2024 — every recording on the channel is live.** All ten recorded regular
  meetings (Jan 16 organizational, Feb 27, Mar 19, Apr 16, May 21, Jun 20,
  Sep 17, Oct 15, Nov 19, Dec 17) are transcribed, audited against their minutes
  and on the site. The 2024 board is the pre-election seven (Schmidt president,
  Anne vice president, Hauff secretary) and Business Services changes hands
  mid-year, so the season carries two rosters — `speakers_2024.json` (Trudel)
  and `speakers_2024_h1.json` (West). 13 meetings — every workshop, both June
  specials, and the Jul 16 and Aug 20 regulars — have no recording located
  anywhere; `manifest_2024.json` records them as `src: null` with a note.

- **2026 — complete through October 20.** All 17 televised meetings (7 workshops,
  10 regulars) live on the site with embed + named transcript + chapters, and
  caption tracks ("English (speaker-attributed)") on all 17 YouTube videos. Only
  the Mar 3 workshop was never recorded anywhere. New meetings follow
  [OPERATIONS.md](OPERATIONS.md#the-whole-chain-in-the-order-it-has-to-run).
- **2025 — complete.** All 19 recorded meetings are transcribed and QA'd (Jan 14,
  May 6, Jul 15, Aug 19 were not televised), and **all 19 are live on the site** with
  embed, chapters, named transcript and an "English (speaker-attributed)" caption
  track. The six TelVue-only recordings — Jan 21 organizational, Feb 25, Mar 8
  Winter Retreat, Oct 14, Nov 18 and Dec 16 — were uploaded to the channel on
  2026-08-07 and wired the same day. The Feb 11 workshop, which existed only as two
  part uploads, was rejoined into one recording (`1-P9EUyx9N0`) in v0.17.0; this
  section said it stayed off the site until 2026-10-23.

## Backfilling a season (the 2025 pattern)

1. Build `transcription/manifest_<year>.json`: one row per meeting — D1
   `name`, source (`yt:<id>` / `telvue:<mediaId>` / `local`), site-eligibility,
   exact channel title. Enumerate the channel with
   `yt-dlp --flat-playlist --print "%(id)s|%(title)s" <channel/videos>`.
   **The TelVue catalogue is the player root**, and Troy's is

       https://connect.telvue.com/player/i-P7YFZryO9zQNfciKbAQTp5wv5_PLoa/series/4132

   — token `i-P7YFZryO9zQNfciKbAQTp5wv5_PLoa`. **Regular meetings are series `4132`;
   workshops are series `5075`** ("Troy School Board Workshops" — the 2026-09-01 and
   2026-10-06 workshops are there, not in 4132). A single recording is
   `/player/<token>/media/<mediaId>`, which `yt-dlp`
   resolves to an HLS master offering 416x234 / 640x360 / 1280x720. Take 720p
   (`-f "b[height=720]"`) for a YouTube upload — the format *id* is derived from the
   bitrate and changes (2390 for most of 2026, 2389 for 2026-10-06), so select by height. This token was documented as `<token>` for
   months and had to be re-found by search each time; it is not a secret, it is
   the address of a public access channel.
   Fetch the player root itself (`https://connect.telvue.com/player/<token>`)
   with a browser User-Agent: it returns the station's whole gallery as `/media/<id>`
   links, each with its duration and every series' latest title and air date. That is the
   authoritative list of what TelVue actually holds, and the quickest way to see whether
   a new meeting has posted. Do not try to bisect the id space — ids are global across
   TelVue's customers, so almost every probe in a range belongs to another station
   and returns a blank title.
2. Write `speakers_<year>.json` with that year's board (who chaired matters).
   Read the roll call and the organizational meeting out of D1 rather than
   guessing: the officer slate is in the January minutes, and the cabinet can
   turn over mid-season. Then narrow it per meeting — drop whoever the minutes
   record as absent, and spend the freed slots (the API caps at 10) on the
   administrators that meeting's agenda says will present.
3. Acquire audio per manifest (yt-dlp audio-only; for TelVue take the `worst`
   video variant and extract audio) and transcribe in waves of ~5. They run
   concurrently — five meetings finish in about the time the longest takes.
4. Audit every meeting with `audit_attribution.py`, passing the attendance the
   minutes record (see "Audit every meeting against the minutes"); re-run
   degenerate meetings (≤3 clusters) with hi-fi stereo audio +
   `--min-speakers/--max-speakers`; fix the rest with evidence-based `overrides`.
5. `make_anchors.py --agenda` per meeting → `upload_transcript.py` for every
   site-eligible meeting → refresh `transcripts/` deliverables → extend
   `upload_captions.py`'s manifest and run it (see "Audit before you push
   captions" below).

## Audit before you push captions

`upload_captions.py` reports what it uploaded. It has never reported what it was
*supposed* to upload, and the difference is not academic: on 2026-08-08 the owed
list carried in notes was 12, and a pre-flight audit against the API found **15**.
It was wrong in both directions — two meetings believed owed (2025-10-14,
2026-02-24) had actually landed before an earlier quota 403, and **five 2025
videos had never been captioned at all** and appeared on nobody's list.

So never work from a remembered list. Ask the API which videos lack the track:

```python
import sys
sys.path.insert(0, 'transcription'); import upload_captions as uc
tok = uc.access_token()
for d, k, v in uc.MEETINGS:
    data = uc.http(f"https://www.googleapis.com/youtube/v3/captions?part=snippet&videoId={v}",
                   headers={"authorization": f"Bearer {tok}"})
    ours = [i for i in data.get("items", [])
            if i["snippet"].get("name") == uc.TRACK_NAME
            and i["snippet"].get("trackKind") != "asr"]
    print(f"{d} {v} {'HAVE' if ours else 'MISSING'}")
```

`captions.list` is only **50 units** against `insert`'s 400, so auditing all ~41
videos costs about the same as five uploads and is the cheapest possible insurance.
Budget the whole job: 41 lists + 15 inserts ≈ 8,050 units exhausted the daily
quota, and the post-push re-audit only got through 27 videos before 403ing. If a
verification sweep matters, run it *before* spending the quota on uploads, or wait
for the reset (midnight Pacific / 3:00 a.m. Eastern).

**`TITLE_BY_VID` is a filename map, not a title map.** It is used only to derive
the local `.srt` path, so an entry that disagrees with the file on disk makes the
script print `MISSING <name>.srt` and skip that video silently — it does not fail.
That is how 2024-01-16 sat uncaptioned: the map called it "Organizational and
Regular Meeting" while both the channel and `manifest_2024.json` title it
"Standing Meeting". When adding rows, copy the title from the manifest's `title`
field, which is the recorded channel title.

## Adding a new meeting (checklist)

1. Download the video (TelVue player page → grep the `master.m3u8` → `yt-dlp`),
   upload to YouTube with `upload_videos.py … --date YYYY-MM-DD --name "<meeting
   name as in D1>"`, note the video id. Those two flags are what let the
   thumbnail step typeset a card when the stream never shows one — see below.
   Then `playlists.py --add ID --date DATE` — nothing else puts the video in its
   year playlist.
2. `transcribe_meeting.py MEDIA --date …` (~$0.40; a 3.8-hour workshop ≈ $1).
   Transcode the local video yourself rather than letting `run_meeting.sh` fetch
   audio from YouTube — a fresh upload is still processing and the fetch fails.
   Draft `speakers.json` from the roll call; run with `--speakers`. **Before writing
   the resolved `mapping`, grab a frame from the middle of each cluster's longest
   turn** (`ffmpeg -ss H:MM:SS -i tsd_<date>.mp4 -frames:v 1 f.jpg`) — the name plate
   on camera is the one lever that does not depend on reading the transcript right —
   then verify with the levers above and write `mapping` back into the spec. A trustee
   with no cluster is a merged cluster until proven absent — and when a cluster holds two
   people (two personas, or the chair's "Stephanie?" and "Audra?" both answered by it), run
   `transcription/split_cluster.py` with seeds from name plates or hand-offs (see "It happened
   again on 2026-10-06" above). When two staff presenters could be confused (DiPilato and
   Griffor sound alike by name), compare the new clusters with the last meeting's settled
   voices, and close guest clusters with a time split when the guest leaves (both above,
   2026-10-20).
3. Build the agenda anchors — **`make_anchors.py` output is a draft, not an
   answer**. Run `anchors/prep_meeting.py DATE --transcript <the .transcript.json>`
   to build the workdir inputs, then `anchors/brief.py DATE`, author the anchor set
   with its agenda numbers in `items`, and apply it with `anchors/apply_anchors.py`
   (after step 4 — it reads the `recordings` row), which validates the set and runs
   the coverage gate. See
   [transcription/anchors/README.md](../transcription/anchors/README.md).
4. `upload_transcript.py … --youtube ID` (wrangler `--remote`).
5. Done — the meeting page picks it up on next load.

## Agenda anchors — why the generator's output is a draft

`transcript_anchors` drives the meeting page's chapter chips and the YouTube
description's clickable agenda, and `make_anchors.py` cannot finish the job alone.
Across the 41-meeting corpus its output carried **54 labels that were raw
transcript prose**, 73 truncated into ellipses, 19 with duplicated prefixes
(`4.c C. RFP …`), leading characters eaten off titles (`4.E Establish` →
`Stablish`, `2026 Spring` → `026 Spring`), and whole agenda items with no anchor —
2026-02-03 had nothing for 3.c, 2026-01-20 nothing for 11.A/11.B/11.C.

The reason is that the evidence deciding where an item was taken up is
conversational — *"we're just gonna tackle these 2 purchase items first, and then
we'll jump into budget"*. A regex cannot hear that. So the anchors are authored
from a digest and then **checked against the transcript**:

- `anchors/brief.py DATE` — agenda, current anchors, and the ~70 utterances of ~800
  that carry a signal (motions, votes, transitions, item references, item keywords).
- `anchors/apply_anchors.py DATE FILE` — validates (first at 0:00, ascending, ≥3,
  ≥10s apart, within duration, no truncated/duplicate-prefix/prose labels), writes
  to D1, runs the coverage gate, queues the description rebuild.
- `anchors/coverage.py [--all]` — for every agenda item in `chunks`, decides from
  the transcript whether it was DISCUSSED / MENTIONED / IN CONSENT / ABSENT /
  UNSEARCHABLE, and asserts anything DISCUSSED has an anchor.

**The coverage gate is the part that matters.** Omitting an item is only defensible
if the board genuinely never took it up — which is a claim about the transcript, so
it gets checked against the transcript. It caught 18 meetings with a discussed item
that had no anchor, two of which had already been hand-authored and signed off:
2025-12-16's roof replacement (0:18:17, omitted as "couldn't locate"), and
2025-11-18 where an anchor sat on the wrong item entirely — 1:22:21 is the traffic
signal, not the security systems it was labelled.

**Out-of-numeric-order agenda items are usually not an error.** Chapters are
chronological; on 2026-01-13 the board really did take 4.c and 4.b before 4.a.
Do not "fix" that by re-sorting.

Anchor writes cost no YouTube quota (D1); the description rebuild does
(`videos.update`, 50 units), so the two are decoupled and the rebuilds queue in
`anchors/pending_push.json` — drain with `anchors/push_pending.py`.

Corpus after the 2026-08-18 rebuild: 540 anchors across 41 meetings (from 422),
zero prose labels, zero truncated, zero duplicated prefixes, zero
discussed-but-unanchored items. As of 2026-09-04: 578 anchors across 43 meetings,
556 of them numbered; `qa_numbers.py` reads 16 COVERED and 11 ORDER, all
eyeballed (procedural items folded into a neighbour, and genuine out-of-sequence
agendas). As of 2026-09-25: 624 anchors across 46 recordings — 602 on 44 board
meetings (the 2026-09-22 regular added 24, numbering valid, and left the QA counts at
16 COVERED / 11 ORDER) plus 22 forum chapters, which carry no agenda numbers. As of 2026-10-10: 649 anchors across
47 recordings — the 2026-10-06 workshop added 25, numbering valid, QA counts unchanged at
16 COVERED / 11 ORDER over 45 board meetings. As of 2026-10-23: 672 anchors across 48
recordings — the 2026-10-20 regular added 23, numbering valid, QA counts unchanged at
16 COVERED / 11 ORDER over 46 board meetings.

## Candidate forums (League of Women Voters)

A forum is a recording, not a meeting: one mic per speaker diarizes cleanly (5 clusters
= moderator + 4 candidates in 2026), every voice is fixed by its own self-introduction
and the moderator's hand-off, and the characteristic defect is that hand-off — "Mr.
Cook." — glued onto the front or back of an answer or misheard ("Masada", "Ms.
Gummel"). Repair it with index-asserted edits that move a fragment only when the
person named is the speaker on the other side of the boundary; never by hand-keyed
offsets. The deliverable is the .docx/.pdf that `transcription/forum_doc.py` builds
from a spec, and the site rows come from the *repaired* utterances with their cluster
letters kept, so `upload_transcript.py` still resolves names through the spec. Worked
examples: `transcription/examples/lwv-2026-09-24/` (spec, keyterms, `repair.py`) and
`lwv-2024-09-25/` (rebuilt from the delivered .docx). Neither the coverage gate nor
`qa_numbers.py` applies — there is no agenda — and `meetings.tsv` does not list them.

## Thumbnails — why the frame grab is not a frame grab

The city cable broadcast opens on a **City of Troy** bumper ("City of Tomorrow,
Today / 1955") and cuts to the district's crest card only afterwards — sometimes
at 2s, sometimes at 21s. `upload_videos.py` originally grabbed a fixed `-ss 2`,
so whenever the cut came late the video kept the bumper: an undated,
byte-identical city graphic that ended up on **35 of 57** board videos, alongside
4 more showing a stray meeting frame.

`transcription/thumbnails.py` therefore *finds* the card rather than assuming it:

- **Scan** the opening at 2 fps and correlate each frame against
  `assets/tsd_card_base.jpg` (normalised grayscale, 64×36). ≥0.80 is the card.
  The hit is re-pulled at full resolution — that artwork is the district's own,
  so its date, time and address are the ones that aired. Every Regular meeting
  before Nov 2024 has one; **no Workshop or Retreat ever does** — they begin cold
  on multi-camera meeting footage.
- **Typeset** from the base card when nothing airs. Only the header/date/time
  lines are relaid: the ground under a line is rebuilt by interpolating the clean
  gap rows above and below it, then text is composited in the card's own face
  (Arial Black 50 — matched at IoU 0.90, and it reproduces the card's
  `7:00pm MEETING` line at exactly its measured 469×47 px).
- **Verify** with `verify_date()`, which reads the date back off the finished
  card and scores it against the date the meeting actually has. Typeset cards
  land at 0.97–0.99, extracted ones at 0.78–0.93; anything under 0.60 wants an
  eyeball. This is the check that catches a frame lifted mid-fade — 2023-09-19
  first came back dimmed mid-transition, and 2023-02-14's aired card is an older
  striped, letterboxed design that could not be validated at all and was typeset
  instead.

**Start time comes from the meeting record, never a default.** The Regular
meetings are not all at 7:00pm — 2023-06-13 is 7:30 PM, 2023-07-18 is 9:30 AM,
2023-08-15 is 6:00 PM, and 2026-07-22 is 1:00 PM. `parse_time()` reads it off the
BoardDocs folder name (`…Workshop 6_15 PM`), the same string D1 stores as
`recordings.meeting_name`. Getting this from a default is how a card ends up
announcing a meeting for the wrong hour.

**Generative fill is the wrong tool for this.** An Adobe Firefly pass on the
2026-07-22 card returned 1376×768 instead of 1280×720, shifted the palette off
the house blue, restyled the date to "July 22nd, 2026" against the card's own
`MAR 17, 2026` convention — and, having no access to the meeting record, left the
time line reading `7:00pm MEETING` for a meeting that started at 1:00 PM. The
card is flat artwork on a near-solid ground; retypesetting one line is exact,
free, and repeatable.

```
python3 transcription/thumbnails.py --audit                 # classify the channel
python3 transcription/thumbnails.py --for-video ID \
    --date 2026-02-03 --name "Board of Education Workshop 6 00 PM" --set
```
