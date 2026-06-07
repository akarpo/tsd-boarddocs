"""Audit BoardDocs agenda coverage — flag agenda items that imply a document but
have no captured attachment.

The crawler (download_troysd.py) only harvests an agenda item's *public-file*
attachments (BD-GetPublicFiles). Documents that are presented but never attached
(e.g. the 2024-03-05 "Levinson Report - Outcomes & Recommendations"), or attached
non-publicly, slip through. This audit cross-references every live agenda item
against the corpus and classifies each item:

  ok                file(s) captured, or a procedural item (no document expected)
  missed-fetchable  BoardDocs HAS public file(s) for this item but none are on
                    disk — a genuine crawl miss; re-run download_troysd.py
  partial-capture   some of the item's public files are on disk, some are not
  marker-no-file    BoardDocs marks it "contains an attachment", but exposes no
                    public file — the attachment is non-public / not fetchable
  doclike-no-file   the title reads like a document (report / findings /
                    recommendation / presentation / study / plan / review /
                    proposal / audit / analysis) with no marker and no file —
                    most likely presented to the board but never attached

A fast pre-filter uses the crawl manifest (`_index.csv`), but BoardDocs
regenerates item/file unique tokens whenever an agenda is edited, so a captured
item can look uncaptured by id alone. Every flagged candidate is therefore
*confirmed live*: we ask BoardDocs for the item's current public files and check
whether those filenames (the only stable key) exist on disk. This eliminates
drift false-positives and is what distinguishes `missed-fetchable` (re-fetch)
from `*-no-file` (nothing to fetch).

It writes `<root>/_coverage_audit.csv` (one row per agenda item) and prints a
summary plus the flagged gaps. Read-only against BoardDocs; downloads nothing.

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
    """item_unique values that have >=1 file in the crawl manifest (_index.csv).

    A fast pre-filter only: BoardDocs regenerates these tokens on agenda edits,
    so absence here is a *candidate* gap to confirm live, not a proven one.
    """
    idx, out = ROOT / "_index.csv", set()
    if idx.exists():
        with idx.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("item_unique"):
                    out.add(row["item_unique"])
    return out


def confirm_gap(unid: str, folder: Path, marker: bool):
    """Live-confirm a candidate gap, drift-proof. Ask BoardDocs for the item's
    *current* public files and match them by filename (the only stable key)
    against the meeting folder on disk — the same path the crawler would write.

    Returns (status, n_boarddocs_files, n_on_disk).
    """
    try:
        files = d.list_files(unid)                       # [(href, filename), …] live
    except Exception:
        files = []
    present = sum(1 for _href, fn in files if (folder / d.safe_name(fn)).exists())
    n = len(files)
    if n and present == n:
        return "ok", n, present                          # captured; the id had drifted
    if present:
        return "partial-capture", n, present
    if n:
        return "missed-fetchable", n, present            # BoardDocs has it, disk doesn't
    return ("marker-no-file" if marker else "doclike-no-file"), 0, 0


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
    gaps, n_items, n_confirm = [], 0, 0
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["meeting_date", "meeting_name", "item_unique", "item_title",
                    "attachment_marker", "boarddocs_files", "files_on_disk", "status"])
        for dt, m in meetings:
            try:
                agenda = d._post("BD-GetAgenda",
                                 {"id": m["unique"], "current_committee_id": d.COMMITTEE_ID})
            except Exception as e:
                print(f"  ! agenda {dt}: {e}", file=sys.stderr)
                continue
            folder = d.meeting_folder(ROOT, dt, m.get("name", ""))
            for unid, title, marker in parse_items(agenda):
                n_items += 1
                doclike = bool(DOC_RE.search(title))
                n_bd = n_disk = ""
                if unid in have:
                    status = "ok"                       # captured (manifest fast-path)
                elif not marker and not doclike:
                    status = "ok"                       # no document implied
                else:
                    # Candidate gap — confirm live (id may have just drifted).
                    status, n_bd, n_disk = confirm_gap(unid, folder, marker)
                    n_confirm += 1
                    time.sleep(0.1)
                w.writerow([dt.isoformat(), m.get("name", ""), unid, title,
                            "yes" if marker else "no", n_bd, n_disk, status])
                if status != "ok":
                    gaps.append((dt.isoformat(), m.get("name", ""), title, status))
            if not args.gaps_only:
                print(f"  {dt} | {m.get('name','')[:45]}", flush=True)
            time.sleep(0.1)

    by = lambda s: [g for g in gaps if g[3] == s]
    order = ["missed-fetchable", "partial-capture", "marker-no-file", "doclike-no-file"]
    blurb = {
        "missed-fetchable": "BoardDocs HAS public file(s) but none are on disk — re-run download_troysd.py",
        "partial-capture": "some of the item's public files are on disk, some are missing",
        "marker-no-file": "BoardDocs flags an attachment but exposes no public file (non-public)",
        "doclike-no-file": "title implies a document but nothing is attached (presented, never uploaded)",
    }
    print(f"\nDONE  meetings={len(meetings)}  items={n_items}  live-confirmed={n_confirm}")
    print("GAPS  " + "  ".join(f"{s}={len(by(s))}" for s in order) + f"  -> {out_path}")
    for s in order:
        rows = by(s)
        if not rows:
            continue
        print(f"\n--- {s} ({blurb[s]}) ---")
        for iso, name, title, _ in rows:
            print(f"  {iso} | {name[:32]} | {title}")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
