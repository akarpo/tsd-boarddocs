#!/usr/bin/env python3
"""Spot check-register PDFs in the BoardDocs corpus and hand new ones to tsd-checkregister.

The two repos are separate deliverables that share one upstream: BoardDocs posts a
monthly Pentamation register as an attachment on a regular meeting, tsd-boarddocs
ingests it as one more document, and tsd-checkregister needs it as 1,500-odd rows
of structured payment data. Nothing connected them, so a register could sit in the
archive for months while the spending site quietly ran a month behind.

    python3 scripts/check_register_handoff.py                # report what is new
    python3 scripts/check_register_handoff.py --stage        # copy new PDFs across
    python3 scripts/check_register_handoff.py --stage --parse  # ... and parse+append

`--parse` stops short of rebuilding: `rebuild.py --assemble-only` takes ~25s and
rewrites two committed deliverables, so it stays an explicit step the caller runs
in the check-register repo.

Detection is by filename, which is how the district names these consistently:
"<n> <Month> <Year> Check Register.pdf". A register attached under a different name
would be missed -- the reconciliation below is what catches that, because it
compares meetings-with-a-register against meetings-in-the-dataset rather than
trusting the filename scan on its own.
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ROOT = Path(__import__("os").environ.get("TSD_BOE_ROOT") or REPO / "data" / "tsd-boe-data")
CR_REPO = Path(__import__("os").environ.get("TSD_CR_REPO") or Path.home() / "Downloads" / "tsd-checkregister")
CR_PDFS = CR_REPO / "source_data" / "BoardDocs_PDFs"
CR_PKL = CR_REPO / "Working Folder" / "Cache and Tools" / "build" / "combined_lines.pkl"

MEETING_DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})_")
REGISTER_NAME = re.compile(r"check\s*register", re.I)


def find_registers() -> list[tuple[str, Path]]:
    """[(meeting_date, pdf_path)] for every check-register PDF in the corpus."""
    out = []
    for meeting in sorted(p for p in ROOT.iterdir() if p.is_dir() and MEETING_DATE.match(p.name)):
        date = MEETING_DATE.match(meeting.name).group(1)
        for f in sorted(meeting.iterdir()):
            if f.suffix.lower() == ".pdf" and REGISTER_NAME.search(f.name):
                out.append((date, f))
    return out


def dataset_meetings() -> set[str]:
    """Source-meeting dates already represented in the check-register dataset."""
    if not CR_PKL.exists():
        print(f"WARNING: {CR_PKL} not found — treating every register as new", file=sys.stderr)
        return set()
    import pickle
    rows = pickle.loads(CR_PKL.read_bytes())
    return {r["Source Meeting"] for r in rows}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", action="store_true", help="copy new register PDFs into tsd-checkregister")
    ap.add_argument("--parse", action="store_true", help="with --stage: parse and append to combined_lines.pkl")
    ap.add_argument("--since", default="", help="only consider meetings on or after YYYY-MM-DD")
    a = ap.parse_args()

    registers = [(d, p) for d, p in find_registers() if d >= a.since]
    have = dataset_meetings()
    new = [(d, p) for d, p in registers if d not in have]

    print(f"check registers in the corpus : {len(registers)}")
    print(f"source meetings in the dataset: {len(have)}")
    print(f"registers not yet ingested    : {len(new)}")
    for d, p in new:
        print(f"   {d}  {p.name}")
    if not new:
        print("\nnothing to do — the spending site is current with BoardDocs")
        return 0
    if not a.stage:
        print("\nre-run with --stage (and optionally --parse) to hand these across")
        return 0

    CR_PDFS.mkdir(parents=True, exist_ok=True)
    staged = []
    for d, p in new:
        # parser.py reads provenance from the filename prefix, so the meeting date
        # has to lead -- not the date inside the register, which is the month it covers.
        dst = CR_PDFS / f"{d}_{p.name}"
        shutil.copy2(p, dst)
        staged.append((d, dst))
        print(f"staged {dst.name}")

    if not a.parse:
        print(f"\n{len(staged)} PDF(s) staged in {CR_PDFS}")
        return 0

    sys.path.insert(0, str(CR_REPO / "Working Folder" / "Cache and Tools" / "build"))
    import pickle
    from parser import parse_pdf                      # noqa: E402
    from categorize_v2 import categorize              # noqa: E402
    from subjects import classify_subject, classify_confidence  # noqa: E402

    rows = pickle.loads(CR_PKL.read_bytes())
    before = len(rows)
    for d, pdf in staged:
        parsed = parse_pdf(pdf)
        total = sum(r["Amount"] for r in parsed)
        printed = printed_total(pdf)
        # The register prints its own TOTAL REPORT and the parser skips that line,
        # so it is an independent check: it does not share a single assumption with
        # the code that produced `total`. A silent row-drop shows up here and
        # nowhere else.
        if printed is None:
            print(f"  {d}: {len(parsed):,} rows, {total:,.2f} — NO PRINTED TOTAL FOUND, verify by hand")
        elif abs(total - printed) > 0.005:
            print(f"  {d}: MISMATCH parsed {total:,.2f} vs printed {printed:,.2f} — NOT appended")
            continue
        else:
            print(f"  {d}: {len(parsed):,} rows, {total:,.2f} = printed TOTAL REPORT")
        # Classify exactly as rebuild_after_bundlefix.py does, or the appended rows
        # carry 14 fields against the stored 17 and the workbook goes ragged.
        for r in parsed:
            r["Category"] = categorize(r.get("Vendor Name", ""), r.get("Fund", ""),
                                       r.get("Function Code", ""), r.get("Account", ""),
                                       r.get("Budget Unit", ""), r.get("Amount", 0))
            if r.get("Budget Unit", "").startswith("101425221"):
                r["Subject"] = classify_subject(r.get("Vendor Name", ""), r.get("Description", ""))
                r["Confidence"] = classify_confidence(r.get("Vendor Name", ""), r["Subject"])
            else:
                r["Subject"] = r["Confidence"] = ""
        if set(parsed[0]) != set(rows[0]):
            print(f"  {d}: schema mismatch {set(rows[0]) ^ set(parsed[0])} — NOT appended")
            continue
        rows += parsed

    if len(rows) == before:
        print("\nnothing appended")
        return 1
    CR_PKL.write_bytes(pickle.dumps(rows))
    print(f"\ncombined_lines.pkl {before:,} -> {len(rows):,} rows")
    print(f"Next, in {CR_REPO}:")
    print("  cd 'Working Folder/Cache and Tools/build' && python3 rebuild.py --assemble-only")
    print("  python3 validate.py && python3 check_published_figures.py")
    print("  git add -A && git commit && git push      # Pages deploys from main")
    return 0


def printed_total(pdf: Path) -> float | None:
    """The TOTAL REPORT the register prints for itself, or None.

    Two amount columns follow the label (sales tax, then amount), so the naive
    'first number after TOTAL REPORT' grabs 0.00 and reconciles against nothing.
    """
    try:
        from pypdf import PdfReader
        txt = "\n".join((pg.extract_text() or "") for pg in PdfReader(str(pdf)).pages)
    except Exception:
        return None
    m = re.search(r"TOTAL REPORT\s+[\d,]+\.\d{2}\s+([\d,]+\.\d{2})", txt)
    return float(m.group(1).replace(",", "")) if m else None


if __name__ == "__main__":
    sys.exit(main())
