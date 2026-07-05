# Operations / Runbook

## Prerequisites

- Python 3.10+ with: `requests pypdf pdfplumber python-docx python-pptx openpyxl striprtf tiktoken` (no ML libs)
- `wrangler` (npm) authenticated to the Cloudflare account (`wrangler login`)
- LibreOffice (`soffice` on PATH) — only for the DOCX/PPTX→PDF viewer conversion
- `$TSD_BOE_ROOT` corpus root (default `~/tsd-boe-data`)
- The ingest worker's secret in `R2PUT_SECRET` (used for D1 / R2 / summary writes)

## Full ingest (first build or full rebuild)

```bash
export TSD_BOE_ROOT=~/tsd-boe-data

python3 download_troysd.py --all --yes     # BoardDocs -> $TSD_BOE_ROOT (incremental)
python3 extract_all.py                      # -> _text/
python3 build_index.py                      # -> _index/chunks.jsonl (meeting_type, agenda_item, R2 urls)
R2PUT_SECRET=<secret> python3 upload_d1.py             # chunks -> D1 (FTS5) via /d1insert (batched)
R2PUT_SECRET=<secret> python3 upload_cloudflare.py --r2   # source docs -> R2 (exact-key PUT, parallel)
```

`download_troysd.py` is incremental (skips meetings already local). `upload_d1.py`
uses parameterized batch inserts (no `SQLITE_TOOBIG`).

## Summaries (Opus, local, resumable)

Three-tier summaries are generated locally with **Opus 4.8** and stored in D1.
"Pending" = a doc whose `url` isn't in the `summaries` table, so this resumes
across days. Batches are fanned across Opus subagents by the workflow.

```bash
export TSD_BOE_ROOT=~/tsd-boe-data

python3 summarize.py --stats                        # done / pending counts
rm -rf /tmp/tsd_out && mkdir -p /tmp/tsd_out
python3 summarize.py --prep-batches 150 --size 10   # -> /tmp/tsd_batches/batch_NNN.json (15 files)
#   run the multi-agent workflow — one Opus agent per batch file; each writes
#   /tmp/tsd_out/batch_NNN.json = { "<url>": {paragraph,page,verbose}, ... }
#   (scripts/summaries_workflow.js, args {batches: 15})
R2PUT_SECRET=<secret> python3 summarize.py --store-dir /tmp/tsd_out   # -> D1 (+ sum: FTS rows)
```

- `--prep-batches N --size S` writes the next N pending docs (newest-first) into
  `ceil(N/S)` batch files, clearing old ones.
- The workflow's `args.batches` = the number of batch files; it parses `args`
  whether it arrives as an object or a JSON string.
- `--store-dir` posts every `batch_*.json` to the ingest worker's `/summaryput`,
  which upserts `summaries` **and** writes/refreshes each doc's `sum:` FTS row.
- Roughly ~8–10K tokens/doc on Opus; 10 docs/agent is ~20% cheaper than 5.

## BoardDocs deep-link map

`bd_links.js` (bundled into the worker) is generated from `boarddocs_unids.json`;
regenerate it after a fresh crawl updates the identifiers:

```bash
python3 - <<'PY'
import json
u=json.load(open('boarddocs_unids.json')); files,meetings=u['files'],u['meetings']
byName={}; byDateName={}
for fid,info in files.items():
    mu=info['meeting_unid']; nm=info['name']; md=meetings.get(mu,{}).get('date','')
    byName.setdefault(nm,set()).add(mu); byDateName[f'{md}|{nm}']=mu
byNameU={n:list(v)[0] for n,v in byName.items() if len(v)==1}
open('bd_links.js','w').write(
  'export const BD_BASE="https://go.boarddocs.com/mi/troysd/Board.nsf/goto?open&id=";\n'
  'export const BD_BY_DATENAME='+json.dumps(byDateName,separators=(",",":"))+';\n'
  'export const BD_BY_NAME='+json.dumps(byNameU,separators=(",",":"))+';\n')
PY
```

## Deploy (Git-connected Worker)

Push to `main` → Cloudflare rebuilds the Worker. `wrangler.toml` supplies the entry
point (`worker.js`), the assets dir (`public/`), and the `DB` (D1) + `MEDIA` (R2)
bindings — **no manual dashboard binding needed**. Custom domain
`tsd-boarddocs.karpowitsch.org` is attached in the dashboard.

```bash
git push                                       # triggers the Worker build
wrangler deploy --dry-run --outdir /tmp/wdry   # bundle + validate locally (catches import/size issues)
```

## The ingest Worker (`tsd-ingest`)

`wrangler` truncates R2 keys at `#` and can't easily write giant D1 batches, so
D1 / R2 / summary writes go through a small worker's bindings. It lives in
`_tsd_ingest/` (outside this repo) and exposes (guarded by `?secret=`):

- `PUT  /r2put?key=<exact key>` → writes R2 verbatim (with content-type)
- `POST /d1insert` `{rows}` → parameterized batch INSERT into `chunks`
- `POST /summaryput` `{rows}` → upsert `summaries` + write each doc's `sum:` FTS row

```bash
wrangler deploy --cwd _tsd_ingest    # deploy/refresh it
```

## Gotchas (learned the hard way)

- **Cloudflare bot-blocks `python-urllib`** → send a browser `User-Agent`, or you
  get 403 on R2, the Worker, and BoardDocs. (`curl` default UA is fine; BoardDocs
  itself 403s any non-browser, so verify its deep-links in a real browser.)
- **`wrangler r2 object put` needs `--remote`** or it silently uploads nothing.
- **`wrangler` truncates R2 keys at `#`** → upload via `/r2put`.
- **FTS5 `snippet()` can't be used with `GROUP BY`** → date sort uses a two-query
  path (pick the k docs by date, then fetch their snippets).
- **Giant SQL strings fail `SQLITE_TOOBIG`** → parameterized batch inserts.
- **`.gitignore` is denylist-by-default** (`/*` then whitelist) — new files/dirs
  must be `!/`-whitelisted (e.g. `!/scripts/`, `!/bd_links.js`) or they won't deploy.
- **Cloudflare Git-connect makes a Worker, not Pages** → `main` + `[assets]` in
  `wrangler.toml`; a `pages_build_output_dir` config fails with "Missing entry-point".
- **Packet-era dates**: 2010–12 / 2018–19 folders carry placeholder dates; the real
  date+type live in the filename (`022718RegMtg`) — `build_index.py` recovers them.

## Backlog

- Wire the **daily GitHub Action** (crawl → extract → chunk → D1/R2 → new docs
  land as `pending`), mirroring the `verify_unids.py` drift-check Action.
- Finish the 2025 summary backfill, then older years.
