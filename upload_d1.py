"""Load chunks into the D1 full-text (FTS5) `chunks` table via the ingest Worker's
/d1insert endpoint (parameterized batch inserts — avoids SQLITE_TOOBIG).

No embeddings — D1 FTS5 does keyword/BM25 search (free tier, no neuron cap).

Usage:
  python upload_d1.py --year 2026
  python upload_d1.py --all [--truncate]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(os.environ.get("TSD_BOE_ROOT") or Path.home() / "tsd-boe-data")
CHUNKS = ROOT / "_index" / "chunks.jsonl"
DB = os.environ.get("D1_DB", "tsd-boarddocs")
D1INSERT = os.environ.get("D1INSERT_URL", "https://tsd-ingest.akarpo.workers.dev/d1insert")
SECRET = os.environ.get("R2PUT_SECRET", "")  # set via env; guards the ingest worker
COLS = ["id", "url", "title", "text", "meeting_date", "meeting_name",
        "meeting_type", "agenda_item", "file", "source"]
BATCH = 50


def post(rows):
    body = json.dumps({"rows": rows}).encode()
    req = urllib.request.Request(D1INSERT + "?secret=" + urllib.parse.quote(SECRET), data=body,
                                 method="POST", headers={"content-type": "application/json",
                                                         "user-agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--truncate", action="store_true")
    a = ap.parse_args()

    chunks = [json.loads(line) for line in CHUNKS.open(encoding="utf-8")]
    if a.year:
        chunks = [c for c in chunks if c.get("meeting_date", "").startswith(a.year)]
    chunks = [c for c in chunks if (c.get("text") or "").strip()]
    print(f"loading {len(chunks):,} rows into D1 '{DB}' via {D1INSERT}", flush=True)

    if a.truncate:
        subprocess.run(["wrangler", "d1", "execute", DB, "--remote", "--yes",
                        "--command", "DELETE FROM chunks;"], capture_output=True)
        print("  table cleared", flush=True)

    total = 0
    for i in range(0, len(chunks), BATCH):
        rows = [{k: (c.get(k) or "") for k in COLS} for c in chunks[i:i + BATCH]]
        try:
            post(rows)
        except Exception as e:
            print("ERROR:", repr(e)[-300:], file=sys.stderr)
            return 1
        total += len(rows)
        if total % 500 == 0 or total == len(chunks):
            print(f"  {total:,}/{len(chunks):,}", flush=True)
    print(f"DONE: {total:,} rows in D1 '{DB}'")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
