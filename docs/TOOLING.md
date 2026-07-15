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
| `upload_d1.py` | Load `chunks.jsonl` into D1 `chunks` (FTS5) via the ingest worker's `/d1insert` (parameterized batches). `--new-only` uploads only urls not already in D1 (for the daily Action; FTS5 has no unique constraint). |
| `upload_cloudflare.py` | `--r2`: upload source docs to R2 (exact-key PUT, parallel). `--r2 --new-only` uploads only docs not already in D1. |
| `scripts/convert_office.py` | Convert DOCX/PPTX (and legacy `.doc`/`.ppt`) to preview PDFs via LibreOffice (`soffice`), upload to R2 as `<key>.pdf`. Resumable (`_index/converted_pdf.done`). Full corpus (1,432 files) done. |

## Summaries (active)

| Script | Role |
|---|---|
| `summarize.py` | Opus summary harness. `--stats` (done/pending), `--prep-batches N --size S` (write batch files), `--store-dir DIR` (post `batch_*.json` to `/summaryput`). Resumable via the D1 pending flag. |
| `scripts/summaries_workflow.js` | Multi-agent Opus fan-out — one agent per prepped batch file; each reads its docs and writes the three tiers. `args {batches: N}`. |

## Proper-noun sheet (custom-vocabulary export)

| Script | Role |
|---|---|
| `scripts/proper_nouns.py` | Generates the categorized proper-noun `.docx` (people, schools, programs, vendors, associations, governmental, streets, acronyms) for speech-to-text custom vocabulary — plus a flat paste-ready appendix. Pulls the clean `summaries` from D1, auto-extracts vendor firms, and merges QA-validated curated lists (financial ledgers excluded). `--qa` prints validation digests — board roll-call timeline, external-name flags, new school/acronym candidates — to extend the curated lists as older years get summarized. `--refresh` re-pulls from D1; default output is `~/Desktop`. |

## Serve (active)

| File | Role |
|---|---|
| `worker.js` | The production Worker: D1 search (`searchCore` / `ftsQuery` with acronym expansion), filters, sort, summaries, `/api/meetings*`, `/doc`, `/mcp`, static assets. |
| `public/index.html` | Single-page site: search + filters + sort + group-by-meeting + browse timeline + document viewer (PDF + summary tiers) + WebMCP. |
| `bd_links.js` | **Generated** from `boarddocs_unids.json`: doc → BoardDocs meeting UNID map, bundled into the worker for deep-links. Regenerate after a crawl (see OPERATIONS). |
| `wrangler.toml` | Worker config: `main`, `[assets]`, `DB` (D1), `MEDIA` (R2) bindings. |
| `_tsd_ingest/worker.js` | **Outside this repo.** Ingest worker: `/r2put` (exact-key R2), `/d1insert` (batch chunks), `/summaryput` (summaries + `sum:` rows), `/urls` (distinct source-doc urls in D1, for `--new-only`). |

## Automation (GitHub Actions)

| Workflow | Role |
|---|---|
| `.github/workflows/update-boarddocs.yml` | **Daily incremental ingest.** Crawls a trailing window of recent meetings → extract → chunk → upload only-new to D1 + R2 → convert new Office docs → open a "pending summaries" issue. Ingest-only (no summaries in CI). Needs the `R2PUT_SECRET` repo secret. |
| `.github/workflows/verify-boarddocs.yml` | Daily drift check on BoardDocs identifiers (`verify_unids.py`); opens/updates an issue on change. |

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
