"""Chunk extracted text into records for the D1 full-text (FTS5) index.

Corpus root via TSD_BOE_ROOT env var (default ~/tsd-boe-data):
  Input:  <root>/_text/<meeting>/<file>.txt
  Output: <root>/_index/chunks.jsonl   one JSON record per chunk:
            id           sha1 of "<meeting>|<file>|<idx>" (stable, short)
            text         the chunk text (indexed by D1 FTS5 for keyword/BM25 search)
            title        source filename without extension
            url          public R2 URL of the source document (citation target)
            source, meeting_date, meeting_name, file, chunk_idx, char_start, char_end

Chunking: ~800 tokens per chunk with 100-token overlap (cl100k tokenizer).
Search is D1 full-text (FTS5 / BM25) — no embeddings (Workers AI + Vectorize were
dropped in v0.4). This step stays torch-free and runs anywhere, including the daily
GitHub Action; upload_d1.py loads the chunks into D1 via the ingest worker.
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

# Older "YYYY Board Packets and Minutes" folders carry a placeholder folder date
# (YYYY-01-01 / YYYY-12-31); the real date+type live in the filename, e.g. 022718RegMtg.
FNAME_DATE_RE = re.compile(r"^W?(\d{2})(\d{2})(\d{2})")


def meeting_type(name: str) -> str:
    n = name.lower()
    for kw, label in (("workshop", "Workshop"), ("special", "Special"),
                      ("organizational", "Organizational"), ("retreat", "Retreat"),
                      ("committee", "Committee"), ("regular", "Regular")):
        if kw in n:
            return label
    return "Meeting"


def filename_meeting(stem: str):
    """Recover (date, type) from an older packet filename like '022718RegMtg'."""
    m = FNAME_DATE_RE.match(stem or "")
    if not m:
        return None
    mm, dd, yy = m.groups()
    if not (1 <= int(mm) <= 12 and 1 <= int(dd) <= 31):
        return None
    s = stem[m.end():].lower()
    for kw, label in (("retreat", "Retreat"), ("org", "Organizational"), ("reg", "Regular"),
                      ("wksh", "Workshop"), ("wksp", "Workshop"), ("sp", "Special")):
        if kw in s:
            return f"20{yy}-{mm}-{dd}", label
    return f"20{yy}-{mm}-{dd}", "Meeting"


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
            m_type = meeting_type(meeting_name)
            # Placeholder folder date => recover the real date+type from the filename.
            if meeting_date[5:] in ("01-01", "12-31"):
                fm = filename_meeting(orig.stem)
                if fm:
                    meeting_date, m_type = fm
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
                    "meeting_type": m_type,
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
