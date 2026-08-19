# Changelog

All notable changes to `tsd-boarddocs` and its tooling. Dates are UTC.
Versioning is loosely semantic; tags are pushed to GitHub (`git tag vX.Y.Z`).

## [Unreleased]

### Both YouTube backlogs drained; agenda numbering corrected — 2026-08-19

- **All 41 descriptions rebuilt and all 10 remaining thumbnails set.** The armed
  drain fired at the 03:34 EDT quota reset: 40 descriptions pushed, then the
  thumbnail drip cleared 10/10 — the rolling per-user cap on `thumbnails.set`
  had recovered on its own after ~20 hours of leaving it alone, which is what
  the one-at-a-time drip was for. `thumbnails.py --audit` reads 51/51 crest
  cards, no WRONG.
- **Seven anchors carried the wrong agenda number while QA read clean.**
  `qa_numbers.py` reported 0 EXISTS / 0 UNIQUE / 0 SEMANTIC because every wrong
  claim shared a word with the item it named — "**Closed** session" numbered
  4.D, *"Schools **Closed** to Open Enrollment"*; a furniture purchase numbered
  2.B, *"State Schools of Character - Larson **Middle School**"*. Corrected in
  `authored/` and D1, and shipped with the same push rather than costing a
  second one.
- New **ORDER** pass finds that class: a board taking a section out of sequence
  moves it and stays there, so categories still run forward on both sides; a
  number on the wrong chapter leaves one anchor below the anchors on *both*
  sides of it. A sentinel past the last anchor catches a meeting ending below
  where it had got to. Ten flags remain, all checked by hand and all genuine
  reordering — ORDER is an eyeball flag like SEMANTIC, not a gate that reads zero.
- **`push_desc.d1()` no longer turns a bad minute into a bad meeting.** It was
  one unchecked `json.loads(...)[0]["results"]`; wrangler reports transient
  errors on stdout, so the parse raised a bare `KeyError` with no cause and
  2024-01-16 sat queued overnight. It now checks the return code, says what
  happened, and retries — the date pushed first try the next morning.

### Every board video carries the district's crest card — 2026-08-17

- 62 thumbnails set; 82 of 86 board videos now show the crest card, verified
  against the live CDN rather than the push's own success count.
- **The cause was a fixed frame grab.** The city broadcast opens on a City of
  Troy bumper ("City of Tomorrow, Today / 1955") and cuts to the crest card only
  afterwards — sometimes at 2s, sometimes at 21s. `upload_videos.py` grabbed
  `-ss 2`, so a late cut kept the bumper: one undated, byte-identical city
  graphic on 52 videos, with 13 more showing a stray meeting frame.
- New `transcription/thumbnails.py` **finds** the card instead of assuming it —
  scans the opening at 2 fps against `assets/tsd_card_base.jpg` and lifts a hit at
  full resolution (10 videos; that artwork is the district's own, so its
  date/time/address are the ones that aired). Where none airs — no Workshop or
  Retreat ever shows one — it retypesets the base card's header/date/time lines.
- `verify_date()` reads the date back off every finished card and scores it
  against the meeting's own date: 62/62 passed (typeset 0.97–0.99, extracted
  0.78–0.93). It earned its place immediately, catching a frame lifted mid-fade
  and a 2023-era striped card that could not be validated and was typeset instead.
- **Start times come from the BoardDocs folder names, never a default.** A
  7:00pm assumption would have mislabelled five cards: 2023-06-13 (7:30 PM),
  2023-07-18 and 2024-07-16 (9:30 AM), 2023-08-15 and 2024-08-20 (6:00 PM), and
  2026-07-22 (1:00 PM). Two workshops with no record carry a blank time row
  rather than an asserted hour.
- **The public listing was not the universe.** `yt-dlp` on `/videos` returned 64
  videos; the authenticated uploads playlist returned 357. The real inventory was
  86 board videos needing 66 cards, not 57 needing 39 — nine 2023–24 workshops,
  two standing meetings and seven unlisted recordings were invisible until the
  token existed. Scope drawn from an unauthenticated listing must be re-derived
  once credentials do.
- Left alone deliberately: two Meet-the-Candidates forums and one advocacy clip
  (not board meetings, so a "REGULAR MEETING" card would misdescribe them), and
  `_ZMz5-A7Pl4`, a 2025-03-08 upload stuck in `processingStatus: processing` with
  `duration: P0D` and no thumbnails ever generated.
- Adds `reauth_youtube.py`: the stored refresh token had expired, because the
  OAuth consent screen is still in *Testing* — Google expires those weekly.
- Prior thumbnails were backed up before any overwrite.

### Every inbound text is logged and shown in /admin — 2026-08-11

- New `sms_inbound` table (`schema/0014_sms_inbound.sql`) and an **Inbound texts**
  panel in `/admin`, showing sender, message, who handled it, and what we replied.
- Records all four dispositions: `local` (handled here), `relayed` (a peer took
  it), `relay_failed` (peer unreachable or rejected the signature), and
  `unrouted` (nobody claimed it — a 403 and no reply). `unrouted` is the row type
  most worth having, since those messages were previously invisible everywhere
  except Twilio's own console, precisely because nothing claimed them.
- Required lifting the command grammar out of the request handler into
  `ownerCommandReply()`. Every branch used to `return twiml(...)` directly, so
  there was no single point where the outcome was known and therefore nowhere to
  log it. Branches now return a string and the handler logs once before replying.
- Logging is best-effort and swallows its own errors: a failed insert must never
  turn a working reply into a 500.
- `from_number` is stored in full, unlike `tsdfeedback-2026`'s copy which hashes
  it. Hashing is right there — its subjects are survey respondents and it only
  needs to correlate. Here the panel already lists registrants' numbers, sits
  behind 2FA, and has one user; a log whose sender you cannot read does not
  answer the question you opened it to ask.
- **Deploy propagation nearly produced a false bug report.** Two of the first six
  test messages did not log, which looks exactly like a dropped write. They had
  hit pre-deploy isolates with no logging code at all. A clean 12-of-12 run
  minutes later confirmed no loss. Same lesson as the auth sweep: measure, don't
  infer, and not immediately after deploying.

### Inbound SMS becomes a router — 2026-08-10

- A phone number has exactly one `sms_url`, so the project holding it holds *all*
  inbound traffic. `+12489271666` points here, and `tsdfeedback-2026` is about to
  start texting **members of the public** for survey phone verification. Those
  people reply — STOP, questions, the code sent back — and under the old handler
  every one of those hit `From !== twilio_to` and got a silent 403 that the owning
  project never saw.
- New `sms_routes` table (`schema/0013_sms_routes.sql`). The first enabled route by
  priority whose `to_number`, `from_number` and `pattern` all match wins; `NULL`
  means "any". `endpoint IS NULL` handles it here, otherwise it relays.
- **Seeded to reproduce the previous behaviour exactly**, verified after deploy:
  owner `1 999` / `2 999` / `YES 99` / `hello` all answer as before, and a stranger
  still gets 403 when no route claims them. The old hardcoded owner test now lives
  in the data as `from_number='$owner'`.
- **Signature validation stays first and unconditional.** It is the one check that
  cannot be delegated to a peer, because verifying it needs the account auth token
  — which is precisely what peers are not given.
- Relay is an HMAC-SHA256 POST signed over `timestamp + "." + body`, so a captured
  request cannot be replayed. 5s timeout, inside Twilio's ~10s abandonment. A dead
  peer produces a plain apology to the sender, not a 500 and not silence —
  exercised against a not-yet-existing endpoint.
- `/admin/sms-routes` lists (secrets as a length, never a value), creates, updates
  and deletes; `/admin/sms-routes/check` sends a signed probe carrying no message
  and reports whether the peer holds the same secret, distinguishing *secrets
  differ* from *unreachable*.
- A route whose regex will not compile is skipped and logged, never thrown. One bad
  pattern must not take the webhook down for every other project.
- **First match wins, so a broad low-priority pattern silently swallows everything
  below it.** Owner routes sit at 10/20 so a project added at 50 cannot capture `1`
  or `YES 4`. Prefer `from_number` over body patterns: no pattern distinguishes two
  projects that both want the word "STOP".
- Contract for peers, with a verification snippet, in **`docs/SMS_ROUTING.md`**.

### Approve registrations by text — 2026-08-10

- `/register` now texts the owner the applicant's name, email, phone and reason.
  Reply **`1`** to approve or **`2`** to decline, optionally with an id. Twelve
  seconds from submitted form to approved account, measured end to end.
- A bare `1`/`2` acts only when exactly one registration is pending; with several
  it lists them and asks for an id. Guessing would grant archive access to
  somebody never vetted, which no text message takes back.
