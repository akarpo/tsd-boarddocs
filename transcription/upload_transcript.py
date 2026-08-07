#!/usr/bin/env python3
"""Load a meeting transcript + YouTube recording into the site's D1 database.

Creates (if needed) and fills three tables the Worker's /api/recording serves:
  recordings         (meeting_date, meeting_name) -> youtube_id, duration_s
  transcript_utts    per-utterance rows: start/end ms, attributed speaker, text
  transcript_anchors agenda-item video chapters: start_ms -> label

Speaker names come from the speakers.json spec (resolution order: overrides >
mapping > raw letter; time-based `splits` handle a cluster that held two people).
Idempotent: re-running replaces the meeting's rows.

Usage
  python3 transcription/upload_transcript.py \
      "…/Troy School Board Meeting - 2026-07-22 transcript.json" \
      --date 2026-07-22 --name "Regular Meeting of the Board of Education 1 00 PM" \
      --youtube v9EHA5_yT-8 \
      --speakers transcription/examples/2026-07-22/speakers.json \
      --anchors  transcription/examples/2026-07-22/anchors.json
  # --dry-run writes the SQL to a temp file (path printed) instead of executing it.

`--name` must match the meeting_name already in D1 chunks (see /api/meetings)
so the meeting page can join the recording to its document set. Executes with
`wrangler d1 execute tsd-boarddocs --remote` (remote! local is a silent no-op
for the deployed site).
"""
from __future__ import annotations
import argparse, json, subprocess, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from transcribe_meeting import clean_mapping

DB = "tsd-boarddocs"

DDL = """
CREATE TABLE IF NOT EXISTS recordings (
  meeting_date TEXT NOT NULL, meeting_name TEXT NOT NULL,
  youtube_id TEXT NOT NULL, duration_s INTEGER,
  PRIMARY KEY (meeting_date, meeting_name)
);
CREATE TABLE IF NOT EXISTS transcript_utts (
  meeting_date TEXT NOT NULL, meeting_name TEXT NOT NULL, idx INTEGER NOT NULL,
  start_ms INTEGER, end_ms INTEGER, speaker TEXT, text TEXT,
  PRIMARY KEY (meeting_date, meeting_name, idx)
);
CREATE TABLE IF NOT EXISTS transcript_anchors (
  meeting_date TEXT NOT NULL, meeting_name TEXT NOT NULL,
  start_ms INTEGER NOT NULL, label TEXT NOT NULL,
  PRIMARY KEY (meeting_date, meeting_name, start_ms)
);
"""


def q(s):  # SQL single-quote escape
    return "'" + str(s).replace("'", "''") + "'"


def namer(spec):
    # Same normalisation the transcriber applies: strip the identifier's
    # split-cluster indices ("Nancy Philippart - 2") and drop "Unknown - N",
    # so what lands in D1 matches the committed transcript exactly. This file
    # having its own namer is why the artifact reached the site as well as the
    # deliverables — fix one, and the other still ships it.
    mapping = clean_mapping(spec.get("mapping") or {})
    mapping.update(spec.get("overrides") or {})
    splits = {s["cluster"]: s for s in spec.get("splits") or []}

    def who(u):
        sp, st = u["speaker"], u["start"]
        if sp in splits:
            s = splits[sp]
            return s["before"] if st < s["at_ms"] else s["after"]
        n = mapping.get(sp, sp)
        return n if n != sp else f"Speaker {sp}"
    return who


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("transcript", help="AssemblyAI transcript JSON (with utterances)")
    ap.add_argument("--date", required=True)
    ap.add_argument("--name", required=True, help="meeting_name exactly as stored in D1 chunks")
    ap.add_argument("--youtube", required=True, help="YouTube video id (e.g. v9EHA5_yT-8)")
    ap.add_argument("--speakers", help="speakers.json (mapping/overrides/splits) for name attribution")
    ap.add_argument("--anchors", help="anchors.json: [{start_ms,label},…] agenda-item chapters")
    ap.add_argument("--dry-run", action="store_true", help="write SQL, don't execute")
    a = ap.parse_args()

    r = json.load(open(a.transcript))
    utts = r.get("utterances") or []
    if not utts:
        raise SystemExit("transcript has no utterances (was speaker_labels on?)")
    who = namer(json.load(open(a.speakers))) if a.speakers else (lambda u: f"Speaker {u['speaker']}")
    anchors = json.load(open(a.anchors)) if a.anchors else []
    d, n = q(a.date), q(a.name)

    sql = [DDL,
           f"DELETE FROM recordings WHERE meeting_date={d} AND meeting_name={n};",
           f"DELETE FROM transcript_utts WHERE meeting_date={d} AND meeting_name={n};",
           f"DELETE FROM transcript_anchors WHERE meeting_date={d} AND meeting_name={n};",
           f"INSERT INTO recordings VALUES ({d},{n},{q(a.youtube)},{int(r.get('audio_duration') or 0)});"]
    for an in anchors:
        sql.append(f"INSERT INTO transcript_anchors VALUES ({d},{n},{int(an['start_ms'])},{q(an['label'])});")
    for i in range(0, len(utts), 40):
        vals = ",\n".join(
            f"({d},{n},{j},{int(u['start'])},{int(u['end'])},{q(who(u))},{q(u['text'].strip())})"
            for j, u in enumerate(utts[i:i + 40], start=i))
        sql.append(f"INSERT INTO transcript_utts VALUES {vals};")

    out = Path(tempfile.mkdtemp()) / f"transcript_{a.date}.sql"
    out.write_text("\n".join(sql), encoding="utf-8")
    print(f"{len(utts)} utterances, {len(anchors)} anchors -> {out}")
    if a.dry_run:
        return
    subprocess.run(["wrangler", "d1", "execute", DB, "--remote", "--yes", "--file", str(out)],
                   check=True, cwd=Path(__file__).resolve().parent.parent)
    print("uploaded to D1 (remote)")


if __name__ == "__main__":
    main()
