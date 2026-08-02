#!/usr/bin/env python3
"""Auto-generate agenda chapter anchors from a meeting transcript.

Heuristic v1: scan utterances for agenda-transition cues (call to order, consent
agenda, item numbers like "8.A", "brings us to…", public communication,
adjournment…), label each hit from the cue class or the sentence fragment after
it, de-duplicate, enforce a minimum gap, cap the count. Good chapters, not
hand-tuned ones — edit the JSON afterwards if a meeting deserves it (see
examples/2026-07-22/anchors.json for the hand-tuned standard).

Usage: python3 make_anchors.py TRANSCRIPT.json -o anchors.json [--max 16] [--gap 75]
"""
from __future__ import annotations
import argparse, json, re

CUES = [
    (re.compile(r"pledge of allegiance|call(ed)? (the |this )?(meeting|workshop) to order", re.I),
     "Call to order · Pledge of Allegiance"),
    (re.compile(r"consent agenda", re.I), "Consent agenda"),
    (re.compile(r"\brecogni(tion|ze|zing)", re.I), "Recognitions"),
    (re.compile(r"student (spotlight|representative)", re.I), "Student reports"),
    (re.compile(r"public (communication|comment)", re.I), "Public communication"),
    (re.compile(r"treasurer'?s report", re.I), "Treasurer's report"),
    (re.compile(r"superintendent'?s (report|update)", re.I), "Superintendent's report"),
    (re.compile(r"board (member )?comments", re.I), "Board comments"),
    (re.compile(r"closed session", re.I), "Closed session"),
    (re.compile(r"\badjourn", re.I), "Adjournment"),
]
ITEM = re.compile(r"\b(?:item\s+)?(\d{1,2})\s?[.·]\s?([A-F])\b|\bitem\s+(number\s+)?(\d{1,2})\b", re.I)
BRIDGE = re.compile(r"(brings us to|next (?:item|on (?:our|the) agenda)|moving on to|first being|"
                    r"final item|next up,?|turn (?:it|now) over to)", re.I)


def tidy(s, n=58):
    s = re.sub(r"\s+", " ", s).strip(" ,.;:-—–")
    if len(s) > n:
        s = s[:n].rsplit(" ", 1)[0] + "…"
    return s[:1].upper() + s[1:] if s else s


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("transcript")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--max", type=int, default=16)
    ap.add_argument("--gap", type=int, default=75, help="min seconds between anchors")
    a = ap.parse_args()

    utts = json.load(open(a.transcript)).get("utterances") or []
    cands = []                                   # (start_ms, label, priority)
    seen_labels = set()
    for u in utts:
        text = u["text"]
        for rx, label in CUES:
            if rx.search(text) and label not in seen_labels:
                seen_labels.add(label)
                cands.append((u["start"], label, 0))
                break
        else:
            m = BRIDGE.search(text)
            if m:
                frag = tidy(text[m.end():])
                if len(frag) >= 8:
                    cands.append((u["start"], frag, 1))
                continue
            m = ITEM.search(text)
            if m and len(text) < 400:
                item = f"{m.group(1)}.{m.group(2).upper()}" if m.group(2) else (m.group(4) or "")
                frag = tidy(text[m.end():], 44)
                if item and len(frag) >= 6:
                    cands.append((u["start"], f"{item} {frag}", 2))

    cands.sort(key=lambda c: (c[0], c[2]))
    anchors, last = [], -10 ** 9
    for start, label, _pri in cands:
        if start - last < a.gap * 1000:
            continue
        anchors.append({"start_ms": start, "label": label})
        last = start
        if len(anchors) >= a.max:
            break
    if not anchors or anchors[0]["start_ms"] > 120000:
        anchors.insert(0, {"start_ms": 0, "label": "Call to order"})

    json.dump(anchors, open(a.out, "w"), indent=1, ensure_ascii=False)
    print(f"{len(anchors)} anchors -> {a.out}")
    for an in anchors:
        s = an["start_ms"] // 1000
        print(f"  {s//60:3d}:{s%60:02d}  {an['label']}")


if __name__ == "__main__":
    main()