- **Digits, not words, because of reserved carrier keywords.** `YES`, `START`,
  `UNSTOP` and the STOP family are intercepted on US long codes before a TwiML
  reply is delivered. Observed live: a bare `YES` reached the Worker, validated
  its signature and generated the correct reply, and the reply never arrived —
  no error anywhere, a healthy-looking invocation in `wrangler tail`, and simply
  no `outbound-reply` in the message log. A keyword *with* an id (`YES 4`) passes
  through; only the bare word is caught.
- TwiML replies quote registrant emails, the first user-controlled content to
  reach that XML, so it is escaped now — a stray `&` is enough for Twilio to drop
  the response.
- New **`docs/ACCESS_CONTROL.md`** documents the whole gated path end to end:
  registration → approval → sign-in → question moderation → admin 2FA, both SMS
  reply grammars, the three call sites `twilioReady()` gates, a signed-probe
  recipe for testing the webhook without a handset, and break-glass procedures.

### Admin login is now two-factor — 2026-08-10

- `/admin` takes the admin key **and** a six-digit code texted to
  `bot_config.twilio_to`. The key no longer authenticates anything on its own;
  it gates *sending* the code, which is what stops an unauthenticated caller
  billing SMS and ringing the owner's phone at will. Sessions last 12 hours.
- **The browser no longer stores the admin key at all.** It lives in a JS
  variable for the seconds between requesting and redeeming a code; only the
  expiring session token is persisted. A stolen browser profile is now worth one
  lapsing session rather than the permanent secret.
- `x-admin-key` against `/admin/*` returns 401 by design — there is no bypass
  header, because one would make the second factor decorative. Scripted reads go
  to D1 directly; `assistant/README.md` documents the break-glass insert into
  `admin_sessions` for when SMS is unavailable.
- New tables in `schema/0012_admin_2fa.sql`. Both are read through `env.DB` and
  never `botCfg()`: that cache has a 60s TTL and would let verify read back a
  hash from before start wrote it — a login broken for exactly one minute.
- Codes are single-use, expire in 10 minutes, allow five attempts, and the
  attempt counter increments *before* the comparison so a crash mid-verify
  cannot hand out a free guess.
- **`--file` cannot apply migrations with the current token.** It uses D1's
  import endpoint and fails `Authentication error [code: 10000]` where
  `--command` succeeds against the query endpoint with the same credentials.
- **Deploy propagation is slow enough to fool a verification sweep.** For several
  minutes after `wrangler deploy`, the custom domain served a mix of old and new
  code — old-key requests returned 200 about a third of the time while
  `*.workers.dev` was already consistently 401. Cache-busting and
  `deployments status` (100% one version) both ruled out the obvious
  explanations and pointed the diagnosis the wrong way. **Sample an auth change
  dozens of times over several minutes before believing it.** The final sweep was
  0 leaks in 120 requests.

### Twilio A2P 10DLC approved; SMS staged but not yet armed — 2026-08-10

- **The campaign is VERIFIED** (`CM8330793…`, TCR `CJ6Z6E9`, 0 errors), five days
  after the 2026-08-05 resubmission rather than the 2-3 weeks budgeted. The
  corrected payload — distinct samples, no embedded links or phone, blank opt-in
  keywords, a MessageFlow quoting the live consent checkbox — is what carriers
  approved.
- **`date_updated` is not stamped on the transition to VERIFIED.** It still reads
  `2026-08-05T19:22:20Z`, identical to `date_created`, so the record looks
  untouched even though the state changed. Read `campaign_status`; the timestamp
  is not evidence of anything.
- **Approval arms nothing.** Three separate things still gated SMS: no `twilio_*`
  rows existed at all, the number was still on Twilio's demo responder, and the
  balance ($1.14) was under the campaign's own $2/month fee.
- **The inbound webhook was pointing at `demo.twilio.com`.** Now
  `/api/assistant/twilio/inbound` — and the prefix is the trap. `worker.js` routes
  on `p = url.pathname.slice("/api/assistant".length)`, so the `"/twilio/inbound"`
  in the handler is the *sliced* path, not a URL. Set verbatim from the source it
  404s, failing exactly like the demo URL it replaced: silently, with questions
  stuck in `awaiting_approval`. Probed both paths to confirm (403 vs 404).
- **A real message reached a real handset**: `SM1b57de5d…` → `delivered`, no error,
  $0.0083, Verizon. Sent through the Messages API *before* arming the Worker, which
  separates "is A2P working" from "is my code working" for the price of one
  message. It also settles the `From:` question — sending from the number rather
  than `MessagingServiceSid` does get A2P treatment, so `twilioSend()` is fine as
  written. The message reported `queued` on POST and only `delivered` on the
  follow-up read, which is the documented trap observed live.
- **Arming is staged behind one row.** `twilio_sid`/`twilio_from`/`twilio_to` are
  written; `twilio_token` is held back so `twilioReady()` stays false. That makes
  the flip a single deliberate statement instead of a side effect of a four-row
  batch.
- **`twilioReady()` gates two things, not one.** Besides OTP delivery it drives
  `const moderate = twilioReady(cfgA)` in `/ask`, so arming silently turns on
  question moderation for every user. Worth knowing before deciding it is an
  OTP-only change.
- **Consent is not a phone number on file.** `/otp/start` requires
  `sms_consent === 1`; row 6 carried the fictional placeholder `+12485550199` and
  a NULL consent, and would have kept falling through to email. Moved to the real
  handset with consent and a timestamp.
- Recorded that the auth token **cannot** move to an `SK…` key without a code
  change: `twilioSigValid()` HMACs webhooks with the account auth token, which is
  what Twilio actually signs with, and `twilioSend()` reuses `twilio_sid` as both
  Basic-auth user and URL account.
- Deleted a junk registration (`asdc@gmail.com`, fictional number) after checking
  the predicate hit exactly one row and no sessions or questions.

### Re-summarization campaign — status 2026-08-08

- **`packets` at 58/151; every year from 2017 onward is complete.** 2020, 2019,
  2018 and 2017 all closed out (2017 finished 2026-08-08), so with the four
  finished campaigns the archive is fully re-summarized from **2017 through
  2026**. What remains is 2010-2016: 93 batches / 334 agents, with 2016 at 2/15.
- **Coverage is reconciled across all five manifests, not any one done-count.**
  The per-year check in `docs/RESUMMARIZE.md` keys off the document key
  (`2018_117_…`), never the URL path — packet-era folders carry placeholder
  dates, and tallying by path once reported 2019 complete with six batches left.
- **Working order changed to descend by year, ascend within it.** `pack()` seeds
  one wave per split batch then fills with singles, and past 2018 every remaining
  batch is a split, so `next` kept reaching outside the year in hand. Waves are
  now hand-claimed via `take_lease()` (there is no `claim` subcommand) and run
  January→December inside each year, because a year read in order is legible:
  the March resolution siting a building, the December one moving it, the January
  one correcting a contractor's name.
- **The arithmetic ban still holds — 0 derived, 0 unknown across every batch this
  session** (1,700+ figures over 17 batches). Three batches did fail FABRICATED
  first, always the same way: cross-document figures quoted in connective
  narrative. `validate_fanout.py` checks each figure against *that batch's own
  source*, so "the same buyer that took Section 16 for $3,383,000.00 in March" is
  true, absent from December's packet, and correctly rejected. Fix is to keep the
  connection but make it nominal — "the Section 16 land" — not to drop it.
  Documented with examples in `docs/RESUMMARIZE.md`.

### Documentation of what the packets turned out to say

Two findings worth recording because they resolve questions the earlier summaries
raised without answering:

- **The Early Childhood Center moved sites in Dec 2017, not later.** The Mar 21,
  2017 resolution sited it on "approximately 8 acres of Section 16"; item 8.E of
  Dec 19, 2017 relocates it to the Niles Continuing Education site, creates the
  ECC Fund, transfers $4,700,000 from Capital Maintenance, restricts revenue from
  *any* property sale through 2020-06-30 to it, appoints Barton Malow CM of
  record, and supersedes all conflicting prior resolutions. That supersession is
  why Section 16 could later be sold whole and why the preschool was built at
  205 Square Lake Road.
- **The Jan 2018 "corrected asbestos resolution" is confirmed at both ends.** The
  original (Dec 19, 2017) names NOVA Environmental — the district's abatement
  *consultant*, not a bidder — at "$82,700.00.00" with a doubled decimal. The
  correction substitutes Qualified Abatement at $82,700.00.

### Captions

- **All 41 channel videos now carry the speaker-attributed SRT track.** The final
  15 were pushed 2026-08-08.
- **A pre-flight `captions.list` audit is now the documented first step**, because
  the owed list carried in notes (12) was wrong in both directions: two videos
  believed owed had already landed before an earlier quota 403, and five 2025
  videos had never been captioned and were on no list. `captions.list` is 50
  units against `insert`'s 400 — auditing every video costs about five uploads.
