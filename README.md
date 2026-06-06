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
| `download_troysd.py` | Crawls BoardDocs (`go.boarddocs.com/mi/troysd/Board.nsf`) via the `BD-GetMeetingsList` / `BD-GetAgenda` / `BD-GetPublicFiles` / `BD-GetMinutes` endpoints, saving every public file under `<YYYY-MM-DD>_<meeting_name>\` plus `_download.log` and `_index.csv`. On run it lists the meetings online, shows how many you already have locally, and prompts you to fetch **all** of them, a **date range**, or a **specific picked set** — or pass `--all` / `--start` / `--end` / `--meetings` / `--meetings-file` to skip the prompt. **Incremental:** meetings already saved locally are skipped (use `--recheck` to re-verify them, `--dry-run` to preview). Individual files are skipped if already present and non-empty. |
| `extract_all.py` | Walks the corpus and writes plain-text `.txt` mirrors into `_text\` for `.pdf`, `.docx`, `.pptx`, `.xlsx`, and `.rtf`. PDF extraction tries `pypdf` first, then falls back to `pdfplumber`. Records skips/errors in `_text\_skipped.txt`. |
| `extract_legacy.py` | Handles the old `.doc` and `.ppt` formats via Word and PowerPoint COM automation. **Windows-only**; exits early on other platforms with conversion instructions for LibreOffice. Restarts the COM apps every 50 files to avoid memory bloat. |
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

## Data layout

All scripts read from and write under a single corpus root. The root is
resolved from the `TSD_BOE_ROOT` environment variable, falling back to
`~/tsd-boe-data` (i.e. `%USERPROFILE%\tsd-boe-data` on Windows,
`$HOME/tsd-boe-data` on macOS / Linux).

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
# Optional — pick a corpus location; otherwise defaults to ~/tsd-boe-data
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
