# tools-troysdboarddocs

Tooling to download every public Troy School District (Michigan) Board of
Education document from BoardDocs, extract their text, and build a local
semantic-search index that can be queried from the command line.

The pipeline runs end-to-end on a single machine with no cloud services or
API keys required — embedding and retrieval are local, and **answering is done
by the Claude Code CLI prompt itself**, not an LLM API (see [Asking
questions](#asking-questions-rag) below). Most scripts work on Windows, macOS,
and Linux; only `extract_legacy.py` is Windows-only (it
relies on Microsoft Word and PowerPoint COM automation to read the obsolete
`.doc` / `.ppt` formats). See [Platform notes](#platform-notes) below.

## Pipeline

```
download_troysd.py    BoardDocs  --->  <root>/<meeting>/<file>
        |
        v
extract_all.py        PDF/DOCX/PPTX/XLSX/RTF -> <root>/_text/<meeting>/<file>.txt
extract_legacy.py     legacy .doc/.ppt via Word/PowerPoint COM (Windows only)
        |
        v
build_index.py        chunk + embed -> <root>/_index/vectors.npy + chunks.jsonl
filter_index.py       drop low-quality chunks in place (optional cleanup)
        |
        v
retrieve.py "query"   top-k cosine search over the index
        |
        v
Claude Code (CLI)     reads the retrieved chunks, answers grounded + cited
                      — the generation half of the RAG; see CLAUDE.md
count_tokens.py       per-type and grand-total token counts (cl100k_base)
```

## Scripts

| Script | What it does |
| --- | --- |
| `download_troysd.py` | Crawls BoardDocs (`go.boarddocs.com/mi/troysd/Board.nsf`) via the `BD-GetMeetingsList` / `BD-GetAgenda` / `BD-GetPublicFiles` / `BD-GetMinutes` endpoints, saving every public file under `<YYYY-MM-DD>_<meeting_name>\` plus `_download.log` and `_index.csv`. On run it lists the meetings online, shows how many you already have locally, and prompts you to fetch **all** of them, a **date range**, or a **specific picked set** — or pass `--all` / `--start` / `--end` / `--meetings` / `--meetings-file` to skip the prompt. **Incremental:** meetings already saved locally are skipped (use `--recheck` to re-verify them, `--dry-run` to preview). Individual files are skipped if already present and non-empty. It also harvests file links embedded in published **minutes** (`BD-GetMinutes`), which `BD-GetPublicFiles` never returns. |
| `audit_coverage.py` | Cross-references every live agenda item against the corpus and writes `_coverage_audit.csv` — one row per agenda item, flagging the gaps the crawler structurally can't see. A fast pre-filter uses the crawl manifest (`_index.csv`), but because BoardDocs regenerates item/file id tokens on every agenda edit, each candidate gap is then **confirmed live** — re-asking BoardDocs for the item's current public files and matching them by filename (the only stable key) against what's on disk. Statuses: `missed-fetchable` (BoardDocs serves a public file but it isn't on disk — a real crawl miss, re-run the downloader), `listed-unavailable` (the agenda lists files but they 404 — purged from BoardDocs, unrecoverable), `partial-capture` (some of the item's files captured, some not), `marker-no-file` (BoardDocs flags an attachment but exposes none publicly), and `doclike-no-file` (title reads like a document — report / findings / recommendation / presentation / … — yet nothing is attached at all, e.g. the 2024-03-05 "Levinson Report"). Read-only — it downloads no documents (just a 1-byte ranged probe to tell a real miss from a dead link). Supports `--start` / `--end` / `--gaps-only`. |
| `extract_all.py` | Walks the corpus and writes plain-text `.txt` mirrors into `_text\` for `.pdf`, `.docx`, `.pptx`, `.xlsx`, and `.rtf`. PDF extraction tries `pypdf` first, then falls back to `pdfplumber`. Records skips/errors in `_text\_skipped.txt`. |
| `extract_legacy.py` | Handles the old `.doc` and `.ppt` formats via Word and PowerPoint COM automation. **Windows-only**; exits early on other platforms with conversion instructions for LibreOffice. Restarts the COM apps every 50 files to avoid memory bloat. |
| `attachment_rate.py` | Reports what share of agenda items carry an attachment, for **Regular** and **Workshop** meetings over a trailing window (default 3 years; Special/closed meetings excluded). Uses BoardDocs' own per-item attachment marker, broken out by meeting type and calendar year. Read-only. `--years N` or `--start` / `--end`. |
| `count_tokens.py` | Estimates total corpus token cost using the `cl100k_base` (GPT-4) tokenizer as a proxy for Claude. Writes `_tokens_per_file.csv`. |
| `build_index.py` | Token-windowed chunking (~800 tokens, 100 overlap) + embedding with `sentence-transformers/all-MiniLM-L6-v2` (384-dim, runs locally). Writes `_index\vectors.npy` and `_index\chunks.jsonl`. |
| `filter_index.py` | Removes low-quality chunks (mostly single-character noise from scanned CAD/spec PDFs) in place. Keeps chunks with at least 30 word-like tokens and no more than 30% length-1 tokens. |
| `retrieve.py` | Loads the index, embeds a query, returns top-k chunks ranked by cosine similarity. Supports `--since` / `--until` date filters and a literal `--grep` substring filter. |

## Asking questions (RAG)

Retrieval is only half of a RAG system; the other half is generation. **This
repo uses the Claude Code CLI prompt as the generator** — there is no LLM API
call in the tooling. Open the repo in Claude Code and ask a question about Troy
SD board business; following the protocol in [`CLAUDE.md`](CLAUDE.md), Claude
runs `retrieve.py --full` to pull the most relevant excerpts, then answers
grounded in them, citing each claim by meeting and date — and says so when the
corpus doesn't cover the question rather than guessing.

You can also run `retrieve.py` yourself to inspect the raw matches. See
[`RAG.md`](RAG.md) for the architecture and build status.

## Coverage auditing

The crawler can only save what BoardDocs exposes as a public file attachment.
Three kinds of document slip through that net:

- **Genuinely missed** — BoardDocs *does* serve a public file, but the crawl
  didn't capture it (interrupted run, transient error). These are re-fetchable.
  (A related case: the agenda still lists files that have since been purged and
  now 404 — flagged separately as `listed-unavailable`, since nothing can be
  fetched.)
- **Non-public attachments** — the agenda marks an item "contains an
  attachment," but the file isn't exposed publicly, so it can't be fetched.
- **Never-attached documents** — a report is presented to the board straight
  from a deck and never uploaded at all (e.g. the 2024-03-05 *Levinson Report -
  Outcomes & Recommendations*, which has zero attachments on BoardDocs).

`audit_coverage.py` makes those gaps visible. It walks every live agenda and
writes `_coverage_audit.csv` — a per-item index classifying each item as `ok`,
`missed-fetchable`, `partial-capture`, `marker-no-file`, or `doclike-no-file`.
A fast pre-filter uses the crawl manifest (`_index.csv`), but BoardDocs
regenerates its item/file id tokens whenever an agenda is edited — so a captured
item can look uncaptured by id alone. Each candidate gap is therefore
**confirmed live**: the audit asks BoardDocs for the item's current public files
and checks whether those filenames (the only stable key) exist on disk. That is
what separates a real `missed-fetchable` from harmless id drift.

```bash
python audit_coverage.py                              # full audit -> _coverage_audit.csv
python audit_coverage.py --start 2023-01-01 --end 2024-06-30
python audit_coverage.py --gaps-only                  # print only the flagged items
```

The actionable rows split cleanly by remedy: `missed-fetchable` /
`partial-capture` are fixed by re-running `download_troysd.py` (the file is on
BoardDocs), while `marker-no-file` / `doclike-no-file` mean the document isn't on
BoardDocs at all and must be sourced out-of-band, dropped into the meeting
folder, and re-indexed. The audit itself is read-only — it downloads nothing.

## Mirroring to Cloudflare R2

The corpus is mirrored to Cloudflare R2 so it lives off-machine and any
environment can rehydrate it without re-crawling BoardDocs. `sync_r2.py` manages
the mirror:

- **Reads are public and credential-free** — objects live at
  `https://media.karpowitsch.org/troysd-boarddocs/<meeting>/<file>`, and a public
  `_manifest.json` lists every key, so the diff and hydrate need no credentials.
- **Writes use `wrangler`** with a `CLOUDFLARE_API_TOKEN` (prompted if it isn't in
  the environment) — only needed when *uploading* net-new documents.

```bash
python sync_r2.py pull              # hydrate the local corpus from R2 (no creds)
python sync_r2.py push              # upload local files missing from R2 (prompts for token)
python sync_r2.py reconcile         # pull, then push (default)
python sync_r2.py rebuild-manifest  # reset the manifest to the local file set
```

Keep-current routine (run locally):

```bash
python sync_r2.py pull                       # get what's already mirrored
python download_troysd.py --all --recheck    # fetch only net-new from BoardDocs
python sync_r2.py push                        # publish the net-new to R2
```

The daily `verify-boarddocs.yml` Action is the "BoardDocs changed" signal that
prompts a sync; uploads are intentionally a local action (the R2 token isn't
stored in CI). See [`RAG.md`](RAG.md).

## Data layout

All scripts read from and write under a single corpus root. The root is
resolved from the `TSD_BOE_ROOT` environment variable, falling back to a
`tsd-boe-data/` folder inside the repository, alongside the scripts. That
folder is matched by `.gitignore`, so the multi-GB corpus is never committed.

```
<root>/
  <YYYY-MM-DD>_<meeting name>/          one folder per meeting
    _minutes.html                       optional, if BoardDocs published minutes
    <agenda item file 1>.pdf
    <agenda item file 2>.pptx
    ...
  _download.log                         downloader stdout, append-only
  _index.csv                            row per file: date, name, url, size
  _tokens_per_file.csv                  token counts per file
  _text/                                mirrored .txt extractions
  _index/
    vectors.npy                         float32 (N, 384), L2-normalized
    chunks.jsonl                        one JSON record per chunk
    model.txt                           embedding model name used
```

The corpus, extracted text, and index are intentionally **not** committed to
this repository — they total several GB of public-record PDFs and binary
artifacts. Run `download_troysd.py` to rebuild from BoardDocs.

## Platform notes

The scripts run on any platform with Python 3.10+ with one exception:

- `extract_legacy.py` uses Microsoft Word and PowerPoint via COM automation
  to read `.doc` and `.ppt` files, and is therefore **Windows + Office only**.
  On macOS or Linux it exits immediately and prints conversion instructions.
  To process legacy files elsewhere, convert them to modern formats first
  with LibreOffice and then run `extract_all.py`:

  ```bash
  soffice --headless --convert-to docx --outdir <dir> <file>.doc
  soffice --headless --convert-to pptx --outdir <dir> <file>.ppt
  ```

- The remaining scripts (`download_troysd.py`, `extract_all.py`,
  `count_tokens.py`, `build_index.py`, `filter_index.py`, `retrieve.py`)
  work on Windows, macOS, and Linux.

## Requirements

- Python 3.10+
- Python packages: `pypdf`, `pdfplumber`, `python-docx`, `python-pptx`,
  `openpyxl`, `striprtf`, `tiktoken`, `numpy`, `sentence-transformers`
- Windows-only extra: `pywin32` (only needed if you run `extract_legacy.py`)

## Quick start

```bash
# Optional — pick a corpus location; otherwise defaults to ./tsd-boe-data (in the repo)
export TSD_BOE_ROOT=/path/to/corpus            # macOS/Linux
$env:TSD_BOE_ROOT = "D:\corpus\tsd-boe"        # PowerShell

# 1. Download meeting documents. Run with no flags for an interactive menu
#    (all meetings / a date range / a specific set); re-runs only fetch
#    meetings you don't already have locally.
python download_troysd.py
python download_troysd.py --all --dry-run        # non-interactive; preview
python download_troysd.py --start 2024-01-01     # just a date range
python download_troysd.py --meetings 2025-06,Workshop   # dates / name substrings

# 2. Extract text
python extract_all.py
python extract_legacy.py    # legacy .doc/.ppt — Windows + Office only

# 3. Build the index (downloads the embedding model on first run)
python build_index.py
python filter_index.py      # optional cleanup pass

# 4. Search
python retrieve.py "bond proposal facilities assessment"
python retrieve.py "superintendent search timeline" -k 30 --since 2023-01-01
```

## Source data

All documents are sourced from the public TroySD BoardDocs site:
<https://go.boarddocs.com/mi/troysd/Board.nsf>. This repo only contains the
tooling to fetch and index them.

## License

[MIT](LICENSE)
