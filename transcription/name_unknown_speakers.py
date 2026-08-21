#!/usr/bin/env python3
"""Name the speakers AssemblyAI left as letters, using the chair's own introduction.

The speaker-identification pass takes a roster of up to 10 names and maps them to
diarization clusters. It also picks up people who are *not* on the roster when the
audio names them — Walter Cook was identified for 2026-08-18 without ever being in
speakers_2026.json, because the chair said "Mr. Walter Cook" immediately before he
spoke. But it is not reliable about it: the chair said "Mr. Beau Taylor first" in
the same meeting, one sentence earlier, and that cluster came back as "Speaker E".

Public comment is where this bites. Commenters are never on the roster (their names
are announced at the meeting, not published with the agenda) and the roster is
already at the API's 10-name cap, so there is no slot to pre-assign. What there IS,
every time, is the chair reading the name off the sign-in sheet.

So: for each unattributed cluster, look at the transcript shortly before each of
its turns and pull an introduced name. Report only — relabeling a transcript is
not something to do on a regex's say-so.

    python3 transcription/name_unknown_speakers.py <transcript.json>
    python3 transcription/name_unknown_speakers.py --d1 2026-08-18
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# "Mr. Beau Taylor first", "Ms. Jane Doe", "Dr. Richard Machesky" — a courtesy
# title is what makes this specific enough to trust. A bare capitalised pair
# matches half the sentences in a board meeting.
INTRO = re.compile(r"\b(?:Mr|Mrs|Ms|Dr|Miss)\.?\s+([A-Z][a-z'-]+(?:\s+[A-Z][a-z'-]+){1,2})\b")
UNKNOWN = re.compile(r"^(?:Speaker\s+)?([A-Z])$")

# How far back to look. The chair's introduction and the commenter's first word are
# adjacent turns in practice; a wider window starts catching the previous agenda item.
LOOKBACK_MS = 90_000


def from_d1(date: str) -> list[dict]:
    for _ in range(3):
        r = subprocess.run(["npx", "wrangler", "d1", "execute", "tsd-boarddocs", "--remote",
                            "--json", "--command",
                            "SELECT start_ms, speaker, text FROM transcript_utts "
                            f"WHERE meeting_date='{date}' ORDER BY start_ms;"],
                           capture_output=True, text=True, cwd=REPO)
        try:
            return json.loads(r.stdout)[0]["results"]
        except Exception:
            continue
    raise SystemExit("D1 query failed")


def from_file(p: Path) -> list[dict]:
    d = json.loads(p.read_text())
    utts = d.get("utterances") or d.get("utts") or []
    return [{"start_ms": u.get("start", u.get("start_ms", 0)),
             "speaker": u.get("speaker", ""), "text": u.get("text", "")} for u in utts]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("transcript", nargs="?", help="path to <base>.transcript.json")
    ap.add_argument("--d1", metavar="YYYY-MM-DD", help="read the meeting from D1 instead")
    a = ap.parse_args()
    if not a.transcript and not a.d1:
        ap.error("give a transcript path or --d1 DATE")
    utts = from_d1(a.d1) if a.d1 else from_file(Path(a.transcript))
    if not utts:
        print("no utterances found")
        return 1

    unknown: dict[str, list[int]] = {}
    for i, u in enumerate(utts):
        sp = str(u.get("speaker") or "")
        if UNKNOWN.match(sp) or sp.startswith("Speaker "):
            unknown.setdefault(sp, []).append(i)

    if not unknown:
        print(f"{len(utts)} utterances · every speaker is named")
        return 0

    print(f"{len(utts)} utterances · {len(unknown)} unattributed cluster(s)\n")
    for sp, idxs in sorted(unknown.items(), key=lambda kv: kv[1][0]):
        # Check before EVERY turn, not just the first. A cluster's first
        # appearance is often a one-word backchannel half an hour before the
        # person actually speaks -- Speaker E's was "so. Okay." at 3:59, while
        # the chair introduced them at 34:04. Anchoring on the first turn looked
        # right and found nothing.
        cands = []
        for i in idxs:
            t0 = utts[i]["start_ms"]
            for u in utts[:i]:
                gap = t0 - u["start_ms"]
                if 0 <= gap <= LOOKBACK_MS:
                    for n in INTRO.findall(u["text"] or ""):
                        cands.append((gap, n, u["start_ms"], len(utts[i].get("text") or "")))
        # Nearest introduction to a substantial turn, not to any turn.
        cands.sort(key=lambda c: (c[0], -c[3]))
        subst = [i for i in idxs if len(utts[i].get("text") or "") > 60]
        anchor = subst[0] if subst else idxs[0]
        ta = utts[anchor]["start_ms"]
        print(f"  {sp}  {len(idxs)} turn(s); first substantive at "
              f"{ta//60000}:{ta//1000%60:02d}")
        if cands:
            gap, name, at, _ = cands[0]
            print(f"     introduced as: {name}   (at {at//60000}:{at//1000%60:02d}, "
                  f"{gap/1000:.0f}s before a turn)")
            others = [n for _, n, _, _ in cands[1:]]
            if others:
                print(f"     also named nearby: {', '.join(dict.fromkeys(others))}")
        else:
            print("     no introduction found in the preceding "
                  f"{LOOKBACK_MS//1000}s of any turn — identify by content")
        print(f"     opens: {(utts[anchor]['text'] or '')[:110]}")
        print()
    print("Verify against the audio or the surrounding text before relabeling; then\n"
          "UPDATE transcript_utts, and re-run upload_captions.py so the .srt matches.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
