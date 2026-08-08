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
   **The TelVue catalogue is the player root**, `https://videoplayer.telvue.com/player/<token>`
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
   upload to YouTube, note the video id.
2. `transcribe_meeting.py MEDIA --date …` (~$0.40). Draft `speakers.json` from
   the roll call; run with `--speakers`; verify with the levers above.
3. Hand-tune `anchors.json` from the transcript's transition lines
   ("That brings us to item…").
4. `upload_transcript.py … --youtube ID` (wrangler `--remote`).
5. Done — the meeting page picks it up on next load.
