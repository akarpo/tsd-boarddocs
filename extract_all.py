"""Extract plain text from every TroySD document into _text/ mirror tree.

Output layout:
  C:\\Dev\\TroySD\\_text\\<meeting_folder>\\<original_filename>.txt

For .doc and .ppt (legacy formats), no extractor is bundled — those files
are skipped and recorded in _text\\_skipped.txt for visibility.
"""
from __future__ import annotations

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

ROOT = Path(r"C:\Dev\TroySD")
TEXT_ROOT = ROOT / "_text"


def text_pdf(p: Path) -> str:
    parts = []
    try:
        r = PdfReader(str(p), strict=False)
        for page in r.pages:
            try:
                t = page.extract_text() or ""
            except Exception:
                t = ""
            parts.append(t)
    except (PdfReadError, Exception):
        pass
    txt = "\n".join(parts).strip()
    if txt:
        return txt
    # fallback: pdfplumber for tricky PDFs
    parts = []
    try:
        with pdfplumber.open(str(p)) as pdf:
            for page in pdf.pages:
                try:
                    parts.append(page.extract_text() or "")
                except Exception:
                    pass
    except Exception:
        pass
    return "\n".join(parts).strip()


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
