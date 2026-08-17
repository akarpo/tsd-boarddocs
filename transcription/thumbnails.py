#!/usr/bin/env python3
"""Give every board video on the channel the district's crest title card.

The city cable broadcast opens with a City of Troy bumper ("City of Tomorrow,
Today / 1955") and only then cuts to the TSD crest card. `upload_videos.py` used
to grab the thumbnail at a fixed `-ss 2`, which lands on the bumper whenever the
cut comes later -- that is how 35 of 57 board videos ended up carrying an
undated, byte-identical city graphic instead of their own card.

So the card is *found*, not assumed, and only typeset when it truly never airs:

  1. SCAN the opening for the crest card (normalised-grayscale correlation against
     `assets/tsd_card_base.jpg`) and lift that frame at full resolution. This is
     the district's own artwork, so the date, time and address are the ones that
     were broadcast. Every Regular meeting that predates Nov 2024 has one.
  2. TYPESET a card from the base when the stream never shows one -- every
     Workshop and the Retreat begin cold on meeting footage.

Typesetting only relays out the header/date/time lines: the ground beneath a line
is rebuilt by interpolating the clean gap rows above and below it, then the text
is composited in the card's own face (Arial Black 50, matched at IoU 0.90; it
reproduces the card's "7:00pm MEETING" line at exactly its measured 469x47 px).
Generative fill is the wrong tool here -- it repaints the whole canvas, drifts the
palette and aspect ratio, and cannot know that 2026-07-22 started at 1:00 PM.

Meeting name and start time come from the BoardDocs folder names in D1, never
from a default: the Regular meetings are not all at 7:00pm (2023-06-13 is 7:30 PM,
2023-07-18 is 9:30 AM, 2023-08-15 is 6:00 PM).

Usage:
  python3 transcription/thumbnails.py --audit
  python3 transcription/thumbnails.py --build 2026-07-22 --time 1:00pm --kind regular -o card.jpg
  python3 transcription/thumbnails.py --for-video VIDEO_ID --date 2026-07-22 \
      --name "Regular Meeting of the Board of Education 1 00 PM" [--set]

Quota: thumbnails.set = 50 units per video. Scope youtube.force-ssl, via
`tsd_secrets` (YT_CLIENT_ID/SECRET/REFRESH_TOKEN); if the refresh token has
expired, run `transcription/reauth_youtube.py`.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tsd_secrets  # noqa: E402

HERE = Path(__file__).resolve().parent
BASE_CARD = HERE / "assets" / "tsd_card_base.jpg"
FACE = "/System/Library/Fonts/Supplemental/Arial Black.ttf"
CHANNEL = "UCl7FMppdq35uQdiSPZz1GpA"

# measured off the authentic card: (y0, y1, x_left, font_px)
LINES = {"hdr1": (146, 182, 620, 46), "hdr2": (206, 242, 620, 49),
         "time": (443, 489, 642, 50), "date": (503, 549, 643, 50)}
# Left bound for any repaint: just right of the vertical rule at x=610-612, so the
# crest and the rule are never touched. Every text line starts at x>=620.
TEXT_X0 = 616
MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
          "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
HEADERS = {"regular": "REGULAR MEETING", "workshop": "WORKSHOP MEETING",
           "retreat": "WINTER RETREAT", "organizational": "ORGANIZATIONAL MEETING"}
MATCH = 0.80            # correlation above which a frame *is* the crest card


# ---------------------------------------------------------------- typesetting

def _rebuild_bg(arr: np.ndarray, y0: int, y1: int, pad: int = 9,
                x0: int = TEXT_X0) -> None:
    """Rebuild the ground under one text row, *right of the rule only*.

    Repainting the full width smears the crest: the seal runs to y=435 with its
    drop shadow below that, so the `time` band (y=443-489) and the `hdr2` band
    (y=206-242) both overlap artwork on the left half. Clipping at `x0` keeps the
    interpolation inside the text column, where the ground really is flat.
    """
    top = arr[y0 - pad - 4:y0 - pad, x0:].mean(axis=0)
    bot = arr[y1 + pad:y1 + pad + 4, x0:].mean(axis=0)
    n = y1 - y0 + 1
    for i in range(n):
        t = (i + 1) / (n + 1)
        arr[y0 + i, x0:] = top * (1 - t) + bot * t


def _draw_line(img: Image.Image, key: str, text: str) -> None:
    """Relay one line. An empty `text` clears the row and leaves it blank."""
    y0, y1, x, size = LINES[key]
    a = np.asarray(img, dtype=np.float32)
    _rebuild_bg(a, y0, y1)
    img.paste(Image.fromarray(a.round().clip(0, 255).astype("uint8")))
    if not text:
        return
    m = Image.new("L", img.size, 0)
    ImageDraw.Draw(m).text((x, y0), text, font=ImageFont.truetype(FACE, size),
                           fill=255, anchor="la")
    bb = m.getbbox()
    if bb:                                   # seat the glyphs on the measured band
        m = m.transform(img.size, Image.AFFINE, (1, 0, bb[0] - x, 0, 1, bb[1] - y0))
    img.paste(Image.new("RGB", img.size, (0, 0, 0)), mask=m)


def synthesize(date: str, time_txt: str | None, kind: str = "regular",
               header: str | None = None) -> Image.Image:
    """Retypeset the base card for one meeting.

    `time_txt=None` clears the time row rather than asserting an hour — used for
    the handful of meetings with no BoardDocs record to read a start time from.
    """
    y, mo, d = (int(v) for v in date.split("-"))
    img = Image.open(BASE_CARD).convert("RGB")
    _draw_line(img, "date", f"{MONTHS[mo - 1]} {d}, {y}")
    _draw_line(img, "time", f"{time_txt} MEETING" if time_txt else "")
    head = header or HEADERS.get(kind, HEADERS["regular"])
    if head != "REGULAR MEETING":             # already what the base card reads
        _draw_line(img, "hdr2", head)
    return img


# ------------------------------------------------------------------ detection

def _feat(im: Image.Image) -> np.ndarray:
    a = np.asarray(im.convert("L").resize((64, 36)), dtype=np.float32)
    return (a - a.mean()) / (a.std() + 1e-6)


def card_from_stream(vid: str, window: int = 90, workdir: Path | None = None):
    """Return (PIL image, seconds) for the crest card as aired, or (None, None)."""
    ref = _feat(Image.open(BASE_CARD))
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(workdir or td)
        tmp.mkdir(parents=True, exist_ok=True)
        subprocess.run(["yt-dlp", "-q", "--no-warnings", "-f", "worst[height<=360]/worst",
                        "--download-sections", f"*0-{window}", "--force-keyframes-at-cuts",
                        "-o", str(tmp / "probe.%(ext)s"),
                        f"https://www.youtube.com/watch?v={vid}"],
                       check=False, capture_output=True)
        probe = next(iter(tmp.glob("probe.*")), None)
        if probe is None:
            return None, None
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(probe),
                        "-vf", "fps=2", "-q:v", "5", str(tmp / "f_%04d.jpg")], check=False)
        best, at = -9.0, None
        for f in sorted(tmp.glob("f_*.jpg")):
            c = float((_feat(Image.open(f)) * ref).mean())
            if c > best:
                best, at = c, (int(f.stem.split("_")[1]) - 1) / 2.0
        if best < MATCH or at is None:
            return None, None
        # re-pull just that moment at full resolution
        subprocess.run(["yt-dlp", "-q", "--no-warnings", "-f", "bestvideo[height<=1080]/best",
                        "--download-sections", f"*{max(0, at - 2)}-{at + 3}",
                        "--force-keyframes-at-cuts", "-o", str(tmp / "hi.%(ext)s"),
                        f"https://www.youtube.com/watch?v={vid}"],
                       check=False, capture_output=True)
        hi = next(iter(tmp.glob("hi.*")), None)
        if hi is None:
            return None, None
        out = tmp / "card.jpg"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "2", "-i", str(hi),
                        "-frames:v", "1", "-vf", "scale=1280:720", "-q:v", "2", str(out)],
                       check=False)
        if not out.exists():
            return None, None
        img = Image.open(out).convert("RGB")
        img.load()
        return img, at


def card_from_file(path: Path, window: int = 90):
    """Same scan, against a local .mp4 -- used while uploading a TelVue capture."""
    ref = _feat(Image.open(BASE_CARD))
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-t", str(window),
                        "-i", str(path), "-vf", "fps=2,scale=640:-2", "-q:v", "5",
                        str(tmp / "f_%04d.jpg")], check=False)
        best, at = -9.0, None
        for f in sorted(tmp.glob("f_*.jpg")):
            c = float((_feat(Image.open(f)) * ref).mean())
            if c > best:
                best, at = c, (int(f.stem.split("_")[1]) - 1) / 2.0
        if best < MATCH or at is None:
            return None, None
        out = tmp / "card.jpg"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(at),
                        "-i", str(path), "-frames:v", "1", "-vf", "scale=1280:720",
                        "-q:v", "2", str(out)], check=False)
        if not out.exists():
            return None, None
        img = Image.open(out).convert("RGB")
        img.load()
        return img, at


def verify_date(img: Image.Image, date: str) -> float:
    """IoU of the card's date line against the date it ought to print (0..1)."""
    y, mo, d = (int(v) for v in date.split("-"))
    txt = f"{MONTHS[mo - 1]} {d}, {y}"
    a = np.asarray(img.convert("RGB").resize((1280, 720)), dtype=np.int16)
    best = 0.0
    for x0 in (600, 620, 635, 660):                  # layout drifts across card eras
        m = (a[:, x0:].sum(axis=2) < 250)
        rows, run, bands = m.sum(axis=1), None, []
        for yy, v in enumerate(rows):
            if v > 0 and run is None:
                run = yy
            elif v == 0 and run is not None:
                if 20 < yy - run < 75:
                    bands.append((run, yy - 1))
                run = None
        for y0b, y1b in bands:
            strip = m[y0b:y1b + 1]
            cols = np.where(strip.any(axis=0))[0]
            if not len(cols):
                continue
            g = strip[:, cols.min():cols.max() + 1]
            for size in range(40, 60):
                im = Image.new("L", (1100, 180), 0)
                ImageDraw.Draw(im).text((20, 20), txt,
                                        font=ImageFont.truetype(FACE, size), fill=255)
                t = np.asarray(im) > 128
                r_, c_ = np.where(t.any(axis=1))[0], np.where(t.any(axis=0))[0]
                t = t[r_.min():r_.max() + 1, c_.min():c_.max() + 1]
                if abs(t.shape[0] - g.shape[0]) > 5 or abs(t.shape[1] - g.shape[1]) > 25:
                    continue
                H, W = max(t.shape[0], g.shape[0]), max(t.shape[1], g.shape[1])
                A = np.zeros((H, W), bool); B = np.zeros((H, W), bool)
                A[:g.shape[0], :g.shape[1]] = g; B[:t.shape[0], :t.shape[1]] = t
                best = max(best, (A & B).sum() / max(1, (A | B).sum()))
    return best


