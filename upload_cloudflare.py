"""Embed chunks via Workers AI and load them into Vectorize; upload source docs to R2.

Reads <root>/_index/chunks.jsonl (from build_index.py). Embedding runs through the
deployed /api/embed Pages Function (Workers AI @cf/baai/bge-base-en-v1.5) — so no
local torch, and byte-for-byte parity with query-time embedding.

Usage:
  python upload_cloudflare.py            # embed+insert to Vectorize, then push docs to R2
  python upload_cloudflare.py --vectors  # only embed + insert into Vectorize
  python upload_cloudflare.py --r2       # only upload source docs to R2

Env overrides: TSD_BOE_ROOT, EMBED_URL, VECTORIZE_INDEX, R2_BUCKET, R2_PREFIX
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(os.environ.get("TSD_BOE_ROOT") or Path.home() / "tsd-boe-data")
CHUNKS = ROOT / "_index" / "chunks.jsonl"
EMBED_URL = os.environ.get("EMBED_URL", "https://tsd-boarddocs.pages.dev/api/embed")
INDEX = os.environ.get("VECTORIZE_INDEX", "tsd-boarddocs")
R2_BUCKET = os.environ.get("R2_BUCKET", "media")
R2_PREFIX = os.environ.get("R2_PREFIX", "troysd-boarddocs")

EMBED_BATCH = 100    # /api/embed cap
INSERT_BATCH = 500   # vectors per `wrangler vectorize insert`
META_KEYS = ("title", "url", "meeting_date", "meeting_name", "file", "source", "chunk_idx", "text")


def embed(texts):
    body = json.dumps({"texts": texts}).encode()
    req = urllib.request.Request(EMBED_URL, data=body, method="POST", headers={
        "content-type": "application/json",
        "accept": "application/json",
        # Cloudflare bot protection 403s the default python-urllib UA; present a browser UA.
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    })
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)["vectors"]
        except Exception as e:
            if attempt == 3:
                raise
            print(f"  embed retry ({e})", flush=True)
            time.sleep(2 * (attempt + 1))


def load_chunks():
    if not CHUNKS.exists():
        print(f"missing {CHUNKS} — run build_index.py first", file=sys.stderr)
        sys.exit(1)
    return [json.loads(line) for line in CHUNKS.open(encoding="utf-8")]


def do_vectors():
    chunks = load_chunks()
    print(f"embedding {len(chunks):,} chunks via {EMBED_URL}", flush=True)
    records = []
    for i in range(0, len(chunks), EMBED_BATCH):
        batch = chunks[i:i + EMBED_BATCH]
        vecs = embed([c["text"] for c in batch])
        for c, v in zip(batch, vecs):
            meta = {k: c[k] for k in META_KEYS if c.get(k) is not None}
            if isinstance(meta.get("text"), str) and len(meta["text"]) > 8000:
                meta["text"] = meta["text"][:8000]  # stay under Vectorize's ~10KiB metadata cap
            records.append(json.dumps({"id": c["id"], "values": v, "metadata": meta}))
        print(f"  embedded {min(i + EMBED_BATCH, len(chunks)):,}/{len(chunks):,}", flush=True)

    total = 0
    for i in range(0, len(records), INSERT_BATCH):
        part = records[i:i + INSERT_BATCH]
        with tempfile.NamedTemporaryFile("w", suffix=".ndjson", delete=False, encoding="utf-8") as f:
            f.write("\n".join(part) + "\n")
            path = f.name
        r = subprocess.run(["wrangler", "vectorize", "insert", INDEX, "--file", path],
                           capture_output=True, text=True)
        os.unlink(path)
        if r.returncode != 0:
            print("INSERT ERROR:\n" + r.stderr[-800:], file=sys.stderr)
            return 1
        total += len(part)
        print(f"  inserted {total:,}/{len(records):,}", flush=True)
    print(f"DONE vectors: {total:,} into '{INDEX}'")
    return 0


def do_r2():
    chunks = load_chunks()
    seen, files = set(), []
    for c in chunks:
        if c["source"] not in seen:
            seen.add(c["source"])
            files.append(c["source"])
    print(f"uploading {len(files):,} source docs to r2://{R2_BUCKET}/{R2_PREFIX}/", flush=True)
    ok = miss = fail = 0
    for n, src in enumerate(files, 1):
        local = ROOT / src
        if not local.exists():
            miss += 1
            continue
        r = subprocess.run(["wrangler", "r2", "object", "put", f"{R2_BUCKET}/{R2_PREFIX}/{src}",
                            "--file", str(local), "--remote"], capture_output=True, text=True)
        if r.returncode == 0:
            ok += 1
        else:
            fail += 1
            print("  put fail:", src, r.stderr[-160:], file=sys.stderr)
        if n % 25 == 0:
            print(f"  {n}/{len(files)} ({ok} ok, {fail} fail)", flush=True)
    print(f"DONE r2: {ok} uploaded, {fail} failed, {miss} missing-local")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--vectors", action="store_true")
    ap.add_argument("--r2", action="store_true")
    a = ap.parse_args()
    both = not (a.vectors or a.r2)
    rc = 0
    if a.vectors or both:
        rc = do_vectors() or rc
    if a.r2 or both:
        rc = do_r2() or rc
    sys.exit(rc)
