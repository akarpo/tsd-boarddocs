# Changelog

All notable changes to `tsd-boarddocs` and its tooling. Dates are UTC.
Versioning is loosely semantic; tags are pushed to GitHub (`git tag vX.Y.Z`).

## [Unreleased]

### Re-summarization campaign — status 2026-07-31

- **Four of five campaigns complete.** `fanout` (26), `wave2` (121), `orphans` (4)
  and `remainder` (76) are all done; every document from 2021 onward is now
  re-summarized from full text. `packets` (2010-2020) stands at 17/151, worked
  newest-first: 2020 finished, 2019 partly done. 134 batches / 496 agents /
  13.67M source tokens remain.
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
