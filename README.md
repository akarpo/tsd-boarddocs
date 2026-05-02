# tsd-boe

Tooling to download every public Troy School District (Michigan) Board of
Education document from BoardDocs, extract their text, and build a local
semantic-search index that can be queried from the command line.

The pipeline is designed to run end-to-end on a single Windows machine with
no cloud services or API keys required — embedding and retrieval are local.

## Pipeline

```
download_troysd.py    BoardDocs  --->  C:\Dev\TroySD\<meeting>\<file>
        |
        v
extract_all.py        PDF/DOCX/PPTX/XLSX/RTF -> _text\<meeting>\<file>.txt
extract_legacy.py     legacy .doc/.ppt via Word/PowerPoint COM (Windows)
        |
        v
build_index.py        chunk + embed -> _index\vectors.npy + chunks.jsonl
filter_index.py       drop low-quality chunks in place (optional cleanup)
        |
        v
retrieve.py "query"   top-k cosine search over the index
count_tokens.py       per-type and grand-total token counts (cl100k_base)
```

## Scripts

| Script | What it does |
| --- | --- |
| `download_troysd.py` | Crawls BoardDocs (`go.boarddocs.com/mi/troysd/Board.nsf`) using the `BD-GetMeetingsList` / `BD-GetAgenda` / `BD-GetPublicFiles` / `BD-GetMinutes` endpoints, saves every public file under `<YYYY-MM-DD>_<meeting_name>\`, writes `_download.log` and `_index.csv`. Idempotent — existing non-empty files are skipped. |
| `extract_all.py` | Walks the corpus and writes plain-text `.txt` mirrors into `_text\` for `.pdf`, `.docx`, `.pptx`, `.xlsx`, and `.rtf`. PDF extraction tries `pypdf` first, then falls back to `pdfplumber`. Records skips/errors in `_text\_skipped.txt`. |
| `extract_legacy.py` | Handles the old `.doc` and `.ppt` formats via Word and PowerPoint COM automation (Windows-only). Restarts the COM apps every 50 files to avoid memory bloat. |
| `count_tokens.py` | Estimates total corpus token cost using the `cl100k_base` (GPT-4) tokenizer as a proxy for Claude. Writes `_tokens_per_file.csv`. |
| `build_index.py` | Token-windowed chunking (~800 tokens, 100 overlap) + embedding with `sentence-transformers/all-MiniLM-L6-v2` (384-dim, runs locally). Writes `_index\vectors.npy` and `_index\chunks.jsonl`. |
| `filter_index.py` | Removes low-quality chunks (mostly single-character noise from scanned CAD/spec PDFs) in place. Keeps chunks with at least 30 word-like tokens and no more than 30% length-1 tokens. |
| `retrieve.py` | Loads the index, embeds a query, returns top-k chunks ranked by cosine similarity. Supports `--since` / `--until` date filters and a literal `--grep` substring filter. |

## Data layout

All scripts read from and write under a single corpus root (default
`C:\Dev\TroySD`). Edit the `ROOT = Path(...)` constant at the top of each
script to point somewhere else.

```
<corpus root>\
  <YYYY-MM-DD>_<meeting name>\          one folder per meeting
    _minutes.html                       optional, if BoardDocs published minutes
    <agenda item file 1>.pdf
    <agenda item file 2>.pptx
    ...
  _download.log                         downloader stdout, append-only
  _index.csv                            row per file: date, name, url, size
  _tokens_per_file.csv                  token counts per file
  _text\                                mirrored .txt extractions
  _index\
    vectors.npy                         float32 (N, 384), L2-normalized
    chunks.jsonl                        one JSON record per chunk
    model.txt                           embedding model name used
```

The corpus, extracted text, and index are intentionally **not** committed to
this repository — they total several GB of public-record PDFs and binary
artifacts. Run `download_troysd.py` to rebuild from BoardDocs.

## Requirements

- Python 3.10+
- Windows (legacy `.doc` / `.ppt` extraction needs Word and PowerPoint via COM)
- Python packages: `pypdf`, `pdfplumber`, `python-docx`, `python-pptx`,
  `openpyxl`, `striprtf`, `tiktoken`, `numpy`, `sentence-transformers`,
  `pywin32` (for `extract_legacy.py`)

## Quick start

```powershell
# 1. Download every meeting document (long; one-time)
python download_troysd.py

# 2. Extract text
python extract_all.py
python extract_legacy.py    # for legacy .doc / .ppt

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
