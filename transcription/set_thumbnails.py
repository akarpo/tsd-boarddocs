#!/usr/bin/env python3
"""Set crest thumbnails on a list of videos, respecting the rate limit.

`thumbnails.set` has a rolling per-user cap that is separate from the daily
quota and much longer-lived: on 2026-08-17 a run of ~100 sets exhausted it, and
it was still refusing 20 hours later while playlist writes in the same run
succeeded. Failed attempts appear to count against the cap as well, so a tight
retry loop keeps it saturated -- 65 retries over 80 minutes never recovered a
single one.

Hence a drip, not a batch: one attempt at a time, and a 429 buys an hour of
silence rather than an immediate retry. Progress is written back to the pending
file after every success, so a reboot costs nothing.

Cards are regenerated from `assets/tsd_card_base.jpg` + `thumbnails_manifest.json`,
so this needs nothing outside the repo.

  python3 transcription/set_thumbnails.py            # work the pending list
  python3 transcription/set_thumbnails.py --check    # just report, set nothing
  nohup python3 transcription/set_thumbnails.py --daemon >/dev/null 2>&1 &
"""
from __future__ import annotations

import argparse, datetime, json, os, sys, time
import urllib.error, urllib.parse, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import tsd_secrets                      # noqa: E402
import thumbnails as T                  # noqa: E402

PENDING = HERE / "thumbnails_pending.json"
MANIFEST = HERE / "thumbnails_manifest.json"
LOG = HERE.parent / "scratch" / "set_thumbnails.log"
BLOCKED_WAIT, OK_WAIT = 3600, 300


def log(msg: str) -> None:
    line = f"{datetime.datetime.now().astimezone():%Y-%m-%d %H:%M:%S %Z}  {msg}"
    print(line, flush=True)
    try:
        LOG.parent.mkdir(exist_ok=True)
        with open(LOG, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def token() -> str:
    d = urllib.parse.urlencode({
        "client_id": tsd_secrets.require("YT_CLIENT_ID"),
        "client_secret": tsd_secrets.require("YT_CLIENT_SECRET"),
        "refresh_token": tsd_secrets.require("YT_REFRESH_TOKEN"),
        "grant_type": "refresh_token"}).encode()
    return json.load(urllib.request.urlopen(urllib.request.Request(
        "https://oauth2.googleapis.com/token", d)))["access_token"]


def card_for(rec: dict):
    """Rebuild this meeting's card from the committed base + manifest row."""
    t = None if rec["time"] in ("(omitted)", "", None) else rec["time"]
    return T.synthesize(rec["date"], t, rec["kind"])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="report state, change nothing")
    ap.add_argument("--daemon", action="store_true", help="detach and drip in the background")
    a = ap.parse_args()

    pending = json.load(open(PENDING)) if PENDING.exists() else []
    man = {r["id"]: r for r in json.load(open(MANIFEST))}
    if not pending:
        print("nothing pending — every board video has its crest card")
        return 0
    if a.check:
        print(f"{len(pending)} thumbnails pending:")
        for v in pending:
            r = man[v]
            print(f"  {r['date']}  {v}  {r['kind']}")
        return 0

    if a.daemon:
        if os.fork():
            os._exit(0)
        os.setsid()
        if os.fork():
            os._exit(0)

    log(f"drip start: {len(pending)} pending (pid {os.getpid()})")
    tok, done = token(), 0
    while pending:
        vid = pending[0]
        rec = man[vid]
        try:
            buf = __import__("io").BytesIO()
            card_for(rec).save(buf, "JPEG", quality=95, subsampling=0)
            req = urllib.request.Request(
                f"https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId={vid}",
                data=buf.getvalue(), method="POST",
                headers={"authorization": f"Bearer {tok}", "content-type": "image/jpeg"})
            urllib.request.urlopen(req, timeout=90)
            pending.pop(0); done += 1
            json.dump(pending, open(PENDING, "w"), indent=1)
            log(f"OK {rec['date']} {vid}  ({done} set, {len(pending)} left)")
            if pending:
                time.sleep(OK_WAIT)
        except urllib.error.HTTPError as e:
            e.read()
            if e.code == 401:
                tok = token(); continue
            log(f"{e.code} on {vid} — rate limited; sleeping {BLOCKED_WAIT // 60}m")
            time.sleep(BLOCKED_WAIT)
            tok = token()
        except Exception as e:                       # noqa: BLE001
            log(f"err {vid} {type(e).__name__}; sleeping 10m")
            time.sleep(600)
    log(f"all set ({done} this run)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
