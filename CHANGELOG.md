# Changelog

All notable changes to `tsd-boarddocs` and its tooling. Dates are UTC.
Versioning is loosely semantic; tags are pushed to GitHub (`git tag vX.Y.Z`).

## [Unreleased]
- (nothing yet)

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
