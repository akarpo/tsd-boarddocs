# Operations / Runbook

## Prerequisites

- Python 3.10+ with: `requests pypdf pdfplumber python-docx python-pptx openpyxl striprtf tiktoken`
  (no ML libs — embedding is done by Workers AI)
- `wrangler` (npm) authenticated to the Cloudflare account (`wrangler login`)
- LibreOffice (`soffice` on PATH) — only for the DOCX/PPTX→PDF conversion pass
- `$TSD_BOE_ROOT` corpus root (default `~/tsd-boe-data`)

## Full ingest (first build or full rebuild)

```bash
export TSD_BOE_ROOT=~/tsd-boe-data
export EMBED_URL=https://tsd-ingest.akarpo.workers.dev/api/embed   # or the prod domain

python3 download_troysd.py --all --yes      # BoardDocs -> $TSD_BOE_ROOT (incremental)
python3 extract_all.py                       # -> _text/
python3 build_index.py                       # -> _index/chunks.jsonl (meeting_type, agenda_item, R2 urls)
python3 upload_cloudflare.py --vectors       # embed via /api/embed -> Vectorize (upsert)
python3 upload_cloudflare.py --r2            # push source docs -> R2 (exact-key PUT, parallel)
```

`download_troysd.py` is incremental (skips meetings already local). `--vectors`
uses `upsert`, so re-running overwrites cleanly (ids are deterministic sha1s).

## Deploy (Git-connected Worker)

Push to `main` → Cloudflare rebuilds the Worker. `wrangler.toml` supplies the
entry point (`worker.js`), the assets dir (`public/`), and the `AI` + `VECTORIZE`
bindings — **no manual dashboard binding needed**. Custom domain
`tsd-boarddocs.karpowitsch.org` is attached in the dashboard.

```bash
git push            # triggers the Worker build
# local validation without deploying:
wrangler deploy --dry-run
```

## The ingest Worker (`tsd-ingest`)

Because the `wrangler` CLI truncates R2 keys at `#`, R2 uploads go through a small
throwaway Worker's R2 binding, which writes the **exact** key. It lives in
`_tsd_ingest/` (outside this repo) and exposes:

- `POST /api/embed` `{texts, query?}` → `{vectors}` (Workers AI bge-base)
- `PUT  /r2put?key=<exact key>&secret=<s>` → writes R2 verbatim (with content-type)

```bash
wrangler deploy --cwd _tsd_ingest      # deploy/refresh it
wrangler delete --name tsd-ingest      # remove it after a backfill
```

`upload_cloudflare.py` reads `R2PUT_URL` / `R2PUT_SECRET` from the environment.
For the daily Action, either keep a persistent ingest Worker or move R2 writes
into the production Worker behind auth.

## Summaries (local, resumable)

Per-document AI summaries are generated **locally in batches**, uploaded to a D1
side-store, and flagged `pending` until done — so ingest keeps running and
summaries backfill over multiple days. Model: **Opus 4.8** (highest quality),
run in budget-sized batches. New docs upload as `pending`; a later batch fills them.

## Gotchas (learned the hard way)

- **Cloudflare bot-blocks `python-urllib`** → send a browser `User-Agent`, or you
  get 403 on both R2 and Worker endpoints. (`curl` default UA is fine.)
- **`wrangler r2 object put` needs `--remote`** or it silently writes to a local
  simulation and uploads nothing.
- **`wrangler` truncates R2 keys at `#`** (and rejects `..`) → upload via the
  ingest Worker's R2 binding (`/r2put`) instead of the CLI.
- **`.gitignore` is denylist-by-default** (`/*` then whitelist) — new files must be
  explicitly `!/`-whitelisted or they won't be tracked/deployed.
- **`wrangler` has no `ai run`** for inference → embed via a deployed AI-binding
  endpoint (the ingest Worker).
- **Vectorize ids must be short** → sha1 the chunk key.
- **Cloudflare Git-connect makes a Worker, not Pages** → use `main` + `[assets]`
  in `wrangler.toml`; a `pages_build_output_dir` config fails with "Missing entry-point".
