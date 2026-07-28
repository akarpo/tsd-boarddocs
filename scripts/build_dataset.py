#!/usr/bin/env python3
"""Build the public dataset artifacts from D1 summaries + the local chunk index.

Three files, deliberately layered by what they cost the consumer to use:

  corpus-map.jsonl     one line per document: paragraph summary + metadata.
                       ~1.5 MB / ~370K tokens -- the whole district's board
                       history fits in a single model context, so an assistant
                       can reason across ALL documents at once instead of
                       retrieving a handful. This is the artifact that does
                       something search cannot.

  summaries-full.jsonl all three tiers per document. The archive: for anyone
                       running their own RAG over the corpus.

  figures.csv          every currency figure in the source text, with the label
                       that precedes it and enough surrounding context to check
                       it. This is what makes budget questions answerable as
                       DATA rather than prose.

On figures.csv, the discipline is the same one the re-summarization campaign
runs on: nothing is computed. Every `amount` is a string that appears verbatim
in the chunk it is attributed to, and `--verify` re-reads the source to prove
it. No deltas, no totals, no percentages -- a derived number in a CSV is more
dangerous than one in a paragraph, because it looks authoritative and gets
charted. Consumers do their own arithmetic on rows they can trace.

  python3 scripts/build_dataset.py --all
  python3 scripts/build_dataset.py --figures --verify
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ROOT = Path(os.environ.get("TSD_BOE_ROOT") or REPO / "data" / "tsd-boe-data")
OUT = Path(os.environ.get("TSD_DATASET_DIR") or REPO / "dataset")
CACHE = Path(os.environ.get("SUMS_CACHE") or "/tmp/tsd_sums_raw.json")
DB = "tsd-boarddocs"

# A currency figure: at least one thousands group, optional cents. Bare 4-digit
# numbers are excluded deliberately -- they are overwhelmingly years, policy
# numbers and codes, and including them buries the real figures in noise.
FIG = re.compile(r'\$?\s?(\d{1,3}(?:,\d{3})+(?:\.\d{2})?)')
# The label is the run of words immediately before the figure. Table rows in
# these documents read "Total Support Services 49,625,852", so the preceding
# words are the line item.
LABEL = re.compile(r'([A-Za-z][A-Za-z&/\'\-\. ]{2,60}?)\s*\$?\s?$')


def load_summaries(refresh: bool) -> list[dict]:
    if refresh or not CACHE.exists():
        print("pulling summaries from D1 ...", file=sys.stderr)
        r = subprocess.run(["npx", "wrangler", "d1", "execute", DB, "--remote", "--yes",
                            "--json", "--command",
                            "SELECT url, paragraph, page, verbose FROM summaries"],
                           capture_output=True, text=True)
        m = re.search(r'\[\s*\{.*\}\s*\]', r.stdout, re.S)
        if not m:
            raise SystemExit(f"could not parse wrangler output:\n{r.stdout[-600:]}\n{r.stderr[-400:]}")
        CACHE.write_text(m.group())
    return json.loads(CACHE.read_text())[0]["results"]


def load_chunks() -> list[dict]:
    idx = ROOT / "_index" / "chunks.jsonl"
    if not idx.exists():
        raise SystemExit(f"missing {idx} — run build_index.py first")
    out = []
    for line in idx.open(encoding="utf-8"):
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def doc_meta(chunks: list[dict]) -> dict[str, dict]:
    """url -> document metadata, taken from its first real (non-summary) chunk."""
    meta = {}
    for c in chunks:
        u = c.get("url")
        if not u or str(c.get("id", "")).startswith("sum:") or u in meta:
            continue
        meta[u] = {"title": c.get("title"), "file": c.get("file"),
                   "meeting_date": c.get("meeting_date"), "meeting_name": c.get("meeting_name"),
                   "meeting_type": c.get("meeting_type"), "agenda_item": c.get("agenda_item")}
    return meta


def write_jsonl(path: Path, rows) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            n += 1
    return n


def build_maps(sums, meta):
    cmap, full = [], []
    for s in sums:
        u = s["url"]
        m = meta.get(u, {})
        base = {"url": u, "title": m.get("title"), "meeting_date": m.get("meeting_date"),
                "meeting_name": m.get("meeting_name"), "meeting_type": m.get("meeting_type"),
                "agenda_item": m.get("agenda_item")}
        cmap.append({**base, "paragraph": s.get("paragraph") or ""})
        full.append({**base, "paragraph": s.get("paragraph") or "",
                     "page": s.get("page") or "", "verbose": s.get("verbose") or ""})
    key = lambda r: (r.get("meeting_date") or "", r.get("title") or "")
    return sorted(cmap, key=key), sorted(full, key=key)


def build_figures(chunks, meta):
    """One row per currency figure in source text, with its label + context.

    Normalised against documents.csv by `doc_id` rather than repeating the url
    and title on every row. At ~334K rows those two columns alone cost ~48 MB,
    which is the difference between a file that fits in git and one that does
    not. Join on doc_id to recover the full document record.
    """
    ids = {u: f"d{i:04d}" for i, u in enumerate(sorted(meta))}
    rows = []
    for c in chunks:
        if str(c.get("id", "")).startswith("sum:"):
            continue                      # summaries are prose; figures come from source
        txt = " ".join((c.get("text") or "").split())
        if not txt:
            continue
        u = c.get("url")
        m = meta.get(u, {})
        did = ids.get(u, "")
        for mo in FIG.finditer(txt):
            amount = mo.group(1)
            if len(amount.replace(",", "").split(".")[0]) < 4:
                continue
            pre = txt[max(0, mo.start() - 80):mo.start()]
            lm = LABEL.search(pre)
            rows.append({
                "amount": amount,
                "label": (lm.group(1).strip() if lm else ""),
                "meeting_date": m.get("meeting_date") or "",
                "doc_id": did,
                "context": txt[max(0, mo.start() - 80):mo.end() + 30].strip(),
                "chunk_id": c.get("id"),
            })
    docs = [{"doc_id": ids[u], "url": u, **meta[u]} for u in sorted(meta)]
    return rows, docs


def verify_figures(rows, chunks) -> tuple[int, int]:
    """Re-read each row's chunk and confirm the amount appears verbatim.

    The same check validate_fanout.py runs on agent output. A CSV that says
    49,625,852 must be traceable to a chunk that literally contains that string.
    """
    by_id = {c.get("id"): " ".join((c.get("text") or "").split()) for c in chunks}
    ok = bad = 0
    for r in rows:
        src = by_id.get(r["chunk_id"], "")
        if r["amount"] in src:
            ok += 1
        else:
            bad += 1
            if bad <= 5:
                print(f"  ! {r['amount']} not found in {r['chunk_id']}", file=sys.stderr)
    return ok, bad


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true", help="build every artifact")
    ap.add_argument("--map", action="store_true", help="corpus-map.jsonl")
    ap.add_argument("--full", action="store_true", help="summaries-full.jsonl")
    ap.add_argument("--figures", action="store_true", help="figures.csv")
    ap.add_argument("--verify", action="store_true", help="re-read sources to prove every amount")
    ap.add_argument("--refresh", action="store_true", help="re-pull summaries from D1")
    a = ap.parse_args()
    if a.all:
        a.map = a.full = a.figures = True
    if not (a.map or a.full or a.figures):
        ap.error("nothing to build — pass --all or one of --map/--full/--figures")

    OUT.mkdir(parents=True, exist_ok=True)
    chunks = load_chunks()
    meta = doc_meta(chunks)
    print(f"chunks {len(chunks):,}   documents {len(meta):,}", file=sys.stderr)

    if a.map or a.full:
        sums = load_summaries(a.refresh)
        cmap, full = build_maps(sums, meta)
        if a.map:
            p = OUT / "corpus-map.jsonl"
            n = write_jsonl(p, cmap)
            print(f"corpus-map.jsonl      {n:>6,} docs  {p.stat().st_size/1e6:>6.1f} MB")
        if a.full:
            p = OUT / "summaries-full.jsonl"
            n = write_jsonl(p, full)
            print(f"summaries-full.jsonl  {n:>6,} docs  {p.stat().st_size/1e6:>6.1f} MB")

    if a.figures:
        rows, docs = build_figures(chunks, meta)

        p = OUT / "figures.csv"
        cols = ["amount", "label", "meeting_date", "doc_id", "context", "chunk_id"]
        with p.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
        print(f"figures.csv           {len(rows):>6,} rows  {p.stat().st_size/1e6:>6.1f} MB")

        d = OUT / "documents.csv"
        dcols = ["doc_id", "url", "title", "file", "meeting_date", "meeting_name",
                 "meeting_type", "agenda_item"]
        with d.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=dcols, extrasaction="ignore")
            w.writeheader()
            w.writerows(docs)
        print(f"documents.csv         {len(docs):>6,} rows  {d.stat().st_size/1e6:>6.1f} MB")

        if a.verify:
            ok, bad = verify_figures(rows, chunks)
            print(f"  verified verbatim: {ok:,}   NOT found: {bad:,}")
            if bad:
                return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
