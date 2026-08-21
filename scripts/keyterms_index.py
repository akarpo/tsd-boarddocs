#!/usr/bin/env python3
"""Grow the speech-to-text keyterm index from each meeting's own packet, with provenance.

Why this exists
---------------
`proper_nouns.py` rebuilds a keyterm list from the whole corpus and keeps the top
40 firms. That has two failure modes, and the 2026-08-18 meeting hit both.

1. **The cap is ours, not the API's.** AssemblyAI's `keyterms_prompt` takes 1,000
   phrases; we were sending 361. The 40-firm ceiling evicted five firms to admit
   five others on a routine refresh, so a name could be in the vocabulary one
   month and gone the next for no reason connected to whether anyone says it.
2. **Whole-corpus ranking buries the meeting you are about to transcribe.** The
   vocabulary that matters for one recording is the vocabulary in that meeting's
   packet, and a first-time vendor ranks last against fifteen years of history.

So this indexes *forward*: before a meeting is transcribed, read its packet, take
the proper nouns, and union them into a persistent index. Terms are never evicted
— an index that forgets is worse than useless for a recurring vendor — and each
carries when it arrived and what brought it in.

The index is deliberately seeded per meeting rather than bulk-loaded from the
corpus. Adding all 463 firms ever named would fit the API budget and would still
be wrong: most are one-off payees who will never be spoken aloud, and the point is
a vocabulary of terms that recur.

Usage
-----
    python3 scripts/keyterms_index.py --meeting 2026-08-18          # report
    python3 scripts/keyterms_index.py --meeting 2026-08-18 --add    # index them
    python3 scripts/keyterms_index.py --emit transcription/keyterms/TSD_keyterms_2025-2026.json
    python3 scripts/keyterms_index.py --history "L Mason Capitani"  # when/why a term is here
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.parse
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
INDEX = REPO / "transcription" / "keyterms" / "index.json"
DB = "tsd-boarddocs"

# Names worth teaching a recognizer: two to five capitalised words, allowing the
# punctuation real firm names carry. Deliberately NOT anchored on a corporate
# suffix -- that is what `proper_nouns.py`'s _ORG does, and it is why "L Mason
# Capitani" and "MI Works!" were invisible to it while every "... Inc." was found.
CANDIDATE = re.compile(r"\b((?:[A-Z][A-Za-z'&!-]*\.?\s+){1,4}[A-Z][A-Za-z'&!-]*)\b")
# A candidate must not span a sentence boundary. "…reviewed Asset Management. The
# board…" matches the shape perfectly and yields "Asset Management. The", which is
# not a name and teaches the recognizer nothing.
# A period ends a sentence only after a real word. "Mason L. Capitani" carries a
# middle initial, and rejecting it was how the firm that won the lease stayed out
# of the vocabulary while every other bidder got in.
SENTENCE_BLEED = re.compile(r"[A-Za-z]{2,}\.\s")

# Sentence-openers and boilerplate that match the shape but are not names.
STOP = {
    "the", "a", "an", "this", "that", "these", "those", "board", "district",
    "meeting", "regular", "special", "workshop", "resolution", "motion", "item",
    "agenda", "minutes", "report", "fund", "total", "school", "schools",
    "troy", "michigan", "president", "secretary", "treasurer", "trustee",
    "superintendent", "attachment", "exhibit", "page", "section", "public",
    "consent", "action", "information", "discussion", "approval", "recommend",
    "recommended", "administration", "office", "department", "purpose",
    "background", "summary", "january", "february", "march", "april", "may",
    "june", "july", "august", "september", "october", "november", "december",
    "monday", "tuesday", "wednesday", "thursday", "friday",
    "be", "it", "therefore", "resolved", "whereas", "now", "further", "hereby",
    "conclusion", "overview", "recommendation", "context", "listed", "because",
}

# Business English that matches the capitalised-phrase shape without naming
# anything: "Building Lease", "Asset Management", "Assistant Manager". A phrase
# made only of these is a category, not a term worth boosting. A phrase that
# pairs one of them with a real name ("Assistant Superintendent Dan Trudel") is
# kept, because the name is the part a recognizer gets wrong.
GENERIC = {
    "assistant", "manager", "management", "asset", "building", "lease", "services",
    "service", "business", "process", "handbook", "standard", "national", "american",
    "affirmative", "action", "employer", "tabulation", "bid", "proposal", "request",
    "director", "coordinator", "supervisor", "principal", "teacher", "staff",
    "committee", "county", "city", "state", "federal", "annual", "monthly",
    "financial", "budget", "revenue", "expenditure", "capital", "projects", "project",
    "general", "special", "education", "student", "students", "elementary",
    "secondary", "instruction", "instructional", "program", "programs", "plan",
    "policy", "procedure", "contract", "agreement", "amendment", "letter", "rec",
    "office", "space", "center", "centre", "north", "south", "east", "west",
    "new", "old", "first", "second", "third", "fourth", "year", "years", "term",
}


def d1(sql: str) -> list[dict]:
    r = subprocess.run(["npx", "wrangler", "d1", "execute", DB, "--remote", "--json",
                        "--command", sql], capture_output=True, text=True, cwd=REPO)
    try:
        return json.loads(r.stdout)[0]["results"]
    except Exception:
        print(r.stdout[-400:] or r.stderr[-400:], file=sys.stderr)
        raise SystemExit("D1 query failed")


def load_index() -> dict:
    return json.loads(INDEX.read_text(encoding="utf-8")) if INDEX.exists() else {}


def save_index(ix: dict) -> None:
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(json.dumps(ix, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")


def meeting_terms(meeting_date: str) -> dict[str, str]:
    """{term: source document title} for candidate proper nouns in one meeting's packet.

    Ledger documents are skipped: a check register is thousands of payee names,
    almost none of which anyone reads aloud, and letting them in is exactly the
    bloat this index is meant to avoid.
    """
    rows = d1("SELECT url, paragraph, page, verbose FROM summaries "
              f"WHERE url LIKE '%{meeting_date}%';")
    ledger = re.compile(r"check register|ach report|p.?card|wire transfer|financial", re.I)
    found: dict[str, str] = {}
    for r in rows:
        title = urllib.parse.unquote((r["url"] or "").split("/")[-1])
        if ledger.search(title):
            continue
        text = " ".join(r.get(k) or "" for k in ("paragraph", "page", "verbose"))
        for m in CANDIDATE.findall(text):
            if SENTENCE_BLEED.search(m):
                continue
            t = re.sub(r"\s+", " ", m).strip(" .,;:")
            words = t.split()
            if not (2 <= len(words) <= 5):
                continue
            if len(t) < 6:
                continue
            low = [w.lower().strip(".,'&!-") for w in words]
            if low[0] in STOP or low[-1] in STOP:
                continue
            # A phrase ending in a bare initial is a truncated name ("Mason L."),
            # which is worse than useless: it teaches half a name.
            if re.fullmatch(r"[A-Za-z]\.?", words[-1]):
                continue
            if all(w in STOP or w in GENERIC for w in low):
                continue
            # ALL-CAPS is ambiguous: "BE IT THEREFORE RESOLVED" is boilerplate and
            # "L. MASON CAPITANI" is a letterhead. Judge the words, not the case --
            # then store the title-cased form so the two spellings collapse to one
            # term instead of two.
            if t.isupper():
                if all(w in STOP or w in GENERIC for w in low):
                    continue
                t = t.title()
                words = t.split()
            if t.lower() not in {k.lower() for k in found}:
                found[t] = title
            # Greedy matching swallows a name into whatever follows it:
            # "MI Works Professional Office Space" instead of "MI Works",
            # "L Mason Capitani Bid Submittal" instead of the firm. The short
            # form is the reusable one -- it recurs across meetings while the
            # long phrase is specific to this packet -- so emit the leading
            # two- and three-word prefixes as well when they stand on their own.
            for n in (2, 3):
                if len(words) > n:
                    pre = " ".join(words[:n])
                    pl = [w.lower().strip(".,'&!-") for w in words[:n]]
                    if (len(pre) >= 6 and pl[0] not in STOP and pl[-1] not in STOP
                            and not re.fullmatch(r"[A-Za-z]\.?", words[n - 1])
                            and not all(w in STOP or w in GENERIC for w in pl)):
                        found.setdefault(pre, title)
    return found


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--meeting", help="YYYY-MM-DD — scan this meeting's packet")
    ap.add_argument("--add", action="store_true", help="write new terms into the index")
    ap.add_argument("--emit", help="write the flat keyterms JSON the transcriber reads")
    ap.add_argument("--history", help="show provenance for one term")
    ap.add_argument("--limit", type=int, default=1000, help="AssemblyAI phrase cap")
    a = ap.parse_args()
    ix = load_index()

    if a.history:
        e = ix.get(a.history)
        print(json.dumps({a.history: e}, indent=1) if e else f"{a.history!r} is not in the index")
        return 0

    if a.emit:
        terms = sorted(ix)
        if len(terms) > a.limit:
            # Never silently truncate: say what was dropped and on what rule.
            terms.sort(key=lambda t: (-ix[t].get("seen", 1), t))
            print(f"NOTE: {len(ix)} terms exceeds the {a.limit} cap — "
                  f"emitting the {a.limit} most-seen, dropping {len(ix)-a.limit}", file=sys.stderr)
            terms = sorted(terms[:a.limit])
        Path(a.emit).write_text(json.dumps(terms, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"emitted {len(terms)} keyterms -> {a.emit}")
        return 0

    if not a.meeting:
        print(f"index holds {len(ix)} terms")
        return 0

    found = meeting_terms(a.meeting)
    new = {t: s for t, s in found.items() if t not in ix}
    seen_again = [t for t in found if t in ix]
    print(f"{a.meeting}: {len(found)} candidate terms · {len(new)} new · {len(seen_again)} already indexed")
    for t, s in sorted(new.items())[:40]:
        print(f"   + {t}   ({s[:46]})")
    if len(new) > 40:
        print(f"   … and {len(new)-40} more")
    if not a.add:
        print("\nre-run with --add to index them")
        return 0

    today = date.today().isoformat()
    for t, s in new.items():
        ix[t] = {"first_added": today, "first_meeting": a.meeting, "source": s, "seen": 1}
    for t in seen_again:
        ix[t]["seen"] = ix[t].get("seen", 1) + 1
        ix[t]["last_meeting"] = a.meeting
    save_index(ix)
    print(f"\nindex {len(ix)-len(new)} -> {len(ix)} terms  ({INDEX.relative_to(REPO)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
