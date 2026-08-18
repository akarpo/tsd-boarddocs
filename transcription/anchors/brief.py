#!/usr/bin/env python3
"""Everything needed to author one meeting's anchors, in one output.

  python3 brief.py 2026-06-16 [--full]

Prints the authoritative agenda, the anchors currently in D1, and a digest of the
transcript reduced to the utterances that actually decide attribution -- motions,
votes, transitions, item references, and mentions of each agenda item's own
distinctive words.
"""
import json, re, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
# Transcript exports, agenda keyword sets and the anchor cache are bulk data
# regenerable from D1, so they are NOT committed -- they live in a workdir.
# Override with ANCHORS_DATA if you keep them elsewhere.
import os as _os
DATA = Path(_os.environ.get("ANCHORS_DATA")
            or (Path(__file__).resolve().parent.parent.parent / "scratch" / "anchors-rebuild"))
sys.path.insert(0, str(HERE))
from digest import digest            # noqa: E402

STOP = set("""the a an and or of for to in on with at by from as is are be recommendation
approve approval award bid tab rec board education meeting regular workshop school district
troy michigan agenda item memo letter update summary final draft copy presentation overview
fund funds public schools resolution consideration purchase report""".split())

def hms(ms):
    s = ms // 1000
    return f"{s//3600}:{s%3600//60:02d}:{s%60:02d}"

def main():
    date = sys.argv[1]
    full = "--full" in sys.argv
    ag = json.load(open(DATA/"agendas.json")).get(date, {})
    print(f"===== {date}  {ag.get('name','?')} =====\n")
    print("--- authoritative agenda ---")
    seen = set()
    for d in ag.get("agenda", []):
        k = (d["item"], d["title"][:40])
        if k in seen: continue
        seen.add(k)
        print(f"  {d['item']:<7} {d['title'][:78]}")
    print("\n--- anchors currently in D1 ---")
    for a in json.load(open(DATA/f"cur_{date}.json")):
        print(f"  {hms(a['start_ms']):>8}  {a['label']}")
    utts = json.load(open(DATA/f"utts_{date}.json"))
    # keywords: each agenda item's distinctive words
    kw = {}
    for d in ag.get("agenda", []):
        t = re.sub(r"^\d+\.[a-z]?\.?\s*", "", d["title"], flags=re.I)
        toks = [w for w in re.findall(r"[A-Za-z]{4,}", t.lower()) if w not in STOP][:3]
        if toks:
            kw.setdefault(f"{d['item']}", [])
            for tk in toks:
                if tk not in kw[f"{d['item']}"]:
                    kw[f"{d['item']}"].append(re.escape(tk))
    rows = digest(utts, kw)
    print(f"\n--- digest: {len(rows)} of {len(utts)} utterances carry a signal ---")
    for x in rows:
        print(f"{hms(x['ms'])} [{x['spk']}] {','.join(x['tags'])}\n    {x['text'][:170]}")

if __name__ == "__main__":
    main()