# ------------------------------------------------------------- meeting record

def parse_time(meeting: str) -> str:
    """'Board of Education Workshop 6_15 PM' -> '6:15pm'."""
    m = re.search(r"(\d{1,2})[_: ](\d{2})\s*([AP])\.?\s*\.?M", meeting, re.I)
    return f"{int(m.group(1))}:{m.group(2)}{m.group(3).lower()}m" if m else "7:00pm"


def kind_of(name: str) -> str:
    n = name.lower()
    return "workshop" if "workshop" in n else ("retreat" if "retreat" in n else "regular")


# ------------------------------------------------------------------- YouTube

def access_token() -> str:
    d = urllib.parse.urlencode({
        "client_id": tsd_secrets.require("YT_CLIENT_ID"),
        "client_secret": tsd_secrets.require("YT_CLIENT_SECRET"),
        "refresh_token": tsd_secrets.require("YT_REFRESH_TOKEN"),
        "grant_type": "refresh_token"}).encode()
    try:
        return json.load(urllib.request.urlopen(urllib.request.Request(
            "https://oauth2.googleapis.com/token", d)))["access_token"]
    except urllib.error.HTTPError as e:
        raise SystemExit(f"OAuth failed ({e.code}): {e.read().decode()[:200]}\n"
                         "  run: python3 transcription/reauth_youtube.py")


