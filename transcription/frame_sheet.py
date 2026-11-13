#!/usr/bin/env python3
"""Labelled contact sheets of video frames, for checking who is speaking (name plates).

    python3 transcription/frame_sheet.py requests.json OUT_PREFIX [--cols 3] [--per 9]

requests.json: [{"video": "<youtube id>", "t": <seconds>, "label": "2025-03-04 B 'Audra Melton' 0:41:12"}, ...]
Each video's stream URL is resolved once (yt-dlp -g, 720p or less) and every frame is pulled with a
seeking ffmpeg read, so nothing is downloaded whole. Sheets are written as OUT_PREFIX_NN.jpg with
the label stamped on each tile. Needs Pillow (the system python3 has it; scratch/venv-voice does not).
"""
from __future__ import annotations
import json, subprocess, sys, tempfile
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


def stream_url(vid: str) -> str:
    return subprocess.run(["yt-dlp", "-q", "--no-warnings", "-g", "-f", "b[height<=720]/best[height<=720]",
                           f"https://youtu.be/{vid}"], capture_output=True, text=True, check=True).stdout.split()[0]


def main() -> int:
    req = json.load(open(sys.argv[1])); prefix = sys.argv[2]
    cols = int(sys.argv[sys.argv.index("--cols") + 1]) if "--cols" in sys.argv else 3
    per = int(sys.argv[sys.argv.index("--per") + 1]) if "--per" in sys.argv else 9
    W, H = 480, 270
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 15)
    except OSError:
        font = ImageFont.load_default()
    urls, tiles = {}, []
    tmp = Path(tempfile.mkdtemp())
    for i, r in enumerate(req):
        if r["video"] not in urls:
            urls[r["video"]] = stream_url(r["video"])
        f = tmp / f"{i}.jpg"
        subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-ss", str(r["t"]), "-i", urls[r["video"]],
                        "-frames:v", "1", "-vf", f"scale={W}:{H}", "-y", str(f)], check=False)
        img = Image.open(f).convert("RGB") if f.exists() else Image.new("RGB", (W, H), "gray")
        d = ImageDraw.Draw(img)
        d.rectangle([0, 0, W, 20], fill="black")
        d.text((4, 2), r["label"][:62], fill="yellow", font=font)
        tiles.append(img)
    sheets = []
    for s in range(0, len(tiles), per):
        chunk = tiles[s:s + per]; rows = (len(chunk) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * W + (cols - 1) * 4, rows * H + (rows - 1) * 4), "white")
        for j, t in enumerate(chunk):
            sheet.paste(t, ((j % cols) * (W + 4), (j // cols) * (H + 4)))
        out = f"{prefix}_{s // per:02d}.jpg"
        sheet.save(out, quality=82); sheets.append(out)
    print("\n".join(sheets))
    return 0


if __name__ == "__main__":
    sys.exit(main())
