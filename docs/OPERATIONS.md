# Operations / Runbook

## Prerequisites

- Python 3.10+ with: `requests pypdf pdfplumber python-docx python-pptx openpyxl striprtf tiktoken` (no ML libs)
- `wrangler` (npm) authenticated to the Cloudflare account (`wrangler login`)
- LibreOffice (`soffice` on PATH) — only for the DOCX/PPTX→PDF viewer conversion
- `$TSD_BOE_ROOT` corpus root (default `<repo>/data/tsd-boe-data`, i.e. inside the
  checkout and gitignored; it was `~/Downloads/tsd-boe-data` before v0.9.0 and
  `~/tsd-boe-data` before v0.8.5 — point `TSD_BOE_ROOT` at an older corpus, or just
  move the directory, rather than re-crawling)
- The ingest worker's secret. **You no longer pass this on the command line.**
  `tsd_secrets.py` reads it from
  `~/Downloads/tsd-boarddocs-keysandsupportingfiles/tsd-secrets.env`
  (override with `$TSD_SECRETS_FILE`); an exported `R2PUT_SECRET` still wins if set.
  See [The support folder](#the-support-folder-keys--ingest-worker).

## Full ingest (first build or full rebuild)

```bash
export TSD_BOE_ROOT=<repo>/data/tsd-boe-data

python3 download_troysd.py --all --yes     # BoardDocs -> $TSD_BOE_ROOT (incremental)
python3 extract_all.py                      # -> _text/
python3 build_index.py                      # -> _index/chunks.jsonl (meeting_type, agenda_item, R2 urls)
python3 upload_d1.py             # chunks -> D1 (FTS5) via /d1insert (batched)
python3 upload_cloudflare.py --r2   # source docs -> R2 (exact-key PUT, parallel)
```

`download_troysd.py` is incremental (skips meetings already local). `upload_d1.py`
uses parameterized batch inserts (no `SQLITE_TOOBIG`).

### The corpus is disposable; D1 and R2 are not

`$TSD_BOE_ROOT` is a working directory — source files, `_text/` extractions, and
`_index/chunks.jsonl`. Losing it costs a re-crawl, nothing more: the durable copies
live in D1 (chunks + summaries) and R2 (source docs and preview PDFs), and
`boarddocs_unids.json` is in git. To rebuild from empty, run the block above with
plain `--all`; **do not** add `--skip-ingested`, which would skip every meeting
already in D1 and leave you with an empty corpus.

Rebuilding does not disturb the site. Re-running `upload_d1.py --all --new-only`
and `upload_cloudflare.py --r2 --new-only` afterward is a no-op for anything already
loaded, and summaries are keyed by url in D1, so they survive independently of the
local files. Only `summarize.py` needs the corpus back — it computes pending by
diffing `chunks.jsonl` against the `summaries` table.

## Summaries (Opus, local, resumable)

Three-tier summaries are generated locally with **Claude Opus** and stored in D1.
"Pending" = a doc whose `url` isn't in the `summaries` table, so this resumes
across days. Large drips are fanned across Opus subagents by the workflow; small
ones are cheaper written inline (see "Small batches" below).

```bash
export TSD_BOE_ROOT=<repo>/data/tsd-boe-data

python3 summarize.py --stats                        # done / pending counts
rm -rf /tmp/tsd_out && mkdir -p /tmp/tsd_out
python3 summarize.py --prep-batches 150 --size 10   # -> /tmp/tsd_batches/batch_NNN.json (15 files)
#   run the multi-agent workflow — one Opus agent per batch file; each writes
#   /tmp/tsd_out/batch_NNN.json = { "<url>": {paragraph,page,verbose}, ... }
#   (scripts/summaries_workflow.js, args {batches: 15})
python3 summarize.py --store-dir /tmp/tsd_out   # -> D1 (+ sum: FTS rows)
```

- `--prep-batches N --size S` writes the next N pending docs (newest-first) into
  `ceil(N/S)` batch files, clearing old ones.
- The workflow's `args.batches` = the number of batch files; it parses `args`
  whether it arrives as an object or a JSON string.
- `--store-dir` posts every `batch_*.json` to the ingest worker's `/summaryput`,
  which upserts `summaries` **and** writes/refreshes each doc's `sum:` FTS row.
- Roughly ~8–10K tokens/doc on Opus; 10 docs/agent is ~20% cheaper than 5.

**Chunks must be in D1 before `--store-dir`.** `/summaryput` reads each doc's chunk
metadata to build its `sum:` FTS row, so run the ingest steps first and summarize
last.

### Small batches

The subagent fan-out earns its overhead on a 150-doc drip. For a single new meeting
(~25 docs) it's cheaper to write the tiers inline: prep the batches, read each
`batch_NNN.json`, write `<outdir>/batch_NNN.json` in the same
`{"<url>": {paragraph, page, verbose}}` shape, then `--store-dir`. No workflow, no
subagents. Validate before storing — every input url present, no extras, all three
tiers non-empty — because `--store-dir` silently skips a file it can't parse.

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

## The support folder (keys + ingest worker)

Two things stay **outside** the repository, in
`~/Downloads/tsd-boarddocs-keysandsupportingfiles/`:

| | what |
|---|---|
| `tsd-secrets.env` | `KEY=value` lines; currently just `R2PUT_SECRET`. Mode `600`. |
| `_tsd_ingest/` | the ingest Worker (below) |

They are outside the tree for one reason: `_tsd_ingest/worker.js` string-compares
an **inline** secret constant, so anywhere under `tsd-boarddocs/` it would be one
`git add -A` from GitHub. Since v0.9.0 the corpus and campaign artifacts *are*
inside the repo, so "not in the repo folder" is no longer an accident of layout —
it is the whole security boundary, and this folder is what enforces it.

`tsd_secrets.py` resolves in this order: exported env var → `$TSD_SECRETS_FILE` →
the path above. So the pipeline commands no longer carry `R2PUT_SECRET=<secret>`,
and a missing secret fails with an actionable message instead of an opaque 403.

### The ingest Worker (`tsd-ingest`)

`wrangler` truncates R2 keys at `#` and can't easily write giant D1 batches, so
D1 / R2 / summary writes go through a small worker's bindings. It exposes
(guarded by `?secret=`):

- `PUT  /r2put?key=<exact key>` → writes R2 verbatim (with content-type)
- `POST /d1insert` `{rows}` → parameterized batch INSERT into `chunks`
- `POST /summaryput` `{rows}` → upsert `summaries` + write each doc's `sum:` FTS row
- `GET  /urls` → distinct source-doc urls already in D1 (powers `--new-only`)

```bash
wrangler deploy --cwd ~/Downloads/tsd-boarddocs-keysandsupportingfiles/_tsd_ingest
```

It also still carries an `[ai]` binding and an `/embed` route left from the
Vectorize era that v0.4 dropped; both are dead code.

**If the secret ever needs rotating**, change the `SECRET` constant in its
`worker.js`, redeploy with the command above, and update `tsd-secrets.env` to
match — the two must agree or every write returns 403.

## Gotchas (learned the hard way)

**A file with no extractor is reported once and then never counted again.** It goes
to `_text/_skipped.txt` and drops out of every subsequent total, which is how 489
documents — 14.9% of the corpus — stayed invisible to search for months while every
counter read complete. Reconcile the corpus against D1, not against the tooling's
own bookkeeping.

**"Extracted" is not "usable."** A scanned page returns its header; a subset font
with no ToUnicode CMap returns glyph ids (`/16/17/18/i255`) that have the right
shape and no words. Neither asserts a figure, so figure validation is blind to
both. And a per-page character floor is not enough on its own — a 2.3MB PDF that
yielded 302 characters clears any floor and is still a photograph, which is why
`_needs_ocr()` also tests source bytes per extracted character.

**Longer is not better when the incumbent is nonsense.** "Keep whichever result is
longer" is right for a thin scan and wrong for glyph garbage: 82,353 characters of
glyph ids beat 31,257 characters of real OCR text on length alone.

**`convert_office.py` read `R2PUT_SECRET` straight from the environment** while the
rest of the pipeline had moved to `tsd_secrets`, so step 6 of the ingest wrapper
uploaded with an empty secret and every PUT came back 403 — per file, on stdout,
with the run still exiting 0. It uses `tsd_secrets.require()` now, which says what
is missing instead.

**The Office-to-PDF done-list holds absolute paths, and a missing done-list is
not a missing conversion.** `_index/converted_pdf.done` is derived state: if it is
empty, `convert_office.py` reports "to convert 1452" even though all but a handful
are already in R2. Rebuild it by probing R2 for `<key>.pdf` rather than re-rendering
the corpus — and seed it with absolute paths, since relative ones match nothing and
silently re-upload 1,452 identical files. The script now normalises either form.

**A batch output file can keep changing after it appears.** Wave 39 wrote
`pk_013.json` three times, each shorter, all after the file first landed and with
the workflow reporting no errors. Wait for the Workflow completion notification
before validating, not for the output files to exist.



- **Cloudflare bot-blocks `python-urllib`** → send a browser `User-Agent`, or you
  get 403 on R2, the Worker, and BoardDocs. (`curl` default UA is fine; BoardDocs
  itself 403s any non-browser, so verify its deep-links in a real browser.)
- **Turnstile now 403s server-side calls to our own `/api/*`.** Since Turnstile
  went live, `curl`/`urllib` against `https://tsd-boarddocs.karpowitsch.org/api/summary?...`
  returns 403 regardless of User-Agent — a browser challenge cannot be satisfied
  from a script. Any check that reads back what the site is serving must go to D1
  instead:

      npx wrangler d1 execute tsd-boarddocs --remote --json \
        --command "SELECT length(verbose) FROM summaries WHERE url LIKE '%<file>.pdf'"

  The `summaries` schema is `(url TEXT PRIMARY KEY, paragraph, page, verbose, updated)`
  — the column is **`verbose`**, not `summary_verbose`. This bit twice in one
  session: the API returned a plausible `0` length before the 403 was noticed, which
  reads exactly like "the summary never stored".
- **BoardDocs rate-limits datacenter / CI IPs** → it intermittently `403`s the
  `list-files` call from GitHub-hosted runners — which is why ingest is not
  automated (see below). `download_troysd.py` retries with exponential backoff
  (`_send()`), tunable via `BD_RETRIES` / `BD_BACKOFF` / `BD_DELAY`. From a home IP
  a rare missed item self-heals on the next crawl; `--recheck` forces a re-walk.
  If the block persists, `--browser always` reissues every request through a
  headless Chrome network stack and cookie jar
  (`pip install playwright && playwright install chromium`); `--browser auto`, the
  default, does this only after the normal retries exhaust on a 401/403/429.
- **Never fetch BoardDocs from inside a page.** BoardDocs answers in-page
  `fetch()` with `HTTP 200` and a **one-byte body** — measured against a healthy
  tenant, so it is a standing anti-scraping response, not an outage symptom. The
  200 status makes it fail silently. Playwright's `context.request` returns the
  real content (36,645 B vs 1 B on the same URL), which is why the fallback uses it.
- **Outages are tenant-scoped.** On 2026-07-27 every `go.boarddocs.com/mi/…` path
  timed out at 30s with `504`, including a *nonexistent* Michigan district, while
  `vsba/loudoun` served in 0.5s and `ca/scusd` returned a fast 404. A fast response
  of any status means the tenant is healthy; a 30s 504 means that shard is down.
  Waiting is the fix — the crawl resumes cleanly. `list_meetings()` raises a clear
  error in that case rather than an opaque `JSONDecodeError`.
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

## Adding a new meeting (incremental ingest)

**Use the wrapper** — it enforces the two things below that silently ruin a run:

```bash
scripts/ingest_meeting.sh              # 45-day trailing window
scripts/ingest_meeting.sh 2026-08-01   # explicit start date
scripts/ingest_meeting.sh --dry-run                          # crawl plan only, no secret needed
```

It crawls with `--skip-ingested`, runs extract → index → **R2 → D1** → Office-to-PDF
in that order, stops on the first failure, exits early when nothing new was
downloaded, and finishes by prepping summary batches for exactly the pending count.
Summary generation itself is not automated (it needs Opus); the script prints the
two remaining commands. `--no-prep` stops after ingest.

### The whole chain, in the order it has to run

Worked end to end for 2026-08-18. Each step assumes the one above it.

```bash
# 1. documents
scripts/ingest_meeting.sh 2026-08-10            # crawl -> extract -> R2 -> D1 -> prep
Workflow summaries_workflow.js {batches: N}     # needs Opus
python3 summarize.py --store-dir /tmp/tsd_out

# 2. check register, if the packet carried one (step 7/7 reports it)
python3 scripts/check_register_handoff.py --stage --parse
#   then in tsd-checkregister: rebuild.py --assemble-only, validate.py,
#   check_published_figures.py, commit (Pages deploys from main)

# 3. video: find the recording on TelVue, series 4132
yt-dlp -f 2390 -o "tsd_<date>.%(ext)s" \
  https://videoplayer.telvue.com/player/i-P7YFZryO9zQNfciKbAQTp5wv5_PLoa/media/<id>
python3 transcription/upload_videos.py <mp4> --title "<channel title>" \
  --date <date> --name "<D1 meeting_name>"

# 4. transcript (refreshes the keyterm index first, then skips what already exists)
transcription/run_meeting.sh <date> "<D1 meeting_name>" <youtube-id> <workdir>
python3 transcription/name_unknown_speakers.py --d1 <date>   # public commenters
cp <workdir>/"Troy School Board Meeting - <date>".srt \
   transcripts/"<channel title>.srt"                          # captions read from here
python3 transcription/upload_captions.py --only <date>        # add the id to MEETINGS first

# 5. chapters — the YouTube description IS the anchors
python3 transcription/anchors/fetch_agenda.py <date>
python3 transcription/anchors/brief.py <date>                 # author from this
python3 transcription/anchors/apply_anchors.py <date> transcription/anchors/authored/anchors_<date>.json
python3 transcription/anchors/push_pending.py
```

**Order that matters, each learned by getting it wrong:** R2 before D1, or
`--new-only` treats "in D1" as "in R2" and the viewer 404s. Keyterms before
transcription, or the vocabulary helps the next meeting instead of this one.
Summaries before the keyterm refresh, since it reads the meeting's summaries.
Anchors before the description push, because the description is generated from
them — a meeting left on `make_anchors.py`'s draft gets a five-line agenda and at
least one chapter pointing at the wrong place.

The 4-step transcription checklist is in
[TRANSCRIPTION.md](TRANSCRIPTION.md#adding-a-new-meeting-checklist).

The manual sequence follows, for when you need to run a step on its own.

Run locally, from a checkout with the corpus at `$TSD_BOE_ROOT`:

```bash
python3 download_troysd.py --start <YYYY-MM-DD> --yes   # only meetings you don't have
python3 extract_all.py                                  # skips already-extracted files
python3 build_index.py                                  # full rebuild of chunks.jsonl
python3 upload_cloudflare.py --r2 --new-only   # R2 FIRST
python3 upload_d1.py --all --new-only          # then D1
python3 scripts/convert_office.py                       # new DOCX/PPTX -> preview PDF
```

**Upload R2 before D1.** Both steps define "new" as *not already in D1*, but
`upload_cloudflare.py` uses that as a proxy for "already pushed to R2"
(`# source already in D1 -> already pushed to R2`). Load D1 first and the R2 step
sees every new url as already present and uploads **nothing** — the docs would be
searchable but the viewer would 404. The old daily Action had them in the wrong
order; it never ingested anything, so the bug never surfaced.

Both scripts now warn about this: `upload_d1.py --new-only` prints a reminder when
it has new rows to load, and `upload_cloudflare.py --r2 --new-only` flags the
ambiguity when it finds nothing new. If you do hit it, recover with the explicit
filter, which ignores D1 entirely:

```bash
python3 upload_cloudflare.py --r2 --meetings 2026-07-22
```

`--meetings` takes comma-separated case-insensitive substrings matched against
`"<meeting_date> <source path>"`, so `2026-07-22`, `2026-07`, or a filename
fragment all work.

`--new-only` skips any url already in D1 (via the ingest worker's `GET /urls`). That
matters because `chunks` is an FTS5 table with **no unique constraint** — a blind
re-insert duplicates rows. New docs land searchable but with no summary (they show as
`pending`); run the Opus summary drip above to fill them in.

Only documents that produced extractable text reach R2 — the upload iterates
`chunks.jsonl`. Legacy `.doc`/`.ppt` (no extractor) and scanned PDFs (empty
extraction) are therefore neither searchable nor viewable; they remain reachable
through the per-document BoardDocs deep-link.

The site is API-driven (`/api/meetings`, `/api/meeting`), so a D1 insert is enough to
make a meeting appear — there is no redeploy step.

### Why this isn't automated

There were two daily GitHub Actions (`update-boarddocs`, `verify-boarddocs`), removed
in v0.8.3. **BoardDocs 403s the GitHub-hosted runner IP**, so the ingest Action never
successfully ingested a single document: every run reported success with `new_docs=0`
and skipped its upload steps. It is not a rate/volume problem — a run that skipped
straight to the one new meeting (via `--skip-ingested`) still got
`403 Forbidden` on `list-files` for nearly every agenda item. The same crawl from a
home IP succeeds with zero 403s, so ingest has to run from a residential connection.

## Backlog

**Moved to [ROADMAP.md](ROADMAP.md).** Open work is tracked there in one place; this section
kept drifting out of date because it sat in the middle of a runbook nobody re-reads top to
bottom — it still described the A2P campaign as "in carrier review" and SMS as off five days
after both stopped being true.

One item worth keeping here, because it is a runbook fact rather than planned work:

- `turnstile_enable.sh` carried a latent bug until 2026-08-05 — a multi-line `--command` value
  makes wrangler 4.x on Windows abort with "Missing required option --command" before any SQL
  executes. Fixed by putting the SQL on one line. Applies to any script in this repo that shells
  out to `wrangler d1 execute`.

## Pre-2020 extraction and the reorder pass

`extract_all.py` combines pypdf's characters with pdfplumber's reading order (see
docs/ARCHITECTURE.md). Three exclusions keep the cost sane, all env-overridable:

    TSD_REORDER_AFTER=0000-00-00   # include meetings before 2020-01-01
    TSD_REORDER_PACKETS=1          # include full-meeting packets
    TSD_MAX_REORDER_MB=0           # ignore the 15 MB size cap

The packet exclusion was originally written as a correctness judgement ("no
consistent heading/table pairing to repair"). **That was wrong** — measured on the
pre-2020 era the reorder moves 54-73% of a packet's lines and fixes real damage:
pypdf emits the agenda footer *before* the agenda. It is a speed trade-off, so it
is now a flag rather than hardcoded.

Re-extracting an era requires deleting its `_text/` output first — `extract_all.py`
skips any file that already exists non-empty, and will otherwise report a clean run
having done nothing.

    # back up, delete, re-extract (285 pre-2020 files, ~20 min)
    tar -czf ~/Downloads/tsd_text_pre2020_backup.tar.gz -C "$ROOT/_text" -T <(list)
    tr '\n' '\0' < list | xargs -0 rm -f      # NOT bare xargs -- folder names
                                               # contain spaces and it silently
                                               # deletes nothing
    TSD_REORDER_AFTER=0000-00-00 TSD_REORDER_PACKETS=1 python3 extract_all.py

## Reloading part of the corpus into D1

After re-extraction the text on disk is fixed but D1 still holds the old chunks.
`build_index.py` rewrites `_index/chunks.jsonl` wholesale, then the affected rows
must be replaced. Three traps, all hit at least once:

**1. `--truncate` deletes the whole table.** There is no targeted-delete flag and
no delete endpoint on tsd-ingest. Use `wrangler d1 execute` directly.

**2. D1 rejects long LIKE patterns.** `url LIKE 'https://media.karpowitsch.org/
troysd-boarddocs/201%'` fails with `SQLITE_ERROR 7500: LIKE or GLOB pattern too
complex`. Use `substr()` instead — the URL prefix is 47 characters, so the folder
year is `substr(url,48,4)`.

**3. Summary rows are marked on `id`, not `url`.** `/summaryput` writes one
`sum:<url>` row per document into `chunks`, carrying the document's **plain** url.
A delete keyed only on url takes the summaries with it and silently removes that
era from summary-backed search. Always exclude them:

    -- verify the predicate BEFORE converting it to a DELETE
    SELECT COUNT(*) FROM chunks WHERE substr(url,48,3)='201' AND id NOT LIKE 'sum:%';
    SELECT COUNT(*) FROM chunks WHERE substr(url,48,3)='201' AND id LIKE 'sum:%';

    DELETE FROM chunks WHERE substr(url,48,3)='201' AND id NOT LIKE 'sum:%';
    for y in 2010..2019; do python3 upload_d1.py --year $y; done

`upload_d1.py` needs `R2PUT_SECRET` or every insert returns HTTP 403.

**Verify afterwards.** `chunks` is FTS5 with no unique key, so a partial delete
plus a full reload silently doubles rows:

    SELECT COUNT(*) rows, COUNT(DISTINCT id) uniq FROM chunks;   -- must be equal

Note `upload_d1.py --year` filters on `meeting_date` while a url predicate keys on
the **folder** date, and 176 chunks disagree (a 2017 meeting filed in a 2018
folder). Confirm the two sets are identical before mixing the two.
