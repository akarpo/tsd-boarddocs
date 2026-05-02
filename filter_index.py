"""Drop low-quality chunks (mostly single-char garbage from CAD/spec PDFs)
from the existing index, in place. Rewrites vectors.npy and chunks.jsonl.

A chunk is kept if:
  - it has >= 30 word-like tokens, AND
  - <= 30% of those tokens are length-1
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

INDEX_DIR = Path(r"C:\Dev\TroySD\_index")

MIN_WORDS = 30
MAX_SINGLE_RATIO = 0.30


def quality(text: str) -> bool:
    words = text.split()
    if len(words) < MIN_WORDS:
        return False
    short = sum(1 for w in words if len(w) <= 1)
    return short / len(words) <= MAX_SINGLE_RATIO


def main():
    vecs = np.load(INDEX_DIR / "vectors.npy")
    with (INDEX_DIR / "chunks.jsonl").open(encoding="utf-8") as f:
        chunks = [json.loads(line) for line in f]
    assert len(chunks) == len(vecs)
    keep_idx = [i for i, c in enumerate(chunks) if quality(c["text"])]
    drop = len(chunks) - len(keep_idx)
    print(f"input:  {len(chunks):,} chunks")
    print(f"keep:   {len(keep_idx):,}")
    print(f"drop:   {drop:,}  ({drop/len(chunks)*100:.1f}%)")
    new_vecs = vecs[keep_idx]
    np.save(INDEX_DIR / "vectors.npy", new_vecs)
    with (INDEX_DIR / "chunks.jsonl").open("w", encoding="utf-8") as f:
        for i in keep_idx:
            f.write(json.dumps(chunks[i], ensure_ascii=False) + "\n")
    print(f"saved: {new_vecs.shape}")


if __name__ == "__main__":
    main()
