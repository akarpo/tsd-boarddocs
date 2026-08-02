#!/usr/bin/env python3
"""Transcribe a Troy SD board-meeting recording with AssemblyAI, boosted by the
district proper-noun vocabulary, then (optionally) attribute real speaker names.

Pipeline (each stage skippable / resumable):
  1. ffmpeg  → 16 kHz mono 64 kbps MP3 (a 1.4 GB TelVue MP4 becomes ~40 MB)
  2. upload  → POST /v2/upload
  3. create  → POST /v2/transcript   speech_models: ["universal-3-5-pro", "universal-2"]
                                     keyterms_prompt: ≤1,000 phrases (≤6 words each)
                                     speaker_labels: true   (anonymous A/B/C… diarization)
  4. poll    → GET  /v2/transcript/{id}  until completed
  5. attribute (with --speakers) → POST llm-gateway /v1/understanding
                                     speaker_identification, speaker_type "name",
                                     ≤10 candidate names per request; skipped when the
                                     spec already carries a resolved "mapping"
  6. write   → <base>.transcript.json / .txt / .srt (+ .attributed.txt when named)

The API key is read via tsd_secrets: env ASSEMBLYAI_API_KEY, else the
tsd-secrets.env file outside the repo. See docs/TRANSCRIPTION.md for the full
methodology, costs (~$0.40 per 85-min meeting) and verification checklist.

Usage
  python3 transcription/transcribe_meeting.py MEETING.mp4 --date 2026-07-22 \
      --speakers transcription/examples/2026-07-22/speakers.json
  # re-run attribution only, against an already-paid-for transcript:
  python3 transcription/transcribe_meeting.py --transcript-id ID --date 2026-07-22 \
      --speakers speakers.json --outdir ~/Downloads
"""
from __future__ import annotations
import argparse, json, subprocess, sys, tempfile, time, urllib.error, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tsd_secrets

BASE = "https://api.assemblyai.com/v2"
UNDERSTAND = "https://llm-gateway.assemblyai.com/v1/understanding"
AUDIO_EXTS = {".mp3", ".m4a", ".wav", ".aac", ".flac", ".ogg"}


def call(url, key, data=None, headers=None):
    h = {"authorization": key}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"HTTP {e.code} from {url}:\n{e.read().decode('utf-8', 'replace')[:800]}")


def hms(ms, srt=False):
    s, ms = divmod(int(ms), 1000)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}" if srt else f"{h:d}:{m:02d}:{s:02d}"


def transcode(media: Path) -> Path:
    out = Path(tempfile.mkdtemp()) / (media.stem + ".mp3")
    print(f"ffmpeg: {media.name} -> 16k mono mp3 ...", flush=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(media),
                    "-vn", "-ac", "1", "-ar", "16000", "-b:a", "64k", str(out)], check=True)
    print(f"  {out.stat().st_size/1e6:.0f} MB", flush=True)
    return out


def transcribe(media: Path, keyterms: list[str], key: str) -> dict:
    audio = media if media.suffix.lower() in AUDIO_EXTS else transcode(media)
    print("uploading ...", flush=True)
    up = call(f"{BASE}/upload", key, data=audio.read_bytes(),
              headers={"content-type": "application/octet-stream"})
    cfg = {"audio_url": up["upload_url"],
           "speech_models": ["universal-3-5-pro", "universal-2"],
           "keyterms_prompt": keyterms,
           "speaker_labels": True,
           "language_code": "en_us"}
    t = call(f"{BASE}/transcript", key, data=json.dumps(cfg).encode(),
             headers={"content-type": "application/json"})
    print("transcript id:", t["id"], flush=True)
    while True:
        time.sleep(15)
        r = call(f"{BASE}/transcript/{t['id']}", key)
        print("  status:", r["status"], flush=True)
        if r["status"] == "completed":
            return r
        if r["status"] == "error":
            raise SystemExit("transcription error: " + str(r.get("error")))