- **Fixed `TITLE_BY_VID` for `42C3J23nSgY`.** It named the 2024-01-16 video
  "Organizational and Regular Meeting" while the channel and `manifest_2024.json`
  both title it "Standing Meeting". The map derives the local `.srt` filename, so
  the mismatch made the script print `MISSING …srt` and skip the video silently
  rather than fail — that video had been uncaptioned since the 2024 backfill.

### Verification

- **Turnstile 403s server-side calls to our own `/api/*`.** `curl`/`urllib`
  against `/api/summary?...` now fails regardless of User-Agent, and returned a
  plausible `0` length before the 403 was spotted — which reads exactly like "the
  summary never stored". All read-back verification goes to D1 directly via
  `wrangler d1 execute --remote`. The column is **`verbose`**, not
  `summary_verbose`; schema is
  `summaries(url TEXT PRIMARY KEY, paragraph, page, verbose, updated)`.
  Recorded in `docs/OPERATIONS.md` and `docs/RESUMMARIZE.md`.
- **The arithmetic ban held across every campaign** — 0 derived and 0 unknown in
  every batch. The one apparent violation was a malformed thousands separator in
  the source (`$3,488.377.00`), not a fabrication.
- **The split path is proven.** Nine split batches ran across the first two
  `packets` waves, up to 7 sections for the Dec 2019 packet, all clean —
  section-notes-then-synthesise preserves figure fidelity.
- **Measured costs recorded in docs/RESUMMARIZE.md.** Agent spend runs ~3.6x a
  batch's source tokens. Cost per agent ranges 1.9 (small documents) to 3.2
  (split-heavy packets); `PTS_PER_AGENT = 4.9` is a ceiling, not an estimate.
  Sizing a split-heavy wave at a split-light rate overshot the 90% release line
  to 96%.
- Three gaps were found by reconciling what *should* have been processed against
  what was: 395 documents in no manifest, 24 catalogued but never batched, and 14
  clean batches misreported as failed. All closed; `stage_campaign.py --dry-run`
  reproduces the reconciliation on demand.


- Assistant: **email sign-in codes are LIVE** via Resend from
  `admin@karpowitsch.org` (domain DKIM/return-path verified 2026-08-03; apex
  MX/SPF untouched — iCloud receiving unaffected). Channel ladder active:
  SMS once Twilio's 10DLC campaign is armed → email meanwhile. First real
  account validated end-to-end (register → approve → emailed code).

