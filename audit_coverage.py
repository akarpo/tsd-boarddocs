"""Audit BoardDocs agenda coverage — flag agenda items that imply a document but
have no captured attachment.

The crawler (download_troysd.py) only harvests an agenda item's *public-file*
attachments (BD-GetPublicFiles). Documents that are presented but never attached
(e.g. the 2024-03-05 "Levinson Report - Outcomes & Recommendations"), or attached
non-publicly, slip through. This audit cross-references every live agenda item
against what the crawl actually captured (`_index.csv`) and classifies each item:

  ok               file(s) captured, or a procedural item (no document expected)
  marker-no-file   BoardDocs marks it "contains an attachment", but the crawl
                   captured none — the attachment is non-public / not fetchable
  doclike-no-file  the title reads like a document (report / findings /
                   recommendation / presentation / study / plan / review /
                   proposal / audit / analysis) with no marker and no file —
                   most likely presented to the board but never attached

It writes `<root>/_coverage_audit.csv` (one row per agenda item) and prints a
summary plus the flagged gaps. Reads-only against BoardDocs; downloads nothing.

Usage:
  python audit_coverage.py
  python audit_coverage.py --start 2023-01-01 --end 2024-06-30
  python audit_coverage.py --gaps-only        # print only the flagged items
"""
from __future__ import annotations

import argparse
import csv
import html
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import download_troysd as d  # reuse the BoardDocs client + helpers

ROOT = Path(os.environ.get("TSD_BOE_ROOT") or Path(__file__).resolve().parent / "tsd-boe-data")
ATTACH_MARKER = "contains an attachment"
DOC_RE = re.compile(r"\b(report|findings|recommendation|presentation|study|plan|"
                    r"review|proposal|audit|analysis|results|data|update|summary)\b", re.I)
# BoardDocs stores each item's title in an Xtitle attr as "<ActionType> - <Title>"
# (or " - <Title>" when the action type is blank). Strip that leading prefix.
ACTION_PREFIX_RE = re.compile(r"^(?:\s*-\s*|\s*[A-Z][a-z]+\s+-\s+)")


def _strip(h: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", h))).strip()


def parse_items(agenda_html: str):
    """Yield (unid, title, has_marker) for each real agenda item.

    Titles come from the <li> ``Xtitle`` attribute — BoardDocs' own item title —
    with the leading action-type prefix removed. The attachment marker is read
    from the item's own ``<li>…</li>`` body so a following section header can't
    leak its text (or a stray marker) into the wrong item.
    """
    for chunk in re.split(r"(?=<li\b[^>]*\bunique=)", agenda_html):
        head = re.match(r"<li\b[^>]*>", chunk)
        if not head:
            continue
        m = re.search(r'\bunique="([A-Z0-9]+)"', head.group(0))
        if not m:
            continue
        body = chunk.split("</li>", 1)[0]            # this item's content only
        has_marker = ATTACH_MARKER in body.lower()
        xt = re.search(r'\bXtitle="([^"]*)"', head.group(0))
        title = ACTION_PREFIX_RE.sub("", html.unescape(xt.group(1)).strip()) if xt else _strip(body)
        title = re.sub(r"\s+", " ", title).strip()
        if not title:
            continue
        yield m.group(1), title[:140], has_marker


def captured_item_unids() -> set:
    """item_unique values that have >=1 file in the crawl manifest (_index.csv)."""
    idx, out = ROOT / "_index.csv", set()
    if idx.exists():
        with idx.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("item_unique"):
                    out.add(row["item_unique"])
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Audit BoardDocs agenda attachment coverage.")
    ap.add_argument("--start", metavar="YYYY-MM-DD", type=d.parse_iso_date)
    ap.add_argument("--end", metavar="YYYY-MM-DD", type=d.parse_iso_date)
    ap.add_argument("--gaps-only", action="store_true", help="print only flagged items")
    args = ap.parse_args(argv)

    have = captured_item_unids()
    meetings = d.all_dated_meetings(d.list_meetings())
    if args.start:
        meetings = [(dt, m) for dt, m in meetings if dt >= args.start]
    if args.end:
        meetings = [(dt, m) for dt, m in meetings if dt <= args.end]

    ROOT.mkdir(parents=True, exist_ok=True)
    out_path = ROOT / "_coverage_audit.csv"
    gaps, n_items = [], 0
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["meeting_date", "meeting_name", "item_unique", "item_title",
                    "attachment_marker", "file_captured", "status"])
        for dt, m in meetings:
            try:
                agenda = d._post("BD-GetAgenda",
                                 {"id": m["unique"], "current_committee_id": d.COMMITTEE_ID})
            except Exception as e:
                print(f"  ! agenda {dt}: {e}", file=sys.stderr)
                continue
            for unid, title, marker in parse_items(agenda):
                n_items += 1
                has_file = unid in have
                if has_file:
                    status = "ok"
                elif marker:
                    status = "marker-no-file"
                elif DOC_RE.search(title):
                    status = "doclike-no-file"
                else:
                    status = "ok"
                w.writerow([dt.isoformat(), m.get("name", ""), unid, title,
                            "yes" if marker else "no", "yes" if has_file else "no", status])
                if status != "ok":
                    gaps.append((dt.isoformat(), m.get("name", ""), title, status))
            if not args.gaps_only:
                print(f"  {dt} | {m.get('name','')[:45]}", flush=True)
            time.sleep(0.1)

    marker_gaps = [g for g in gaps if g[3] == "marker-no-file"]
    doc_gaps = [g for g in gaps if g[3] == "doclike-no-file"]
    print(f"\nDONE  meetings={len(meetings)}  items={n_items}")
    print(f"GAPS  marker-no-file={len(marker_gaps)}  doclike-no-file={len(doc_gaps)}  -> {out_path}")
    print("\n--- doclike-no-file (a document is implied but nothing was attached) ---")
    for iso, name, title, _ in doc_gaps:
        print(f"  {iso} | {name[:32]} | {title}")
    print("\n--- marker-no-file (BoardDocs flags an attachment we couldn't fetch) ---")
    for iso, name, title, _ in marker_gaps[:60]:
        print(f"  {iso} | {name[:32]} | {title}")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
