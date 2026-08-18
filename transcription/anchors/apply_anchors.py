#!/usr/bin/env python3
"""Replace one meeting's anchors in D1 from a hand-authored JSON, then validate.

  python3 apply_anchors.py 2026-01-13 anchors_2026-01-13.json [--dry-run]

The JSON is [{"t": "H:MM:SS", "label": "..."}, ...] in chronological order.
"""
import argparse, json, re, subprocess, sys
sys_path_hack = None
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Transcript exports, agenda keyword sets and the anchor cache are bulk data
# regenerable from D1, so they are NOT committed -- they live in a workdir.
# Override with ANCHORS_DATA if you keep them elsewhere.
import os as _os
DATA = Path(_os.environ.get("ANCHORS_DATA")
            or (Path(__file__).resolve().parent.parent.parent / "scratch" / "anchors-rebuild"))
REPO = HERE.parent.parent

def secs(t):
    p = [int(x) for x in t.split(":")]
    return p[0]*3600 + p[1]*60 + p[2] if len(p) == 3 else p[0]*60 + p[1]

def d1(sql):
    r = subprocess.run(["npx","wrangler","d1","execute","tsd-boarddocs","--remote",
                        "--json","--command",sql], cwd=REPO, capture_output=True, text=True)
    if r.returncode != 0:
        # wrangler reports API errors on stdout, not stderr -- reporting only
        # stderr produced a blank "D1 failed:" that said nothing
        raise SystemExit(f"D1 failed (rc={r.returncode}):\n"
                         f"  stdout: {r.stdout[:400]}\n  stderr: {r.stderr[:200]}")
    return json.loads(r.stdout)[0]["results"]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("date"); ap.add_argument("json"); ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    rows = json.load(open(a.json))
    name = d1(f"SELECT meeting_name FROM recordings WHERE meeting_date='{a.date}'")[0]["meeting_name"]
    dur = d1(f"SELECT duration_s FROM recordings WHERE meeting_date='{a.date}'")[0]["duration_s"] or 0

    # ---- validate before touching anything -------------------------------
    errs = []
    ms = [secs(r["t"])*1000 for r in rows]
    if ms[0] != 0: errs.append("first anchor is not 0:00")
    if ms != sorted(ms): errs.append("timestamps are not ascending")
    if len(ms) != len(set(ms)): errs.append("duplicate timestamps")
    if len(rows) < 3: errs.append("fewer than 3 chapters")
    for i in range(len(ms)-1):
        if ms[i+1]-ms[i] < 10000: errs.append(f"gap under 10s at {rows[i+1]['t']}")
    if dur and ms[-1] > dur*1000: errs.append(f"last anchor {rows[-1]['t']} exceeds duration")
    for r in rows:
        L = r["label"]
        if L.endswith("…"): errs.append(f"truncated label: {L}")
        if re.match(r"^\d+\.[a-z]\s+[A-Za-z]\.", L): errs.append(f"duplicated prefix: {L}")
        if re.match(r"^[a-z]", L): errs.append(f"lowercase (prose?) label: {L}")
        if re.match(r"^\d{1,2}(\.[A-Za-z0-9]{1,3})?\s", L):
            errs.append(f"authored label must not carry the number inline "
                        f"(put it in `items`): {L}")
        if len(L) > 100: errs.append(f"label over 100 chars: {L[:40]}…")
    if errs:
        print("VALIDATION FAILED:"); [print("  -", e) for e in errs]; return 1

    print(f"{a.date}  {len(rows)} anchors, {ms[-1]//60000}m span, duration {dur//60}m — valid")
    for r in rows: print(f"   {r['t']:>8}  {r['label']}")
    if a.dry_run: return 0

    # The authored file keeps `items` and a clean `label`; D1 stores them joined, so
    # the site's chapter chips and the YouTube description both show the same
    # numbering a viewer sees on BoardDocs.
    for r in rows:
        it = r.get("items") or []
        r["_display"] = (f"{'/'.join(it)} " if it else "") + r["label"]

    esc = lambda s: s.replace("'", "''")
    d1(f"DELETE FROM transcript_anchors WHERE meeting_date='{a.date}' AND meeting_name='{esc(name)}'")
    vals = ",".join(f"('{a.date}','{esc(name)}',{secs(r['t'])*1000},'{esc(r['_display'])}')" for r in rows)
    d1(f"INSERT INTO transcript_anchors (meeting_date,meeting_name,start_ms,label) VALUES {vals}")
    n = d1(f"SELECT COUNT(*) n FROM transcript_anchors WHERE meeting_date='{a.date}'")[0]["n"]
    print(f"written: {n} anchors now in D1")

    # Coverage gate: an agenda item the transcript shows being DISCUSSED must have
    # an anchor. Leaving one out is only defensible when the board genuinely never
    # took it up -- which is a claim about the transcript, so check it against the
    # transcript. This caught a roof-replacement item and a traffic-signal item
    # that had been hand-authored out of two meetings.
    json.dump([{"start_ms": secs(r["t"])*1000, "label": r["label"],
                "items": r.get("items", [])} for r in rows],
              open(DATA / f"cur_{a.date}.json", "w"))
    # Gate on the published BoardDocs outline, not on `chunks`: chunks only knows
    # items that carry an attachment, and its numbering disagrees with the outline.
    try:
        import qa_numbers
        probs = qa_numbers.check(a.date)
        if probs:
            print(f"  QA: {len(probs)} to review")
            for k, t, msg in probs[:6]:
                print(f"    {k:<9} {t:>8}  {msg}")
        else:
            print("  QA: numbering valid, every discussed item has a chapter")
    except Exception as e:                                   # noqa: BLE001
        print(f"  (QA unavailable: {type(e).__name__}: {e})")

    # queue the YouTube description rebuild; it costs API quota, D1 does not
    q = HERE / "pending_push.json"
    pend = json.load(open(q)) if q.exists() else []
    if a.date not in pend:
        pend.append(a.date)
        json.dump(sorted(pend), open(q, "w"), indent=1)
    print(f"  queued for description push ({len(pend)} pending)")
    return 0

if __name__ == "__main__":
    sys.exit(main())
