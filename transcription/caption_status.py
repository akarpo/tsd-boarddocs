#!/usr/bin/env python3
"""Is each meeting's YouTube caption track as new as its local SRT? Read-only.

    python3 transcription/caption_status.py 2026-02-03 2026-04-07 2026-08-18
    python3 transcription/caption_status.py --all          # every meeting in upload_captions.MEETINGS

For each date: the "English (speaker-attributed)" track's lastUpdated on YouTube against the
modification time of transcripts/<title>.srt. A track older than its SRT is STALE: push it with
`python3 transcription/upload_captions.py --only DATE` (450 units). Costs 50 quota units per date
(captions.list); after the daily quota is spent every call 403s until midnight Pacific (3 a.m. ET),
and so does this check. Written after 2026-11-14, when three pushes were left for the next session.
"""
from __future__ import annotations
import datetime as dt, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import upload_captions as uc  # noqa: E402


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dates = [d for d, _, _ in uc.MEETINGS] if "--all" in sys.argv else args
    if not dates:
        print(__doc__); return 2
    rows = {d: (k, v) for d, k, v in uc.MEETINGS}
    tok = uc.access_token()
    stale = 0
    for d in dates:
        if d not in rows:
            print(f"{d}  not in upload_captions.MEETINGS"); stale += 1; continue
        kind, vid = rows[d]
        srt = uc.SRT_DIR / f"{uc.TITLE_BY_VID.get(vid, f'{d} - Troy (MI) School District - Board of Education - {kind} Meeting')}.srt"
        local = dt.datetime.fromtimestamp(srt.stat().st_mtime, dt.timezone.utc) if srt.exists() else None
        items = uc.http(f"https://www.googleapis.com/youtube/v3/captions?part=snippet&videoId={vid}",
                        headers={"authorization": f"Bearer {tok}"}).get("items", [])
        mine = [i["snippet"] for i in items if i["snippet"].get("trackKind") != "asr" and i["snippet"].get("name") == uc.TRACK_NAME]
        if not mine:
            print(f"{d}  {vid}  NO TRACK"); stale += 1; continue
        yt = dt.datetime.fromisoformat(mine[0]["lastUpdated"].replace("Z", "+00:00"))
        if local is None:
            state = "no local SRT"
        elif yt >= local:
            state = "current"
        else:
            state = "STALE"; stale += 1
        print(f"{d}  {vid}  YouTube {yt:%Y-%m-%d %H:%M}Z  local {local:%Y-%m-%d %H:%M}Z  {state}" if local
              else f"{d}  {vid}  YouTube {yt:%Y-%m-%d %H:%M}Z  {state}")
    print(f"{len(dates) - stale}/{len(dates)} current")
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main())
