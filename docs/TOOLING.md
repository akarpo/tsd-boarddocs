# Tooling inventory

Every script in the repo, grouped by role, with current status. The corpus data
itself is not committed — see [ARCHITECTURE](ARCHITECTURE.md#data-flow-ingest--serve).

## Ingest pipeline (active)

| Script | Role |
|---|---|
| `download_troysd.py` | Crawl public TroySD BoardDocs; save each file under `<YYYY-MM-DD>_<meeting>/`. Incremental (`--all` / `--start` / `--end` / `--meetings` / `-y`). Also captures `boarddocs_unids.json`. |
| `extract_all.py` | PDF/DOCX/PPTX/XLSX/RTF → `.txt` mirrors in `_text/`. |
| `extract_legacy.py` | Legacy `.doc` / `.ppt` via MS Office COM (Windows only). |
| `build_index.py` | Token-window chunk `_text/` → `_index/chunks.jsonl` (sha1 ids, R2 urls, `meeting_type`, `agenda_item`; recovers packet-era dates from filenames). |
| `filter_index.py` | Drop low-quality chunks (single-char garbage from CAD/spec PDFs). |
| `upload_d1.py` | Load `chunks.jsonl` into D1 `chunks` (FTS5) via the ingest worker's `/d1insert` (parameterized batches). |
| `upload_cloudflare.py` | `--r2`: upload source docs to R2 (exact-key PUT, parallel). |

## Summaries (active)

| Script | Role |
|---|---|
| `summarize.py` | Opus summary harness. `--stats` (done/pending), `--prep-batches N --size S` (write batch files), `--store-dir DIR` (post `batch_*.json` to `/summaryput`). Resumable via the D1 pending flag. |
| `scripts/summaries_workflow.js` | Multi-agent Opus fan-out — one agent per prepped batch file; each reads its docs and writes the three tiers. `args {batches: N}`. |

## Serve (active)

| File | Role |
|---|---|
| `worker.js` | The production Worker: D1 search (`searchCore` / `ftsQuery` with acronym expansion), filters, sort, summaries, `/api/meetings*`, `/doc`, `/mcp`, static assets. |
| `public/index.html` | Single-page site: search + filters + sort + group-by-meeting + browse timeline + document viewer (PDF + summary tiers) + WebMCP. |
| `bd_links.js` | **Generated** from `boarddocs_unids.json`: doc → BoardDocs meeting UNID map, bundled into the worker for deep-links. Regenerate after a crawl (see OPERATIONS). |
| `wrangler.toml` | Worker config: `main`, `[assets]`, `DB` (D1), `MEDIA` (R2) bindings. |
| `_tsd_ingest/worker.js` | **Outside this repo.** Ingest worker: `/r2put` (exact-key R2), `/d1insert` (batch chunks), `/summaryput` (summaries + `sum:` rows). |

## Maintenance

| Script | Role |
|---|---|
| `verify_unids.py` | Daily drift check that BoardDocs identifiers still resolve; opens a GitHub issue on change. |
| `count_tokens.py` | Estimate token count for the corpus (planning utility). |

## Deprecated (kept for history)

| Script | Why |
|---|---|
| `retrieve.py` | Local CLI retriever over the pre-cloud vector index. Superseded by the hosted `/api/search`. |
| `upload_cloudflare.py --vectors` | Embedded chunks into Vectorize. Vectorize + Workers AI were dropped in v0.4 (now D1 FTS). The `--r2` half is still used. |
