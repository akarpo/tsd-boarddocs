#!/usr/bin/env python3
"""Auto-generate agenda chapter anchors from a meeting transcript.

Two signal sources, merged:
  1. Structural cues — call to order, consent agenda, public communication,
     item numbers ("8.A"), transition phrases ("that brings us to…"), adjournment.
  2. Agenda-title matching (with --agenda, the /api/meeting JSON): each agenda
     document's distinctive title words are located in the transcript, so a
     workshop presentation gets a chapter even when nobody says "item 6.B".

Good chapters, not hand-tuned ones — edit the JSON afterwards when a meeting
deserves it (see examples/2026-07-22/anchors.json for the hand-tuned standard).

Usage:
  python3 make_anchors.py TRANSCRIPT.json -o anchors.json \
      [--agenda agenda.json] [--max 16] [--gap 75]
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
ITEM = re.compile(r"\b(?:item\s+)?(\d{1,2})\s?[.·]\s?([A-F])\b", re.I)
BRIDGE = re.compile(r"(brings us to|next (?:item|on (?:our|the) agenda)|moving on to|first being|"
                    r"final item(?: in our \w+ agenda)?|turn (?:it|now) over to)", re.I)
SKIP_DOC = re.compile(r"check register|ach report|p ?card|wire transfer|financial statement|"
                      r"treasurers? letter|^m\d{6}|minutes", re.I)
STOP = set("""board education troy school district meeting meetings minutes report resolution
resolutions recommendation consideration agenda memo letter update item summary final signed
draft copy full suggested presentation overview 2024 2025 2026 fund funds regular workshop
special session public schools michigan""".split())


FILLER = re.compile(r"\b(i|we|you|they|he|she|my|our|your|kind of|sort of|you know|"
                    r"i think|i mean|gonna|wanna|okay|yeah|thank you|please|let'?s|"
                    r"if you could|maybe|really|just)\b", re.I)


def looks_like_item(frag):
    """Is this fragment an agenda item, or is it just the next thing someone said?

    BRIDGE matches a transition phrase and takes the words after it, which is only
    a label when the speaker actually names the item. When they carry on talking it
    produced things like "The classics, if you could think about it, the great…" --
    54 such labels across the corpus. Demand something title-shaped instead:
    conversational, first-person or filler-laden text is prose, not an agenda item.
    """
    if not frag or len(frag.split()) < 3:
        return False
    if FILLER.search(frag):
        return False
    if frag.rstrip("…").rstrip().endswith((",", "and", "the", "a", "to", "of", "that")):
        return False
    words = frag.split()
    capitals = sum(1 for w in words[1:] if w[:1].isupper())
    return bool(ITEM.search(frag)) or capitals >= 1 or len(words) <= 8


def tidy(s, n=90):
    """Normalise a label. n=90 because 58 cut real agenda titles mid-phrase --
    "RFP 2526-12 - BOND - Phase 1 Elementary Toilet Room…" told a viewer nothing
    the untruncated title would not have. Cut on a separator when possible so the
    label still ends on a complete thought, and only ellipsise a genuine trim."""
    s = re.sub(r"\s+", " ", s).strip(" ,.;:-—–")
    if len(s) > n:
        head = s[:n]
        cut = max(head.rfind(" - "), head.rfind(" — "), head.rfind(": "))
        s = (head[:cut] if cut > n // 2 else head.rsplit(" ", 1)[0]).rstrip(" ,.;:-—–") + "…"
    return s[:1].upper() + s[1:] if s else s


def dedupe_prefix(item, title):
    """"4.c" + "C. RFP 2526-12 …" must not render as "4.c C. RFP 2526-12 …"."""
    if item:
        letter = item.rsplit(".", 1)[-1].strip().lower()
        title = re.sub(rf"^{re.escape(letter)}[.)]\s+", "", title, flags=re.I)
    return title


def title_tokens(title):
    words = re.findall(r"[A-Za-z]{4,}", title.lower())
    return [w for w in words if w not in STOP]


def agenda_candidates(agenda_path, utts):
    """Locate each distinctive agenda-doc title in the transcript."""
    docs = (json.load(open(agenda_path)) or {}).get("docs") or []
    out, used_items = [], set()
    for d in docs:
        title = d.get("title") or ""
        if SKIP_DOC.search(title):
            continue
        item = (d.get("agenda_item") or "").strip()
        if item and item in used_items:            # one anchor per agenda item
            continue
        toks = title_tokens(title)[:6]
        if len(toks) < 2:
            continue
        # Anchor on the DENSEST cluster of mentions, not the first one. A single
        # sentence often name-checks several upcoming items ("the toilet
        # renovations… and then the gyms"), and first-match put every one of them
        # on that same second, in the wrong order.
        marks = [u["start"] for u in utts if u["start"] >= 60000
                 and sum(1 for t in toks if t in u["text"].lower()) >= 2]
        best_at, best_n = None, 0
        for m in marks:
            n_in = sum(1 for x in marks if m <= x < m + 600000)
            if n_in > best_n:
                best_at, best_n = m, n_in
        for u in utts:
            if best_at is None or u["start"] < best_at:
                continue
            low = u["text"].lower()
            hits = sum(1 for t in toks if t in low)
            if hits >= 2:
                # Strip an agenda-item prefix ("4.E. Establish Fund Depositories"), but only
                # a complete one: the marker has to end in a dot before the whitespace.
                # A looser class ate the title's own first letter whenever it fell in A-F —
                # "4.E. Establish" became "Stablish", "5.F Food Service" became "Ood Service" —
                # and a bare ^\d would swallow the year off "2024 Proposed Bylaws".
                stripped = re.sub(r"^\d{1,2}(?:\.[A-Za-z0-9]{1,3})*\.\s+", "", title)
                label = (f"{item} " if item else "") + tidy(dedupe_prefix(item, stripped))
                out.append((u["start"], label.strip(), 1))
                if item:
                    used_items.add(item)
                break
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("transcript")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--agenda", help="/api/meeting JSON for this meeting (adds title-match anchors)")
    ap.add_argument("--max", type=int, default=16)
    ap.add_argument("--gap", type=int, default=75, help="min seconds between anchors")
    a = ap.parse_args()

    utts = json.load(open(a.transcript)).get("utterances") or []
    cands = []                                   # (start_ms, label, priority: lower wins)
    seen_labels = set()
    for u in utts:
        text = u["text"]
        for rx, label in CUES:
            if rx.search(text) and label not in seen_labels:
                if u["start"] < 90000 and "order" not in label.lower():
                    continue                     # agenda read-through at the top of the meeting
                seen_labels.add(label)
                cands.append((u["start"], label, 0))
                break
        else:
            m = ITEM.search(text)
            if m and len(text) < 400:
                frag = tidy(text[m.end():], 44)
                if len(frag) >= 6:
                    cands.append((u["start"], f"{m.group(1)}.{m.group(2).upper()} {frag}", 2))
                continue
            m = BRIDGE.search(text)
            if m:
                frag = tidy(text[m.end():])
                # A bridge phrase marks a transition reliably; the words after it are
                # only a *label* when the speaker names the item. Otherwise drop it and
                # let the agenda titles carry the meeting.
                if any(len(w) >= 5 for w in frag.split()) and looks_like_item(frag):
                    cands.append((u["start"], frag, 3))

    if a.agenda:
        cands += agenda_candidates(a.agenda, utts)

    cands.sort(key=lambda c: (c[0], c[2]))
    anchors, last = [{"start_ms": 0, "label": "Call to order"}], 0
    for start, label, _pri in cands:
        if start - last < a.gap * 1000:
            continue
        anchors.append({"start_ms": start, "label": label})
        last = start
        if len(anchors) >= a.max:
            break
    if len(anchors) > 1 and "order" in anchors[1]["label"].lower():
        anchors.pop(0)                            # a real call-to-order cue replaced the synthetic one

    json.dump(anchors, open(a.out, "w"), indent=1, ensure_ascii=False)
    print(f"{len(anchors)} anchors -> {a.out}")
    for an in anchors:
        s = an["start_ms"] // 1000
        print(f"  {s//60:3d}:{s%60:02d}  {an['label']}")


if __name__ == "__main__":
    main()