- Assistant: optional **Twilio SMS moderation** — with `twilio_*` rows in
  `bot_config`, each question from an approved account holds in
  `awaiting_approval` and the owner gets an SMS with the question; reply
  `YES <id>` / `NO <id>` (signature-verified, owner's number only) or use the
  new `/admin` buttons. Unconfigured, questions flow straight through; failed
  sends degrade to unmoderated instead of stranding the asker.

## [0.18.2] — 2026-08-07

**Correction: the YouTube quota is real, and we exhausted it.**

- Measured consumption for the day is **~20,600 units**, about 2.1x the 10,000-unit
  default — so this project has a raised quota, and the day's work spent all of it.
  Seven `videos.insert` calls account for 11,200 (54%); the rest is ~8,000 in caption
  inserts and updates plus verification reads.
- The 0.16.0 note read the first six uploads succeeding as evidence the ceiling was
  not binding. That was premature: it is binding, just further out than the default
  arithmetic predicts. Once exhausted, **even a 50-unit `captions.list` read 403s**,
  so verification is impossible until reset (midnight Pacific).
- Practical budget for planning: ~1,650 per meeting to publish a video, ~400 for a
  new caption track, ~450 to update one. A full backfill day is roughly a dozen
  meetings, not unlimited.

## [0.18.1] — 2026-08-07

**Caption coverage: the 2024 season was never in the captions manifest.**

- `upload_captions.py` listed 31 meetings — 12 from 2026, 19 from 2025, and **none
  from 2024**. All ten 2024 videos have therefore never carried a caption track, and
  the attribution fixes made to 2024-04-16 and 2024-05-21 had nothing to update.
  All ten are now in the manifest with their titles; a dry run resolves each SRT to
  its video.
- Outstanding caption pushes, all blocked on YouTube's daily quota (403, exhausted
  after the day's seven video uploads and ~20 caption operations):
  the ten 2024 tracks, plus 2025-10-14 and 2026-02-24 whose attribution changed
  today. Their transcripts and site pages are already correct — only the caption
  files lag.

## [0.18.0] — 2026-08-07

**Archive-wide attribution inspection: two trustees were quoted on nights they were absent.**

- Built an attendance table for **96 meetings** by parsing every minutes document's
  roll call, then checked all 41 transcripts against it. Five flags, three of them
  false positives worth recording: Potts (2024-04-16) and Melton (2024-05-21) spoke
  as residents *before* joining the board, and **Alic (2025-10-07) was participating
  remotely** — the minutes say "connected via remote communications", which the
  `present were` list does not contain.
- **Two were real.** On 2025-05-20 and 2025-10-14 the vice president chaired while
  President Philippart was absent, and the identifier — expecting the president to be
  chairing — put 1,437 and 1,759 words in her mouth. Both clusters are Vital Anne;
  on 2025-10-14 the speaker's own opening line is "welcome to the October 14th Board
  of Education meeting. We have 6 of our 7 trustees present". Relabelled.
- **Absence vs remote participation** is now documented as a distinct trap: read the
  whole attendance paragraph, not the roll-call list.

### The 13 unnamed-twin candidates

Six resolved, seven deliberately left alone rather than guessed:

| Meeting | Cluster | Resolution |
| --- | --- | --- |
| 2024-04-16 | C | Karl Schmidt — reads public-comment cards aloud |
| 2024-05-21 | C | Karl Schmidt — "I'll read—", "Just get through it. Okay, moving on." |
| 2025-03-18 | B | Nancy Philippart — calls each trustee for comments (one student line rides along mid-cluster and cannot be split out) |
| 2025-05-20 | B | Vital Anne — opens the meeting alongside cluster A |
| 2025-10-14 | B | Vital Anne — "Resolution passes.", "Mr. Haupt." |
| 2026-02-24 | B | Vital Anne — recognitions floor management |
| 2024-04-16 | D | left — interjections mixed with a student's remarks |
| 2024-12-17 | F | left — chair vs Hauff unresolved |
| 2025-02-25 | D | left — a recognitions reader the minutes do not name |
| 2025-04-22 | E | left — mixed, includes a roll-call "I'm here." |
| 2025-12-16 | F | left — reads honoree names; reader vs chair unresolved |
| 2026-01-20 | C | left — merged: chair's roll calls plus a trustee's "Support." |
| 2026-04-21 | B | left — chair-like, but the adjacency points at Machesky |

- Unattributed after the pass: 0.0% on 2025-03-18, 2025-05-20 and 2026-05-19; 1.4%
  on 2026-02-24; 9.2% on 2025-10-14.
- **Pending:** the 2025-10-14 and 2026-02-24 caption tracks — YouTube's daily quota
  hit 403 mid-run. Everything else is pushed.

## [0.17.1] — 2026-08-07

**A second form of the split-cluster failure, which the earlier fix cannot catch.**

- On 2026-05-19 `Speaker B` was President Anne's own voice split into a second
  cluster — 35 short floor-management turns that alternate with cluster A rather
  than converse with it, on a night the minutes record Anne presiding. Fixed by
  override; her share goes 2,243w → 2,358w.
- The distinction that matters: `clean_mapping()` merges twins the identifier
  *named* (`Nancy Philippart - 1` / `- 2`). When it names one twin and leaves the
  other unlabelled, there is no suffix to strip and the twin ships as a bare
  `Speaker` letter. Only an explicit override fixes that.
- A scan of all 41 transcripts finds **13 clusters with the same profile** (≥12
  turns averaging ≤6 words). They are *not* uniformly chair twins: sampling the
  content shows some are the chair (2024-04-16 reading public-comment cards,
  2025-10-14 calling on a trustee), one is a student introducing herself by name
  (2025-03-18, "my name is Vanessa Liu"), and several are recognitions readers.
  Each needs its own evidence pass; blanket-merging would fabricate attributions.
- Also named 2026-05-19's award nominator from the minutes — Rebecca Roy, who
  nominated honoree Matt Snitgen — via a timestamp split rather than labelling the
  whole cluster, since its last turn is a different voice.

## [0.17.0] — 2026-08-07

**The 2025 season is whole: Feb 11 rejoined from its two part uploads.**

- The Feb 11 workshop existed only as two YouTube parts, and **TelVue has no Feb 11
  recording at all** — its catalogue jumps from Jan 21 to Feb 25 — so there was no
  pristine single source to re-download. Both parts were pulled at full quality and
  rejoined losslessly (concat demuxer, stream copy) into one 4:02:26 video, uploaded
  as `1-P9EUyx9N0`. The minutes record the workshop running 6:00 p.m. to 10:00 p.m.,
  which matches the joined runtime and confirms nothing is missing.
- Re-transcribed as one meeting from the joined full-quality stereo audio (the muxed
  360p track is weaker) using the new **2025 H1 era keyterms**: 12 clusters,
  **7.7% unattributed**, and the identifier's three `Nancy Philippart - N` clusters
  collapse correctly onto one person.
- **All 19 recorded 2025 meetings are now live.** The two part videos remain on the
  channel and can be deleted.
- `docs/TRANSCRIPTION.md` now records that **the TelVue catalogue is the player
  root** — one request with a browser UA returns the station's whole gallery with air
  dates. Bisecting the id space does not work: ids are global across TelVue's
  customers, so nearly every probe lands on another station and returns a blank title.

### Found while enumerating

- **2025-05-06 is on TelVue** (media 951580) but the season notes list it among the
  meetings that "were not televised". That claim is wrong for at least this date; the
  workshop exists in D1 and a recording exists. Not yet transcribed.

## [0.16.0] — 2026-08-07

**The 2025 season is published — all six TelVue-only recordings are on the channel.**

- Uploaded, wired and captioned in one pass: Jan 21 organizational (`sTzIheFJq-A`),
  Feb 25 (`uhNHN8v5O2g`), Mar 8 Winter Retreat (`ePCmC8TTgrw`), Oct 14
  (`cjjyxD3_Z8A`), Nov 18 (`MpmAQMClpiA`) and Dec 16 (`t1a1rKAYn4E`). Titles follow
  the channel convention, `YYYY-MM-DD - Troy (MI) School District - Board of
  Education - <Kind>`, taken from the staged filename so they match exactly.
- **18 of the 19 recorded 2025 meetings are now live** with embed, chapters, named
  transcript and an "English (speaker-attributed)" caption track — verified through
  the Data API, one track per video, 6 of 6. Only Feb 11 stays off: it exists on the
  channel as two part uploads rather than one recording.
- The day's quota absorbed six `videos.insert` (1,600 each), six thumbnails and
  thirteen caption pushes. **Corrected in 0.18.2:** this was read at the time as
  the 10,000-unit ceiling not being binding. It is binding — the project simply has
  a raised quota, and later work in the same day exhausted it.
- `manifest_2025.json` now records every meeting's real `yt:` source, and
  `upload_captions.py` carries all six new videos.

## [0.15.1] — 2026-08-07

**Cleared the split-cluster artifact out of everything already published.**

- The nine 2025/2026 transcripts carrying `Nancy Philippart - 1` / `- 2` labels
  (and 2025-11-18's nine `Unknown - N` clusters) were regenerated offline from
  their stored transcript ids, so `clean_mapping()` now normalises what ships.
  2025-11-18's unplaceable clusters correctly fall back to Speaker letters
  instead of a fabricated "Unknown" name.
- **`upload_transcript.py` had its own `namer()`** reading the raw mapping, so
  fixing the transcriber alone would have left the site serving the artifact
  after the deliverables were clean. It now shares `clean_mapping`. Seven live
  meetings re-uploaded; `/api/recording` verified artifact-free on all seven.
- Deliverables in `transcripts/` and the staged SRTs in the YouTube upload kit
  refreshed for all nine. Caption tracks re-pushed for the seven with videos —
  two updated, and five that turned out never to have been pushed at all, which
  also clears five of the queued 2025 caption backlog.
- 2025-02-25 and 2025-11-18 remain local-only: they are TelVue recordings whose
  videos are still staged for upload, so they have no D1 rows and no captions.

## [0.15.0] — 2026-08-07

**The rest of the 2024 season, and a vocabulary per era.**

### Meeting recordings — 2024 complete

- The five first-half meetings — Jan 16 (organizational), Feb 27, Mar 19, Apr 16,
  May 21 — are transcribed, audited and live. Every recording the channel holds
  for 2024 is now on the site; D1 goes 29 → 34 recordings.
- Two meetings needed the degenerate-diarization remedy, and one needed it twice.
  Apr 16 came back as **2 clusters for 94 minutes**; full-fidelity stereo at
  `--min-speakers 6` gave 9, and `--min-speakers 14` gave **30 clusters, 24
  named**. Mar 19 returned 4 clusters for 2.5 hours — above the ≤3 flag but
  plainly collapsed — and the hi-fi re-run doubled it. Cluster count has to be
  judged against duration.
- YouTube 403'd the two longest downloads. `-f 140/bestaudio` with retries fixes
  it; overriding the player client does not (it leaves only image formats).

### `era_keyterms.py` — the vocabulary has to match the era

- New: harvests an era's people out of its own board minutes — attendance roll
  calls, movers and supporters, presenters with titles, student representatives,
  podium speakers — and merges them with the base vocabulary. One list per
  six-month era.
- The 2025-26 list does not merely omit older names, it **pulls unfamiliar ones
  toward the district names it contains**: two 2024 meetings produced
  `Ryan Zawislak` and `Brian Zawislak`, Zawislak being a district surname in that
  list, where the minutes say Ryan Stasinski and Brian Fahnestock.
- Run against 2024 H1 it recovered both speakers that had been demoted to
  `Public commenter` for lack of a reliable name: **Brian Fahnestock** (Baker
  Middle School teacher) and **Katie Starn**, whom the chair had announced as
  "Katie Skarn". Run against 2024 H2 it confirmed the other three demotions were
  right — those commenters are named nowhere.

### Fixed — the anchor labeller was eating the first letter of titles

- `^\d[\s.A-F]*` was meant to strip an agenda-item prefix but kept consuming
  letters A-F from the title itself: "4.E. Establish Fund Depositories" became
  "Stablish Fund Depositories", "5.F Food Service Contract" became "Ood Service
  Contract", "2.A Athens Boys Soccer" became "Thens Boys Soccer". A bare `^\d`
  also swallowed the year off "2024 Proposed Bylaws". Now the marker must be
  complete — digits, optional letter, a dot, whitespace — before anything is
  stripped. All ten 2024 meetings had their anchors regenerated and re-uploaded.

## [0.14.0] — 2026-08-07

**The 2024 season opens, and speaker attribution gets a gate.**

### Meeting recordings — 2024 season, first wave

- **Five meetings live**: the newest recorded 2024 regular meetings — Jun 20,
  Sep 17, Oct 15, Nov 19, Dec 17 — transcribed, audited and wired to the site
  with embed, chapters and named transcript. 24 → 29 recordings in D1.
- `transcription/manifest_2024.json` catalogues all 23 board meetings of 2024
  against D1: ten have video on the channel, and 13 (every workshop, both June
  specials, the Jul 16 and Aug 20 regulars) have no recording located anywhere —
  recorded as `src: null` with a note rather than left as a silent gap.
- Two rosters, because the season has two: `speakers_2024.json` and
  `speakers_2024_h1.json`. The 2024 board is the pre-election seven (Schmidt
  president, Anne vice president, Hauff secretary — Melton, Potts and Zendler
  were not seated until 2025), and Business Services passes from Rick West to
  Daniel Trudel mid-year. Each meeting's candidate list was then narrowed to
  who the minutes record as present.

### `audit_attribution.py` — the check that uses evidence the audio cannot supply

- New: speaker word-shares plus four flags — DEGENERATE (≤3 clusters),
  UNATTRIBUTED (>30% of words on bare Speaker letters), **ABSENT** (words
  attributed to someone the minutes record as absent) and **MISSING** (a trustee
  recorded present who never speaks). The last two are checkable only against the
  roll call the minutes print, which is the point.
- It earned itself on the first pass: on Dec 17 the vice president chaired
  because the president was absent, and on two other nights a trustee was out.
  Every out-of-roster name the identifier produced was then run against that
  meeting's minutes — confirming presenters and student representatives,
  correcting what the STT mangled (`Macy Justice` → Maisie Justes, `Kris Bunch`
  → Chris Bunch, `Seo-Wee Kim` → Seowoo Kim), and demoting to `Public commenter`
  the two names it had read off the chair's uncertain announcements.
- `Ryan Zawislak` was the sharpest catch: a student introducing himself on camera,
  pulled toward a district surname that sits in the keyterms vocabulary. The
  minutes name him Ryan Stasinski.
- Unattributed words after the pass: 0.5% / 9.1% / 10.8% / 16.1% / 27.5%.

### Fixed — split-cluster indices were reaching readers

- When one voice diarizes into several clusters, the identifier maps each to the
  same candidate and disambiguates with a trailing index. Those indices were
  being written verbatim, so a reader saw `Nancy Philippart - 1`, `- 2` and
  `- 3` as three speakers. `clean_mapping()` strips the suffix and the clusters
  collapse back onto the one person.
- The same fix rescues the `Unknown` filter, which tested for equality and so
  never caught the `Unknown - 1` the API actually returns.
- **This is a pre-existing defect in published output**: nine 2025/2026
  transcripts in `transcripts/`, their rows in `transcript_utts`, and their
  YouTube caption tracks all carry the artifact. Re-running each meeting's
  `transcribe_meeting.py --transcript-id` is free and offline; re-pushing the
  captions is quota-bound.

## [0.13.0] — 2026-08-04

**The 2025 meeting season, passwordless sign-in, and A2P-compliant SMS.**

### Meeting recordings — 2025 season (and 2026 captions)
- **All 19 recorded 2025 meetings transcribed** (~43 hours; the Jan 14, May 6,
  Jul 15 and Aug 19 meetings were never televised) with the 2025 roster
  (`transcription/speakers_2025.json` — Dr. Philippart chairing). Attribution
  QA'd the same way as 2026: three degenerate-diarization meetings re-run with
  hi-fi stereo + `speaker_options` hints (Jun 3: 2 clusters → 11, 2.7%
  unattributed), nine more fixed by evidence (self-introductions, minutes
  roll-calls, content ownership).
- **12 meetings live on the site** with embed + named transcript + agenda
  chapters. Season state machine-readable in
  `transcription/manifest_2025.json` (src `yt:`/`telvue:`, site-eligibility,
  channel title).
- **`transcription/upload_videos.py`** (new): resumable `videos.insert` +
  2-second title-card `thumbnails.set`, reusing the captions OAuth. Used to
  publish the TelVue full recordings of Jun 3 + Nov 11 (`XM0MoYkdd9g`,
  `kXSehoFagAQ`), replacing the two-part uploads; six more TelVue-only 2025
  videos are downloaded and staged in `~/Downloads/youtube-upload/`.
- **`transcription/upload_captions.py`** (new): batch `captions.insert/update`
  of the speaker-attributed SRTs — all 12 × 2026 videos done (track "English
  (speaker-attributed)"); 14 × 2025 queued. Desktop-app **loopback OAuth**
  (Google's device flow rejects `youtube.force-ssl`); refresh token self-saves
  to tsd-secrets.env. Pending work is **YouTube-quota-bound**: 10K units/day,
  1,600/video upload, 400/caption.
- **Trustee name corrected: Ayesha Potts** (was "Ayessa" — a typo the curated
  roster inherited from two source documents). Fixed in roster/keyterms/specs/
  transcripts/live D1 (179 speaker labels) and burned into the uploaded
  captions. The spoken text was never affected — the two spellings are
  homophones.

### Ask the Archive — auth, moderation, compliance
- **Passwordless sign-in**: registration drops the password (name, email,
  mobile, reason); sign-in texts/emails a 6-digit one-time code (hashed at
  rest, 10-min expiry, 5 attempts, 1 send/min, no account enumeration).
  Channel ladder: **Twilio SMS when the A2P campaign is armed → Resend email
  meanwhile → closed if neither**.
- **Email codes are LIVE via Resend** from `admin@karpowitsch.org` (domain
  verified 2026-08-03; DKIM + return-path in the Cloudflare zone; apex MX/SPF
  untouched — iCloud receiving unaffected). Graph mailer kept dormant (the
  tenant has no Exchange).
- **Twilio SMS question moderation**: with `twilio_*` in `bot_config`, each
  question holds `awaiting_approval` and the owner approves by SMS reply
  (`YES <id>` / `NO <id>`, signature-verified, owner's number only) or /admin
  buttons.
- **A2P 10DLC compliance** (campaign rejection 30909 → fixed): express,
  affirmative, unchecked **SMS-consent checkbox** on /ask with full carrier
  disclosures (frequency, STOP/HELP, "consent is not a condition"); corrected
  campaign payload as a runnable script; **Cloudflare Turnstile** on register
  and sign-in (`scripts/turnstile_enable.sh` sets sitekey+secret atomically in
  `bot_config`; worker verifies `turnstile_token` server-side).
- **/privacy + /terms** pages (plain-language, FoxHall-style), linked from
  registration, /ask footer, and the site footer.
- **Search modes** on the main page: "📄 Document Search" (active) beside
  "🎓 AI Search" with accretion-gradient animated text and a *coming soon*
  pill linking to /ask.

## [0.12.0] — 2026-08-02

**🎓 Ask the Archive** — registration-gated public Q&A answered by a local
Claude Code instance. `/ask`: register → owner approves in `/admin` (admin key)
→ sign in → ask; caps 600 chars, 2 open, 10/day. Worker `/api/assistant/*`
holds users/sessions/questions in D1 (PBKDF2-100k passwords, cookie sessions,
stale-answer retry). `assistant/runner.py` polls outbound from the owner's
machine (no tunnel): Haiku topic gate (strictly Troy SD board business, polite
decline otherwise) → Opus 5 via `claude -p` caged to `Bash(curl:*)` against the
site's own search API, usage streamed and killed past 100K weighted tokens per
question (input x1, cache-write x1.25, cache-read x0.1, output x5 — measured:
a good cited answer ≈ 42K weighted). launchd plist + Mac Mini README included.
Found along the way: the zone WAF 403s non-browser UAs (runner sends one), the
CLI repeats per-message usage on every content block (dedupe before summing),
and the result event's usage is the authoritative session total.

- Singularity polish: the accretion disk now visibly rotates (two sweeping
  density arms + tangential motion streaks, additive blending); the equalizer
  is **real** — a precomputed 12-band spectrum of the actual track (~10 KB of
  derived band energies, no audio redistributed) synced to the YouTube player's
  reported `currentTime`; the footer easter-egg 🕳️ gained a spinning conic
  accretion ring so it catches the eye.
- Batch transcription tooling: `transcription/run_meeting.sh` (YouTube upload →
  transcript → anchors → D1, one command, idempotent), `make_anchors.py`
  (heuristic agenda-chapter generator from transcript transition cues) and
  `speakers_2026.json` (generic identification roster). `transcribe_meeting.py`
  now persists the per-meeting resolved speaker spec (`<base>.speakers.json`)
  so the upload step shares the exact attribution. First batch: the four public
  2026 workshop videos (01-13, 02-03, 04-07, 04-28); regular-meeting videos are
  unlisted and need their IDs supplied.

## [0.11.0] — 2026-08-02

**🕳️ Easter egg: `/singularity`.** A tiny black hole in the site footer leads to a
whimsical explainer page — how the archive works (distilled from the
*BoardDocs, How It Works* write-up: PDF drawing-instructions, the
summary-as-translation-layer trick, `TEXT_CAP`, figure verification), how the
summaries bootstrap the speech-to-text vocabulary ("the paper trail teaches the
ear"), a Shannon compression-is-intelligence primer (after 3Blue1Brown's
*Reinventing Entropy*), and the black-holes-as-ultimate-computers coda
(Bekenstein bound, Lloyd's ultimate laptop). Canvas art: colorful accretion disk
with the corpus's glyphs spiraling in past the photon ring, a retro terminal in
safe orbit, starfield; translucent content panels over it. Background music
(Reznor & Ross, *Painted Sun in Abstract*) plays muted via a hidden **YouTube
embed** — deliberately not re-hosted audio, so playback stays licensed — with a
stylized equalizer and an unmute control. `prefers-reduced-motion` respected;
`noindex`.

## [0.10.0] — 2026-08-02

**Meeting recordings on the site + the transcription pipeline that feeds them.**
Full guide: [docs/TRANSCRIPTION.md](docs/TRANSCRIPTION.md).

- **Site — recording & searchable transcript per meeting.** A meeting page now
  shows its YouTube recording (privacy-enhanced embed) with agenda-item chapter
  chips and the full speaker-attributed transcript; clicking a chapter or any
  transcript line seeks the video to that moment (YouTube widget postMessage —
  no external script). Live search over the transcript with match highlighting.
  New Worker route `/api/recording`; new D1 tables `recordings`,
  `transcript_utts`, `transcript_anchors`. First meeting ingested: 2026-07-22
  regular meeting (439 utterances, 15 chapters, YouTube `v9EHA5_yT-8`).
- **`transcription/` pipeline** (new): `transcribe_meeting.py` — video →
  ffmpeg 16 kHz mono → AssemblyAI `speech_models: ["universal-3-5-pro",
  "universal-2"]` + 361-term `keyterms_prompt` + diarization → native
  speaker-identification (≤10 names/request) with manual `overrides`/`splits`
  reconciliation → txt/srt/attributed outputs (~$0.40 per 85-min meeting);
  `upload_transcript.py` — attributed transcript + hand-tuned agenda anchors →
  D1 (`wrangler --remote`, idempotent). Worked example with verified
  `speakers.json` under `transcription/examples/2026-07-22/`. API drift found by
  probing (docs lag): singular `speech_model` 400s, `min/max_speakers_expected`
  rejected, Slam-1 and `word_boost` deprecated. Key via `tsd_secrets`
  (`ASSEMBLYAI_API_KEY`), never committed.
- `scripts/proper_nouns.py`: roster refresh from the 22 Jul 2026 packet (new
  principals/APs, Kyle Anderson, Gayle Moran, student board reps, Barton
  Malow/Lecole team); new `--dataset` (local summaries-full.jsonl), `--since`
  and `--flat-out` options producing the AssemblyAI `keyterms_prompt` flat list
  (≤6 words/term). Ledger docs always excluded. Snapshot committed at
  `transcription/keyterms/`. Known homophone trap: archival "Gary Hauff" vs
  current trustee "Matt Haupt" (Hauff joined the Oakland Schools ISD board
  June 2026).

- **Corrects a wrong conclusion recorded in the previous commit.** `w2_066` was
  reported as a genuine fabrication — an agent summing bid line items to invent a
  "Bid Total" of 3,488,377.00. That was wrong. The figure **is** in the source,
  printed as `$3,488.377.00` with a period where the thousands comma belongs, and
  the agent not only transcribed it correctly but disclosed the anomaly in its own
  text. The fabrication finding came from probing the source for `3488377`,
  `3,488,377` and `3488377.00` and never for the period-separator form.
- **`validate_fanout.py` now normalises malformed thousands separators.**
  `classify()` stripped `[,\s]` but not a period acting as a separator, so a
  correct transcription of a malformed source figure was classified `derived` and
  requeued **forever** — the batch could never pass, and `next` retries failures
  ahead of real work, so it would have burned one agent per wave indefinitely.
  Only tokens carrying more than one period are touched; a single period is a
  decimal point and stripping it would invent figures 100x too large.
  - With the fix `w2_066` validates clean (25 exact, 1 spaced, 0 derived) and the
    campaign returns to **0 derived, 0 unknown across 7,130 figures**.

- **New `scripts/build_dataset.py` + four downloadable artifacts** (docs/DATASET.md).
  The summaries answered "which document mentions X" well and budget questions
  badly, because prose cannot be summed or trended. Now:
  - `corpus-map.jsonl` (2,798 docs, 0.5 MB gz) — every paragraph summary in one
    file, **~370K tokens**, so a model holds the district's entire board history
    in context and reasons across all of it at once rather than retrieving a few.
  - `summaries-full.jsonl` (3.5 MB gz) — all three tiers; the archive.
  - `figures.csv` (334,163 rows, 8.0 MB gz) + `documents.csv` — every currency
    figure in the source text with its preceding label, ±80 chars of context and
    its chunk id. **Nothing is computed**: `--verify` re-reads each source chunk
    and confirmed all 334,163 amounts appear verbatim (0 unverifiable). Consumers
    do their own arithmetic on rows they can trace, because a derived number in a
    CSV looks authoritative and gets charted.
  - Normalising url/title out of `figures.csv` into `documents.csv` took it from
    132.8 MB to 65.0 MB — the difference between fitting in git and not.
  - Documented the **packet-era gap**: pre-2020 meetings are single bundled PDFs,
    so 2018 and 2019 have 0 budget-*titled* documents despite ~2,400 chunks each.
    The figures are indexed; the titles are not. Filter those years by label, not
    title.

- **`resummarize_queue.py next` now fails closed.** `usage()` returned
  `(None, None)` on any exception and `next` skipped its **entire** headroom check
  when the value was `None` — so an unreadable or malformed usage snapshot
  silently released a full 8-agent wave instead of blocking one. A guardrail that
  disappears when its input is missing is worse than no guardrail, because the
  output looks identical to a wave that was checked and approved.
  - It now also rejects readings it cannot *trust*, in both directions:
    `resets_at` in the past (the hook has not rewritten the file for the new
    window, so the percentage describes the **expired** one — reads high), and a
    snapshot older than 10 minutes (usage continued since — reads low, which is
    the direction that releases work into a nearly-spent window).
  - `--force` / `TSD_QUEUE_FORCE=1` overrides. Forced past an untrustworthy
    reading, the wave is emitted **untrimmed** with a warning rather than sized
    against a number already declared unreliable.
  - Found after a fresh-mtime snapshot reported 88% while its `resets_at` was
    158 minutes in the past; the window had in fact rolled and usage was 2%.
    A fresh mtime does not mean fresh numbers — `resets_at` is the field that
    tells you.

## [0.9.0] — 2026-07-28
Bring the working set under the repo; keep the secrets out of it.

- **The corpus, campaign artifacts and backups now live inside the checkout.**
  `$TSD_BOE_ROOT` defaults to `<repo>/data/tsd-boe-data` (was
  `~/Downloads/tsd-boe-data`), resolved from `__file__` rather than `$HOME`, so it
  follows the checkout instead of assuming one machine's layout. Changed in the
  same **12** modules v0.8.5 touched, so the pipeline cannot half-move.
- **`.gitignore` now decides what reaches GitHub, not folder location.** Committed:
  manifests, `resummarize/<campaign>_out/` (agent output) and
  `resummarize/stores/` (~15 MB). Ignored: `data/` (3.7 GB corpus + 147 MB
  backups) and `resummarize/<campaign>/` batch text (25 MB, regenerable from a
  manifest's urlmap plus the corpus). Agent output is committed on purpose — it
  cannot be rebuilt without paying for Opus again, and the queue derives its
  done/pending state from it, so a fresh clone resumes a campaign correctly.
- **New `tsd_secrets.py`.** Resolves exported env var → `$TSD_SECRETS_FILE` →
  `~/Downloads/tsd-boarddocs-keysandsupportingfiles/tsd-secrets.env`. `summarize.py`,
  `upload_d1.py` and `upload_cloudflare.py` use it, so no pipeline command carries
  `R2PUT_SECRET=<secret>` any more, and a missing secret fails with an actionable
  message instead of an opaque HTTP 403.
- **Secrets and the ingest Worker moved to
  `~/Downloads/tsd-boarddocs-keysandsupportingfiles/`.** `_tsd_ingest/worker.js`
  string-compares an inline `SECRET` constant; with the corpus now *inside* the
  repo, "outside the repo folder" stopped being incidental and became the actual
  boundary keeping that constant off GitHub.
- Docs: README data-layout tree, ARCHITECTURE, OPERATIONS (new "support folder"
  section, secret-free command blocks), TOOLING (new Secrets section), RESUMMARIZE
  (state table now records what is and isn't committed).

## [0.8.9] — 2026-07-28
Fix three path bugs that made a second re-summarization campaign unrunnable.

- **The campaign's three directories were resolved independently and drifted.**
  `validate_fanout.py` takes its batch-text dir from its own `TSD_FAN_IN`, which
  `resummarize_queue.py` never set — so running wave2 with
  `TSD_FAN_MANIFEST`/`TSD_FAN_OUT` left the validator reading the *first*
  campaign's input dir, where none of its batch files exist. It died on
  `FileNotFoundError`, returned no output, and `validated()` read that empty
  result as "no batch is clean".
  - wave2 reported **0 done / 14 failed** when all 14 were in fact **100% clean**
    (2,321 figures, 0 derived, 0 unknown). Because `next` retries failures first,
    the next wave would have re-run 8 known-good batches at ~39 points of a 5-hour
    window while leaving the 107 genuinely-missing ones untouched.
  - All three paths now default off the manifest stem; the queue passes them to
    the validator explicitly; a non-zero validator exit is reported instead of
    being indistinguishable from total failure.
- **`validate_fanout.py` no longer aborts on a missing batch-text file** — it
  returns `NO_SOURCE` for that batch and continues, the same defence the existing
  `KeyError` guard provides.
- **`resummarize_workflow.js` used `process.env.HOME`**, but workflow scripts have
  no Node API: it threw `process is not defined` and killed the run before any
  agent started. Every earlier launch passed `args.dir`, which short-circuits the
  `||` and hid it. Now a literal path, and `next` emits `dir`/`inDir`/`outDir`, so
  a wave launched straight from the queue can't be pointed at the wrong campaign.

## [0.8.8] — 2026-07-27
Fix the v0.8.7 fallback: it was returning a 1-byte body, silently.

- **v0.8.7 shipped a broken transport.** It replayed requests as an in-page
  `fetch()` on the BoardDocs origin. BoardDocs answers those with `HTTP 200` and a
  **one-byte body** (`' '`) — so the fallback "succeeded" while returning nothing,
  and the 200 status meant it never raised. Measured against a *healthy* tenant
  (`vsba/loudoun`), so this is a standing anti-scraping response, not an artifact of
  the outage that was happening at the time.
- **Now uses Playwright's `APIRequestContext`** (`context.request.fetch`), which
  issues through the browser's own network stack and cookie jar. On the identical
  URL: **36,645 bytes vs 1 byte**. Verified against live BoardDocs — byte-identical
  to `urlopen` except a single character in the `info-server` field
  (`Diligent-Secaucus3` vs `…2`, i.e. a different backend in their pool) — and all
  three `--browser` modes re-verified under a simulated 403.
  - Drops the JS + chunked-base64 marshalling entirely; `res.body()` returns bytes.
- **Corrects a wrong conclusion recorded in v0.8.7.** That entry blamed the 1-byte
  body on a degraded BoardDocs. It is unrelated to health — it is how BoardDocs
  answers page-context fetches.
- **Outage scope, measured.** The 2026-07-27 failure was tenant-scoped: every
  `go.boarddocs.com/mi/…` path timed out at 30s with `504`, *including a
  nonexistent Michigan district*, while `vsba/loudoun` served in 0.5s and
  `ca/scusd` returned a fast 404. Documented in OPERATIONS as the way to tell a
  dead shard from a block: fast response of any status = healthy tenant.

## [0.8.7] — 2026-07-27
Headless-Chrome fallback transport, and stop reporting outages as tracebacks.

- **`download_troysd.py --browser {auto,always,never}`** (also `$BD_BROWSER`).
  When BoardDocs blocks the plain HTTP client, the same request is replayed as a
  credentialed `fetch()` executed inside a live headless-Chrome page on the
  BoardDocs origin, so it carries the cookies, headers and TLS fingerprint the CDN
  expects. `auto` (default) engages only after the normal retries exhaust on a
  **401/403/429**, then stays engaged for the rest of the run; `always` uses the
  browser for everything; `never` is the old behaviour. Requires
  `pip install playwright && playwright install chromium` — without it the fallback
  is skipped with a note rather than failing.
  - One browser is started lazily and reused, closed via `atexit`.
  - Verified byte-identical to `urlopen` on both JSON (77,628 B) and a real PDF
    (96,466 B, chunked base64 path), and 4xx maps back to `HTTPError`.
- **Clear failures instead of tracebacks.** A fatal network error now prints one
  actionable line and exits 2, distinguishing a server-side 5xx ("wait, the crawl is
  resumable") from a block ("try `--browser always`"); `KeyboardInterrupt` exits 130.
- **Guard the silent-degradation case.** During a 2026-07-27 BoardDocs outage the
  service returned `504` to plain clients but `200 text/plain` with a **one-byte
  body** to the browser. `list_meetings()` now raises a clear error naming the
  symptom instead of an opaque `JSONDecodeError` several frames deep.

## [0.8.6] — 2026-07-27
Add `scripts/ingest_meeting.sh` — one command to add a new meeting.

- Wraps the six-step incremental ingest (crawl → extract → index → **R2 → D1** →
  Office-to-PDF) plus summary-batch prep, so the two failure modes that produce a
  *silently wrong* result can't be forgotten:
  - always crawls with **`--skip-ingested`**. The crawler's default skip test is
    "is the meeting folder on disk", which is useless on a fresh corpus — it would
    re-download the whole window and get rate-limited before reaching the new
    meeting. This is exactly what killed the daily Action.
  - always uploads **R2 before D1**, because `upload_cloudflare.py --new-only`
    treats "already in D1" as "already in R2" (see v0.8.4).
- `set -euo pipefail`, so it stops at the first failure rather than carrying on with
  a half-ingested meeting. Parses the crawler's `DONE downloaded=N … failed=K` line
  to exit early when nothing new arrived and to warn on partial 403 failures.
- Preps summary batches sized to the actual pending count (read from
  `summarize.py --stats`), then prints the two remaining steps. Generation stays
  manual — it needs Opus. `--no-prep` stops after ingest.
- Options: optional `START_DATE` (defaults to a 45-day trailing window, validated),
  `--dry-run` (crawl plan only, no secret required), `--no-prep`, `--help`.
  Honors `TSD_BOE_ROOT`, `TSD_BATCH_DIR`, `TSD_OUT_DIR`. Requires `R2PUT_SECRET`
  and fails fast, before any network call, if it is unset.

## [0.8.5] — 2026-07-27
Default the corpus root to `~/Downloads/tsd-boe-data`.

- The corpus previously defaulted to `Path.home() / "tsd-boe-data"`, dropping several
  GB of scraped documents directly into the home folder. It now defaults to
  `~/Downloads/tsd-boe-data`, alongside the other working directories.
- Changed in all **12** modules that resolve the root — `download_troysd.py`,
  `extract_all.py`, `build_index.py`, `filter_index.py`, `upload_d1.py`,
  `upload_cloudflare.py`, `summarize.py`, `count_tokens.py`, `extract_legacy.py`,
  `retrieve.py`, `scripts/convert_office.py`, `scripts/proper_nouns.py` — so the
  pipeline can't half-move.
- `TSD_BOE_ROOT` still overrides, and takes precedence exactly as before. An existing
  corpus at `~/tsd-boe-data` needs no re-crawl: move the directory, or point
  `TSD_BOE_ROOT` at it.

## [0.8.4] — 2026-07-27
Finish the 2026-07-22 ingest, and guard the R2/D1 upload-order trap in code.

- **2026-07-22 Regular Meeting is fully live**: 25 documents to R2, 170 chunks to
  D1, 15 Office→PDF previews (corpus total 1,432 → **1,447**), and all 25 three-tier
  summaries stored. Corpus is back to **2,798 docs / 2,798 summarized / 0 pending**,
  across **419 meetings**. Three of the 28 crawled files carry no extractable text
  (2 legacy `.doc`, 1 scanned PDF); since the R2 upload iterates `chunks.jsonl`,
  those are neither searchable nor in R2 and remain reachable via BoardDocs only.
- **Upload-order bug, now guarded.** `upload_cloudflare.py --r2 --new-only` decides
  what to push by asking D1 and treats "already in D1" as "already in R2". Running
  `upload_d1.py` first therefore makes every new doc look uploaded, silently pushing
  nothing to R2 and leaving the viewer to 404. Documented in v0.8.3's runbook; now
  enforced at both ends:
  - `upload_d1.py --new-only` prints an ordering reminder when it has new rows
  - `upload_cloudflare.py --r2 --new-only` flags the ambiguity when it finds nothing
    new, instead of reporting success
- **New `upload_cloudflare.py --meetings LIST`** — recovery path that filters by
  comma-separated, case-insensitive substrings of `"<meeting_date> <source path>"`
  and ignores D1 entirely, so a meeting can be re-pushed to R2 after the trap is
  sprung: `--r2 --meetings 2026-07-22`.
- Docs: corrected corpus counts (`README` ~2,800 docs, `TOOLING` 1,447 converted);
  de-pinned the summary model to "Claude Opus"; documented that `--store-dir` must
  run *after* chunks reach D1 (`/summaryput` reads chunk metadata to build `sum:`
  rows); added an OPERATIONS section on writing small summary batches inline rather
  than through the subagent fan-out, and one on rebuilding the local corpus — which
  is disposable, unlike D1 and R2.

## [0.8.3] — 2026-07-26
Remove the GitHub Actions. BoardDocs blocks the runner IP, so CI ingest can't work.

- **Removed** `.github/workflows/update-boarddocs.yml` and
  `.github/workflows/verify-boarddocs.yml`. Ingest and the drift check are now run
  locally, on demand — see [docs/OPERATIONS.md](docs/OPERATIONS.md).
- **Why**: v0.8.2 correctly diagnosed the wasted re-crawl and fixed it, but the fix
  proved the remaining problem is not volume. With `--skip-ingested` the runner
  loaded the 418-meeting skip set, skipped the 33-document 2026-06-16 meeting, and
  reached the new 2026-07-22 meeting **5 seconds** into the crawl — then still took
  `403 Forbidden` on `list-files` for nearly every agenda item. The identical crawl
  from a home IP completes with **zero** 403s. BoardDocs is blocking the datacenter
  IP itself, so no amount of pacing or retry makes CI ingest viable.
- `download_troysd.py` keeps `--skip-ingested` — it's still useful for crawling from
  a machine that doesn't hold the corpus. Docstrings reworded away from CI framing.
- Docs updated: `README`, `docs/TOOLING.md`, `docs/ARCHITECTURE.md`, and
  `docs/OPERATIONS.md` (the "Daily update Action" runbook is replaced by an
  "Adding a new meeting" one, plus a note on why it isn't automated).

## [0.8.2] — 2026-07-26
Make the CI **crawl** incremental, not just the upload — the daily Action had
never ingested a document.

- **Bug**: every `update-boarddocs` run since v0.8.0 reported success with
  `new_docs=0` and skipped the upload steps. The crawler decides what to skip from
  **local meeting folders**, and the runner's workspace is empty every run
  (`0 meeting folder(s) already saved locally`), so it re-downloaded the entire
  45-day window daily. BoardDocs 403s the runner IP partway through — the 2026-07-24
  log shows 16 files fetched, then `403 Forbidden` on everything after, including
  both the 2026-06-16 Special and the new **2026-07-22 Regular** meeting
  (`DONE downloaded=16 skipped=0 failed=12`). The v0.8.1 retry/backoff was active and
  still lost; the fix is to stop making the requests at all.
- `download_troysd.py`: new **`--skip-ingested`** — seeds the skip set from the live
  site's public, read-only `/api/meetings` (env `TSD_MEETINGS_URL`) in addition to
  local folders, so a throwaway workspace skips meetings already in D1. New
  `meeting_key()` normalizes the folder-name round-trip (`7:00 PM` on BoardDocs vs
  `7 00 PM` in D1) so the two spellings compare equal. Falls back to local-only
  skipping with a warning if the endpoint is unreachable; `--recheck` still forces a
  full re-walk.
- `update-boarddocs` Action crawls with `--skip-ingested`, cutting a typical run from
  ~40 documents to just the new meeting; `BD_DELAY` raised `0.6` → `1.0` now that the
  request count is small.
- Fixed the always-blank `Detected new docs:` log line — it read
  `steps.detect.outputs.new_docs` from inside the step that sets it.
- Crawled the missed meetings locally (home IP is not blocked): **2026-07-22
  Regular Meeting, 28 files downloaded**. 2026-06-16 Special has no public files.
  (Ingest of that crawl completed in v0.8.4 — 25 of the 28 files carry extractable
  text and reached D1/R2.)

## [0.8.1] — 2026-07-15
Harden the crawler against BoardDocs rate-limiting.
- `download_troysd.py`: all BoardDocs HTTP now goes through a `_send()` wrapper with
  **bounded retry + exponential backoff (jittered)** on the intermittent
  `403/429/5xx` BoardDocs throws at automated clients (seen on the CI runner IP for
  `list-files`), plus an optional per-request delay. Env-tunable: `BD_RETRIES` (4),
  `BD_BACKOFF` (2.0s), `BD_BACKOFF_CAP` (30s), `BD_DELAY` (0s).
- `update-boarddocs` Action crawls with `BD_DELAY=0.6`, `BD_RETRIES=5` to pace the
  datacenter-IP crawl under the limiter.

## [0.8.0] — 2026-07-15
Corpus fully summarized, and a daily incremental ingest Action.
- **All 2,773 documents summarized** (2010–2026): the three-tier Opus backfill is
  complete — **0 pending**. Ran as budget-paced 150-doc drips, oldest years last.
- **Office → PDF conversion complete**: all **1,432** DOCX/PPTX source docs have
  preview PDFs in R2 (`scripts/convert_office.py`, resumable done-list).
- **Daily ingest Action** — `.github/workflows/update-boarddocs.yml`: crawls a
  trailing window of recent meetings → extract → chunk → uploads **only new** docs
  to D1 + R2 → converts new Office docs to PDF. New docs land **without a summary**
  (`pending`); it opens/updates a GitHub issue reminding to run the local Opus drip.
  **Ingest-only** — summaries are not generated in CI (that needs Opus). Requires a
  single repo secret, `R2PUT_SECRET`; no Cloudflare API token / wrangler login.
- **Idempotent `--new-only` uploads**: `upload_d1.py --new-only` and
  `upload_cloudflare.py --r2 --new-only` upload only urls not already in D1
  (`chunks` is an FTS5 table with no unique constraint, so a blind re-insert
  duplicates rows). Backed by a new guarded **`GET /urls`** endpoint on the
  `tsd-ingest` worker.
- Docstrings/docs refreshed: `build_index.py` no longer claims Workers AI / Vectorize
  embedding (search has been D1 FTS5 since v0.4).

## [0.7.0] — 2026-07-05
Meeting browse + acronym search (Tier-2), and time formatting.
- `worker.js`: bidirectional **acronym/synonym expansion** in `ftsQuery` (RIF, IEP, ISD, CTE, MTSS, GSRP, RFP, MOU, SPED, SEL, ELL, PD → FTS phrases); new `/api/meetings` + `/api/meeting` endpoints.
- `public/index.html`: **📅 Browse meetings** timeline (year-collapsible → meeting → its full document set); meeting times shown as `7PM` / `6:30 PM`.
- Decision/outcome badges evaluated and **not built** — vote data is motion-level in ~130 sparse minutes docs; item docs carry blank vote templates (no reliable per-doc signal).

## [0.6.0] — 2026-07-05
Search filters, BoardDocs deep-links, and a corpus date fix (Tier-1).
- **Document-type filter** (Resolution / Financial / Budget / Policy / Presentation / Contract / Other), **sort** (relevance / newest / oldest), **group-by-meeting** — all URL-synced and on the MCP `search` tool.
- **Meeting-type** toggle (All / Regular / Workshop / **Special** = the other types) + **year** multi-select; viewer **Back** returns to the prior results (history state + URL sync).
- **BoardDocs deep-links**: `bd_links.js` generated from `boarddocs_unids.json` (100% doc coverage), bundled into the worker; each result gets a "View on BoardDocs" link.
- **Meeting-date fix**: 130 packet-era docs (2010–12 / 2018–19) had placeholder folder dates; `build_index.py` now recovers the real date+type from the filename (`022718RegMtg`), and D1 was backfilled.

## [0.5.0] — 2026-07-05
Summaries at scale + summary-driven search.
- **Three-tier summaries** (paragraph / single-page / verbose) generated locally with **Opus 4.8**, stored in a D1 `summaries` table; viewer pill-toggle + `/api/summary`. `public/summaries.json` retired.
- **Search leverages the verbose summary**: `/summaryput` writes a `sum:<url>` FTS row so a doc surfaces on its clean summary text; results de-duplicated per document.
- Tooling: `summarize.py` (`--prep-batches` / `--store-dir`, resumable pending-flag) + `scripts/summaries_workflow.js` (Opus fan-out, one agent per batch); ingest worker `/summaryput`.

## [0.4.0] — 2026-07-05
Dropped Workers AI + Vectorize; **search is now D1 full-text (FTS5 / BM25)** — free tier, no neuron cap.
- `worker.js`: D1 keyword search; `/doc` serves R2 objects **same-origin** (fixes the cross-origin PDF embed / "Object not found").
- `wrangler.toml`: `DB` (D1) + `MEDIA` (R2) bindings; AI + Vectorize removed.
- `upload_d1.py` + ingest-worker `/d1insert` — parameterized batch inserts (no `SQLITE_TOOBIG`).
- Three-tier summaries (paragraph / single-page / verbose) prototyped for 3 docs (`public/summaries.json`) with a pill-toggle viewer; docx→PDF via LibreOffice.

## [0.3.0] — 2026-07-04
Full archive + richer UI.
- **All-years backfill**: all 346 meetings (2010–2026) downloaded, extracted, chunked, embedded, and upserted to Vectorize; source docs uploaded to R2.
- `build_index.py`: added `meeting_type` (Workshop/Regular/Special/…) and `agenda_item` (parsed from filename prefix) to chunk metadata.
- `worker.js`: `search`/`fetch` now return `meeting_type`, `agenda_item`, `meeting_name`, `file`.
- `public/index.html`: result cards with meeting-type badge, formatted date, agenda chip; click-to-open inline **PDF viewer** modal with a summary slot (pending state).
- `upload_cloudflare.py`: R2 uploads via the `tsd-ingest` Worker's exact-key `/r2put` (fixes `#`/`..` filenames the `wrangler` CLI mangled); parallel uploads; Vectorize `upsert`.
- Added `tsd-ingest` throwaway Worker (`_tsd_ingest/`) for embed + exact-key R2 writes.

## [0.2.0] — 2026-07-04
From local tool to hosted RAG site + MCP.
- Repo renamed `tools-troysdboarddocs` → **`tsd-boarddocs`**.
- Restructured as a **Cloudflare Worker + Static Assets** (`worker.js`, `public/`, `wrangler.toml`) after Cloudflare's Git-connect created a Worker (not Pages).
- `build_index.py` → chunk-only (torch-free); embedding moved to **Workers AI `bge-base`** (768-d).
- New: `functions`→`worker.js` routes `/api/search`, `/api/fetch`, `/api/embed`, `/mcp` (remote MCP), else static.
- `upload_cloudflare.py`: embed via `/api/embed` → **Vectorize**; push PDFs → **R2**.
- **WebMCP** (Chrome 149 origin trial) in `index.html` via `document.modelContext.registerTool` (`search`/`fetch`); origin-trial token registered for `karpowitsch.org`.
- Deployed to `tsd-boarddocs.karpowitsch.org`; citation 404s (wrangler `#`-key bug) fixed via the ingest Worker.

## [0.1.0] — pre-2026-07-04
Local-only pipeline (as `tools-troysdboarddocs`).
- `download_troysd.py`, `extract_all.py`, `build_index.py` (local `sentence-transformers` MiniLM), `retrieve.py`, `verify_unids.py`. Local semantic search from the CLI; no cloud services.
