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
| `scripts/ingest_meeting.sh` | **The normal way to add a new meeting.** Wraps crawl → extract → index → R2 → D1 → Office-to-PDF → summary-batch prep, forcing `--skip-ingested` and the R2-before-D1 order. `--dry-run`, `--no-prep`, optional `START_DATE` (default 45 days back). |

## Summaries (active)

| Script | Role |
|---|---|
| `summarize.py` | Opus summary harness. `--stats` (done/pending), `--prep-batches N --size S` (write batch files), `--store-dir DIR` (post `batch_*.json` to `/summaryput`). Resumable via the D1 pending flag. |
| `scripts/summaries_workflow.js` | Multi-agent Opus fan-out — one agent per prepped batch file; each reads its docs and writes the three tiers. `args {batches: N}`. |

## Proper-noun sheet (custom-vocabulary export)

| Script | Role |
|---|---|
| `scripts/proper_nouns.py` | Generates the categorized proper-noun `.docx` (people, schools, programs, vendors, associations, governmental, streets, acronyms) for speech-to-text custom vocabulary — plus a flat paste-ready appendix. Pulls the clean `summaries` from D1, auto-extracts vendor firms, and merges QA-validated curated lists (financial ledgers excluded). `--qa` prints validation digests — board roll-call timeline, external-name flags, new school/acronym candidates — to extend the curated lists as older years get summarized. `--refresh` re-pulls from D1; default output is `~/Desktop`. |

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

Full description in `docs/RESUMMARIZE.md`.

**Usage measurement:** the live rate-limit percentages are already written to
`~/.claude/usage_snapshot.json` every turn by the statusline hook — read that file
rather than trying to derive a ceiling from transcripts.
