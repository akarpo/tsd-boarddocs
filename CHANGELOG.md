# Changelog

All notable changes to `tsd-boarddocs` and its tooling. Dates are UTC.
Versioning is loosely semantic; tags are pushed to GitHub (`git tag vX.Y.Z`).

## [Unreleased]
- (nothing yet)

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
