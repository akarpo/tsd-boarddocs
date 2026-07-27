"""Extract plain text from every TroySD document into _text/ mirror tree.

Output layout (corpus root from TSD_BOE_ROOT env var, default ~/Downloads/tsd-boe-data):
  <root>/_text/<meeting_folder>/<original_filename>.txt

For .doc and .ppt (legacy formats), no extractor is bundled — those files
are skipped and recorded in _text/_skipped.txt for visibility. See
extract_legacy.py for an MS Word/PowerPoint COM-based fallback (Windows only).
"""
from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError
import pdfplumber
import docx
from pptx import Presentation
import openpyxl
from striprtf.striprtf import rtf_to_text

ROOT = Path(os.environ.get("TSD_BOE_ROOT") or Path.home() / "Downloads" / "tsd-boe-data")
TEXT_ROOT = ROOT / "_text"


# A digit split off from its own thousands group, e.g. "1 23,879,792".
SPLIT_NUM = re.compile(r"\d \d{2,3},")


def _pypdf_pages(p: Path) -> list[str]:
    try:
        r = PdfReader(str(p), strict=False)
    except (PdfReadError, Exception):
        return []
    out = []
    for page in r.pages:
        try:
            out.append(page.extract_text() or "")
        except Exception:
            out.append("")
    return out


def _plumber_pages(p: Path) -> list[str]:
    try:
        with pdfplumber.open(str(p)) as pdf:
            out = []
            for page in pdf.pages:
                try:
                    out.append(page.extract_text() or "")
                except Exception:
                    out.append("")
            return out
    except Exception:
        return []


def _reorder(pypdf_txt: str, plumber_txt: str) -> str:
    """Rotate pypdf's page text so it starts where pdfplumber says the page does.

    pypdf emits runs in content-stream order; on these documents that puts a
    page's heading block *after* its table, so a sequential reader attributes
    each table to the wrong heading. pdfplumber reads in visual order but
    corrupts figures (it splits "123,879,792" into "1 23,879,792"), so it can't
    be trusted for the characters — only for where the page actually begins.

    Take pdfplumber's first line, find that same line in pypdf's text, and
    rotate. Returns pypdf's text unchanged if the anchor isn't found.
    """
    plines = [l.strip() for l in plumber_txt.split("\n") if l.strip()]
    ylines = pypdf_txt.split("\n")
    if not plines or not ylines:
        return pypdf_txt
    anchor = plines[0]
    if len(anchor) < 6:                      # too generic to match on
        return pypdf_txt
    for i, l in enumerate(ylines):
        if l.strip() == anchor:
            if i == 0:
                return pypdf_txt             # already in reading order
            return "\n".join(ylines[i:] + ylines[:i])
    return pypdf_txt


def text_pdf(p: Path) -> str:
    """Extract a PDF's text with pypdf's characters and pdfplumber's ordering.

    Neither library is correct alone on this corpus. pypdf preserves figures
    exactly but emits page content out of reading order; pdfplumber reads in
    visual order but splits digits off their thousands groups, which silently
    corrupts every dollar amount. Since the corpus exists to be queried for
    dollar amounts, the characters have to come from pypdf.

    So: extract with both, and use pdfplumber only to decide where each page
    starts. pdfplumber is skipped entirely when pypdf's output already looks
    like reading order, and falls back cleanly whenever either side fails.
    """
    ypages = _pypdf_pages(p)
    ytxt = "\n".join(ypages).strip()
    if not ytxt:
        # pypdf found nothing — take pdfplumber's text even with its defects
        return "\n".join(_plumber_pages(p)).strip()

    ppages = _plumber_pages(p)
    if len(ppages) != len(ypages):
        return ytxt                          # can't align pages; trust pypdf

    fixed = [_reorder(y, q) for y, q in zip(ypages, ppages)]
    return "\n".join(fixed).strip()


def text_docx(p: Path) -> str:
    try:
        d = docx.Document(str(p))
    except Exception:
        return ""
    parts = [par.text for par in d.paragraphs]
    for tbl in d.tables:
        for row in tbl.rows:
            for cell in row.cells:
                parts.append(cell.text)
    return "\n".join(parts).strip()


def text_pptx(p: Path) -> str:
    try:
        prs = Presentation(str(p))
    except Exception:
        return ""
    parts = []
    for i, slide in enumerate(prs.slides, 1):
        parts.append(f"--- Slide {i} ---")
        for shape in slide.shapes:
            if shape.has_text_frame:
                for par in shape.text_frame.paragraphs:
                    parts.append("".join(r.text for r in par.runs))
            if shape.has_table:
                for row in shape.table.rows:
                    for cell in row.cells:
                        parts.append(cell.text)
    return "\n".join(parts).strip()


def text_xlsx(p: Path) -> str:
    try:
        wb = openpyxl.load_workbook(str(p), data_only=True, read_only=True)
    except Exception:
        return ""
    parts = []
    for ws in wb.worksheets:
        parts.append(f"=== Sheet: {ws.title} ===")
        for row in ws.iter_rows(values_only=True):
            cells = ["" if v is None else str(v) for v in row]
            if any(cells):
                parts.append("\t".join(cells))
    wb.close()
    return "\n".join(parts).strip()


def text_rtf(p: Path) -> str:
    try:
        return rtf_to_text(p.read_text(encoding="utf-8", errors="replace")).strip()
    except Exception:
        return ""


EXTRACT = {
    ".pdf": text_pdf,
    ".docx": text_docx,
    ".pptx": text_pptx,
    ".xlsx": text_xlsx,
    ".rtf": text_rtf,
}


def main():
    TEXT_ROOT.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in ROOT.rglob("*")
                   if p.is_file()
                   and not p.name.startswith("_")
                   and p.suffix.lower() != ".py"
                   and TEXT_ROOT not in p.parents)

    skipped_log = (TEXT_ROOT / "_skipped.txt").open("w", encoding="utf-8")
    summary = {"ok": 0, "empty": 0, "skipped": 0, "error": 0}
    t0 = time.time()
    n = len(files)

    for i, p in enumerate(files, 1):
        ext = p.suffix.lower()
        rel = p.relative_to(ROOT)
        out = TEXT_ROOT / rel.with_suffix(rel.suffix + ".txt")
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.exists() and out.stat().st_size > 0:
            summary["ok"] += 1
            continue
        fn = EXTRACT.get(ext)
        if fn is None:
            skipped_log.write(f"{rel}\t(no extractor for {ext})\n")
            summary["skipped"] += 1
            continue
        try:
            txt = fn(p)
        except Exception as e:
            skipped_log.write(f"{rel}\tERROR: {e}\n")
            summary["error"] += 1
            continue
        if not txt:
            skipped_log.write(f"{rel}\t(empty extraction)\n")
            summary["empty"] += 1
            continue
        out.write_text(txt, encoding="utf-8")
        summary["ok"] += 1
        if i % 50 == 0 or i == n:
            elapsed = time.time() - t0
            print(f"[{i:>4}/{n}] {elapsed:6.1f}s  {summary}", flush=True)

    skipped_log.close()
    print(f"DONE {summary}")


if __name__ == "__main__":
    sys.exit(main() or 0)
