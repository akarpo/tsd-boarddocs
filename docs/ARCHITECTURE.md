# Architecture

`tsd-boarddocs` ingests every public Troy School District (Michigan) Board of
Education document from BoardDocs, builds a semantic index, and serves it three
ways from a single Cloudflare Worker. Retrieval runs on our infrastructure; the
**visitor's own AI does the generation**, so there is no per-answer LLM cost.

## The three front doors (one retrieval core)

```
                         ┌───────────────────────────────┐
   people ──────────────►│  website (public/index.html)  │
   Chrome 149 agents ───►│  WebMCP tools (in the page)    │
   Claude/ChatGPT ──────►│  /mcp  remote MCP connector    │
                         └───────────────┬───────────────┘
                                         │  search(query) / fetch(id)
                                         ▼
                     Workers AI (bge-base) ► Vectorize ANN ► ranked chunks
                                         │
                                         ▼
                          citations link to source docs in R2
```

All three call the **same** `searchCore` / `fetchCore` in `worker.js`. Tool names
are `search` and `fetch` — the contract shared by OpenAI Deep Research and
Anthropic remote connectors, so one implementation works in both ecosystems.

## Cloudflare resources

| Resource | Name / location | Role |
|---|---|---|
| Worker | `tsd-boarddocs` (Git-connected) | serves site + `/api/*` + `/mcp` |
| Static assets | `public/` (via `[assets]` binding `ASSETS`) | the website |
| Vectorize | index `tsd-boarddocs`, 768-d cosine (`VECTORIZE`) | chunk vectors + citation metadata |
| Workers AI | `@cf/baai/bge-base-en-v1.5` (`AI`) | query + passage embeddings (768-d) |
| R2 | bucket `media`, prefix `troysd-boarddocs/` | source PDFs, public at `media.karpowitsch.org/troysd-boarddocs/` |
| Custom domain | `tsd-boarddocs.karpowitsch.org` | production |

Ingest also uses a **throwaway Worker `tsd-ingest`** (`worker.js` in
`_tsd_ingest/`, outside this repo) that exposes `/api/embed` (Workers AI) and a
`/r2put` endpoint writing R2 with the **exact key** — see [OPERATIONS](OPERATIONS.md).

## Data flow (ingest → serve)

```
download_troysd.py   BoardDocs  ───►  $TSD_BOE_ROOT/<meeting>/<file>
extract_all.py       PDF/DOCX/PPTX/XLSX/RTF ─► $TSD_BOE_ROOT/_text/<meeting>/<file>.txt
build_index.py       token-window chunk ────► $TSD_BOE_ROOT/_index/chunks.jsonl   (no embedding here)
upload_cloudflare.py  embed via /api/embed ─► Vectorize (upsert)
                      push source docs ─────► R2 (exact-key PUT)
```

The corpus, extracted text, and chunk file are **not** committed (multiple GB) —
they live under `$TSD_BOE_ROOT` (default `~/tsd-boe-data`). Only the tooling +
site are in git; the *data* lives in Vectorize and R2.

## Embedding

Both the corpus and every query are embedded with **`@cf/baai/bge-base-en-v1.5`**
(768-dim) so they share one vector space. BGE is asymmetric: the retrieval
instruction (`"Represent this sentence for searching relevant passages: "`) is
prepended to **queries only**, never passages. Keeping embedding on Workers AI
means the Python pipeline (and CI) needs no `torch` / `sentence-transformers`.

## Chunk / metadata schema (`chunks.jsonl`, Vectorize metadata)

| Field | Notes |
|---|---|
| `id` | sha1 of `"<meeting>\|<file>\|<idx>"` — stable, short (Vectorize id limit) |
| `text` | the chunk (also the search snippet / `fetch` body) |
| `title`, `file` | source filename (stem / full) |
| `url` | public R2 URL (citation target) |
| `meeting_date`, `meeting_name` | from the `<YYYY-MM-DD>_<name>` folder |
| `meeting_type` | derived: Workshop / Regular / Special / Organizational / Retreat / Committee |
| `agenda_item` | parsed from the filename prefix (e.g. `8.C`, `4.a`) |
| `chunk_idx`, `char_start`, `char_end` | position within the document |

Summaries live in a **separate D1 side-store keyed by document** (planned), joined
in at display time — so refreshing summaries never forces a re-embed.

## Key design decisions

- **Client generates, we retrieve.** No LLM billed per answer; the connecting
  agent (Claude/ChatGPT/browser agent) reasons over the returned chunks.
- **Worker + Static Assets, not Pages.** Cloudflare's Git-connect flow creates a
  *Worker*; `wrangler.toml` carries `main` + `[assets]` + bindings. (A Pages-style
  `pages_build_output_dir` config fails the build with "Missing entry-point".)
- **Summaries are decoupled + resumable.** Generated locally in batches with a
  "pending" flag, so ingest stays automatable and summaries backfill over days.
- **`search` + `fetch` tool names** for cross-ecosystem MCP compatibility.
