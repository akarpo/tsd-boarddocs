# Changelog

All notable changes to `tsd-boarddocs` and its tooling. Dates are UTC.
Versioning is loosely semantic; tags are pushed to GitHub (`git tag vX.Y.Z`).

## [Unreleased]
- Full 2010–2026 corpus loaded into D1; DOCX/PPTX→PDF for all docs.
- Local Opus-generated summaries at scale (resumable, pending-flag), stored per doc.
- Daily GitHub Action to keep D1 + R2 fresh.

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
