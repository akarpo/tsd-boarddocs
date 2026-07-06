"""Convert local Word/PowerPoint sources to PDF and upload each as <r2-key>.pdf so
the site can preview them inline. Excel is intentionally skipped (the viewer links
those out). Resumable via a done-list; re-run to pick up new files.

  R2PUT_SECRET=... TSD_BOE_ROOT=~/tsd-boe-data python scripts/convert_office.py
"""
import os, sys, shutil, tempfile, subprocess, urllib.request, urllib.parse
from pathlib import Path

ROOT = Path(os.environ.get("TSD_BOE_ROOT") or Path.home() / "tsd-boe-data")
SOFFICE = os.environ.get("SOFFICE", "/opt/homebrew/bin/soffice")
R2PUT = "https://tsd-ingest.akarpo.workers.dev/r2put"
SECRET = os.environ.get("R2PUT_SECRET", "")
PREFIX = "troysd-boarddocs"
EXTS = (".docx", ".doc", ".pptx", ".ppt")
DONE = ROOT / "_index" / "converted_pdf.done"
BATCH = 30


def r2key(src: Path) -> str:
    return f"{PREFIX}/{src.relative_to(ROOT).as_posix()}.pdf"   # <meeting>/<file.docx>.pdf


def upload(pdf: Path, key: str):
    u = R2PUT + "?key=" + urllib.parse.quote(key, safe="") + "&secret=" + urllib.parse.quote(SECRET)
    req = urllib.request.Request(u, data=pdf.read_bytes(), method="PUT",
                                 headers={"user-agent": "Mozilla/5.0", "content-type": "application/pdf"})
    urllib.request.urlopen(req, timeout=180).read()


def main():
    done = set(DONE.read_text().splitlines()) if DONE.exists() else set()
    files = [p for p in ROOT.rglob("*") if p.suffix.lower() in EXTS
             and not any(x.startswith("_") for x in p.relative_to(ROOT).parts)]
    todo = [p for p in files if str(p) not in done]
    print(f"total {len(files)}  done {len(done)}  to convert {len(todo)}", flush=True)
    n_ok = n_fail = 0
    with DONE.open("a") as donef:
        for i in range(0, len(todo), BATCH):
            batch = todo[i:i + BATCH]
            tin, tout = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
            mapping = {}
            for j, f in enumerate(batch):                       # unique names to avoid same-stem collisions
                uname = f"{i+j}__{f.stem}{f.suffix}"
                try: shutil.copy(f, tin / uname); mapping[f"{i+j}__{f.stem}"] = f
                except Exception as e: print("copy fail", f.name, str(e)[:50], flush=True)
            try:
                subprocess.run([SOFFICE, "--headless", "--convert-to", "pdf", "--outdir", str(tout)]
                               + [str(p) for p in tin.iterdir()], capture_output=True, timeout=1200)
            except Exception as e:
                print("soffice batch error:", str(e)[:80], flush=True)
            for ustem, f in mapping.items():
                pdf = tout / (ustem + ".pdf")
                if pdf.exists() and pdf.stat().st_size > 0:
                    try: upload(pdf, r2key(f)); donef.write(str(f) + "\n"); donef.flush(); n_ok += 1
                    except Exception as e: print("upload fail", f.name, str(e)[:60], flush=True); n_fail += 1
                else:
                    print("no pdf produced:", f.name, flush=True); n_fail += 1
            shutil.rmtree(tin, ignore_errors=True); shutil.rmtree(tout, ignore_errors=True)
            print(f"  progress: {n_ok} ok, {n_fail} failed / {len(todo)}", flush=True)
    print(f"DONE: converted+uploaded {n_ok}, failed {n_fail}", flush=True)


if __name__ == "__main__":
    sys.exit(main() or 0)