def set_thumbnail(vid: str, img: Image.Image) -> None:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=95, subsampling=0)
    req = urllib.request.Request(
        f"https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId={vid}",
        data=buf.getvalue(), method="POST",
        headers={"authorization": f"Bearer {access_token()}",
                 "content-type": "image/jpeg"})
    urllib.request.urlopen(req)


def audit(channel: str = CHANNEL) -> list[dict]:
    """Classify every board video's live thumbnail: crest card, city bumper, or frame."""
    out = subprocess.run(["yt-dlp", "--no-warnings", "--flat-playlist", "--skip-download",
                          "-J", f"https://www.youtube.com/channel/{channel}/videos"],
                         capture_output=True, text=True, check=True).stdout
    ref = _feat(Image.open(BASE_CARD))
    rows = []
    for e in json.loads(out).get("entries", []):
        title = e.get("title") or ""
        if "School District" not in title and "Board of Education" not in title:
            continue
        try:
            b = urllib.request.urlopen(urllib.request.Request(
                f"https://i.ytimg.com/vi/{e['id']}/maxresdefault.jpg",
                headers={"user-agent": "Mozilla/5.0"}), timeout=25).read()
            im = Image.open(io.BytesIO(b)).convert("RGB")
        except Exception:
            continue
        c = float((_feat(im) * ref).mean())
        m = re.match(r"(\d{4}-\d{2}-\d{2})", title)
        rows.append({"id": e["id"], "date": m.group(1) if m else "?", "title": title,
                     "corr": round(c, 3), "ok": c > 0.55})
    return sorted(rows, key=lambda r: r["date"])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--audit", action="store_true", help="classify the channel's thumbnails")
    ap.add_argument("--build", metavar="YYYY-MM-DD", help="typeset a card for this date")
    ap.add_argument("--for-video", metavar="ID", help="scan this video, else typeset")
    ap.add_argument("--date"); ap.add_argument("--name", default="")
    ap.add_argument("--time"); ap.add_argument("--kind", choices=list(HEADERS))
    ap.add_argument("--set", action="store_true", help="upload the result to YouTube")
    ap.add_argument("-o", "--out")
    a = ap.parse_args()

    if a.audit:
        rows = audit()
        for r in rows:
            print(f"{'  ok ' if r['ok'] else ' WRONG'} {r['date']}  {r['id']}  "
                  f"corr={r['corr']:>6}  {r['title'][:58]}")
        print(f"\ncrest card: {sum(r['ok'] for r in rows)} / {len(rows)}")
        return

    date = a.date or a.build
    if not date:
        ap.error("need --audit, --build DATE, or --for-video ID --date DATE")
    kind = a.kind or kind_of(a.name)
    time_txt = a.time or parse_time(a.name)

    img, src = None, "typeset"
    if a.for_video:
        img, at = card_from_stream(a.for_video)
        if img is not None:
            src = f"stream@{at}s"
    if img is None:
        img = synthesize(date, time_txt, kind)

    iou = verify_date(img, date)
    print(f"{date}  {kind:<9} {time_txt:<8} {src:<14} date-check IoU={iou:.3f}"
          f"{'' if iou > 0.60 else '   <-- VERIFY BY EYE'}")
    if a.out:
        img.save(a.out, quality=95, subsampling=0)
        print(f"wrote {a.out} ({img.size[0]}x{img.size[1]})")
    if a.set:
        if not a.for_video:
            ap.error("--set needs --for-video ID")
        set_thumbnail(a.for_video, img)
        print(f"thumbnail set on https://youtu.be/{a.for_video}")


if __name__ == "__main__":
    main()