def identify(tid: str, spec: dict, key: str) -> dict:
    """Native speaker identification (≤10 names). Returns {letter: name}."""
    speakers = spec.get("speakers") or []
    if len(speakers) > 10:
        raise SystemExit(f"speakers.json lists {len(speakers)} names; the API caps at 10 per request")
    body = {"transcript_id": tid,
            "speech_understanding": {"request": {"speaker_identification": {
                "speaker_type": "name", "speakers": speakers}}}}
    resp = call(UNDERSTAND, key, data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json"})
    si = (resp.get("speech_understanding") or {}).get("response", {}).get("speaker_identification", {})
    print("identification status:", si.get("status"), "mapping:", si.get("mapping"), flush=True)
    return si.get("mapping") or {}


def namer(mapping: dict, spec: dict):
    """Compose API mapping + manual overrides + time-based cluster splits.

    Diarization is imperfect (one voice can split into two clusters, a remote
    caller and a podium speaker can merge into one) and the identifier can
    guess wrong — see docs/TRANSCRIPTION.md. `overrides` pins letter→name;
    `splits` assigns one cluster different names before/after a timestamp.
    """
    mapping = dict(mapping)
    mapping.update(spec.get("overrides") or {})
    splits = {s["cluster"]: s for s in spec.get("splits") or []}

    def who(u):
        sp, st = u["speaker"], u["start"]
        if sp in splits:
            s = splits[sp]
            return s["before"] if st < s["at_ms"] else s["after"]
        n = mapping.get(sp, sp)
        return n if n != sp else f"Speaker {sp}"
    return who


def write_outputs(r: dict, outdir: Path, base: str, who=None, header_notes=()):
    utts = r.get("utterances") or []
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / f"{base}.transcript.json").write_text(json.dumps(r, indent=1), encoding="utf-8")

    label = who or (lambda u: f"Speaker {u['speaker']}")
    hdr = [f"# {base}",
           f"# AssemblyAI {'+'.join(r.get('speech_models') or [])} · "
           f"keyterms_prompt: {len(r.get('keyterms_prompt') or [])} terms · "
           f"duration {hms((r.get('audio_duration') or 0)*1000)} · "
           f"diarized clusters: {len({u['speaker'] for u in utts})}"]
    hdr += [f"# {n}" for n in header_notes] + [""]
    txt = hdr + [f"[{hms(u['start'])}] {label(u)}: {u['text'].strip()}" for u in utts]
    suffix = ".transcript.attributed.txt" if who else ".transcript.txt"
    (outdir / f"{base}{suffix}").write_text("\n".join(txt) + "\n", encoding="utf-8")

    srt = [f"{i}\n{hms(u['start'],1)} --> {hms(u['end'],1)}\n[{label(u)}] {u['text'].strip()}\n"
           for i, u in enumerate(utts, 1)]
    (outdir / f"{base}.srt").write_text("\n".join(srt), encoding="utf-8")
    print(f"wrote {base}{suffix} / .srt / .transcript.json in {outdir}", flush=True)


def main():
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("media", nargs="?", help="video/audio file (omit with --transcript-id)")
    ap.add_argument("--date", help="meeting date YYYY-MM-DD, used in output names")
    ap.add_argument("--keyterms", default=str(here / "keyterms" / "TSD_keyterms_2025-2026.json"),
                    help="JSON array of keyterms (≤1,000 × ≤6 words)")
    ap.add_argument("--speakers", help="speakers.json → run name attribution "
                                       "(see examples/2026-07-22/speakers.json)")
    ap.add_argument("--transcript-id", help="reuse a completed transcript (skip stages 1-4)")
    ap.add_argument("--outdir", help="output dir (default: alongside the media file)")
    a = ap.parse_args()
    if not a.media and not a.transcript_id:
        ap.error("give a media file, or --transcript-id to reuse a completed transcript")

    key = tsd_secrets.require("ASSEMBLYAI_API_KEY")
    if a.transcript_id:
        r = call(f"{BASE}/transcript/{a.transcript_id}", key)
        if r.get("status") != "completed":
            raise SystemExit(f"transcript {a.transcript_id} status: {r.get('status')}")
    else:
        keyterms = json.load(open(a.keyterms))
        print(f"{len(keyterms)} keyterms loaded", flush=True)
        r = transcribe(Path(a.media), keyterms, key)

    date = a.date or (Path(a.media).stem if a.media else r["id"][:8])
    base = f"Troy School Board Meeting - {date}"
    outdir = Path(a.outdir) if a.outdir else (Path(a.media).parent if a.media else Path.cwd())

    who, notes = None, []
    if a.speakers:
        spec = json.load(open(a.speakers))
        if spec.get("mapping"):
            # A verified spec (like the committed examples) carries the resolved mapping —
            # reuse it: reproducible, offline, and no repeat identification charge.
            mapping = spec["mapping"]
            print("using resolved mapping from speakers spec (identification call skipped)", flush=True)
        else:
            try:
                mapping = identify(r["id"], spec, key)
            except SystemExit as e:
                print(f"identification failed ({e}); continuing with overrides/splits only", flush=True)
                mapping = {}
        who = namer(mapping, spec)
        notes = spec.get("notes") or []
        # Persist the resolved spec so upload_transcript.py (and re-runs) share
        # exactly this attribution without another identification call.
        resolved = {**spec, "mapping": mapping}
        outdir.mkdir(parents=True, exist_ok=True)
        (outdir / f"{base}.speakers.json").write_text(
            json.dumps(resolved, indent=1, ensure_ascii=False), encoding="utf-8")
    write_outputs(r, outdir, base, who, notes)


if __name__ == "__main__":
    main()
