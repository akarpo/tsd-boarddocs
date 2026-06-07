"""Extract text from legacy .doc and .ppt files via MS Word/PowerPoint COM.

Windows-only — uses COM automation against installed Microsoft Office.
On macOS or Linux, convert legacy files to .docx/.pptx with LibreOffice
(`soffice --headless --convert-to docx file.doc`) and run extract_all.py
instead.

Output mirrors extract_all.py: writes .txt files under <root>/_text/ so
build_index.py can pick them up automatically. Corpus root is set via
the TSD_BOE_ROOT env var (default: a tsd-boe-data/ folder beside the scripts).

Skips files that already have a non-empty .txt counterpart (idempotent).
Restarts Word/PowerPoint every 50 files to avoid memory bloat or hangs.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

if sys.platform != "win32":
    sys.exit(
        "extract_legacy.py requires Windows + Microsoft Office (uses COM).\n"
        "On macOS/Linux, convert .doc/.ppt to .docx/.pptx with LibreOffice:\n"
        "  soffice --headless --convert-to docx <file>.doc\n"
        "  soffice --headless --convert-to pptx <file>.ppt\n"
        "then run extract_all.py."
    )

import win32com.client
import pythoncom
from pywintypes import com_error

ROOT = Path(os.environ.get("TSD_BOE_ROOT") or Path(__file__).resolve().parent / "tsd-boe-data")
TEXT_ROOT = ROOT / "_text"


def open_word():
    # Late binding via Dispatch is more robust than gencache.EnsureDispatch
    # when restarting after Quit().
    w = win32com.client.Dispatch("Word.Application")
    try:
        w.Visible = False
    except com_error:
        time.sleep(1)
        w = win32com.client.Dispatch("Word.Application")
        w.Visible = False
    w.DisplayAlerts = False
    try:
        w.AutomationSecurity = 3  # msoAutomationSecurityForceDisable
    except Exception:
        pass
    return w


def open_pp():
    p = win32com.client.Dispatch("PowerPoint.Application")
    try:
        p.WindowState = 2  # minimized
    except Exception:
        pass
    return p


def text_doc(word, abs_path: str) -> str:
    doc = word.Documents.Open(
        FileName=abs_path,
        ReadOnly=True,
        AddToRecentFiles=False,
        Visible=False,
        ConfirmConversions=False,
    )
    try:
        return doc.Content.Text or ""
    finally:
        doc.Close(SaveChanges=False)


def text_ppt(pp, abs_path: str) -> str:
    pres = pp.Presentations.Open(
        FileName=abs_path,
        ReadOnly=True,
        Untitled=False,
        WithWindow=False,
    )
    parts = []
    try:
        for i, slide in enumerate(pres.Slides, 1):
            parts.append(f"--- Slide {i} ---")
            for shape in slide.Shapes:
                try:
                    if shape.HasTextFrame and shape.TextFrame.HasText:
                        parts.append(shape.TextFrame.TextRange.Text or "")
                except com_error:
                    pass
    finally:
        pres.Close()
    return "\n".join(parts)


def collect(ext_lower: str):
    out = []
    for p in ROOT.rglob(f"*"):
        if not p.is_file():
            continue
        if p.suffix.lower() != ext_lower:
            continue
        if "_text" in p.parts or "_index" in p.parts:
            continue
        rel = p.relative_to(ROOT)
        dest = TEXT_ROOT / rel.with_suffix(rel.suffix + ".txt")
        if dest.exists() and dest.stat().st_size > 0:
            continue
        out.append((p, dest))
    return out


def process(label: str, opener, extractor, files):
    if not files:
        print(f"[{label}] nothing to do")
        return {"ok": 0, "empty": 0, "error": 0}
    summary = {"ok": 0, "empty": 0, "error": 0}
    pythoncom.CoInitialize()
    app = opener()
    print(f"[{label}] {len(files)} files; app started")
    t0 = time.time()
    try:
        for i, (src, dest) in enumerate(files, 1):
            try:
                txt = extractor(app, str(src))
            except com_error as e:
                summary["error"] += 1
                print(f"  ! {src.name}: COM error {e.args}", flush=True)
                # restart on bad state
                try:
                    app.Quit()
                except Exception:
                    pass
                app = opener()
                continue
            except Exception as e:
                summary["error"] += 1
                print(f"  ! {src.name}: {type(e).__name__}: {e}", flush=True)
                continue
            txt = (txt or "").strip()
            if not txt:
                summary["empty"] += 1
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(txt, encoding="utf-8")
            summary["ok"] += 1
            if i % 25 == 0 or i == len(files):
                print(f"  [{i:>4}/{len(files)}] {time.time()-t0:6.1f}s  {summary}",
                      flush=True)
    finally:
        try:
            app.Quit()
        except Exception:
            pass
        pythoncom.CoUninitialize()
    print(f"[{label}] DONE {summary}")
    return summary


def main():
    TEXT_ROOT.mkdir(parents=True, exist_ok=True)
    docs = collect(".doc")
    ppts = collect(".ppt")
    print(f"todo: {len(docs)} .doc, {len(ppts)} .ppt")
    s_doc = process("DOC", open_word, text_doc, docs)
    s_ppt = process("PPT", open_pp, text_ppt, ppts)
    print(f"FINAL  doc={s_doc}  ppt={s_ppt}")


if __name__ == "__main__":
    sys.exit(main() or 0)
