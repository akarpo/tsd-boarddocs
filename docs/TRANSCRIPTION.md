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

## Season coverage (as of 2026-08-08)

**All 41 channel videos carry the "English (speaker-attributed)" caption track**
as of 2026-08-08 — 2024, 2025 and 2026 complete. The last 15 were pushed that
morning after an API audit found the owed list was wrong in both directions; see
"Audit before you push captions" below.

- **2024 — every recording on the channel is live.** All ten recorded regular
  meetings (Jan 16 organizational, Feb 27, Mar 19, Apr 16, May 21, Jun 20,
  Sep 17, Oct 15, Nov 19, Dec 17) are transcribed, audited against their minutes
  and on the site. The 2024 board is the pre-election seven (Schmidt president,
  Anne vice president, Hauff secretary) and Business Services changes hands
  mid-year, so the season carries two rosters — `speakers_2024.json` (Trudel)
  and `speakers_2024_h1.json` (West). 13 meetings — every workshop, both June
  specials, and the Jul 16 and Aug 20 regulars — have no recording located
  anywhere; `manifest_2024.json` records them as `src: null` with a note.

- **2026 — complete.** All 12 televised meetings (5 workshops, 7 regulars) live
  on the site with embed + named transcript + chapters, and caption tracks
  ("English (speaker-attributed)") on all 12 YouTube videos. Only the Mar 3
  workshop was never recorded anywhere.
- **2025 — complete.** All 19 recorded meetings are transcribed and QA'd (Jan 14,
  May 6, Jul 15, Aug 19 were not televised), and **18 are live on the site** with
  embed, chapters, named transcript and an "English (speaker-attributed)" caption
  track. The six TelVue-only recordings — Jan 21 organizational, Feb 25, Mar 8
  Winter Retreat, Oct 14, Nov 18 and Dec 16 — were uploaded to the channel on
  2026-08-07 and wired the same day. Only the Feb 11 workshop stays off the site:
  it exists on the channel as two separate part uploads rather than one recording.

## Backfilling a season (the 2025 pattern)

1. Build `transcription/manifest_<year>.json`: one row per meeting — D1
   `name`, source (`yt:<id>` / `telvue:<mediaId>` / `local`), site-eligibility,
   exact channel title. Enumerate the channel with
   `yt-dlp --flat-playlist --print "%(id)s|%(title)s" <channel/videos>`.
   **The TelVue catalogue is the player root**, and Troy's is

       https://connect.telvue.com/player/i-P7YFZryO9zQNfciKbAQTp5wv5_PLoa/series/4132

   — token `i-P7YFZryO9zQNfciKbAQTp5wv5_PLoa`, board meetings are series `4132`,
   and a single recording is `/player/<token>/media/<mediaId>`, which `yt-dlp`
   resolves to an HLS master offering 416x234 / 640x360 / 1280x720. Take 720p
   (`-f 2390`) for a YouTube upload. This token was documented as `<token>` for
   months and had to be re-found by search each time; it is not a secret, it is
   the address of a public access channel.
   with a browser User-Agent: it returns the station's whole gallery as `/media/<id>`
   links each followed by its air date, which is the authoritative list of what
   TelVue actually holds. Do not try to bisect the id space — ids are global across
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
2. `transcribe_meeting.py MEDIA --date …` (~$0.40). Draft `speakers.json` from
   the roll call; run with `--speakers`; verify with the levers above.
3. Build the agenda anchors — **`make_anchors.py` output is a draft, not an
   answer**. Run `anchors/brief.py DATE`, author the anchor set, apply it with
   `anchors/apply_anchors.py`, which validates the set and runs the coverage gate.
   See [transcription/anchors/README.md](../transcription/anchors/README.md).
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
discussed-but-unanchored items.

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
