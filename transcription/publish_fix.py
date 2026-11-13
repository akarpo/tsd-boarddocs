#!/usr/bin/env python3
"""Re-publish one meeting after its speaker spec changed (transcription/examples/<date>/speakers.json).

    python3 transcription/publish_fix.py DATE [--captions]

1. back up the workdir outputs (scratch/backups/<date>/)
2. re-attribute offline: transcribe_meeting.py --transcript-id <id from the workdir JSON>
3. audit_attribution.py (prints its flags; a DEGENERATE/UNATTRIBUTED flag stops here)
4. copy .srt / .attributed.txt into transcripts/ under the channel-title name upload_captions uses
5. upload_transcript.py to D1 (chapters untouched)
6. --captions: upload_captions.py --only DATE (450 quota units; ~20 a day fit)
"""
from __future__ import annotations
import json, shutil, subprocess, sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
W = REPO / "scratch" / "tsd-transcripts"
sys.path.insert(0, str(REPO / "transcription"))
import upload_captions as uc  # noqa: E402


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
    return r.returncode, (r.stdout + r.stderr)


def main() -> int:
    d = sys.argv[1]; caps = "--captions" in sys.argv
    base = W / f"Troy School Board Meeting - {d}"
    spec = REPO / "transcription" / "examples" / d / "speakers.json"
    tid = json.load(open(f"{base}.transcript.json")).get("id")
    bak = REPO / "scratch" / "backups" / d; bak.mkdir(parents=True, exist_ok=True)
    for ext in (".transcript.json", ".transcript.attributed.txt", ".srt"):
        if Path(f"{base}{ext}").exists() and not (bak / Path(f"{base}{ext}").name).exists():
            shutil.copy(f"{base}{ext}", bak)
    rc, out = run(["python3", "transcription/transcribe_meeting.py", "--transcript-id", tid, "--date", d,
                   "--speakers", str(spec), "--outdir", str(W)])
    if rc or "wrote" not in out:
        print(f"{d}: re-attribution FAILED\n{out[-600:]}"); return 1
    rc, out = run(["python3", "transcription/audit_attribution.py", f"{base}.transcript.json"])
    flags = [l for l in out.splitlines() if "DEGENERATE" in l or "UNATTRIBUTED" in l]
    print(f"{d}: audit {'FLAGS ' + '; '.join(flags) if flags else 'clean'}")
    if flags:
        return 1
    row = next(((dd, k, v) for dd, k, v in uc.MEETINGS if dd == d), None)
    if not row:
        print(f"{d}: not in upload_captions.MEETINGS"); return 1
    _, kind, vid = row
    title = uc.TITLE_BY_VID.get(vid, f"{d} - Troy (MI) School District - Board of Education - {kind} Meeting")
    shutil.copy(f"{base}.srt", REPO / "transcripts" / f"{title}.srt")
    shutil.copy(f"{base}.transcript.attributed.txt", REPO / "transcripts" / f"{title}.txt")
    rc, out = run(["npx", "wrangler", "d1", "execute", "tsd-boarddocs", "--remote", "--json", "--command",
                   f"SELECT meeting_name FROM recordings WHERE meeting_date='{d}'"])
    name = json.loads(out[out.index("["):])[0]["results"][0]["meeting_name"]
    rc, out = run(["python3", "transcription/upload_transcript.py", f"{base}.transcript.json", "--date", d,
                   "--name", name, "--youtube", vid, "--speakers", str(spec)])
    print(f"{d}: D1 {'loaded' if 'uploaded to D1' in out else 'FAILED ' + out[-300:]}")
    if caps:
        rc, out = run(["python3", "transcription/upload_captions.py", "--only", d])
        print(f"{d}: captions {[l for l in out.splitlines() if d in l][:1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
