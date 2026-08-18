#!/usr/bin/env python3
"""Assign every anchor its BoardDocs agenda number.

The numbers a viewer sees on go.boarddocs.com cover the whole agenda -- Pledge,
Recognition, Public Communication, Adjournment included -- while `chunks` only
records `agenda_item` for items that carry an attachment. Numbering chapters from
`chunks` therefore numbered about a fifth of them and looked like an oversight.
`fetch_agenda.py` pulls the real outline; this maps anchors onto it.

Where the two disagree, the published outline wins: on 2026-01-13 `chunks` calls
the purchase items 4.a/4.b/4.c and BoardDocs calls them 3.A/3.B/3.C.

Matching is order-aware. Anchors are chronological and an agenda is mostly worked
in order, so a title match that would go backwards is only taken when it is much
stronger than the alternatives -- boards do jump around (2026-01-13 took 3.C and
3.B before 3.A) but they rarely do it twice in a row.

  python3 number_anchors.py 2026-01-13            # preview
  python3 number_anchors.py --all --write         # rewrite authored/*.json
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
import os as _os
DATA = Path(_os.environ.get("ANCHORS_DATA") or (REPO / "scratch" / "anchors-rebuild"))
AUTH = HERE / "authored"


def _outlines():
    """Committed alongside the tools; the workdir copy wins if present."""
    w = DATA / "agenda_outlines.json"
    return w if w.exists() else HERE / "agenda_outlines.json"


STOP = set("""the a an and or of for to in on with at by from as is are be consideration
report resolution update presentation discussion review board education meeting troy
school district information item items guidelines approve action""".split())

# BoardDocs titles abbreviate what a chapter label spells out, so "THS Main & Aux
# Gym Remodel" and "Athens & Troy High gym renovations" shared exactly one word.
ALIAS = {"ths": "troy high", "ahs": "athens", "bpms": "boulan park",
         "remodel": "renovation", "renovations": "renovation", "reno": "renovation",
         "elem": "elementary", "aux": "auxiliary", "svcs": "services",
         "rfp": "", "consideration": "", "amendment": "budget amendment"}

def stem(w):
    """Crude but sufficient: "contracts"/"contract" and "extensions"/"extension"
    were the only thing keeping "Administrator contract extensions" from matching
    "Extension of Administrative Contracts"."""
    for suf in ("ations", "ation", "ives", "ive", "ing", "ies", "es", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w

def toks(s):
    out = set()
    for w in re.findall(r"[a-z0-9]{2,}", s.lower()):
        for part in ALIAS.get(w, w).split():
            if len(part) >= 3 and part not in STOP:
                out.add(stem(part))
    return out

def score(label, title):
    a, b = toks(label), toks(title)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b) ** 0.5      # favour overlap, forgive length

# structural chapters carry no distinctive words; match them by role instead
ROLE = [
    (re.compile(r"pledge|call to order", re.I),          re.compile(r"pledge|call to order", re.I)),
    (re.compile(r"^recognition|mission moment|student spotlight", re.I),
                                                          re.compile(r"recognition", re.I)),
    (re.compile(r"public comm.*agenda items|public comment on agenda", re.I),
                                                          re.compile(r"public communication \(agenda", re.I)),
    (re.compile(r"public comm.*non-agenda", re.I),        re.compile(r"non-?agenda", re.I)),
    (re.compile(r"^public communication$|^public comment$", re.I),
                                                          re.compile(r"public communication", re.I)),
    (re.compile(r"consent agenda", re.I),                 re.compile(r"consent agenda", re.I)),
    (re.compile(r"^personnel", re.I),                     re.compile(r"^personnel", re.I)),
    (re.compile(r"^curriculum", re.I),                    re.compile(r"^curriculum", re.I)),
    (re.compile(r"adjourn", re.I),                        re.compile(r"adjourn", re.I)),
    # anchored to the start: an unanchored "student rep" also matched
    # "Recognition - new student REPresentatives" and sent it to OTHER
    (re.compile(r"^student rep|^student reports|^board member comments"
                r"|^superintendent'?s report|^president'?s remarks|^board comments"
                r"|^other\b", re.I), re.compile(r"^other", re.I)),
]

BOOKEND = re.compile(r"call to order|pledge|adjourn|closing remarks|wrap-?up", re.I)


def assign(anchors, outline):
    """Globally best pairing, not sequential greedy.

    Sequential matching mis-assigned in both directions: it penalised 2026-01-13's
    3.B because the board took 3.C first (they really did jump), and it handed 2.B
    to the chapter before the one that actually matched it. Score every
    anchor x outline pair, then take them highest-first -- each anchor and each
    sub-item used once -- so a strong match cannot be stolen by a weaker earlier one.
    Categories (level 1) may be reused, since several chapters can sit under one.
    """
    pairs = []
    for ai, a in enumerate(anchors):
        for oi, o in enumerate(outline):
            s = score(a["label"], o["title"])
            for lp, op in ROLE:
                if lp.search(a["label"]) and op.search(o["title"]):
                    # a category is the fallback; a named sub-item is the real answer
                    s = max(s, 0.60 if o["level"] == 1 else 0.95)
                    break
            if s > 0:
                pairs.append((s, ai, oi))
    pairs.sort(reverse=True)

    taken_a, taken_o, best = set(), set(), {}
    for s, ai, oi in pairs:
        if s < 0.34 or ai in taken_a:
            continue
        o = outline[oi]
        if o["level"] == 2 and oi in taken_o:
            continue
        best[ai] = (o["item"], s)
        taken_a.add(ai)
        if o["level"] == 2:
            taken_o.add(oi)

    out = []
    for ai, a in enumerate(anchors):
        rec = {"t": a["t"]}
        if ai in best:
            rec["items"] = [best[ai][0]]
        # A previously hand-set number is deliberately NOT kept: those came from
        # `chunks`, whose scheme disagrees with the published outline (2026-01-13's
        # purchase items are 4.a/4.b/4.c there, 3.A/3.B/3.C on BoardDocs).
        rec["label"] = a["label"]
        rec["_score"] = round(best.get(ai, (None, 0.0))[1], 2)
        out.append(rec)

    # Sub-topics added to make long blocks navigable ("Illustrative Math review"
    # inside TEACHING & LEARNING) have no agenda entry of their own, but they do sit
    # inside a numbered category -- inherit it from the nearest numbered neighbour.
    cats = [(i, r["items"][0].split(".")[0]) for i, r in enumerate(out) if r.get("items")]
    for i, r in enumerate(out):
        if r.get("items"):
            continue
        # Bookends are not agenda items. A workshop outline has no Call to Order and
        # no Adjournment, so inheriting a neighbour's number would assert something
        # false -- leave those blank rather than label the close of a meeting "4".
        if BOOKEND.search(r["label"]):
            continue
        before = [c for j, c in cats if j < i]
        if before:
            r["items"], r["_inherited"] = [before[-1]], True
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("date", nargs="?")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    outlines = json.load(open(_outlines()))
    dates = sorted(outlines) if a.all else [a.date]
    unmatched = 0
    for d in dates:
        f = AUTH / f"anchors_{d}.json"
        if not f.exists():
            continue
        rows = assign(json.load(open(f)), outlines[d])
        miss = [r for r in rows if "items" not in r]
        unmatched += len(miss)
        if not a.all or miss:
            print(f"\n===== {d} =====")
            for r in rows:
                num = "/".join(r.get("items", [])) or "—"
                print(f"  {r['t']:>8}  {num:<7} [{r['_score']:.2f}] {r['label'][:60]}")
        if a.write:
            json.dump([{k: v for k, v in r.items() if k != "_score"} for r in rows],
                      open(f, "w"), indent=1)
    print(f"\nanchors with no agenda number: {unmatched}")

if __name__ == "__main__":
    sys.exit(main())
