"""
Download public BoardDocs documents for Troy School District (TroySD)
Board of Education.

On run the script lists every meeting available online, shows how many you
already have saved locally, and lets you choose what to fetch:

  * ALL meetings
  * a DATE RANGE (start / end)
  * a SPECIFIC SET you pick from the list (or pass via --meetings)

Whatever you choose, meetings already downloaded locally are skipped unless
you pass --recheck. If you run non-interactively (cron, pipe) without a
selection flag, it behaves as before: every meeting, incrementally.

Endpoints discovered on https://go.boarddocs.com/mi/troysd/Board.nsf:
  POST BD-GetMeetingsList   form: current_committee_id          -> JSON
  POST BD-GetAgenda         form: id, current_committee_id      -> HTML
  POST BD-GetPublicFiles    form: id, parentid, filetype=public,
                                  current_committee_id          -> HTML
  POST BD-GetMinutes        form: id, current_committee_id      -> HTML/empty
  GET  files/<unid>/$file/<name>                                -> binary

Output (under the corpus root, configurable via TSD_BOE_ROOT env var;
defaults to ~/tsd-boe-data):
  <root>/<YYYY-MM-DD>_<meeting_name>/<filename>
  <root>/_download.log
  <root>/_index.csv     (one row per newly downloaded file)

Usage:
  python download_troysd.py                       # interactive menu
  python download_troysd.py --all                 # every meeting, incrementally
  python download_troysd.py --start 2024-01-01    # a date range (end defaults to today)
  python download_troysd.py --start 2023-07-01 --end 2024-06-30
  python download_troysd.py --meetings 2025-06,Workshop   # dates and/or name substrings
  python download_troysd.py --meetings-file picks.txt     # same, one per line
  python download_troysd.py --all --recheck       # also re-verify meetings already on disk
  python download_troysd.py --all --dry-run       # show what would download, fetch nothing

A meeting counts as "already downloaded" once its <YYYY-MM-DD>_<name> folder
exists locally and is non-empty. Within a meeting, individual files are still
skipped if already present and non-empty, so --recheck is safe and resumable.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from datetime import date, datetime
from html import unescape
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urljoin
from urllib.request import Request, urlopen

SITE_URL = "https://go.boarddocs.com/mi/troysd/Board.nsf"
COMMITTEE_ID = "A4EP6J588C05"  # Board of Education
OUT = Path(os.environ.get("TSD_BOE_ROOT") or Path.home() / "tsd-boe-data")
UA = "Mozilla/5.0 TroySD-BoardDocs-Downloader/1.0"
BASELINE_PATH = Path(__file__).parent / "boarddocs_unids.json"

ITEM_RE = re.compile(r'<li\b[^>]*\bunique="(?P<unique>[A-Z0-9]+)"', re.I)
FILE_RE = re.compile(
    r'<a\b[^>]*class="public-file"[^>]*href="(?P<href>[^"]+)"[^>]*>'
    r'(?P<text>.*?)</a>',
    re.I | re.S,
)
FILE_UNID_RE = re.compile(r'/files/(?P<unid>[A-Z0-9]+)/\$file/', re.I)
INVALID_FN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
MEETING_DIR_RE = re.compile(r'\d{4}-\d{2}-\d{2}_')
DATE_TERM_RE = re.compile(r'\d{4}(-\d{2}(-\d{2})?)?$')


# --------------------------------------------------------------------------
# BoardDocs HTTP
# --------------------------------------------------------------------------
def _post(path: str, data: dict) -> str:
    body = "&".join(f"{k}={quote(str(v))}" for k, v in data.items()).encode()
    req = Request(
        f"{SITE_URL}/{path}?open",
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": UA,
            "Accept": "*/*",
        },
        method="POST",
    )
    with urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", errors="replace")


def _get(path: str) -> bytes:
    url = path if path.startswith("http") else urljoin(SITE_URL + "/", path.lstrip("/"))
    if path.startswith("/mi/"):
        url = "https://go.boarddocs.com" + path
    req = Request(url, headers={"User-Agent": UA})
    with urlopen(req, timeout=180) as r:
        return r.read()


def list_meetings():
    return json.loads(_post("BD-GetMeetingsList", {"current_committee_id": COMMITTEE_ID}))


def list_item_uniques(meeting_unique: str):
    html = _post("BD-GetAgenda", {
        "id": meeting_unique,
        "current_committee_id": COMMITTEE_ID,
    })
    return [m.group("unique") for m in ITEM_RE.finditer(html)]


def list_files(item_unique: str):
    html = _post("BD-GetPublicFiles", {
        "id": item_unique,
        "parentid": item_unique,
        "filetype": "public",
        "current_committee_id": COMMITTEE_ID,
    })
    out = []
    for m in FILE_RE.finditer(html):
        href = unescape(m.group("href").strip())
        url_basename = unquote(href.rsplit("/", 1)[-1])
        out.append((href, url_basename))
    return out


def fetch_minutes(meeting_unique: str) -> str:
    return _post("BD-GetMinutes", {
        "id": meeting_unique,
        "current_committee_id": COMMITTEE_ID,
    })


# --------------------------------------------------------------------------
# Baseline UNID index (boarddocs_unids.json)
#
# Read by verify_unids.py to spot-check that BoardDocs identifiers still
# resolve. Maintained additively here — every observed meeting + file UNID
# stays in the baseline forever, even when meetings drop off the live list.
# --------------------------------------------------------------------------
def extract_file_unid(href: str):
    m = FILE_UNID_RE.search(href)
    return m.group("unid") if m else None


def write_baseline(observed_meetings: dict, observed_files: dict) -> None:
    baseline = {}
    if BASELINE_PATH.exists():
        try:
            baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            baseline = {}
    baseline["committee_id"] = COMMITTEE_ID
    baseline.setdefault("meetings", {})
    baseline.setdefault("files", {})
    baseline["meetings"].update(observed_meetings)
    baseline["files"].update(observed_files)
    BASELINE_PATH.write_text(
        json.dumps(baseline, indent=2, sort_keys=True), encoding="utf-8")


# --------------------------------------------------------------------------
# Naming / dates
# --------------------------------------------------------------------------
def safe_name(s: str, max_len: int = 150) -> str:
    s = INVALID_FN.sub("_", s).strip().rstrip(". ")
    return (s[:max_len] or "_unnamed").strip()


def parse_date(numberdate: str) -> date:
    return datetime.strptime(numberdate, "%Y%m%d").date()


def parse_iso_date(s: str) -> date:
    """Parse a YYYY-MM-DD string (used for --start/--end and prompts)."""
    return datetime.strptime(s.strip(), "%Y-%m-%d").date()


def meeting_dirname(d: date, meeting_name: str) -> str:
    """The folder name this script uses for a given meeting."""
    return f"{d.isoformat()}_{safe_name(meeting_name, 100)}"


def meeting_folder(out: Path, d: date, meeting_name: str) -> Path:
    return out / meeting_dirname(d, meeting_name)


def scan_local_meetings(out: Path) -> set[str]:
    """Folder names of meetings already saved locally and non-empty.

    Used to decide which meetings are new. A meeting whose folder exists but
    is empty is treated as NOT downloaded, so it gets retried.
    """
    found: set[str] = set()
    if not out.is_dir():
        return found
    for child in out.iterdir():
        if (child.is_dir()
                and MEETING_DIR_RE.match(child.name)
                and any(child.iterdir())):
            found.add(child.name)
    return found


# --------------------------------------------------------------------------
# Meeting selection
# --------------------------------------------------------------------------
def all_dated_meetings(meetings) -> list[tuple[date, dict]]:
    """All meetings that have a parseable date, sorted oldest-first."""
    out = []
    for m in meetings:
        try:
            out.append((parse_date(m["numberdate"]), m))
        except (KeyError, ValueError):
            continue
    out.sort(key=lambda x: x[0])
    return out


def load_meeting_terms(meetings_arg: str | None, meetings_file: str | None) -> list[str]:
    """Collect selection terms from --meetings and --meetings-file."""
    terms: list[str] = []
    if meetings_arg:
        terms += [t.strip() for t in meetings_arg.split(",") if t.strip()]
    if meetings_file:
        for line in Path(meetings_file).read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                terms.append(line)
    return terms


def meeting_matches_term(d: date, m: dict, term: str) -> bool:
    """A term is either a date prefix (YYYY, YYYY-MM, YYYY-MM-DD) or a
    case-insensitive substring of the meeting name."""
    if DATE_TERM_RE.match(term):
        return d.isoformat().startswith(term)
    return term.lower() in (m.get("name") or "").lower()


def apply_filters(dated, start: date | None, end: date | None,
                  terms: list[str]) -> list[tuple[date, dict]]:
    """Filter (date, meeting) pairs by date bounds and/or selection terms."""
    sel = dated
    if start:
        sel = [(d, m) for d, m in sel if d >= start]
    if end:
        sel = [(d, m) for d, m in sel if d <= end]
    if terms:
        sel = [(d, m) for d, m in sel
               if any(meeting_matches_term(d, m, t) for t in terms)]
    return sel


def parse_index_spec(raw: str, n: int) -> list[int]:
    """'1-5,12,40' -> sorted 0-based indices within [0, n). Raises ValueError
    on malformed input."""
    picked: set[int] = set()
    for part in raw.replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            for i in range(int(a), int(b) + 1):
                picked.add(i)
        else:
            picked.add(int(part))
    return sorted(i - 1 for i in picked if 1 <= i <= n)


def prompt_selection(dated, local: set[str], ask=input, out=print):
    """Interactive menu. Returns the chosen list of (date, meeting) pairs.

    `ask` (input) and `out` (print) are injected so this is unit-testable.
    """
    out("")
    out("What would you like to download?")
    out("  [1] All meetings")
    out("  [2] A date range")
    out("  [3] Specific meetings (pick from the list)")
    try:
        choice = (ask("Choice [1]: ") or "1").strip()
    except EOFError:
        choice = "1"

    if choice == "2":
        lo, hi = dated[0][0], dated[-1][0]
        try:
            s = (ask(f"Start date YYYY-MM-DD [{lo}]: ") or "").strip()
            e = (ask(f"End date YYYY-MM-DD [{hi}]: ") or "").strip()
        except EOFError:
            s = e = ""
        start = parse_iso_date(s) if s else lo
        end = parse_iso_date(e) if e else hi
        return [(d, m) for d, m in dated if start <= d <= end]

    if choice == "3":
        display = list(reversed(dated))  # newest first
        out("")
        for i, (d, m) in enumerate(display, 1):
            mark = "*" if meeting_dirname(d, m.get("name", "")) in local else " "
            out(f"  [{i:>3}] {mark} {d}  {m.get('name', '')}")
        out("")
        out("  (* = already downloaded locally)")
        try:
            raw = ask("Enter numbers/ranges to download (e.g. 1-5,12,40): ")
        except EOFError:
            raw = ""
        try:
            idxs = parse_index_spec(raw or "", len(display))
        except ValueError:
            out("Could not parse that selection — nothing selected.")
            return []
        chosen = [display[i] for i in idxs]
        chosen.sort(key=lambda x: x[0])
        return chosen

    # default / "1"
    return list(dated)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sel = ap.add_argument_group(
        "meeting selection", "choose at most one; omit all of these to be "
        "prompted interactively (or to default to every meeting when not "
        "running in a terminal)")
    sel.add_argument("--all", action="store_true",
                     help="every meeting available on BoardDocs")
    sel.add_argument("--start", metavar="YYYY-MM-DD", type=parse_iso_date,
                     help="only meetings on or after this date")
    sel.add_argument("--end", metavar="YYYY-MM-DD", type=parse_iso_date,
                     help="only meetings on or before this date")
    sel.add_argument("--meetings", metavar="LIST",
                     help="comma-separated list of date prefixes "
                          "(YYYY, YYYY-MM, or YYYY-MM-DD) and/or "
                          "case-insensitive meeting-name substrings")
    sel.add_argument("--meetings-file", metavar="PATH",
                     help="file with one date prefix or name substring per "
                          "line (# comments allowed)")

    mod = ap.add_argument_group("modifiers")
    mod.add_argument("--recheck", action="store_true",
                     help="re-walk selected meetings already on disk and "
                          "verify each file (picks up files added to old "
                          "meetings; finishes an interrupted run)")
    mod.add_argument("--dry-run", action="store_true",
                     help="list what would be downloaded, then exit "
                          "(no files or folders are written)")
    mod.add_argument("-y", "--yes", action="store_true",
                     help="skip the 'proceed?' confirmation prompt")
    mod.add_argument("-i", "--interactive", action="store_true",
                     help="force the interactive menu even when stdin is "
                          "not a terminal")
    args = ap.parse_args(argv)

    has_flag_selection = bool(args.all or args.start or args.end
                              or args.meetings or args.meetings_file)
    interactive = args.interactive or (not has_flag_selection and sys.stdin.isatty())

    log_f = None
    if not args.dry_run:
        OUT.mkdir(parents=True, exist_ok=True)
        log_f = (OUT / "_download.log").open("a", encoding="utf-8")

    def say(msg: str):
        line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
        print(line, flush=True)
        if log_f:
            log_f.write(line + "\n")
            log_f.flush()

    say(f"Listing meetings for committee {COMMITTEE_ID}...")
    meetings = list_meetings()
    dated = all_dated_meetings(meetings)
    if not dated:
        say("No meetings with parseable dates returned — nothing to do.")
        if log_f:
            log_f.close()
        return 0
    local = scan_local_meetings(OUT)
    say(f"{len(dated)} meetings online ({dated[0][0]} .. {dated[-1][0]}) "
        f"| {len(local)} meeting folder(s) already saved locally")

    # Baseline accumulators (written at end of run via try/finally).
    # Meeting UNIDs come from the live list and can be captured before any
    # download; file UNIDs are only known after list_files() runs per meeting.
    observed_meetings = {
        m["unique"]: {"date": d.isoformat(), "name": m.get("name", "")}
        for d, m in dated if m.get("unique")
    }
    observed_files: dict = {}
    try:

        # --- choose meetings ---------------------------------------------------
        if has_flag_selection:
            if args.all:
                selected = list(dated)
            else:
                terms = load_meeting_terms(args.meetings, args.meetings_file)
                selected = apply_filters(dated, args.start, args.end, terms)
        elif interactive:
            selected = prompt_selection(dated, local)
        else:
            selected = list(dated)  # non-interactive default: every meeting
        selected.sort(key=lambda x: x[0])

        # --- review against what's already downloaded --------------------------
        todo = []
        already = 0
        for d, m in selected:
            if not args.recheck and meeting_dirname(d, m.get("name", "")) in local:
                already += 1
            else:
                todo.append((d, m))

        verb = "re-check" if args.recheck else "download"
        say(f"selected {len(selected)} meeting(s) | {already} already downloaded "
            f"locally | {len(todo)} to {verb}")

        if args.dry_run:
            for d, m in todo:
                say(f"   would {verb}: {d} | {m.get('name', '')}")
            say("DONE dry-run (nothing downloaded)")
            return 0

        if not todo:
            say("DONE nothing to download")
            if log_f:
                log_f.close()
            return 0

        # --- confirm -----------------------------------------------------------
        if interactive and not args.yes:
            try:
                ans = input(f"Proceed to {verb} {len(todo)} meeting(s)? [Y/n] ").strip().lower()
            except EOFError:
                ans = "n"
            if ans in ("n", "no"):
                say("aborted by user")
                if log_f:
                    log_f.close()
                return 0

        # --- download ----------------------------------------------------------
        idx_path = OUT / "_index.csv"
        idx_new = not idx_path.exists()
        idx_f = idx_path.open("a", encoding="utf-8", newline="")
        idx_w = csv.writer(idx_f)
        if idx_new:
            idx_w.writerow(["meeting_date", "meeting_name", "meeting_unique",
                            "item_unique", "filename", "size_bytes", "url"])

        downloaded = skipped = failed = 0
        minutes_saved = 0

        for d, m in todo:
            meeting_unique = m["unique"]
            meeting_name = m.get("name", "")
            folder = meeting_folder(OUT, d, meeting_name)
            folder.mkdir(parents=True, exist_ok=True)
            say(f"-- {d} | {meeting_name} | {meeting_unique}")

            # Best-effort: save minutes HTML if recorded
            try:
                minutes_html = fetch_minutes(meeting_unique).strip()
                if minutes_html:
                    mp = folder / "_minutes.html"
                    if not mp.exists():
                        mp.write_text(minutes_html, encoding="utf-8")
                        minutes_saved += 1
                        say(f"   m _minutes.html ({len(minutes_html):,} B)")
            except Exception as e:
                say(f"   ! minutes fetch failed: {e}")

            try:
                items = list_item_uniques(meeting_unique)
            except Exception as e:
                say(f"   ! agenda failed: {e}")
                failed += 1
                continue

            for item_unique in items:
                try:
                    files = list_files(item_unique)
                except Exception as e:
                    say(f"   ! item {item_unique} list-files failed: {e}")
                    failed += 1
                    continue

                for href, fname in files:
                    fname = safe_name(fname)
                    file_unid = extract_file_unid(href)
                    if file_unid:
                        observed_files[file_unid] = {
                            "meeting_unid": meeting_unique,
                            "name": fname,
                        }
                    else:
                        say(f"   ! could not extract file UNID from href: {href}")
                    dest = folder / fname
                    if dest.exists() and dest.stat().st_size > 0:
                        skipped += 1
                        continue
                    try:
                        data = _get(href)
                    except (HTTPError, URLError) as e:
                        say(f"   ! download {href}: {e}")
                        failed += 1
                        continue
                    except Exception as e:
                        say(f"   ! download {href}: {e}")
                        failed += 1
                        continue
                    dest.write_bytes(data)
                    downloaded += 1
                    idx_w.writerow([d.isoformat(), meeting_name, meeting_unique,
                                    item_unique, fname, len(data),
                                    "https://go.boarddocs.com" + href if href.startswith("/") else href])
                    idx_f.flush()
                    say(f"   + {fname} ({len(data):,} B)")
                    time.sleep(0.1)

            time.sleep(0.2)

        say(f"DONE downloaded={downloaded} skipped={skipped} failed={failed} "
            f"minutes={minutes_saved}")
        if log_f:
            log_f.close()
        idx_f.close()
        return 0
    finally:
        if not args.dry_run and (observed_meetings or observed_files):
            write_baseline(observed_meetings, observed_files)


if __name__ == "__main__":
    sys.exit(main() or 0)
