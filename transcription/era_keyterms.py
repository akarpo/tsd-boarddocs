#!/usr/bin/env python3
"""Build a keyterms vocabulary for one era of the archive.

The committed vocabulary is built from 2025 onward, which is the wrong list for a
2019 meeting: the people who actually speak are missing, and — worse — the names
that *are* in the list pull the transcriber toward them. Two of the first ten 2024
meetings produced a wrong-but-plausible name that way: a student introducing
himself on camera came out as `Ryan Zawislak`, and a commenter as `Brian
Zawislak`, Zawislak being a district surname sitting in the 2025-26 list.

So each era gets its own list, harvested from the board minutes of that era —
attendance roll calls, movers and supporters, presenters with titles, student
representatives, and the people the minutes name at the podium — merged with the
base vocabulary of schools, programs, unions and acronyms that does not change.

    python3 transcription/era_keyterms.py --start 2024-01-01 --end 2024-06-30 --label 2024H1

Writes transcription/keyterms/TSD_keyterms_<label>.txt and its .json twin, which
`transcribe_meeting.py --keyterms` takes directly. AssemblyAI caps the prompt at
1,000 phrases of ≤6 words each; both limits are enforced here.
"""
from __future__ import annotations
import argparse, json, re, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE / "keyterms" / "TSD_keyterms_2025-2026.json"
DB = "tsd-boarddocs"
MAX_TERMS, MAX_WORDS = 1000, 6

HON = r"(?:Mr|Mrs|Ms|Dr|Miss)\.?"
NAME = r"[A-Z][a-zA-Z'’\-]+"

PATTERNS = [
    # "Mr. Jason Cichowicz, President of the Troy Education Association"
    rf"{HON}\s+({NAME}\s+{NAME})\b",
    # "Diana D'Aloisio, student representative for Athens High School"
    rf"\b({NAME}\s+{NAME}),\s+student representative",
    # "Ms. Karen Hunt, TSD parent" / "Heather Kelly, TSD teacher"
    rf"\b({NAME}\s+{NAME}),\s+(?:TSD|Troy)\b",
    # "Natalie Haezebrouck, Director of Teaching and Learning"
    rf"\b({NAME}\s+{NAME}),\s+(?:Assistant |Deputy )?(?:Superintendent|Director|Principal|Supervisor|Coordinator)",
    # "Mr. David Recker, who will begin his duties as Principal"
    rf"\b({NAME}\s+{NAME})\s+(?:was|will|has)\s+(?:been\s+)?(?:appointed|selected|named|begin)",
]
# Attendance roll calls give surnames only — still worth boosting, and the
# board's own minutes are the authority on spelling.
ROLLCALL = [
    r"present were Board members ([^.]{5,200})\.",
    r"administrators ([^.]{5,260})\.",
    r"[Ii]n addition to (?:Mr|Mrs|Ms|Dr)\.?\s+(\w+)",
    r"moved by {H}\s+(\w+)".replace("{H}", HON),
    r"supported by {H}\s+(\w+)".replace("{H}", HON),
]
FIRM = re.compile(r"\b((?:[A-Z][\w&'’.\-]*\s+){0,3}[A-Z][\w&'’.\-]*\s+"
                  r"(?:Inc|LLC|L\.L\.C|Corp|Company|Associates|Group|Partners|Consulting|"
                  r"Construction|Contracting|Architects|Engineering|Solutions)\b\.?)")
# Words that show up capitalised mid-sentence and are not people.
STOP = {"Board", "Education", "Troy", "School", "District", "Meeting", "Minutes", "President",
        "Vice", "Secretary", "Treasurer", "Superintendent", "Trustee", "Yes", "No", "Absent",
        "Public", "Communication", "Consent", "Agenda", "Business", "Services", "Regular",
        "Workshop", "Special", "Organizational", "High", "Middle", "Elementary", "Michigan",
        "January", "February", "March", "April", "May", "June", "July", "August", "September",
        "October", "November", "December", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
        "Resolution", "Recommendation", "Whereas", "Therefore", "Resolved", "Moved", "Supported",
        "Student", "Spotlight", "Recognition", "Personnel", "Curriculum", "Fund", "General"}


def d1(sql: str) -> list[dict]:
    r = subprocess.run(["npx", "wrangler", "d1", "execute", DB, "--remote", "--json", "--command", sql],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"wrangler failed:\n{r.stderr[-800:]}")
    return json.loads(r.stdout)[0]["results"]


def clean(term: str) -> str | None:
    t = re.sub(r"\s+", " ", term).strip(" .,;:'\"")
    if not t or len(t) < 3 or len(t.split()) > MAX_WORDS:
        return None
    if any(w in STOP for w in t.split()):
        return None
    if not re.match(r"^[A-Z]", t):
        return None
    return t


def harvest(texts: list[str]) -> tuple[set, set]:
    people, firms = set(), set()
    for t in texts:
        for pat in PATTERNS:
            for m in re.finditer(pat, t):
                c = clean(m.group(1))
                if c and len(c.split()) == 2:
                    people.add(c)
        for pat in ROLLCALL:
            for m in re.finditer(pat, t):
                for part in re.split(r",| and ", m.group(1)):
                    c = clean(part)
                    if c and len(c.split()) == 1:
                        people.add(c)
        for m in FIRM.finditer(t):
            c = clean(m.group(1))
            if c:
                firms.add(c)
    return people, firms


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", required=True, help="era start, YYYY-MM-DD (inclusive)")
    ap.add_argument("--end", required=True, help="era end, YYYY-MM-DD (inclusive)")
    ap.add_argument("--label", required=True, help="era label used in the filename, e.g. 2024H1")
    ap.add_argument("--no-base", action="store_true",
                    help="omit the shared base vocabulary (schools, programs, unions, acronyms)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    # Minutes are the densest, best-spelled source of names in the corpus: every
    # meeting's minutes name who attended, who moved what, and who came to the podium.
    rows = d1("SELECT title, text FROM chunks WHERE meeting_date BETWEEN '%s' AND '%s' "
              "AND (title LIKE 'M0%%' OR title LIKE 'M1%%' OR lower(title) LIKE '%%minutes%%')"
              % (a.start, a.end))
    if not rows:
        raise SystemExit(f"no minutes documents found between {a.start} and {a.end}")
    people, firms = harvest([r["text"] for r in rows])
    print(f"{len(rows)} minutes chunks · {len(people)} people · {len(firms)} firms")

    terms = sorted(people | firms)
    if not a.no_base:
        base = json.loads(BASE.read_text(encoding="utf-8"))
        # Era terms first: if the 1,000-phrase cap bites, the era keeps its own names.
        seen, merged = set(), []
        for t in terms + base:
            k = t.lower()
            if k not in seen:
                seen.add(k)
                merged.append(t)
        terms = merged
    if len(terms) > MAX_TERMS:
        print(f"capping {len(terms)} -> {MAX_TERMS} terms")
        terms = terms[:MAX_TERMS]

    out = HERE / "keyterms" / f"TSD_keyterms_{a.label}.txt"
    print(f"{len(terms)} terms -> {out}")
    print("  era sample:", ", ".join(sorted(people)[:12]))
    if a.dry_run:
        return
    out.write_text("\n".join(terms) + "\n", encoding="utf-8")
    out.with_suffix(".json").write_text(json.dumps(terms, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
