"""What share of agenda items carry an attachment?

Counts, across a trailing window (default 3 years), how many agenda items in
**Regular** and **Workshop** meetings have a BoardDocs attachment marker
("This Agenda Item Contains an Attachment"). Special meetings (closed session)
and other meeting types are excluded.

An "agenda item" is any distinct `<li unique=...>` line item. "Has an
attachment" uses BoardDocs' own per-item marker, which counts an attached
document whether or not it is exposed publicly (so this is the inclusive rate;
public-only access is a subset). Read-only against BoardDocs.

Usage:
  python attachment_rate.py                 # trailing 3 years to today
  python attachment_rate.py --years 5
  python attachment_rate.py --start 2023-01-01 --end 2025-12-31
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import download_troysd as d
from audit_coverage import parse_items


def meeting_type(name: str) -> str:
    if "Regular Meeting" in name:
        return "Regular"
    if "Workshop" in name:
        return "Workshop"
    if "Special Meeting" in name:
        return "Special"
    return "Other"


def pct(a: int, b: int) -> str:
    return f"{100 * a / b:.1f}%" if b else "n/a"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Attachment rate for Regular + Workshop meetings.")
    ap.add_argument("--years", type=int, default=3, help="trailing window in years (default 3)")
    ap.add_argument("--start", metavar="YYYY-MM-DD", type=d.parse_iso_date)
    ap.add_argument("--end", metavar="YYYY-MM-DD", type=d.parse_iso_date)
    args = ap.parse_args(argv)

    end = args.end or dt.date.today()
    start = args.start or end.replace(year=end.year - args.years)
    print(f"window: {start} .. {end}  (Regular + Workshop meetings only)\n")

    by_type = defaultdict(lambda: [0, 0])      # type -> [items, with_attachment]
    by_year = defaultdict(lambda: [0, 0])      # year -> [items, with_attachment]
    meetings_counted = Counter()
    excluded = Counter()

    for date, m in d.all_dated_meetings(d.list_meetings()):
        if not (start <= date <= end):
            continue
        name = m.get("name", "")
        t = meeting_type(name)
        if t not in ("Regular", "Workshop"):
            excluded[t] += 1
            continue
        try:
            agenda = d._post("BD-GetAgenda",
                             {"id": m["unique"], "current_committee_id": d.COMMITTEE_ID})
        except Exception as e:
            print(f"  ! agenda {date}: {e}", file=sys.stderr)
            continue
        n_items = n_attach = 0
        for _unid, _title, marker in parse_items(agenda):
            n_items += 1
            n_attach += 1 if marker else 0
        by_type[t][0] += n_items
        by_type[t][1] += n_attach
        by_year[date.year][0] += n_items
        by_year[date.year][1] += n_attach
        meetings_counted[t] += 1
        print(f"  {date} | {t:8} | {name[:42]:42} | items={n_items:3}  attach={n_attach:3}  {pct(n_attach, n_items)}")

    tot_i = sum(v[0] for v in by_type.values())
    tot_a = sum(v[1] for v in by_type.values())
    print(f"\n==== Attachment rate, {start} .. {end} ====")
    for t in ("Regular", "Workshop"):
        i, a = by_type[t]
        print(f"  {t:8}: {a:5}/{i:<5} items have an attachment = {pct(a, i):>6}"
              f"   ({meetings_counted[t]} meetings)")
    print(f"  {'TOTAL':8}: {tot_a:5}/{tot_i:<5} items have an attachment = {pct(tot_a, tot_i):>6}"
          f"   ({sum(meetings_counted.values())} meetings)")
    print("\n  by calendar year (Regular + Workshop combined):")
    for y in sorted(by_year):
        i, a = by_year[y]
        print(f"    {y}: {pct(a, i):>6}   ({a}/{i})")
    if excluded:
        print(f"\n  excluded meeting types in window: {dict(excluded)}")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
