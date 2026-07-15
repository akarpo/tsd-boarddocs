"""Upload source docs to R2 (exact-key PUT via the tsd-ingest Worker).

Search moved to D1 full-text in v0.4, so the `--vectors` path (embed via Workers AI
-> Vectorize) is DEPRECATED — load chunks with upload_d1.py instead. The `--r2`
half (pushing source PDFs to R2) is still the live document-upload step.

Usage:
  python upload_cloudflare.py --r2             # push all source docs to R2 (parallel, exact-key)
  python upload_cloudflare.py --r2 --new-only  # push only docs not already in D1 (daily Action)
  python upload_cloudflare.py --vectors        # DEPRECATED: embed + insert into Vectorize (gone in v0.4)

Env overrides: TSD_BOE_ROOT, R2PUT_URL, URLS_URL, R2PUT_SECRET, R2_BUCKET, R2_PREFIX
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(os.environ.get("TSD_BOE_ROOT") or Path.home() / "tsd-boe-data")
CHUNKS = ROOT / "_index" / "chunks.jsonl"
EMBED_URL = os.environ.get("EMBED_URL", "https://tsd-boarddocs.karpowitsch.org/api/embed")
# R2 uploads go through an ingest Worker's R2 binding (writes the EXACT key —
# the wrangler CLI truncates keys at '#'). Override for the daily Action.
R2PUT_URL = os.environ.get("R2PUT_URL", "https://tsd-ingest.akarpo.workers.dev/r2put")
URLS_URL = os.environ.get("URLS_URL", "https://tsd-ingest.akarpo.workers.dev/urls")
R2PUT_SECRET = os.environ.get("R2PUT_SECRET", "")  # set via env; guards the ingest worker
INDEX = os.environ.get("VECTORIZE_INDEX", "tsd-boarddocs")
R2_BUCKET = os.environ.get("R2_BUCKET", "media")
R2_PREFIX = os.environ.get("R2_PREFIX", "troysd-boarddocs")

EMBED_BATCH = 100    # /api/embed cap
INSERT_BATCH = 500   # vectors per `wrangler vectorize insert`
META_KEYS = ("title", "url", "meeting_date", "meeting_name", "meeting_type", "agenda_item", "file", "source", "chunk_idx", "text")


UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def _embed_call(texts):
    body = json.dumps({"texts": texts}).encode()
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(EMBED_URL, data=body, method="POST", headers={
                "content-type": "application/json", "accept": "application/json", "user-agent": UA})
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)["vectors"]
        except Exception as e:
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise last


def embed(texts):
    """One vector per text; None for any single chunk Workers AI refuses (garbled
    scans can 500). On batch failure, split and retry so one bad chunk never
    sinks the whole run."""
    if not texts:
        return []
    try:
        return _embed_call(texts)
    except Exception:
        if len(texts) == 1:
            return [None]
        mid = len(texts) // 2
        return embed(texts[:mid]) + embed(texts[mid:])


def load_chunks():
    if not CHUNKS.exists():
        print(f"missing {CHUNKS} — run build_index.py first", file=sys.stderr)
        sys.exit(1)
    return [json.loads(line) for line in CHUNKS.open(encoding="utf-8")]


def do_vectors():
    chunks = [c for c in load_chunks() if (c.get("text") or "").strip()]
    print(f"embedding {len(chunks):,} chunks via {EMBED_URL}", flush=True)
    records = []
    skipped = 0
    for i in range(0, len(chunks), EMBED_BATCH):
        batch = chunks[i:i + EMBED_BATCH]
        vecs = embed([c["text"] for c in batch])
        for c, v in zip(batch, vecs):
            if v is None:
                skipped += 1
                continue
            meta = {k: c[k] for k in META_KEYS if c.get(k) is not None}
            if isinstance(meta.get("text"), str) and len(meta["text"]) > 8000:
                meta["text"] = meta["text"][:8000]  # stay under Vectorize's ~10KiB metadata cap
            records.append(json.dumps({"id": c["id"], "values": v, "metadata": meta}))
        print(f"  embedded {min(i + EMBED_BATCH, len(chunks)):,}/{len(chunks):,} ({skipped} skipped)", flush=True)

    total = 0
    for i in range(0, len(records), INSERT_BATCH):
        part = records[i:i + INSERT_BATCH]
        with tempfile.NamedTemporaryFile("w", suffix=".ndjson", delete=False, encoding="utf-8") as f:
            f.write("\n".join(part) + "\n")
            path = f.name
        r = subprocess.run(["wrangler", "vectorize", "upsert", INDEX, "--file", path],
                           capture_output=True, text=True)
        os.unlink(path)
        if r.returncode != 0:
            print("INSERT ERROR:\n" + r.stderr[-800:], file=sys.stderr)
            return 1
        total += len(part)
        print(f"  inserted {total:,}/{len(records):,}", flush=True)
    print(f"DONE vectors: {total:,} into '{INDEX}'")
    return 0


def _put_one(src):
    local = ROOT / src
    if not local.exists():
        return ("miss", src, "")
    # Upload through the ingest Worker's R2 binding, which writes the EXACT key.
    key = f"{R2_PREFIX}/{src}"
    put = f"{R2PUT_URL}?secret={urllib.parse.quote(R2PUT_SECRET)}&key={urllib.parse.quote(key, safe='')}"
    try:
        req = urllib.request.Request(put, data=local.read_bytes(), method="PUT",
                                     headers={"User-Agent": "Mozilla/5.0", "content-type": "application/octet-stream"})
        with urllib.request.urlopen(req, timeout=180) as r:
            return ("ok", src, "") if r.status < 300 else ("fail", src, f"HTTP {r.status}")
    except Exception as e:
        return ("fail", src, repr(e)[-160:])


def existing_urls():
    """Set of source-doc urls already loaded in D1 (via the ingest worker's /urls)."""
    u = URLS_URL + "?secret=" + urllib.parse.quote(R2PUT_SECRET)
    req = urllib.request.Request(u, headers={"user-agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        return set(json.load(r).get("urls") or [])


def do_r2(workers=10, new_only=False):
    from concurrent.futures import ThreadPoolExecutor, as_completed
    chunks = load_chunks()
    have = existing_urls() if new_only else set()
    seen, files = set(), []
    for c in chunks:
        if c["source"] in seen:
            continue
        if new_only and c.get("url") in have:
            continue          # source already in D1 -> already pushed to R2
        seen.add(c["source"])
        files.append(c["source"])
    if new_only:
        print(f"--new-only: {len(files):,} new source docs ({len(have):,} urls already in D1)", flush=True)
        if not files:
            print("nothing new to upload to R2")
            return 0
    print(f"uploading {len(files):,} source docs to r2://{R2_BUCKET}/{R2_PREFIX}/ ({workers}-way parallel)", flush=True)
    ok = miss = fail = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(_put_one, s) for s in files]
        for n, fut in enumerate(as_completed(futs), 1):
            status, src, err = fut.result()
            if status == "ok":
                ok += 1
            elif status == "miss":
                miss += 1
            else:
                fail += 1
                print("  put fail:", src, err, file=sys.stderr)
            if n % 100 == 0:
                print(f"  {n}/{len(files)} ({ok} ok, {fail} fail)", flush=True)
    print(f"DONE r2: {ok} uploaded, {fail} failed, {miss} missing-local")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--vectors", action="store_true")
    ap.add_argument("--r2", action="store_true")
    ap.add_argument("--new-only", action="store_true",
                    help="with --r2, upload only source docs whose url isn't already in D1")
    a = ap.parse_args()
    both = not (a.vectors or a.r2)
    rc = 0
    if a.vectors or both:
        rc = do_vectors() or rc
    if a.r2 or both:
        rc = do_r2(new_only=a.new_only) or rc
    sys.exit(rc)
