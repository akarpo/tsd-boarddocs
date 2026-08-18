#!/usr/bin/env python3
"""For each agenda item, did the board actually discuss it -- and if not, why not?

Omitting an item from the chapter list is only correct if the item genuinely was
not discussed. This checks that claim against the transcript instead of assuming
it: every agenda item is searched for by its own distinctive words (RFP numbers,
proper nouns, content words), and the verdict says whether it was DISCUSSED (a
cluster of mentions), MENTIONED (in passing -- typically swept through the consent
agenda), or ABSENT (no trace at all, i.e. tabled or pulled).

  python3 coverage.py 2026-02-03
  python3 coverage.py --all
"""
import json, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STOP = set("""the a an and or of for to in on with at by from as is are be recommendation
approve approval award bid tab rec board education meeting regular workshop school district
troy michigan agenda item memo letter update summary final draft copy presentation overview
fund funds public schools resolution consideration purchase report full new proposed""".split())

def hms(ms):
    s = ms // 1000
    return f"{s//3600}:{s%3600//60:02d}:{s%60:02d}"

def tokens(title):
    t = re.sub(r"^\d+\.[a-z]?\.?\s*", "", title, flags=re.I)
    out = []
    for m in re.findall(r"\d{4}-\d{2}", t):                 # RFP numbers are the strongest signal
        out.append((re.escape(m).replace(r"\-", "[-\\s]?"), 3))
    for w in re.findall(r"[A-Za-z]{4,}", t):
        lw = w.lower()
        if lw in STOP: continue
        weight = 2 if w[0].isupper() else 1                 # proper nouns beat generic words
        out.append((re.escape(lw), weight))
    return out[:6]

def consent_block(utts):
    """The window where the chair reads the consent agenda list."""
    for u in utts:
        t = (u.get("text") or "").lower()
        if "consent agenda" in t and re.search(r"\bitems?\s+[a-z]\b|minutes of", t):
            return u["start_ms"], u["start_ms"] + 240000
    return None, None

def check(date):
    ag = json.load(open(HERE/"agendas.json")).get(date, {})
    utts = json.load(open(HERE/f"utts_{date}.json"))
    anchors = json.load(open(HERE/f"cur_{date}.json"))
    c0, c1 = consent_block(utts)
    items = {}
    for d in ag.get("agenda", []):
        items.setdefault(d["item"], []).append(d["title"])
    rows = []
    for item, titles in sorted(items.items()):
        best = []
        for title in titles:
            toks = tokens(title)
            if not toks: continue
            hits = []
            for u in utts:
                low = (u.get("text") or "").lower()
                score = sum(w for pat, w in toks if re.search(pat, low))
                if score >= 3:
                    hits.append((u["start_ms"], score))
            if len(hits) > len(best):
                best = hits
        if not best:
            # ABSENT is only meaningful when the title HAD searchable words. Some
            # titles are pure filenames ("24680 Troy School District-0625-AUD-Final")
            # and cannot be located no matter how thoroughly the board discussed them.
            searchable = any(tokens(t) for t in titles)
            verdict, where = ("ABSENT" if searchable else "UNSEARCHABLE"), "-"
        else:
            # densest 10-minute window says where it was actually taken up
            top_at, top_n = best[0][0], 0
            for ms, _ in best:
                n = sum(1 for m2, _ in best if ms <= m2 < ms + 600000)
                if n > top_n: top_at, top_n = ms, n
            if top_n >= 3:
                verdict, where = "DISCUSSED", hms(top_at)
            elif c0 is not None and any(c0 <= ms <= c1 for ms, _ in best):
                verdict, where = "IN CONSENT", hms(best[0][0])
            else:
                verdict, where = "MENTIONED", hms(best[0][0])
        # match the item anywhere in a label: a single anchor legitimately covers
        # several items ("8.A/8.B Countywide enhancement millage resolution")
        covered = any(re.search(rf"(?<![\d.]){re.escape(item)}(?![\d])", a["label"], re.I)
                      for a in anchors)
        rows.append((item, verdict, where, top_n if best else 0, covered, titles[0][:52]))
    return rows

def main():
    if "--all" in sys.argv:
        dates = [l.split("\t")[0] for l in open(HERE/"meetings.tsv")]
    else:
        dates = [sys.argv[1]]
    gaps = 0
    for date in dates:
        rows = check(date)
        miss = [r for r in rows if r[1] == "DISCUSSED" and not r[4]]
        if len(dates) > 1 and not miss:
            continue
        print(f"\n===== {date} =====")
        print(f"{'item':<7}{'verdict':<12}{'at':>9}{'hits':>5}  anchored  title")
        for item, verdict, where, n, covered, title in rows:
            flag = "" if covered or verdict != "DISCUSSED" else "   <<< DISCUSSED BUT NOT ANCHORED"
            print(f"{item:<7}{verdict:<12}{where:>9}{n:>5}  {'yes' if covered else 'no ':<8}  {title}{flag}")
        gaps += len(miss)
    if len(dates) > 1:
        print(f"\nmeetings with a discussed-but-unanchored item: {gaps}")

if __name__ == "__main__":
    main()
