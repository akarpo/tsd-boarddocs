# Architecture

`tsd-boarddocs` ingests every public Troy School District (Michigan) Board of
Education document from BoardDocs, builds a full-text index + AI summaries, and
serves it three ways from a single Cloudflare Worker. Retrieval runs on our
infrastructure; the **visitor's own AI does the generation**, so there is no
per-answer LLM cost. Everything runs on Cloudflare's free tier.

## The three front doors (one retrieval core)

```
                         ┌───────────────────────────────┐
   people ──────────────►│  website (public/index.html)  │
   Chrome 149 agents ───►│  WebMCP tools (in the page)    │
   Claude/ChatGPT ──────►│  /mcp  remote MCP connector    │
                         └───────────────┬───────────────┘
                                         │  search(query, filters) / fetch(id)
                                         ▼
                       D1 FTS5 / BM25  ►  ranked, de-duplicated documents
                                         │
                                ┌────────┴────────┐
                       summaries (D1)      source docs (R2, via /doc)
```

All three call the **same** `searchCore` / `fetchCore` in `worker.js`. Tool names
are `search` and `fetch` — the contract shared by OpenAI Deep Research and
Anthropic remote connectors, so one implementation works in both ecosystems.

## Cloudflare resources

| Resource | Name / location | Role |
|---|---|---|
| Worker | `tsd-boarddocs` (Git-connected) | serves site + `/api/*` + `/mcp` |
| Static assets | `public/` (`[assets]` binding `ASSETS`) | the website |
| D1 | database `tsd-boarddocs` (`DB`) | `chunks` (FTS5) + `summaries` tables |
| R2 | bucket `media`, prefix `troysd-boarddocs/` (`MEDIA`) | source PDFs, public at `media.karpowitsch.org/troysd-boarddocs/` |
| Custom domain | `tsd-boarddocs.karpowitsch.org` | production |

Ingest also uses a **throwaway Worker `tsd-ingest`** (in `_tsd_ingest/`, outside
this repo) whose bindings write D1 + R2 with exact keys — see [OPERATIONS](OPERATIONS.md).

## Search (D1 FTS5)

- The `chunks` table is an **FTS5** virtual table (`tokenize='porter unicode61'`)
  over `title` + `text`, with `meeting_date/name/type`, `agenda_item`, `file`,
  `url`, `source` as stored (UNINDEXED) columns for filtering + display.
- `ftsQuery()` tokenizes the query, quotes each token, OR-joins, and **expands
  board acronyms bidirectionally** (RIF ↔ "reduction in force", IEP, ISD, CTE, …)
  as FTS phrase alternatives. BM25 (`ORDER BY rank`) does the ranking.
- `searchCore()` fetches a window, **de-duplicates to one row per document**
  (a `sum:` summary row wins when its clean text matches best), and attaches each
  doc's `doc_type`, BoardDocs deep-link, and paragraph summary.
- **Filters** (optional, composable): `meeting_type IN (...)` or
  `NOT IN (Regular,Workshop)` (the "Special" bucket); year via
  `substr(meeting_date,1,4) IN (...)`; document type via title-keyword `LIKE`
  clauses (`DOC_TYPES` taxonomy); **sort** relevance (BM25) / newest / oldest.
  Date sort uses a two-query path because FTS5 `snippet()` can't be used with
  `GROUP BY`.

## Summaries (three tiers, in D1)

Each document gets **paragraph / single-page / verbose** summaries, generated
locally with **Opus 4.8** and stored in the D1 `summaries` table keyed by `url`.

- The paragraph shows on the result card; the viewer's pill toggle fetches the
  page + verbose tiers from `/api/summary`.
- On store, the ingest worker also writes a `sum:<url>` row into the `chunks` FTS
  with the combined summary text, so **search leverages the verbose summary** —
  the cleanest, densest representation of a document.
- "Pending" = a `url` not yet in `summaries`, so generation is **resumable** across
  days and batches. New ingested docs arrive pending; a later batch fills them.

## Meeting browse

`/api/meetings` returns one row per meeting (date, name, type, doc count,
BoardDocs link); `/api/meeting?date=&name=` returns that meeting's documents in
agenda order. The site's **📅 Browse meetings** view renders a year-collapsible
timeline; picking a meeting shows its full document set.

