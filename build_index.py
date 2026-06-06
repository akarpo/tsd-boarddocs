"""Chunk extracted text and build a local vector index.

Corpus root via TSD_BOE_ROOT env var (default: a tsd-boe-data/ folder beside the scripts):
  Input:  <root>/_text/<meeting>/<file>.txt
  Output: <root>/_index/
            vectors.npy   float32 (N, 384)  L2-normalized
            chunks.jsonl  one JSON per chunk: id, text, source, meeting_date,
                          meeting_name, file, chunk_idx, char_start, char_end

Chunking: ~800 tokens per chunk with 100-token overlap (cl100k tokenizer).
Embedding: sentence-transformers all-MiniLM-L6-v2 (384-dim, free, local).
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

import numpy as np
import tiktoken
from sentence_transformers import SentenceTransformer

ROOT = Path(os.environ.get("TSD_BOE_ROOT") or Path(__file__).resolve().parent / "tsd-boe-data")
TEXT_ROOT = ROOT / "_text"
INDEX_DIR = ROOT / "_index"
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
CHUNK_TOKENS = 800
CHUNK_OVERLAP = 100
BATCH_SIZE = 64

ENC = tiktoken.get_encoding("cl100k_base")
DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_(.+)$")


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
        # locate sub in original text for char offsets (approximate — sub may
        # not match exactly due to tokenizer normalization, so we fall back)
        cs = text.find(sub[:40]) if sub else -1
        if cs < 0:
            cs = 0
        ce = cs + len(sub)
        yield sub, cs, ce, idx
        idx += 1
        if i + CHUNK_TOKENS >= len(toks):
            break


def main():
    if not TEXT_ROOT.exists():
        print("Run extract_all.py first.", file=sys.stderr)
        return 1
    INDEX_DIR.mkdir(parents=True, exist_ok=True)

    # Walk _text/ and collect chunks
    print("[1/3] chunking...", flush=True)
    chunks = []
    txt_files = sorted(p for p in TEXT_ROOT.rglob("*.txt")
                       if not p.name.startswith("_"))
    for tp in txt_files:
        rel = tp.relative_to(TEXT_ROOT)
        # original filename = strip the trailing .txt we appended
        orig = rel.with_suffix("")  # removes only the last suffix (.txt)
        meeting_folder = rel.parts[0] if len(rel.parts) > 1 else ""
        m = DATE_RE.match(meeting_folder)
        meeting_date = m.group(1) if m else ""
        meeting_name = m.group(2).replace("_", " ") if m else meeting_folder
        try:
            text = tp.read_text(encoding="utf-8")
        except Exception:
            continue
        for sub, cs, ce, idx in chunk_text(text):
            chunks.append({
                "id": f"{meeting_folder}|{orig.name}|{idx}",
                "text": sub,
                "source": str(orig).replace("\\", "/"),
                "meeting_date": meeting_date,
                "meeting_name": meeting_name,
                "file": orig.name,
                "chunk_idx": idx,
                "char_start": cs,
                "char_end": ce,
            })
    print(f"      {len(chunks):,} chunks from {len(txt_files):,} files", flush=True)

    if not chunks:
        print("No chunks. Aborting.", file=sys.stderr)
        return 1

    # Embed
    print(f"[2/3] loading {MODEL_NAME}...", flush=True)
    model = SentenceTransformer(MODEL_NAME)
    print("[2/3] embedding...", flush=True)
    t0 = time.time()
    texts = [c["text"] for c in chunks]
    vecs = model.encode(
        texts,
        batch_size=BATCH_SIZE,
        show_progress_bar=True,
        convert_to_numpy=True,
        normalize_embeddings=True,
    ).astype("float32")
    print(f"      {vecs.shape} in {time.time()-t0:.1f}s", flush=True)

    # Persist
    print("[3/3] saving index...", flush=True)
    np.save(INDEX_DIR / "vectors.npy", vecs)
    with (INDEX_DIR / "chunks.jsonl").open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    (INDEX_DIR / "model.txt").write_text(MODEL_NAME, encoding="utf-8")
    print(f"DONE  {len(chunks):,} chunks  ->  {INDEX_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
