# tsd-boarddocs

A searchable, AI-queryable archive of every public Troy School District (Michigan)
Board of Education document. It ingests BoardDocs, builds a semantic index, and
serves it three ways from one Cloudflare Worker:

1. **A search website** — [tsd-boarddocs.karpowitsch.org](https://tsd-boarddocs.karpowitsch.org)
2. **A remote MCP connector** (`/mcp`) — add it to Claude, ChatGPT, etc.; their
   agent answers questions using the `search` / `fetch` tools.
3. **WebMCP** — Chrome 149+ browser agents auto-discover the same `search`/`fetch`
   tools while on the page (via `document.modelContext`, origin-trial).

The retrieval runs on your infrastructure; **the visitor's own AI does the
generation**, so there's no per-answer LLM cost and nothing to bill.

## Architecture

```
INGEST (Python, local or GitHub Action)
  download_troysd.py   BoardDocs -> <root>/<meeting>/<file>
  extract_all.py       PDF/DOCX/PPTX/XLSX/RTF -> <root>/_text/<meeting>/<file>.txt
  build_index.py       chunk (~800 tok) -> <root>/_index/chunks.jsonl   (torch-free)
  upload_cloudflare.py  embed via /api/embed -> Vectorize;  push docs -> R2

SERVE (Cloudflare Worker — worker.js)
  /api/search  q -> Workers AI bge-base embed -> Vectorize ANN -> ranked chunks
  /api/fetch   id -> full passage text
  /api/embed   texts -> embeddings (used by the ingest step; no torch in CI)
  /mcp         remote MCP (search/fetch tools)
  else         static site from public/

DATA
  Vectorize index "tsd-boarddocs"  (768-d, cosine)  — chunk vectors + citations
  R2 media/troysd-boarddocs/       — source PDFs, public at media.karpowitsch.org
```

Embedding uses **`@cf/baai/bge-base-en-v1.5`** (Workers AI) on both sides, so the
corpus vectors and query vectors share one space. Ingest calls the Worker's
`/api/embed`, which keeps Python (and CI) free of `torch`/`sentence-transformers`.

## Scripts

| Script | What it does |
| --- | --- |
| `download_troysd.py` | Crawls the TroySD BoardDocs endpoints; saves every public file under `<YYYY-MM-DD>_<meeting>/`. Incremental (skips meetings already local). Flags: `--all` / `--start` / `--end` / `--meetings` / `-y`. |
| `extract_all.py` | PDF/DOCX/PPTX/XLSX/RTF → `.txt` mirrors in `_text/`. |
| `build_index.py` | Token-windowed chunking → `_index/chunks.jsonl` (sha1 ids, R2 citation urls, page/meeting metadata). No embedding here — that happens on Cloudflare. |
| `upload_cloudflare.py` | Embeds chunks via `/api/embed`, upserts to Vectorize, and (parallel) uploads source docs to R2. `--vectors` / `--r2` to run one phase. |
| `verify_unids.py` | Daily drift check on the BoardDocs identifiers; opens an issue if they change. |

## Data layout

Corpus root = `$TSD_BOE_ROOT` (default `~/tsd-boe-data`). The corpus, extracted
text, and chunk file are **not** committed (several GB) — rebuild with the ingest
scripts. Source PDFs live in R2; vectors live in Vectorize.

## Deploy

The repo is a **Cloudflare Worker with static assets**, deployed by connecting it
to the Cloudflare dashboard (push to `main` → build). `wrangler.toml` supplies the
entry point (`worker.js`), the assets dir (`public/`), and the `AI` + `VECTORIZE`
bindings, so no manual dashboard binding is needed. (Note: Cloudflare's Git flow
creates a *Worker*, not a Pages project — a Pages-style `wrangler.toml` fails with
"Missing entry-point".)

## Requirements (ingest)

Python 3.10+ and: `requests`, `pypdf`, `pdfplumber`, `python-docx`, `python-pptx`,
`openpyxl`, `striprtf`, `tiktoken`. Plus `wrangler` (npm) for Vectorize/R2 loads.
No ML libraries — embedding is done by Workers AI.

## Source data

All documents are public, from <https://go.boarddocs.com/mi/troysd/Board.nsf>.
This repo only fetches, indexes, and serves them. Independent project — not
affiliated with Troy School District.

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — system design, data flow, decisions
- [docs/OPERATIONS.md](docs/OPERATIONS.md) — runbook: ingest, deploy, the ingest worker, gotchas
- [docs/PROMPT_HISTORY.md](docs/PROMPT_HISTORY.md) — the prompts that shaped the project
- [CHANGELOG.md](CHANGELOG.md) — version history

## License

[MIT](LICENSE)
