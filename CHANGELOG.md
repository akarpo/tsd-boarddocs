# Changelog

All notable changes to `tsd-boarddocs` and its tooling. Dates are UTC.
Versioning is loosely semantic; tags are pushed to GitHub (`git tag vX.Y.Z`).

## [Unreleased]
- DOCX/PPTX/XLSX → PDF conversion at ingest + uniform in-page viewer.
- D1 summary side-store + `doc_id` join; local Opus-generated summaries (resumable, pending-flag).
- Daily GitHub Action to keep the index fresh (download → embed → upsert → R2).

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
