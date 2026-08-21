# Tooling inventory

Every script in the repo, grouped by role, with current status. The corpus data
itself is not committed — see [ARCHITECTURE](ARCHITECTURE.md#data-flow-ingest--serve).

## Ingest pipeline (active)

| Script | Role |
|---|---|
| `download_troysd.py` | Crawl public TroySD BoardDocs; save each file under `<YYYY-MM-DD>_<meeting>/`. Incremental (`--all` / `--start` / `--end` / `--meetings` / `-y`), `--skip-ingested` to skip what D1 already has. Falls back to a headless-Chrome transport when BoardDocs blocks the plain client (`--browser auto\|always\|never`). Also captures `boarddocs_unids.json`. |
| `extract_all.py` | PDF/DOCX/PPTX/XLSX/RTF → `.txt` mirrors in `_text/`. |
| `extract_legacy.py` | Legacy `.doc` / `.ppt` via MS Office COM (Windows only). |
| `build_index.py` | Token-window chunk `_text/` → `_index/chunks.jsonl` (sha1 ids, R2 urls, `meeting_type`, `agenda_item`; recovers packet-era dates from filenames). |
| `filter_index.py` | Drop low-quality chunks (single-char garbage from CAD/spec PDFs). |
| `upload_d1.py` | Load `chunks.jsonl` into D1 `chunks` (FTS5) via the ingest worker's `/d1insert` (parameterized batches). `--new-only` uploads only urls not already in D1 (FTS5 has no unique constraint). |
| `upload_cloudflare.py` | `--r2`: upload source docs to R2 (exact-key PUT, parallel). `--r2 --new-only` uploads only docs not already in D1 — **run before `upload_d1.py`**, see OPERATIONS. `--meetings 2026-07-22` re-pushes one meeting regardless of D1 state. |
| `scripts/convert_office.py` | Convert DOCX/PPTX (and legacy `.doc`/`.ppt`) to preview PDFs via LibreOffice (`soffice`), upload to R2 as `<key>.pdf`. Resumable (`_index/converted_pdf.done`). Full corpus (1,447 files) done. |
| `scripts/ingest_meeting.sh` | **The normal way to add a new meeting.** Wraps crawl → extract → index → R2 → D1 → Office-to-PDF → check-register check → summary-batch prep, forcing `--skip-ingested` and the R2-before-D1 order. `--dry-run`, `--no-prep`, optional `START_DATE` (default 45 days back). Summary prep packs by `--batch-chars` (default 96,000 ≈ 24K tokens), not a fixed document count. |
| `scripts/check_register_handoff.py` | Step 7/7. Reconciles the check-register PDFs in the corpus against the source meetings already in `tsd-checkregister`'s dataset, so a monthly register cannot sit in the archive while the spending site runs a month behind. `--stage` copies new PDFs across, `--parse` also classifies and appends them. **A parsed total that disagrees with the register's own printed TOTAL REPORT refuses the append** — that check shares no assumption with the parser, so a silently dropped row shows up there and nowhere else. Reading that total needs the second amount column; sales tax prints first. Report-only from the ingest wrapper, because staging rewrites another repo's committed deliverables. |

## Summaries (active)

| Script | Role |
|---|---|
| `summarize.py` | Opus summary harness. `--stats` (done/pending), `--prep-batches N --size S` (write batch files), `--store-dir DIR` (post `batch_*.json` to `/summaryput`). Resumable via the D1 pending flag. |
| `scripts/summaries_workflow.js` | Multi-agent Opus fan-out — one agent per prepped batch file; each reads its docs and writes the three tiers. `args {batches: N}`. |

## Proper-noun sheet (custom-vocabulary export)

| Script | Role |
|---|---|
| `scripts/proper_nouns.py` | Generates the categorized proper-noun `.docx` (people, schools, programs, vendors, associations, governmental, streets, acronyms) for speech-to-text custom vocabulary — plus a flat paste-ready appendix. Pulls the clean `summaries` from D1 **or a local dataset** (`--dataset dataset/summaries-full.jsonl`), auto-extracts vendor firms, and merges QA-validated curated lists (financial ledgers excluded; rosters refreshed from the 22 Jul 2026 packet). `--since YYYY-MM-DD` scopes the corpus; `--flat-out vocab.txt` writes the flat AssemblyAI `keyterms_prompt` list (≤6 words/term, + `.json` twin). `--qa` prints validation digests — board roll-call timeline, external-name flags, new school/acronym candidates — to extend the curated lists as older years get summarized. `--refresh` re-pulls from D1; default output is `~/Desktop`. |

## Transcription (active)

Recording → named transcript → site. Full guide: [TRANSCRIPTION.md](TRANSCRIPTION.md).

| Script | Role |
|---|---|
| `transcription/transcribe_meeting.py` | Meeting video/audio → AssemblyAI (`speech_models: ["universal-3-5-pro", "universal-2"]`, `keyterms_prompt` vocabulary, `speaker_labels`) → transcript JSON/txt/srt; `--speakers speakers.json` attributes names — reusing the spec's resolved `mapping` when present (offline, reproducible), else calling native speaker identification (≤10 names) — plus manual `overrides`/`splits`. `--transcript-id` reuses a completed transcript. Key: `ASSEMBLYAI_API_KEY` via `tsd_secrets`. |
| `transcription/name_unknown_speakers.py` | Names the diarization clusters AssemblyAI left as bare letters, by reading the chair's own introduction ("Mr. Beau Taylor first") out of the transcript. Public commenters can never be pre-rostered — their names are read off a sign-in sheet at the meeting and the identification API caps at 10 names — so this is the only handle on them. Report-only. Scans before **every** turn of a cluster, not just its first: a cluster's first appearance is often a one-word backchannel half an hour before the person actually speaks. `--d1 YYYY-MM-DD` or a transcript path. |
| `scripts/keyterms_index.py` | Grows the `keyterms_prompt` vocabulary from each meeting's own packet and records, per term, when it arrived and which document brought it. Terms are never evicted. Run **before** transcription (`run_meeting.sh` does). Exists because `proper_nouns.py` ranks the whole corpus and keeps the top 40 firms — a cap that is ours, not the API's (AssemblyAI takes 1,000 phrases) — and matches organisations by corporate suffix, so a firm named "L Mason Capitani" is invisible to it at any cap. Seeded per meeting rather than bulk-loaded: adding all 463 firms ever named would fit the budget and still be wrong, since most are one-off payees nobody says aloud. `--meeting`, `--add`, `--emit`, `--history <term>`. |
| `transcription/upload_transcript.py` | Transcript JSON + `speakers.json` + `anchors.json` + YouTube id → D1 (`recordings`, `transcript_utts`, `transcript_anchors`) via `wrangler --remote`. Idempotent per meeting; powers `/api/recording` and the meeting-page recording section. |
| `transcription/run_meeting.sh` | **Adding a meeting recording** — one command: YouTube id → audio → transcript → auto-anchors → D1. Idempotent per meeting; workdir `scratch/tsd-transcripts/` (repo-local, gitignored). |
| `transcription/make_anchors.py` | Heuristic agenda-chapter generator (transition cues, item numbers) → `anchors.json`. **Draft only** — its output needs authoring and checking; see `transcription/anchors/`. |
| `transcription/anchors/` | **The anchor workflow.** `brief.py` (agenda + current anchors + a transcript digest of the ~70 signal-bearing utterances out of ~800), `apply_anchors.py` (validates, writes D1, runs the coverage gate, queues the description rebuild), `coverage.py` (per agenda item: DISCUSSED / MENTIONED / IN CONSENT / ABSENT / UNSEARCHABLE, asserting anything DISCUSSED is anchored), `push_desc.py` / `push_pending.py` (rebuild YouTube descriptions from current D1 anchors; quota-aware queue). `authored/` holds the hand-authored anchor sets for all 41 meetings. |
| `transcription/audit_attribution.py` | The gate before a transcript ships: speaker word-shares plus four flags — DEGENERATE (≤3 clusters), UNATTRIBUTED (>30% on Speaker letters), ABSENT (words given to someone the minutes record as absent) and MISSING (a trustee recorded present who never speaks). Pass the meeting's roll call via `--absent` / `--expect`. |
| `transcription/speakers_2026.json` / `speakers_2025.json` / `speakers_2024.json` + `_h1` | Season identification rosters (≤10 names; 2025 has Dr. Philippart chairing; 2024 is the pre-election seven under Schmidt, and splits into `_h1` (West on Business Services) and the default (Trudel, from mid-year)). Per-meeting resolved specs are written next to each transcript. |
| `transcription/manifest_2025.json` / `manifest_2024.json` | The season, machine-readable: per meeting `src` (`yt:<id>` / `telvue:<mediaId>` / `local`), site-eligibility, exact channel title. Drives audio acquisition, site wiring, and the captions batch. A `src` of `null` carries a `note` saying no recording has been located — the 2024 workshops and both June specials are in that state. |
| `transcription/upload_captions.py` | Batch caption upload (Data API v3 `captions.insert`/`update`, 400/450 units) of the attributed SRTs to existing videos; re-runs update the track (use after transcript corrections). Desktop-app **loopback OAuth** — Google's device flow rejects the captions scope; `YT_CLIENT_ID/SECRET/REFRESH_TOKEN` via tsd-secrets.env, refresh token self-saves on first run. |
| `transcription/upload_videos.py` | Full video upload (`videos.insert` resumable, 1,600 units) + crest-card thumbnail via `thumbnails.py`; same OAuth. Used for TelVue-only meetings the channel lacks. Pass `--date`/`--name` so a card can be typeset when the stream shows none. |
| `transcription/thumbnails.py` | **Meeting thumbnails.** The broadcast opens on a City of Troy bumper and cuts to the TSD crest card only afterwards, so a fixed `-ss 2` grab put an undated city graphic on 35 of 57 board videos. Scans the opening for the crest card (correlation ≥0.80 against `assets/tsd_card_base.jpg`) and lifts it at full resolution; when none airs — every Workshop and the Retreat begin cold on meeting footage — retypesets the base card's header/date/time lines instead (ground rebuilt from the gap rows, Arial Black 50, matched at IoU 0.90). `verify_date()` gates the result by reading the date back off the rendered card. `--audit` classifies the whole channel. |
| `transcription/reauth_youtube.py` | Mints a fresh `YT_REFRESH_TOKEN` (loopback OAuth, `youtube.force-ssl`) and rewrites it into `tsd-secrets.env`, verifying the refresh round-trips. Run it when a call returns `invalid_grant`. The weekly expiry that stranded the token on 2026-08-17 is fixed — the consent screen for project `river-inquiry-309911` (number 589628968274, the `YT_CLIENT_ID` prefix) is now **In production** rather than *Testing*, so tokens are long-lived; publishing did not invalidate the existing one. |
| `transcription/assets/tsd_card_base.jpg` | The authentic 2026-03-17 crest card (1280×720) every typeset thumbnail is derived from. |
| `transcription/era_keyterms.py` | Builds a per-era keyterms vocabulary from that era's board minutes (roll calls, movers, presenters with titles, student reps, podium speakers) merged with the base list. One per six-month era; pass it to `transcribe_meeting.py --keyterms`. Without it the 2025-26 vocabulary pulls older names toward the district names it happens to contain. |
| `transcription/keyterms/` | Generated 361-term vocabulary snapshot (Jan 2025 → Jul 2026); regenerate with `proper_nouns.py --since 2025-01-01 --flat-out …`. |
| `transcription/examples/2026-07-22/` | Worked example: verified `speakers.json`, hand-tuned `anchors.json`, attributed transcript, `.srt`, meeting brief. |

## Secrets

| Script | Role |
|---|---|
| `tsd_secrets.py` | Resolves pipeline secrets: exported env var -> `$TSD_SECRETS_FILE` -> `~/Downloads/tsd-boarddocs-keysandsupportingfiles/tsd-secrets.env`. Used by `summarize.py`, `upload_d1.py`, `upload_cloudflare.py`, so none of them need `R2PUT_SECRET=` on the command line. `require()` fails with an actionable message rather than letting the call 403. |

## Dataset artifacts

| Script | Role |
|---|---|
| `scripts/build_dataset.py` | Builds `corpus-map.jsonl`, `summaries-full.jsonl`, `figures.csv` and `documents.csv` from D1 + the chunk index. `--verify` re-reads every source chunk to prove each of the 334K figures appears verbatim. Output is gitignored and served gzipped from R2. See [DATASET.md](DATASET.md). |

## Serve (active)

| File | Role |
|---|---|
| `worker.js` | The production Worker: D1 search (`searchCore` / `ftsQuery` with acronym expansion), filters, sort, summaries, `/api/meetings*`, `/doc`, `/mcp`, static assets. |
| `public/index.html` | Single-page site: search + filters + sort + group-by-meeting + browse timeline + document viewer (PDF + summary tiers) + WebMCP. |
| `bd_links.js` | **Generated** from `boarddocs_unids.json`: doc → BoardDocs meeting UNID map, bundled into the worker for deep-links. Regenerate after a crawl (see OPERATIONS). |
| `wrangler.toml` | Worker config: `main`, `[assets]`, `DB` (D1), `MEDIA` (R2) bindings. |
| `_tsd_ingest/worker.js` | **Outside this repo**, in `~/Downloads/tsd-boarddocs-keysandsupportingfiles/` (it holds an inline secret). Ingest worker: `/r2put` (exact-key R2), `/d1insert` (batch chunks), `/summaryput` (summaries + `sum:` rows), `/urls` (distinct source-doc urls in D1, for `--new-only`). |

## Automation

None. Ingest and summaries are both run by hand from a local checkout — see
[OPERATIONS.md](OPERATIONS.md). There were two daily GitHub Actions
(`update-boarddocs`, `verify-boarddocs`); they were removed in v0.8.3 because
BoardDocs 403s the GitHub runner IP, so the ingest Action never actually
ingested anything.

## Maintenance

| Script | Role |
|---|---|
| `verify_unids.py` | Drift check that BoardDocs identifiers still resolve. Run on demand. |
| `count_tokens.py` | Estimate token count for the corpus (planning utility). |

## Deprecated (kept for history)

| Script | Why |
|---|---|
| `retrieve.py` | Local CLI retriever over the pre-cloud vector index. Superseded by the hosted `/api/search`. |
| `upload_cloudflare.py --vectors` | Embedded chunks into Vectorize. Vectorize + Workers AI were dropped in v0.4 (now D1 FTS). The `--r2` half is still used. |

## Re-summarization fan-out

| script | what it does |
|---|---|
| `scripts/resummarize_workflow.js` | Workflow script — one agent per batch; oversized budget books split into sections then synthesized |
| `scripts/validate_fanout.py` | re-reads each batch's source, classifies every figure the agent asserted, stages only clean batches |
| `scripts/stage_campaign.py` | Stages every capped document no manifest covers into a new campaign (manifest + batch text), deriving the boundary from the corpus instead of by hand. `--dry-run` reports the plan. `--prefix` guards batch-id collisions — `wave2_manifest.json` already owns `w2_*` **and** `w3_*`. |
| `scripts/resummarize_queue.py` | derives done/failed/pending from disk; emits the next wave sized against live usage |
| `~/.claude/bin/usage5h.py` | reads the authoritative 5h/7d percentages and converts headroom into work units |

Five campaigns: `fanout`, `wave2`, `orphans`, `remainder` (all complete) and
`packets` (2010-2020, 17/151). Select one with `TSD_FAN_MANIFEST=<name>_manifest.json`;
the batch dir, output dir and store dir all default off that stem.

Full description in `docs/RESUMMARIZE.md`.

**Usage measurement:** the live rate-limit percentages are already written to
`~/.claude/usage_snapshot.json` every turn by the statusline hook — read that file
rather than trying to derive a ceiling from transcripts.
