"""Generate + store per-document AI summaries (Opus, local, resumable).

Documents are grouped from _index/chunks.jsonl. "Pending" = a document whose url
is not yet in the D1 `summaries` table, so generation resumes across sessions and
days. The only expensive step is Claude writing the summaries — everything here is
plumbing.

  python summarize.py --stats                 # done / pending counts
  python summarize.py --next 20               # -> /tmp/tsd_batch.json (next 20 pending docs)
  #   Claude reads that batch and writes /tmp/tsd_summaries.json
  #      = { "<url>": {"paragraph": "...", "page": "...", "verbose": "..."}, ... }
  python summarize.py --store /tmp/tsd_summaries.json   # upsert to D1, marks them done
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
SUMPUT = os.environ.get("SUMMARYPUT_URL", "https://tsd-ingest.akarpo.workers.dev/summaryput")
SECRET = os.environ.get("R2PUT_SECRET", "")
BATCH_JSON = Path("/tmp/tsd_batch.json")
STORE_BATCH = 40
TEXT_CAP = 6000


def docs():
    d = {}
    for line in CHUNKS.open(encoding="utf-8"):
        c = json.loads(line)
        u = c.get("url")
        if not u:
            continue
        e = d.setdefault(u, {"url": u, "title": c.get("title"), "meeting_date": c.get("meeting_date"),
                             "meeting_type": c.get("meeting_type"), "meeting_name": c.get("meeting_name"),
                             "agenda_item": c.get("agenda_item"), "_chunks": []})
        e["_chunks"].append((c.get("chunk_idx", 0), c.get("text", "")))
    for e in d.values():
        e["text"] = " ".join(t for _, t in sorted(e["_chunks"]))[:TEXT_CAP]
        del e["_chunks"]
    return d


def done_urls():
    r = subprocess.run(["wrangler", "d1", "execute", DB, "--remote", "--yes", "--json",
                        "--command", "SELECT url FROM summaries;"], capture_output=True, text=True)
    try:
        return {row["url"] for row in json.loads(r.stdout)[0]["results"]}
    except Exception:
        return set()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--next", type=int)
    ap.add_argument("--store")
    a = ap.parse_args()

    if a.store:
        sums = json.load(open(a.store))
        rows = [{"url": u, "paragraph": v.get("paragraph", ""), "page": v.get("page", ""),
                 "verbose": v.get("verbose", "")} for u, v in sums.items()]
        for i in range(0, len(rows), STORE_BATCH):
            body = json.dumps({"rows": rows[i:i + STORE_BATCH]}).encode()
            req = urllib.request.Request(SUMPUT + "?secret=" + urllib.parse.quote(SECRET), data=body,
                                         method="POST", headers={"content-type": "application/json",
                                                                 "user-agent": "Mozilla/5.0"})
            urllib.request.urlopen(req, timeout=120).read()
        print(f"stored {len(rows)} summaries to D1")
        return 0

    d = docs()
    done = done_urls()
    pending = [e for u, e in d.items() if u not in done]
    pending.sort(key=lambda e: e.get("meeting_date") or "", reverse=True)  # recent first

    if a.stats:
        print(f"docs: {len(d):,}  summarized: {len(done):,}  pending: {len(pending):,}")
        return 0

    n = a.next or 20
    batch = pending[:n]
    BATCH_JSON.write_text(json.dumps(batch, ensure_ascii=False, indent=1))
    print(f"wrote {len(batch)} pending docs -> {BATCH_JSON}  ({len(pending):,} pending total)")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
