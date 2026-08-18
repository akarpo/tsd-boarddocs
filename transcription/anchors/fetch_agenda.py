#!/usr/bin/env python3
"""Pull the COMPLETE numbered agenda outline for a meeting from BoardDocs.

`chunks` only records `agenda_item` for items that carry an attachment, so the
structural half of every agenda -- Pledge, Recognition, Public Communication,
Adjournment -- has no number anywhere in D1. BoardDocs itself numbers all of it.
This reads `BD-GetAgenda` and returns every category and sub-item with its number.

  python3 fetch_agenda.py 2026-07-22
  python3 fetch_agenda.py --all -o agenda_outlines.json
"""
from __future__ import annotations
import argparse, html, importlib.util, json, re, sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
spec = importlib.util.spec_from_file_location("dl", REPO / "download_troysd.py")
dl = importlib.util.module_from_spec(spec); spec.loader.exec_module(dl)

# The outline is a flat sequence, not a tree: each <dl class="wrap-category"> is
# followed by the <li class="item"> rows that belong to it (the <dd> inside the
# <dl> is left empty). So walk the document in order and carry the current
# category number.
CAT = re.compile(r'<dl[^>]*class="wrap-category"[^>]*categoryorder="(\d+)"', re.S)
CAT_NAME = re.compile(r'<span class="order">\s*([^<]*?)\s*</span>\s*'
                      r'<span class="category-name">(.*?)</span>', re.S)
ITEM = re.compile(r'<li[^>]*class="[^"]*\bitem\b[^"]*"[^>]*>.*?'
                  r'<span class="order">\s*([A-Za-z0-9]+)\.\s*</span>\s*'
                  r'<span class="title">(.*?)</span>', re.S)

def clean(t: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", t))).strip()

def outline(date: str) -> list[dict]:
    nd = date.replace("-", "")
    ms = [m for m in dl.list_meetings() if m.get("numberdate") == nd]
    if not ms:
        return []
    raw = dl._post("BD-GetAgenda",
                   {"id": ms[0]["unique"], "current_committee_id": dl.COMMITTEE_ID})
    marks = []
    for m in CAT.finditer(raw):
        marks.append(("cat", m.start(), m.group(1)))
    for m in ITEM.finditer(raw):
        marks.append(("item", m.start(), (m.group(1), clean(m.group(2)))))
    marks.sort(key=lambda x: x[1])

    out, cur = [], None
    for kind, pos, payload in marks:
        if kind == "cat":
            cur = payload
            nm = CAT_NAME.search(raw, pos, pos + 900)
            out.append({"item": cur, "title": clean(nm.group(2)) if nm else "",
                        "level": 1})
        elif cur:
            letter, title = payload
            out.append({"item": f"{cur}.{letter}", "title": title, "level": 2})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("date", nargs="?")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("-o", "--out")
    a = ap.parse_args()
    if a.all:
        data = {}
        for line in open(Path(__file__).resolve().parent.parent.parent /
                         "scratch/anchors-rebuild/meetings.tsv"):
            d = line.split("\t")[0].strip()
            data[d] = outline(d)
            print(f"{d}: {len(data[d])} agenda entries", flush=True)
        json.dump(data, open(a.out or "agenda_outlines.json", "w"), indent=1)
    else:
        for r in outline(a.date):
            print(f"  {r['item']:<7}{'  ' if r['level']==2 else ''}{r['title'][:74]}")

if __name__ == "__main__":
    sys.exit(main())