## BoardDocs deep-links

`boarddocs_unids.json` maps BoardDocs file UNIDs → `{meeting_unid, name}` and
meeting UNIDs → `{date, name}`. A build step distills this into `bd_links.js`
(keyed by `meeting_date|file`, name fallback; 100% doc coverage), bundled into the
worker. Each result's `boarddocs_url` is
`https://go.boarddocs.com/mi/troysd/Board.nsf/goto?open&id=<meeting_unid>`, which
opens the source meeting agenda.

## Data flow (ingest → serve)

```
download_troysd.py   BoardDocs  ───►  $TSD_BOE_ROOT/<meeting>/<file>
extract_all.py       PDF/DOCX/… ───►  $TSD_BOE_ROOT/_text/<meeting>/<file>.txt
build_index.py       token-window chunk ─► $TSD_BOE_ROOT/_index/chunks.jsonl
upload_d1.py         chunks ──────────► D1 chunks (FTS5), via /d1insert
upload_cloudflare.py --r2   source docs ► R2 (exact-key PUT)
convert_office.py    DOCX/PPTX  ───────► R2 <key>.pdf (LibreOffice preview)
summarize.py + workflow     Opus 3-tier ► D1 summaries (+ sum: FTS rows)
```

The corpus, extracted text, and chunk file are **not** committed (multiple GB) —
they live under `$TSD_BOE_ROOT` (default `~/tsd-boe-data`). Only the tooling + site
are in git; the *data* lives in D1 and R2.

### Incremental updates (daily Action)

The full pipeline above is the first build / full rebuild. Day-to-day, the
`update-boarddocs` GitHub Action keeps things fresh **without** re-processing the
corpus: it crawls only a trailing window of recent meetings, then runs the same
extract → chunk steps and uploads with `--new-only`. Because `chunks` is an FTS5
table with **no unique constraint**, re-inserting a doc would duplicate rows — so
`--new-only` first fetches the set of urls already in D1 (the ingest worker's
`GET /urls`) and uploads only the difference. New docs arrive **without a summary**
(`pending`); the local Opus drip fills them in later (CI can't run Opus). See
[OPERATIONS](OPERATIONS.md#daily-update-action-incremental-ingest).

## Chunk / metadata schema (`chunks.jsonl` → D1 `chunks`)

| Field | Notes |
|---|---|
| `id` | sha1 of `"<meeting>\|<file>\|<idx>"` (real chunks); `sum:<url>` for summary rows |
| `text` | the chunk (search snippet / `fetch` body); combined summary for `sum:` rows |
| `title`, `file` | source filename (stem / full) |
| `url` | public R2 URL (citation + `/doc` key) |
| `meeting_date`, `meeting_name` | from the `<YYYY-MM-DD>_<name>` folder (packet-era dates recovered from the filename) |
| `meeting_type` | Workshop / Regular / Special / Organizational / Retreat / Committee / Meeting |
| `agenda_item` | parsed from the filename prefix (e.g. `8.C`, `4.a`) |
| `source` | `<meeting>/<file>` for real chunks; `summary` for `sum:` rows |

`summaries` is a separate D1 table (`url`, `paragraph`, `page`, `verbose`,
`updated`), joined in at display time — refreshing summaries never touches chunks.

## Key design decisions

- **Client generates, we retrieve.** No LLM billed per answer.
- **D1 full-text, not embeddings** (v0.4). ID/proper-noun/dollar-heavy corpus +
  our own summaries → keyword/BM25 fits and stays free (no neuron cap).
- **Verbose summary is the strongest search artifact** — indexed as a per-doc
  `sum:` row so clean prose, not noisy OCR, drives ranking.
- **Worker + Static Assets, not Pages** — Git-connect makes a Worker; `wrangler.toml`
  carries `main` + `[assets]` + bindings.
- **Summaries decoupled + resumable** — Opus, local, pending-flag, backfills over days.
- **Idempotent incremental ingest** — the daily Action re-crawls a recent window and
  uploads `--new-only`; since FTS5 has no unique key, dedup is done client-side
  against `GET /urls`, so re-runs never duplicate rows.
- **`search` + `fetch` tool names** for cross-ecosystem MCP compatibility.
