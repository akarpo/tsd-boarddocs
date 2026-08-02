#!/bin/bash
# One-shot: YouTube upload of a board meeting -> transcript -> anchors -> D1 (site).
#   usage: run_meeting.sh DATE "MEETING NAME (as in D1 chunks)" YOUTUBE_ID [workdir]
#   e.g.:  transcription/run_meeting.sh 2026-02-03 "Board of Education Workshop 6 00 PM" SBV4mbIzKlk
# Idempotent: skips download/transcription when their outputs already exist in workdir.
set -euo pipefail
DATE="$1"; NAME="$2"; YT="$3"; WD="${4:-$HOME/Downloads/tsd-transcripts}"
HERE="$(cd "$(dirname "$0")" && pwd)"
BASE="Troy School Board Meeting - $DATE"
mkdir -p "$WD"

AUD="$WD/tsd_${DATE}.mp3"
if [ ! -s "$AUD" ]; then
  echo "[$DATE] downloading audio from youtu.be/$YT ..."
  yt-dlp -q -f bestaudio -x --audio-format mp3 \
    --postprocessor-args "ffmpeg:-ac 1 -ar 16000 -b:a 64k" \
    -o "$WD/tsd_${DATE}.%(ext)s" "https://youtu.be/$YT"
fi
ls -lh "$AUD"

if [ ! -s "$WD/$BASE.transcript.json" ]; then
  python3 "$HERE/transcribe_meeting.py" "$AUD" --date "$DATE" \
    --speakers "$HERE/speakers_2026.json" --outdir "$WD"
fi

python3 "$HERE/make_anchors.py" "$WD/$BASE.transcript.json" -o "$WD/anchors_${DATE}.json"
python3 "$HERE/upload_transcript.py" "$WD/$BASE.transcript.json" \
  --date "$DATE" --name "$NAME" --youtube "$YT" \
  --speakers "$WD/$BASE.speakers.json" --anchors "$WD/anchors_${DATE}.json"
echo "[$DATE] DONE"
