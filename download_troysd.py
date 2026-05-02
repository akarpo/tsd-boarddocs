"""
Download all public BoardDocs documents for Troy School District (TroySD)
Board of Education from 2023-01-01 through today.

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
  <root>/_index.csv

Idempotent: existing non-empty files are skipped.
"""

from __future__ import annotations

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
START = date(2011, 7, 1)
END = date.today()
OUT = Path(os.environ.get("TSD_BOE_ROOT") or Path.home() / "tsd-boe-data")
UA = "Mozilla/5.0 TroySD-BoardDocs-Downloader/1.0"

ITEM_RE = re.compile(r'<li\b[^>]*\bunique="(?P<unique>[A-Z0-9]+)"', re.I)
FILE_RE = re.compile(
    r'<a\b[^>]*class="public-file"[^>]*href="(?P<href>[^"]+)"[^>]*>'
    r'(?P<text>.*?)</a>',
    re.I | re.S,
)
INVALID_FN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


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


def safe_name(s: str, max_len: int = 150) -> str:
    s = INVALID_FN.sub("_", s).strip().rstrip(". ")
    return (s[:max_len] or "_unnamed").strip()


def parse_date(numberdate: str) -> date:
    return datetime.strptime(numberdate, "%Y%m%d").date()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    log_path = OUT / "_download.log"
    idx_path = OUT / "_index.csv"
    log_f = log_path.open("a", encoding="utf-8")
    idx_new = not idx_path.exists()
    idx_f = idx_path.open("a", encoding="utf-8", newline="")
    idx_w = csv.writer(idx_f)
    if idx_new:
        idx_w.writerow(["meeting_date", "meeting_name", "meeting_unique",
                        "item_unique", "filename", "size_bytes", "url"])

    def say(msg: str):
        line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
        print(line, flush=True)
        log_f.write(line + "\n")
        log_f.flush()

    say(f"Listing meetings for committee {COMMITTEE_ID}...")
    meetings = list_meetings()
    in_range = []
    for m in meetings:
        try:
            d = parse_date(m["numberdate"])
        except (KeyError, ValueError):
            continue
        if START <= d <= END:
            in_range.append((d, m))
    in_range.sort(key=lambda x: x[0])
    say(f"{len(in_range)} meetings in range {START} .. {END} (of {len(meetings)} total)")

    downloaded = skipped = failed = 0
    minutes_saved = 0

    for d, m in in_range:
        meeting_unique = m["unique"]
        meeting_name = m.get("name", "")
        folder = OUT / f"{d.isoformat()}_{safe_name(meeting_name, 100)}"
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
                dest = folder / fname
                if dest.exists() and dest.stat().st_size > 0:
                    skipped += 1
                    idx_w.writerow([d.isoformat(), meeting_name, meeting_unique,
                                    item_unique, fname, dest.stat().st_size,
                                    "https://go.boarddocs.com" + href if href.startswith("/") else href])
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

    say(f"DONE downloaded={downloaded} skipped={skipped} failed={failed} minutes={minutes_saved}")
    log_f.close()
    idx_f.close()


if __name__ == "__main__":
    sys.exit(main() or 0)
