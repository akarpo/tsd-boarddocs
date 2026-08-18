"""Condense a meeting transcript to the lines that decide agenda attribution."""
import json, re, sys

MOTION = re.compile(r"\b(motion to|move to (approve|adopt|accept)|i'?ll move|second(ed)?\b|"
                    r"all (those )?in favor|roll call|ayes? have it|motion (carries|passes)|"
                    r"opposed|abstain)", re.I)
TRANS  = re.compile(r"\b(next (item|on the agenda|up)|brings us to|moving on|move on to|turn(ing)? (it |now )?over|"
                    r"item (number )?\d|agenda item|first item|final item|last item|"
                    r"call(ing)? (the|this) (meeting|workshop) to order|pledge of allegiance|"
                    r"public (comment|communication)|adjourn|closed session|recess|"
                    r"recogni(tion|ze)|superintendent'?s report|treasurer'?s report|consent agenda)", re.I)
ITEMREF = re.compile(r"\b\d{1,2}\s?[.\-]\s?[a-fA-F]\b|\bRFP\s*\d{2}-?\d{2}-?\d{1,2}\b", re.I)

def digest(utts, keywords):
    out = []
    for u in utts:
        t = (u.get("text") or "").strip()
        if not t:
            continue
        tags = []
        if MOTION.search(t):  tags.append("MOTION")
        if TRANS.search(t):   tags.append("TRANS")
        if ITEMREF.search(t): tags.append("ITEMREF")
        for lab, pats in keywords.items():
            if sum(1 for p in pats if re.search(p, t, re.I)) >= 1:
                tags.append(f"KW:{lab}")
        if tags:
            out.append({"ms": u["start_ms"], "spk": (u.get("speaker") or "?")[:22],
                        "tags": sorted(set(tags)), "text": re.sub(r"\s+", " ", t)[:190]})
    return out

if __name__ == "__main__":
    utts = json.load(open(sys.argv[1]))
    kw = json.load(open(sys.argv[2])) if len(sys.argv) > 2 else {}
    d = digest(utts, kw)
    def hms(ms):
        s = ms // 1000
        return f"{s//3600}:{s%3600//60:02d}:{s%60:02d}"
    print(f"# {len(d)} of {len(utts)} utterances carry a signal\n")
    for x in d:
        print(f"{hms(x['ms'])} [{x['spk']}] {','.join(x['tags'])}\n    {x['text']}")
