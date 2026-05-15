"""verify_unids.py — daily spot-check that BoardDocs identifiers still resolve.

Order of operations:
  1. Load baseline (boarddocs_unids.json). Tenant ID lives in its
     `committee_id` field, mirrored from download_troysd.py:COMMITTEE_ID.
  2. One-call liveness probe: does the committee ID itself still return a
     non-empty meetings list? If not, write a committee-ID-specific report
     and exit 3 — distinct failure, distinct remediation.
  3. Otherwise sample N meeting + N file UNIDs and verify each. Exit 1 if
     mismatches reach --mismatch-threshold.

Exit codes:
  0 = ok
  1 = per-UNID drift
  2 = couldn't verify (baseline missing, malformed, empty)
  3 = committee-ID liveness failure
"""
import argparse
import json
import random
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

SITE = "https://go.boarddocs.com/mi/troysd/Board.nsf"
UA = "Mozilla/5.0 TroySD-BoardDocs-Verifier/1.0"
BASELINE = Path(__file__).parent / "boarddocs_unids.json"
REPORT = Path(__file__).parent / "verify-report.txt"


def check_committee_alive(committee_id):
    body = f"current_committee_id={quote(committee_id)}".encode()
    req = Request(
        f"{SITE}/BD-GetMeetingsList",
        data=body,
        method="POST",
        headers={
            "User-Agent": UA,
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with urlopen(req, timeout=25) as r:
            text = r.read().decode("utf-8", errors="replace")
    except (HTTPError, URLError) as e:
        return "ERROR", str(e)[:120]
    try:
        meetings = json.loads(text)
    except json.JSONDecodeError:
        return "MISMATCH", f"non-JSON response (len={len(text)})"
    if not isinstance(meetings, list) or len(meetings) == 0:
        return "MISMATCH", "BD-GetMeetingsList returned empty list"
    return "OK", f"{len(meetings)} meetings live"


def check_meeting(unid, expected_name, committee_id):
    body = f"id={quote(unid)}&current_committee_id={quote(committee_id)}".encode()
    req = Request(
        f"{SITE}/BD-GetAgenda",
        data=body,
        method="POST",
        headers={
            "User-Agent": UA,
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with urlopen(req, timeout=25) as r:
            html = r.read().decode("utf-8", errors="replace")
    except (HTTPError, URLError) as e:
        return "ERROR", str(e)[:120]
    if len(html) < 200:
        return "MISMATCH", f"empty/short agenda (len={len(html)})"
    if expected_name and expected_name not in html:
        return "MISMATCH", f"meeting name {expected_name!r} absent from agenda HTML"
    return "OK", ""


def check_file(unid, name):
    url = f"{SITE}/files/{unid}/$file/{quote(name)}"
    req = Request(url, method="HEAD", headers={"User-Agent": UA})
    try:
        with urlopen(req, timeout=25) as r:
            length = int(r.headers.get("Content-Length") or 0)
            if length <= 0:
                return "MISMATCH", "0-byte response"
            return "OK", f"{length} bytes"
    except HTTPError as e:
        return "MISMATCH", f"HTTP {e.code}"
    except URLError as e:
        return "ERROR", str(e)[:120]


def _throttle(last, throttle):
    delta = time.time() - last
    if delta < throttle:
        time.sleep(throttle - delta)
    return time.time()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sample", type=int, default=20,
                    help="N meeting UNIDs + N file UNIDs to sample (default: 20)")
    ap.add_argument("--throttle", type=float, default=0.7,
                    help="Seconds between requests (default: 0.7)")
    ap.add_argument("--mismatch-threshold", type=int, default=3,
                    help="Per-UNID mismatches before exiting 1 (default: 3)")
    args = ap.parse_args()

    if not BASELINE.exists():
        print("boarddocs_unids.json missing — run download_troysd.py first",
              file=sys.stderr)
        return 2
    try:
        data = json.loads(BASELINE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"boarddocs_unids.json malformed: {e}", file=sys.stderr)
        return 2
    committee_id = data.get("committee_id")
    if not committee_id:
        print("baseline missing 'committee_id' — re-run download_troysd.py to refresh",
              file=sys.stderr)
        return 2
    meetings = list(data.get("meetings", {}).items())
    files = list(data.get("files", {}).items())

    # --- step 1: committee-ID liveness probe -------------------------------
    v, d = check_committee_alive(committee_id)
    print(f"  committee {committee_id} {v} {d}")
    if v != "OK":
        with REPORT.open("w", encoding="utf-8") as f:
            f.write(
                f"BoardDocs committee-ID liveness check FAILED at "
                f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n\n"
            )
            f.write(f"  committee_id={committee_id}: {d}\n\n")
            f.write(
                "This is NOT per-UNID drift. The tenant identifier itself "
                "no longer resolves on BoardDocs, which means every "
                "`BD-Get*` call from the downloader is also returning empty "
                "results (silently — the downloader cannot tell this from "
                "'nothing new to fetch').\n\n"
                "Likely cause: the BoardDocs tenant rotated its committee "
                "ID, or the BD-Get* endpoints changed shape. No amount of "
                "`--recheck` will fix it.\n\n"
                "Remediation: load "
                "https://go.boarddocs.com/mi/troysd/Board.nsf in a browser, "
                "inspect the live `current_committee_id` form parameter on "
                "any committee selector, and update COMMITTEE_ID in "
                "download_troysd.py. Then re-run the downloader — it will "
                "refresh the baseline's `committee_id` field on the next pass.\n"
            )
        return 3

    # --- step 2: per-UNID sampling -----------------------------------------
    if not meetings and not files:
        print("baseline has no UNIDs to sample — committee ID is alive, "
              "nothing else to verify", file=sys.stderr)
        if REPORT.exists():
            REPORT.unlink()
        return 0

    rng = random.Random()
    m_sample = rng.sample(meetings, min(args.sample, len(meetings))) if meetings else []
    f_sample = rng.sample(files, min(args.sample, len(files))) if files else []

    counts = {"OK": 0, "MISMATCH": 0, "ERROR": 0}
    mismatches = []
    last = 0.0
    for unid, meta in m_sample:
        last = _throttle(last, args.throttle)
        v, d = check_meeting(unid, meta.get("name", ""), committee_id)
        counts[v] += 1
        print(f"  meeting {unid[:8]}.. {v} {d}")
        if v == "MISMATCH":
            mismatches.append(("meeting", unid, meta, d))
    for unid, meta in f_sample:
        last = _throttle(last, args.throttle)
        v, d = check_file(unid, meta.get("name", ""))
        counts[v] += 1
        print(f"  file    {unid[:8]}.. {v} {d}")
        if v == "MISMATCH":
            mismatches.append(("file", unid, meta, d))

    total_sampled = len(m_sample) + len(f_sample)
    print(f"\nverify-summary: ok={counts['OK']} mismatch={counts['MISMATCH']} "
          f"error={counts['ERROR']} sampled={total_sampled} "
          f"threshold={args.mismatch_threshold}")
    if counts["MISMATCH"] >= args.mismatch_threshold:
        with REPORT.open("w", encoding="utf-8") as f:
            f.write(
                f"BoardDocs per-UNID verification failed at "
                f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n\n"
            )
            f.write(
                f"Committee ID ({committee_id}) is alive, but "
                f"{counts['MISMATCH']} of {total_sampled} sampled UNIDs "
                f"no longer resolve:\n\n"
            )
            for kind, unid, meta, d in mismatches:
                f.write(f"  - {kind} {unid}: {d}  meta={meta}\n")
            f.write(
                "\nLikely cause: BoardDocs rebuilt its Notes database or "
                "the items were deleted/re-uploaded. Re-run "
                "`python download_troysd.py --recheck` to refresh the "
                "baseline.\n"
            )
        return 1
    if REPORT.exists():
        REPORT.unlink()
    return 0


if __name__ == "__main__":
    sys.exit(main())
