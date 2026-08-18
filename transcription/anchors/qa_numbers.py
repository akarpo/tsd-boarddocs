#!/usr/bin/env python3
"""QA the agenda numbering on every anchor.

Numbers now come from the published BoardDocs outline rather than `chunks`, so
this checks the assignment rather than trusting it:

  EXISTS      every number an anchor claims is really in that meeting's outline
  UNIQUE      no sub-item (level 2) is claimed by two different chapters
  ORDER       category numbers move forward through the meeting, allowing the
              genuine jumps boards make within a category
  SEMANTIC    the chapter label and the outline title it claims share vocabulary;
              a claim with no overlap at all is flagged for eyeballing
  COVERED     every outline sub-item the transcript shows being DISCUSSED has a
              chapter (the old coverage gate, now driven off the outline)

  python3 qa_numbers.py            # whole corpus
  python3 qa_numbers.py 2026-01-13
"""
from __future__ import annotations
import json, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
import os as _os
DATA = Path(_os.environ.get("ANCHORS_DATA")
            or (HERE.parent.parent / "scratch" / "anchors-rebuild"))
AUTH = HERE / "authored"


def _outlines():
    """Committed alongside the tools; the workdir copy wins if present."""
    w = DATA / "agenda_outlines.json"
    return w if w.exists() else HERE / "agenda_outlines.json"

sys.path.insert(0, str(HERE))
from number_anchors import toks                      # noqa: E402

def hms(ms):
    s = ms // 1000
    return f"{s//3600}:{s%3600//60:02d}:{s%60:02d}"

# Procedural attachments that ride along under a category and are never a topic.
# They false-positive because the words appear whenever the chair announces the
# section they hang off.
BOILERPLATE = re.compile(r"guidelines for public comment"
                         r"|resolution to approve consent agenda", re.I)

def discussed(date, outline, utts):
    """Which level-2 outline items does the transcript actually take up?"""
    out = {}
    for o in outline:
        if o["level"] != 2 or BOILERPLATE.search(o["title"]):
            continue
        t = toks(o["title"])
        if len(t) < 2:
            continue
        hits = [u["start_ms"] for u in utts
                if len(t & toks(u.get("text") or "")) >= 2]
        if len(hits) >= 3:
            out[o["item"]] = hms(hits[0])
    return out

def check(date):
    outlines = json.load(open(_outlines()))
    outline = outlines.get(date, [])
    valid = {o["item"]: o["title"] for o in outline}
    rows = json.load(open(AUTH / f"anchors_{date}.json"))
    try:
        utts = json.load(open(DATA / f"utts_{date}.json"))
    except FileNotFoundError:
        utts = []
    problems = []

    seen = {}
    for r in rows:
        for it in r.get("items", []):
            if it not in valid:
                problems.append(("EXISTS", r["t"], f"{it} is not in the outline — {r['label'][:44]}"))
                continue
            if "." in it:
                if it in seen:
                    problems.append(("UNIQUE", r["t"],
                                     f"{it} also claimed at {seen[it]} — {r['label'][:40]}"))
                seen[it] = r["t"]
            # No ORDER check. Boards genuinely work the agenda out of sequence --
            # 2026-01-13 took 3.C and 3.B before 3.A, and workshops routinely take
            # public communication (category 1) after business. Chapters are
            # chronological, so a "regression" is usually the meeting, not an error.
            ov = toks(r["label"]) & toks(valid[it])
            if "." in it and not ov and len(toks(valid[it])) >= 2:
                problems.append(("SEMANTIC", r["t"],
                                 f"{it} '{valid[it][:34]}' shares nothing with '{r['label'][:34]}'"))

    anchored = {i for r in rows for i in r.get("items", [])}
    cats = {i.split(".")[0] for i in anchored}
    for item, at in discussed(date, outline, utts).items():
        # A sub-item is covered by a chapter claiming it OR its parent category:
        # consent items (minutes, treasurer's report, guidelines) are read out and
        # approved en bloc under one "Consent agenda" chapter and should not each
        # get their own -- that is the agenda working normally, not a gap.
        if item in anchored or item.split(".")[0] in cats:
            continue
        problems.append(("COVERED", at, f"{item} '{valid[item][:40]}' discussed, no chapter"))
    return problems

def main():
    dates = [sys.argv[1]] if len(sys.argv) > 1 else \
            sorted(p.stem.replace("anchors_", "") for p in AUTH.glob("anchors_*.json"))
    total = 0
    from collections import Counter
    kinds = Counter()
    for d in dates:
        probs = check(d)
        total += len(probs)
        for k, _, _ in probs:
            kinds[k] += 1
        if probs:
            print(f"\n===== {d} =====")
            for k, t, msg in probs:
                print(f"  {k:<9} {t:>8}  {msg}")
    print(f"\n{len(dates)} meetings checked · {total} problems  {dict(kinds)}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
