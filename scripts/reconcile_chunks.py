"""Reconcile D1 `chunks` against the local index, chunk id by chunk id.

    python3 scripts/reconcile_chunks.py          # report only
    python3 scripts/reconcile_chunks.py --fix    # insert missing, delete stale

Document-level checks (docs = summaries = sum rows) cannot see a document that is
*partly* loaded. On 2026-10-10 this found two kinds that had been live for weeks:

  - MISSING: twelve documents re-extracted with more text in the 2026-08-21 parse-gap
    recovery still had only their first chunk in D1 (an Atlantic article: 1 of 20).
    `upload_d1.py --new-only` skips any url already present, so it never sends the rest.
  - STALE: the PEPS report's 46 glyph-garbage chunks stayed beside its 26 OCR'd ones,
    because a reload adds rows and nothing removes the old extraction's.

Chunk ids are content hashes, so a re-extracted document gets new ids. "Stale" is a
non-summary row whose id the index no longer has; `sum:` rows are never touched.
Rebuild the index first (`build_index.py`) or every re-extraction reads as drift.
"""
from __future__ import annotations

import argparse
import collections
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import upload_d1  # noqa: E402  (post(), COLS, CHUNKS, DB)


def d1(sql: str) -> list[dict]:
    out = subprocess.run(["npx", "wrangler", "d1", "execute", upload_d1.DB, "--remote", "--json",
                          "--command", sql], capture_output=True, text=True, check=True).stdout
    return json.loads(out)[0]["results"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--fix", action="store_true", help="insert missing chunks and delete stale ones")
    a = ap.parse_args()

    idx = [json.loads(l) for l in upload_d1.CHUNKS.open(encoding="utf-8")]
    idx = [c for c in idx if (c.get("text") or "").strip()]   # what upload_d1 would send
    have = d1("SELECT id, url FROM chunks WHERE id NOT LIKE 'sum:%'")
    want_ids = {c["id"] for c in idx}
    have_ids = collections.Counter(r["id"] for r in have)

    missing = [c for c in idx if c["id"] not in have_ids]
    stale = [r for r in have if r["id"] not in want_ids]
    dups = [i for i, n in have_ids.items() if n > 1]
    print(f"index {len(idx):,}  D1 {len(have):,}  missing {len(missing)}  stale {len(stale)}  "
          f"duplicate ids {len(dups)}")
    by_url = collections.Counter([("missing", c["url"]) for c in missing] +
                                 [("stale", r["url"]) for r in stale])
    for (kind, url), n in sorted(by_url.items(), key=lambda kv: kv[0][1]):
        print(f"  {kind:7} {n:3}  {url.split('/troysd-boarddocs/')[-1][:110]}")
    if dups:
        print("  duplicate ids need a by-hand delete-and-reload; not repaired here:", dups[:5])
    if not a.fix or not (missing or stale):
        return 1 if (missing or stale or dups) else 0

    for i in range(0, len(missing), upload_d1.BATCH):
        upload_d1.post([{k: (c.get(k) or "") for k in upload_d1.COLS}
                        for c in missing[i:i + upload_d1.BATCH]])
    for i in range(0, len(stale), 100):
        ids = ",".join("'" + r["id"].replace("'", "''") + "'" for r in stale[i:i + 100])
        d1(f"DELETE FROM chunks WHERE id IN ({ids}) AND id NOT LIKE 'sum:%'")
    print(f"inserted {len(missing)}, deleted {len(stale)} -- re-run without --fix to confirm")
    return 0


if __name__ == "__main__":
    sys.exit(main())
