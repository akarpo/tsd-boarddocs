#!/bin/bash
# One-shot: YouTube upload of a board meeting -> transcript -> anchors -> D1 (site).
#   usage: run_meeting.sh DATE "MEETING NAME (as in D1 chunks)" YOUTUBE_ID [workdir]
#   e.g.:  transcription/run_meeting.sh 2026-02-03 "Board of Education Workshop 6 00 PM" SBV4mbIzKlk
# Idempotent: skips download/transcription when their outputs already exist in workdir.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DATE="$1"; NAME="$2"; YT="$3"; WD="${4:-$HERE/../scratch/tsd-transcripts}"
BASE="Troy School Board Meeting - $DATE"
mkdir -p "$WD"

AUD="$WD/tsd_${DATE}.mp3"
# Audio is only ever an input to transcription. Guarding the download on the mp3
# alone re-fetches it for a meeting that is already transcribed -- and a freshly
# uploaded video is still "processing" on YouTube's side, so that download fails
# and takes the anchor/D1 steps down with it. Skip when the transcript exists.
if [ ! -s "$WD/$BASE.transcript.json" ] && [ ! -s "$AUD" ]; then
  echo "[$DATE] downloading audio from youtu.be/$YT ..."
  yt-dlp -q -f bestaudio -x --audio-format mp3 \
    --postprocessor-args "ffmpeg:-ac 1 -ar 16000 -b:a 64k" \
    -o "$WD/tsd_${DATE}.%(ext)s" "https://youtu.be/$YT"
fi
[ -s "$AUD" ] && ls -lh "$AUD" || echo "[$DATE] no local mp3 (transcript already present)"

if [ ! -s "$WD/$BASE.transcript.json" ]; then
  # Grow the keyterm index from THIS meeting's packet before transcribing it.
  # The vocabulary that matters for one recording is the vocabulary in its own
  # agenda, and a first-time vendor ranks nowhere against fifteen years of
  # history -- the 2026-08-18 lease award went to a firm the recognizer had
  # never been shown, because the corpus-wide list had no reason to rank it.
  # Runs before transcription or it does nothing for this meeting.
  python3 "$HERE/../scripts/keyterms_index.py" --meeting "$DATE" --add || true
  python3 "$HERE/../scripts/keyterms_index.py" \
    --emit "$HERE/keyterms/TSD_keyterms_index.json" || true
  python3 "$HERE/transcribe_meeting.py" "$AUD" --date "$DATE" \
    --speakers "$HERE/speakers_2026.json" --outdir "$WD"
fi

AG="$WD/agenda_${DATE}.json"
curl -sG 'https://tsd-boarddocs.karpowitsch.org/api/meeting' \
  --data-urlencode "date=$DATE" --data-urlencode "name=$NAME" -o "$AG" || echo '{}' > "$AG"
python3 "$HERE/make_anchors.py" "$WD/$BASE.transcript.json" -o "$WD/anchors_${DATE}.json" --agenda "$AG"
python3 "$HERE/upload_transcript.py" "$WD/$BASE.transcript.json" \
  --date "$DATE" --name "$NAME" --youtube "$YT" \
  --speakers "$WD/$BASE.speakers.json" --anchors "$WD/anchors_${DATE}.json"
echo "[$DATE] DONE"
