#!/usr/bin/env python3
"""Build the paste-ready Facebook post and first comment for a meeting, as Word files.

    python3 scripts/facebook_notes.py facebook/2026-10-06.md --date 2026-10-06 \
        --transcript "transcripts/2026-10-06 - Troy (MI) School District - Board of Education - Workshop Meeting.txt"

Writes two .docx files to --out-dir (default ~/Desktop), each meant to be opened, selected
in full and pasted into Facebook as-is — no labels, no page breaks to copy around:

  TSD Board <Kind> <date> - Facebook Post.docx           the post body, from the source file
  TSD Board <Kind> <date> - Facebook First Comment.docx  the YouTube description, from D1

The format, the writing rules and the source syntax are in docs/FACEBOOK_NOTES.md. Source
syntax, one block per line (blank lines are ignored):

  *text*            italic paragraph (the title line; the closing caveat)
  **text**          bold paragraph (the lede; every section heading)
  X Recording - URL "Meeting Recording - " / "Forum Recording - " italic, the link plain
  · text            bullet (the middle dot is kept as text, which is how Facebook shows it)
  > text            stand-alone quote, italic
  anything else     plain paragraph

With --transcript, every double-quoted passage of four or more words is looked up in the
transcript (case, punctuation and spacing ignored) and any that is not found is printed:
a quote that is not in the record does not go out. Exit 1 if any quote is missing or the
post breaks the format.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from docx import Document
from docx.shared import Pt

REPO = Path(__file__).resolve().parent.parent
REC = re.compile(r"^((?:Meeting|Forum) Recording - )(\S+)\s*$")


def parse(src: str) -> list[tuple[str, str]]:
    """Source lines -> [(kind, text)] with kind in title/italic/bold/recording/bullet/quote/plain."""
    out = []
    for raw in src.splitlines():
        s = raw.strip()
        if not s:
            continue
        if s.startswith("**") and s.endswith("**") and len(s) > 4:
            out.append(("bold", s[2:-2]))
        elif s.startswith("*") and s.endswith("*") and len(s) > 2:
            out.append(("italic", s[1:-1]))
        elif REC.match(s):
            out.append(("recording", s))
        elif s.startswith("· "):
            out.append(("bullet", s))
        elif s.startswith("> "):
            out.append(("quote", s[2:]))
        else:
            out.append(("plain", s))
    return out


def problems(blocks: list[tuple[str, str]]) -> list[str]:
    """The shape every post has had: title, recording link, bold lede ... bold caveat + italic."""
    p = []
    kinds = [k for k, _ in blocks]
    if kinds[:3] != ["italic", "recording", "bold"]:
        p.append(f"must open with *title*, the recording line, then the **lede** (got {kinds[:3]})")
    if len(blocks) < 2 or blocks[-2] != ("bold", "One important caveat") or kinds[-1] != "italic":
        p.append("must close with **One important caveat** followed by one *italic* paragraph")
    for k, t in blocks:
        if t.count('"') % 2:
            p.append(f"unbalanced quote marks: {t[:70]}…")
    return p


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9$%' ]", " ", s.lower().replace("’", "'"))).strip()


def missing_quotes(blocks, transcript: str) -> list[str]:
    hay = norm(transcript)
    bad = []
    for _, t in blocks:
        for q in re.findall(r'"([^"]+)"', t):
            if len(q.split()) >= 4 and norm(q) not in hay:
                bad.append(q)
    return bad


def write_post(blocks, path: Path) -> None:
    doc = Document()
    st = doc.styles["Normal"]
    st.font.name, st.font.size = "Calibri", Pt(11)
    st.paragraph_format.space_after = Pt(6)
    for kind, text in blocks:
        p = doc.add_paragraph()
        if kind == "recording":
            m = REC.match(text)
            p.add_run(m.group(1)).italic = True
            p.add_run(m.group(2))
        else:
            r = p.add_run(text)
            r.bold = kind == "bold"
            r.italic = kind in ("italic", "quote")
    doc.save(path)


def write_comment(text: str, path: Path) -> None:
    doc = Document()
    st = doc.styles["Normal"]
    st.font.name, st.font.size = "Calibri", Pt(11)
    st.paragraph_format.space_after = Pt(0)
    for line in text.split("\n"):
        doc.add_paragraph(line)
    doc.save(path)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("source", help="facebook/<date>.md")
    ap.add_argument("--date", required=True, help="YYYY-MM-DD; the first comment is built from D1")
    ap.add_argument("--transcript", help="attributed transcript .txt to check quotes against")
    ap.add_argument("--comment-file", help="use this text for the first comment instead of D1")
    ap.add_argument("--out-dir", default=str(Path.home() / "Desktop"))
    a = ap.parse_args()

    blocks = parse(Path(a.source).read_text(encoding="utf-8"))
    bad = problems(blocks)
    if a.transcript:
        miss = missing_quotes(blocks, Path(a.transcript).read_text(encoding="utf-8"))
        bad += [f"quote not in the transcript: \"{q}\"" for q in miss]

    if a.comment_file:
        comment = Path(a.comment_file).read_text(encoding="utf-8").strip()
    else:
        sys.path.insert(0, str(REPO / "transcription" / "anchors"))
        import push_desc  # the same builder that writes the YouTube description
        comment = push_desc.build(a.date)[1]

    title = blocks[0][1]
    kind = "Workshop" if "Workshop" in title else "Regular Meeting" if "Regular" in title else "Meeting"
    out = Path(a.out_dir).expanduser()
    post_p = out / f"TSD Board {kind} {a.date} - Facebook Post.docx"
    comm_p = out / f"TSD Board {kind} {a.date} - Facebook First Comment.docx"
    write_post(blocks, post_p)
    write_comment(comment, comm_p)
    words = sum(len(t.split()) for _, t in blocks)
    print(f"{post_p}\n  {len(blocks)} blocks, {words} words")
    print(f"{comm_p}\n  {len(comment.splitlines())} lines")
    for b in bad:
        print("  !", b)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
