# tsd-boarddocs

A searchable, AI-queryable archive of every public Troy School District (Michigan)
Board of Education document. It ingests BoardDocs, builds a full-text index, adds
AI summaries, and serves it three ways from one Cloudflare Worker:

1. **A search website** — [tsd-boarddocs.karpowitsch.org](https://tsd-boarddocs.karpowitsch.org)
2. **A remote MCP connector** (`/mcp`) — add it to Claude, ChatGPT, etc.; their
   agent answers questions using the `search` / `fetch` tools.
3. **WebMCP** — Chrome 149+ browser agents auto-discover the same `search`/`fetch`
   tools while on the page (via `document.modelContext`, origin-trial).

Retrieval runs on your infrastructure; **the visitor's own AI does the
generation**, so there's no per-answer LLM cost. The whole system runs on
Cloudflare's **free tier** (D1 + R2 + Workers).

## What you can do

- **Full-text search** (D1 FTS5 / BM25) over ~2,773 documents (2010–2026) with
  filters: meeting type (Regular / Workshop / Special), document type
  (Resolution / Financial / Budget / Policy / Presentation / Contract / Other),
  year (multi-select), and sort (relevance / newest / oldest). Board acronyms
  (RIF, IEP, ISD, CTE, …) expand automatically to their full phrases and back.
- **AI summaries** — three tiers per document (paragraph / single-page / verbose),
  generated locally with **Opus 4.8**. The verbose summary is indexed as a
  per-document search row, so a doc can surface on its clean summary text; a pill
  toggle in the viewer switches tiers.
- **Group by meeting** and a **📅 meeting-browse timeline** (year → meeting → its
  full document set, in agenda order).
- **Inline document viewer** (same-origin PDF) with a **"View on BoardDocs"**
  deep-link to the source meeting agenda.

## Architecture

```
INGEST (Python, local or GitHub Action)
  download_troysd.py           BoardDocs -> $TSD_BOE_ROOT/<meeting>/<file>
  extract_all.py               PDF/DOCX/PPTX/XLSX/RTF -> _text/<meeting>/<file>.txt
  build_index.py               chunk (~800 tok) -> _index/chunks.jsonl   (torch-free)
  upload_d1.py                 chunks -> D1 (FTS5) via the ingest worker
  upload_cloudflare.py --r2    source docs -> R2 (exact-key PUT)
  summarize.py + scripts/summaries_workflow.js   Opus 3-tier summaries -> D1

SERVE (Cloudflare Worker — worker.js)
  /api/search              q (+ filters, sort) -> D1 FTS5/BM25 -> ranked, de-duped docs
  /api/fetch               id -> full passage text
  /api/summary             url -> the three summary tiers
  /api/meetings /api/meeting   the browse timeline
  /doc                     key -> R2 object, served same-origin (PDF viewer)
  /mcp                     remote MCP (search/fetch tools)
  else                     static site from public/

DATA
  D1 database "tsd-boarddocs"  — chunks (FTS5) + summaries; free tier
  R2 media/troysd-boarddocs/   — source PDFs, public at media.karpowitsch.org
```

Search is **keyword/BM25 over D1**, not embeddings — the corpus is dense with IDs,
proper nouns, and dollar amounts, and we generate our own summaries, so full-text
search fits better and stays on the free tier (no Workers AI neuron cap). Workers
AI + Vectorize were dropped in v0.4.

## Scripts / tooling

Full inventory + status in **[docs/TOOLING.md](docs/TOOLING.md)**. The active pipeline:

| Script | What it does |
| --- | --- |
| `download_troysd.py` | Crawls TroySD BoardDocs; saves every public file under `<YYYY-MM-DD>_<meeting>/`. Incremental. |
| `extract_all.py` | PDF/DOCX/PPTX/XLSX/RTF → `.txt` mirrors in `_text/`. |
| `build_index.py` | Token-windowed chunking → `_index/chunks.jsonl` (sha1 ids, R2 urls, meeting/agenda metadata; recovers packet-era dates from filenames). |
| `upload_d1.py` | Loads `chunks.jsonl` into D1 via the ingest worker's `/d1insert` (parameterized batches). |
| `upload_cloudflare.py --r2` | Uploads source docs to R2 (exact-key PUT, parallel). `--vectors` is deprecated (Vectorize gone). |
| `summarize.py` | Opus summary harness: `--stats`, `--prep-batches N`, `--store-dir`. Resumable via a D1 "pending" flag. |
| `scripts/summaries_workflow.js` | Multi-agent Opus fan-out (one agent per prepped batch file). |
| `bd_links.js` | Generated map (from `boarddocs_unids.json`) of doc → BoardDocs meeting UNID for deep-links; bundled into the worker. |
| `verify_unids.py` | Daily drift check on the BoardDocs identifiers. |

## Data layout

Corpus root = `$TSD_BOE_ROOT` (default `~/tsd-boe-data`). The corpus, extracted
text, and `chunks.jsonl` are **not** committed (several GB) — rebuild with the
ingest scripts. Source PDFs live in R2; searchable data + summaries live in D1.

## Deploy

A **Cloudflare Worker with static assets**, deployed by connecting the repo in the
Cloudflare dashboard (push to `main` → build). `wrangler.toml` supplies the entry
point (`worker.js`), the assets dir (`public/`), and the `DB` (D1) + `MEDIA` (R2)
bindings — no manual dashboard binding needed. (Cloudflare's Git flow creates a
*Worker*, not Pages; a Pages-style `wrangler.toml` fails with "Missing entry-point".)

```bash
git push                    # triggers the Worker build
wrangler deploy --dry-run   # local validation without deploying
```

## Requirements (ingest)

Python 3.10+ with `requests pypdf pdfplumber python-docx python-pptx openpyxl
striprtf tiktoken`, plus `wrangler` (npm). LibreOffice (`soffice` on PATH) only for
the DOCX/PPTX→PDF viewer conversion. No ML libraries.

## Source data

All documents are public, from <https://go.boarddocs.com/mi/troysd/Board.nsf>.
This repo only fetches, indexes, summarizes, and serves them. Independent
project — not affiliated with Troy School District.

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — system design, data flow, decisions
- [docs/OPERATIONS.md](docs/OPERATIONS.md) — runbook: ingest, summaries, deploy, gotchas
- [docs/TOOLING.md](docs/TOOLING.md) — every script + its status
- [docs/PROMPT_HISTORY.md](docs/PROMPT_HISTORY.md) — the prompts that shaped the project
- [CHANGELOG.md](CHANGELOG.md) — version history

## License

[MIT](LICENSE)
