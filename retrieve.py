"""Retrieve top-k chunks from the TroySD vector index.

Usage:
  python retrieve.py "your question here"
  python retrieve.py "your question here" -k 30
  python retrieve.py "your question here" --since 2024-01-01 --until 2024-12-31

Prints chunks ranked by cosine similarity, with source metadata.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# force UTF-8 stdout so chunks with em-dashes / smart quotes don't crash on Windows cp1252
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import numpy as np
from sentence_transformers import SentenceTransformer

ROOT = Path(os.environ.get("TSD_BOE_ROOT") or Path(__file__).resolve().parent / "tsd-boe-data")
INDEX_DIR = ROOT / "_index"


def load_index():
    vecs = np.load(INDEX_DIR / "vectors.npy")
    with (INDEX_DIR / "chunks.jsonl").open(encoding="utf-8") as f:
        chunks = [json.loads(line) for line in f]
    model_name = (INDEX_DIR / "model.txt").read_text(encoding="utf-8").strip()
    return vecs, chunks, model_name


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query", help="question or search phrase")
    ap.add_argument("-k", "--k", type=int, default=20, help="top-k chunks (default 20)")
    ap.add_argument("--since", help="only chunks from meetings on/after YYYY-MM-DD")
    ap.add_argument("--until", help="only chunks from meetings on/before YYYY-MM-DD")
    ap.add_argument("--grep", help="substring filter (case-insensitive) — only chunks containing this literal string are scored")
    ap.add_argument("--max-chars", type=int, default=1500,
                    help="trim each chunk's preview to this many chars (default 1500)")
    ap.add_argument("--full", action="store_true", help="print full chunk text")
    args = ap.parse_args()

    vecs, chunks, model_name = load_index()
    model = SentenceTransformer(model_name)
    q = model.encode([args.query], normalize_embeddings=True,
                     convert_to_numpy=True).astype("float32")
    sims = vecs @ q[0]

    # date + grep filter
    mask = np.ones(len(chunks), dtype=bool)
    needle = args.grep.lower() if args.grep else None
    if args.since or args.until or needle:
        for i, c in enumerate(chunks):
            d = c.get("meeting_date", "")
            if args.since and d < args.since:
                mask[i] = False
            if args.until and d > args.until:
                mask[i] = False
            if needle and needle not in c["text"].lower():
                mask[i] = False
    if not mask.all():
        sims = np.where(mask, sims, -1e9)

    order = np.argsort(-sims)[: args.k]

    print(f"# Query: {args.query}")
    print(f"# Index: {len(chunks):,} chunks | model: {model_name}")
    if args.since or args.until:
        print(f"# Filter: since={args.since} until={args.until}")
    print()
    for rank, idx in enumerate(order, 1):
        c = chunks[idx]
        score = float(sims[idx])
        body = c["text"] if args.full else c["text"][: args.max_chars]
        print(f"--- [{rank}] score={score:.3f} | {c['meeting_date']} | "
              f"{c['meeting_name']} | {c['file']} | chunk {c['chunk_idx']}")
        print(body)
        print()


if __name__ == "__main__":
    sys.exit(main() or 0)
