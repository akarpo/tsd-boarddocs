"""Chunk extracted text into records ready for embedding + Vectorize upload.

Corpus root via TSD_BOE_ROOT env var (default ~/tsd-boe-data):
  Input:  <root>/_text/<meeting>/<file>.txt
  Output: <root>/_index/chunks.jsonl   one JSON record per chunk:
            id           sha1 of "<meeting>|<file>|<idx>" (stable, <64B for Vectorize)
            text         the chunk text (also stored as Vectorize metadata)
            title        source filename without extension
            url          public R2 URL of the source document (citation target)
            source, meeting_date, meeting_name, file, chunk_idx, char_start, char_end

Chunking: ~800 tokens per chunk with 100-token overlap (cl100k tokenizer).
Embedding is deliberately NOT done here — it happens in upload_cloudflare.py via
Workers AI @cf/baai/bge-base-en-v1.5, so this step is torch-free and runs anywhere
(including the daily GitHub Action).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import urllib.parse
from pathlib import Path

import tiktoken

ROOT = Path(os.environ.get("TSD_BOE_ROOT") or Path.home() / "tsd-boe-data")
TEXT_ROOT = ROOT / "_text"
INDEX_DIR = ROOT / "_index"
# Public R2 custom domain + project prefix. Citations point here; upload_cloudflare.py
# puts the source files at the matching keys.
R2_BASE = os.environ.get("TSD_R2_BASE", "https://media.karpowitsch.org/troysd-boarddocs")
CHUNK_TOKENS = 800
CHUNK_OVERLAP = 100

ENC = tiktoken.get_encoding("cl100k_base")
DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_(.+)$")
# Leading agenda token in a filename, e.g. "8.C.", "4.a.", "5.D.1".
AGENDA_RE = re.compile(r"^\s*(\d{1,2}(?:\.[A-Za-z0-9]{1,3})+)\.?\s")


def meeting_type(name: str) -> str:
    n = name.lower()
    for kw, label in (("workshop", "Workshop"), ("special", "Special"),
                      ("organizational", "Organizational"), ("retreat", "Retreat"),
                      ("committee", "Committee"), ("regular", "Regular")):
        if kw in n:
            return label
    return "Meeting"


def agenda_item(filename: str) -> str:
    m = AGENDA_RE.match(filename)
    return m.group(1) if m else ""


def chunk_text(text: str):
    """Yield (text, char_start, char_end, chunk_idx) for token-windowed chunks."""
    toks = ENC.encode(text, disallowed_special=())
    if not toks:
        return
    step = CHUNK_TOKENS - CHUNK_OVERLAP
    idx = 0
    for i in range(0, len(toks), step):
        window = toks[i:i + CHUNK_TOKENS]
        if not window:
            break
        sub = ENC.decode(window)
        cs = text.find(sub[:40]) if sub else -1
        if cs < 0:
            cs = 0
        ce = cs + len(sub)
        yield sub, cs, ce, idx
        idx += 1
        if i + CHUNK_TOKENS >= len(toks):
            break


def r2_url(meeting_folder: str, filename: str) -> str:
    return f"{R2_BASE}/{urllib.parse.quote(meeting_folder)}/{urllib.parse.quote(filename)}"


def main():
    if not TEXT_ROOT.exists():
        print("Run extract_all.py first.", file=sys.stderr)
        return 1
    INDEX_DIR.mkdir(parents=True, exist_ok=True)

    print("[1/2] chunking...", flush=True)
    txt_files = sorted(p for p in TEXT_ROOT.rglob("*.txt") if not p.name.startswith("_"))
    n_chunks = 0
    with (INDEX_DIR / "chunks.jsonl").open("w", encoding="utf-8") as out:
        for tp in txt_files:
            rel = tp.relative_to(TEXT_ROOT)
            orig = rel.with_suffix("")            # strip the trailing .txt
            meeting_folder = rel.parts[0] if len(rel.parts) > 1 else ""
            m = DATE_RE.match(meeting_folder)
            meeting_date = m.group(1) if m else ""
            meeting_name = m.group(2).replace("_", " ") if m else meeting_folder
            try:
                text = tp.read_text(encoding="utf-8")
            except Exception:
                continue
            for sub, cs, ce, idx in chunk_text(text):
                key = f"{meeting_folder}|{orig.name}|{idx}"
                out.write(json.dumps({
                    "id": hashlib.sha1(key.encode("utf-8")).hexdigest(),
                    "text": sub,
                    "title": orig.stem,
                    "url": r2_url(meeting_folder, orig.name),
                    "source": str(orig).replace("\\", "/"),
                    "meeting_date": meeting_date,
                    "meeting_name": meeting_name,
                    "meeting_type": meeting_type(meeting_name),
                    "file": orig.name,
                    "agenda_item": agenda_item(orig.name),
                    "chunk_idx": idx,
                    "char_start": cs,
                    "char_end": ce,
                }, ensure_ascii=False) + "\n")
                n_chunks += 1

    print(f"[2/2] wrote {n_chunks:,} chunks from {len(txt_files):,} files -> {INDEX_DIR / 'chunks.jsonl'}")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
