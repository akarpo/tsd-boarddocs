#!/usr/bin/env python3
"""Upload meeting videos to YouTube via the Data API (resumable), set the district's
crest title card as the thumbnail, and print the new video id.

The thumbnail is *found*, not assumed: the broadcast opens with a City of Troy
bumper and cuts to the crest card only afterwards, so the old fixed `-ss 2` grab
captured the wrong graphic whenever that cut came late. `thumbnails.py` scans the
opening for the card and typesets one from the meeting record when none airs —
pass `--date`/`--name` so it can (Workshops never show a card).

Reuses the captions uploader's OAuth (YT_CLIENT_ID/SECRET/REFRESH_TOKEN in
tsd-secrets.env — youtube.force-ssl covers videos.insert and thumbnails.set).
Quota: videos.insert = 1600 units each; thumbnails.set = 50.

Usage:
  python3 transcription/upload_videos.py "PATH.mp4" --title "…" \
      --date 2026-07-22 --name "Regular Meeting of the Board of Education 1 00 PM"
"""
from __future__ import annotations
import argparse, json, os, subprocess, sys, tempfile, urllib.parse, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import tsd_secrets
import thumbnails

CHUNK = 64 * 1024 * 1024


def access_token():
    d = urllib.parse.urlencode({"client_id": tsd_secrets.require("YT_CLIENT_ID"),
        "client_secret": tsd_secrets.require("YT_CLIENT_SECRET"),
        "refresh_token": tsd_secrets.require("YT_REFRESH_TOKEN"),
        "grant_type": "refresh_token"}).encode()
    return json.load(urllib.request.urlopen(
        urllib.request.Request("https://oauth2.googleapis.com/token", d)))["access_token"]


def upload(path: Path, title: str, privacy: str, description: str) -> str:
    tok = access_token()
    size = path.stat().st_size
    meta = json.dumps({"snippet": {"title": title, "description": description,
                                   "categoryId": "25"},
                       "status": {"privacyStatus": privacy,
                                  "selfDeclaredMadeForKids": False}}).encode()
    req = urllib.request.Request(
        "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
        data=meta, method="POST",
        headers={"authorization": f"Bearer {tok}", "content-type": "application/json",
                 "x-upload-content-length": str(size), "x-upload-content-type": "video/mp4"})
    with urllib.request.urlopen(req) as r:
        session = r.headers["location"]
    sent = 0
    with open(path, "rb") as f:
        while sent < size:
            chunk = f.read(CHUNK)
            end = sent + len(chunk) - 1
            put = urllib.request.Request(session, data=chunk, method="PUT",
                headers={"authorization": f"Bearer {tok}",
                         "content-range": f"bytes {sent}-{end}/{size}"})
            try:
                with urllib.request.urlopen(put, timeout=600) as r:
                    body = r.read()
                    print(f"  upload complete ({size/1e9:.2f} GB)", flush=True)
                    return json.loads(body)["id"]
            except urllib.error.HTTPError as e:
                if e.code != 308:                      # 308 = chunk accepted, continue
                    raise SystemExit(f"upload failed {e.code}: {e.read().decode()[:300]}")
            sent += len(chunk)
            print(f"  {100*sent//size}%", flush=True)
    raise SystemExit("upload ended without a video id")


def set_thumbnail(vid: str, video_path: Path, date: str = "", name: str = ""):
    """Give the video the district's crest card -- found in the stream, else typeset.

    A fixed `-ss 2` grab used to be enough, but the city broadcast opens with a
    City of Troy bumper and only then cuts to the card, so the naive grab put an
    undated city graphic on 35 of 57 board videos. See thumbnails.py.
    """
    img, at = thumbnails.card_from_file(video_path)
    if img is None:
        if not date:
            raise SystemExit("no crest card in the stream and no --date to typeset one")
        img = thumbnails.synthesize(date, thumbnails.parse_time(name),
                                    thumbnails.kind_of(name))
        print("  no card in stream -> typeset one", flush=True)
    else:
        print(f"  crest card found at {at}s", flush=True)
    if date:
        iou = thumbnails.verify_date(img, date)
        print(f"  date check IoU={iou:.3f}"
              f"{'' if iou > 0.60 else '  <-- VERIFY BY EYE'}", flush=True)
    thumbnails.set_thumbnail(vid, img)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("--title", required=True)
    ap.add_argument("--date", default="", help="YYYY-MM-DD; lets the thumbnail be "
                    "typeset (and date-checked) when the stream shows no card")
    ap.add_argument("--name", default="", help="meeting name as in D1, e.g. "
                    '"Board of Education Workshop 6 00 PM" -- carries the start time')
    ap.add_argument("--privacy", default="public", choices=["public", "unlisted", "private"])
    ap.add_argument("--description", default="Troy School District Board of Education public meeting. "
                    "Searchable transcript: https://tsd-boarddocs.karpowitsch.org")
    a = ap.parse_args()
    p = Path(a.video)
    print(f"uploading {p.name} ({p.stat().st_size/1e9:.2f} GB) as {a.privacy} …", flush=True)
    vid = upload(p, a.title, a.privacy, a.description)
    set_thumbnail(vid, p, a.date, a.name)
    print(f"DONE https://youtu.be/{vid}")


if __name__ == "__main__":
    main()
