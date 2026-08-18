#!/usr/bin/env python3
"""QA the agenda numbering on every anchor.

Numbers now come from the published BoardDocs outline rather than `chunks`, so
this checks the assignment rather than trusting it:

  EXISTS      every number an anchor claims is really in that meeting's outline
  UNIQUE      no sub-item (level 2) is claimed by two different chapters
  ORDER       one anchor's category dips below BOTH its neighbours -- the shape
              a mis-assignment makes, as distinct from the sustained excursion a
              board makes when it genuinely takes a section out of sequence
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
            # Sub-item order within a category is deliberately NOT checked:
            # 2026-01-13 took 3.C and 3.B before 3.A, which is the meeting, not an
            # error. The ORDER pass below works on categories and only on the
            # isolated-dip shape, for the same reason.
            ov = toks(r["label"]) & toks(valid[it])
            if "." in it and not ov and len(toks(valid[it])) >= 2:
                problems.append(("SEMANTIC", r["t"],
                                 f"{it} '{valid[it][:34]}' shares nothing with '{r['label'][:34]}'"))

    # ORDER -- an isolated backward dip in category number.
    #
    # A board working out of sequence moves a whole section and stays there, so
    # its categories still run forward on either side of the move. A number
    # applied to the wrong chapter does something different: one anchor sits
    # below the anchors on BOTH sides of it, then the meeting carries on where it
    # left off. That shape is what this looks for, and it is the check that would
    # have caught 2024-03-19's furniture purchase -- numbered 2.B, "State Schools
    # of Character", between 8.E and 9.
    #
    # SEMANTIC could not: "Furniture purchase -- elementaries & middle schools"
    # and "State Schools of Character - Larson Middle School" share "middle" and
    # "school", so a vocabulary test passes a claim that is plainly wrong. Every
    # one of the seven mis-numberings found on 2026-08-18 shared that property --
    # an incidental token in common, and a category out of place.
    #
    # The last anchor is compared against a sentinel above every category, so a
    # meeting that ends below where it had got to is flagged too; that is how
    # 2024-02-27's closed session was found, numbered 4.D for "Schools Closed to
    # Open Enrollment" on the strength of the word "closed".
    def _cat(i):
        try: return int(str(i).split(".")[0])
        except ValueError: return None
    seq = [(c, r) for r, c in ((r, _cat((r.get("items") or [None])[0])) for r in rows)
           if c is not None]
    for i, (cur, r) in enumerate(seq):
        prev = seq[i - 1][0] if i else None
        nxt = seq[i + 1][0] if i + 1 < len(seq) else 10 ** 6
        if prev is not None and cur < prev and cur < nxt:
            it = r["items"][0]
            after = "the end" if nxt == 10 ** 6 else nxt
            problems.append(("ORDER", r["t"],
                             f"{it} dips below {prev} and {after} — {r['label'][:40]}"))

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
