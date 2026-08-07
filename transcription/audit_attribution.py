#!/usr/bin/env python3
"""Audit the speaker attribution of a finished transcript before it goes on the site.

Diarization and the name identifier both fail in ways that still produce
plausible output (docs/TRANSCRIPTION.md, "trust, but verify"), so every meeting
gets checked against evidence the transcript itself cannot supply: the
attendance the board minutes record.

Reports per transcript — duration, cluster count, the resolved letter→name
mapping, and each speaker's share of the spoken words — and raises these flags:

  DEGENERATE     ≤3 diarized clusters (the mic chain collapsed the room)
  UNATTRIBUTED   >30% of words still on bare Speaker letters
  ABSENT         words attributed to someone the minutes record as absent
  MISSING        a trustee the minutes record as present who never speaks

ABSENT is the sharpest of the four: it is the one flag that says the identifier
put words in a specific person's mouth, and it is checkable against a source
outside the audio. Fix it with `overrides` in the speakers spec, then re-run
transcribe_meeting.py --transcript-id (offline, no new charge).

Usage
  python3 transcription/audit_attribution.py scratch/tsd-transcripts/*.transcript.json
  python3 transcription/audit_attribution.py T.json --absent "Karl Schmidt" "Nicole Wilson" \
      --expect "Vital Anne" "Emina Alic" "Gary Hauff" "Matt Haupt" "Nancy Philippart"
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path

DEGENERATE_CLUSTERS = 3
UNATTRIBUTED_PCT = 30.0


def hms(sec):
    s = int(sec or 0)
    return f"{s//3600:d}:{(s%3600)//60:02d}:{s%60:02d}"


def resolve(spec: dict):
    """letter → name, exactly as transcribe_meeting.namer composes it."""
    mapping = dict(spec.get("mapping") or {})
    mapping.update(spec.get("overrides") or {})
    splits = {s["cluster"]: s for s in spec.get("splits") or []}

    def who(u):
        sp, st = u["speaker"], u["start"]
        if sp in splits:
            s = splits[sp]
            return s["before"] if st < s["at_ms"] else s["after"]
        return mapping.get(sp, f"Speaker {sp}")
    return who, mapping


def audit(path: Path, absent: list[str], expect: list[str], samples: int):
    r = json.loads(path.read_text(encoding="utf-8"))
    utts = r.get("utterances") or []
    if not utts:
        print(f"{path.name}: NO UTTERANCES"); return 1

    spec_path = path.with_name(path.name.replace(".transcript.json", ".speakers.json"))
    spec = json.loads(spec_path.read_text(encoding="utf-8")) if spec_path.exists() else {}
    who, mapping = resolve(spec)

    words, lines, first = {}, {}, {}
    for u in utts:
        n = who(u)
        w = len(u["text"].split())
        words[n] = words.get(n, 0) + w
        lines[n] = lines.get(n, 0) + 1
        first.setdefault(n, u["start"])
    total = sum(words.values()) or 1
    clusters = {u["speaker"] for u in utts}
    unattr = sum(w for n, w in words.items() if n.startswith("Speaker "))

    print(f"\n=== {path.name}")
    print(f"    duration {hms(r.get('audio_duration'))} · {len(utts)} utterances · "
          f"{total:,} words · {len(clusters)} clusters · model {r.get('speech_model_used') or '?'}")
    print(f"    mapping: {mapping if mapping else '(none — identification produced nothing)'}")
    for n, w in sorted(words.items(), key=lambda kv: -kv[1]):
        print(f"      {w*100/total:5.1f}%  {w:6,}w  {lines[n]:4d} lines  @{hms(first[n]/1000)}  {n}")

    flags = []
    if len(clusters) <= DEGENERATE_CLUSTERS:
        flags.append(f"DEGENERATE: {len(clusters)} clusters — re-run with hi-fi stereo audio "
                     f"and --min-speakers 6 --max-speakers 25")
    if unattr * 100 / total > UNATTRIBUTED_PCT:
        flags.append(f"UNATTRIBUTED: {unattr*100/total:.1f}% of words on bare Speaker letters")
    for name in absent:
        if words.get(name):
            flags.append(f"ABSENT: {words[name]:,} words attributed to {name}, "
                         f"whom the minutes record as absent (first @{hms(first[name]/1000)})")
    for name in expect:
        if not words.get(name):
            flags.append(f"MISSING: {name} was present per the minutes but never speaks")

    for f in flags:
        print(f"    !! {f}")
    if not flags:
        print(f"    ok — {unattr*100/total:.1f}% unattributed")

    if samples:
        for n in sorted((n for n in words if n.startswith("Speaker ")), key=lambda n: -words[n]):
            ex = [u for u in utts if who(u) == n and len(u["text"].split()) > 12][:samples]
            if ex:
                print(f"    ── {n} ({words[n]:,}w) samples:")
                for u in ex:
                    text = re.sub(r"\s+", " ", u["text"])[:150]
                    print(f"       @{hms(u['start']/1000)} {text}")
    return len(flags)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("transcripts", nargs="+", type=Path)
    ap.add_argument("--absent", nargs="*", default=[],
                    help="names the minutes record as absent (any words = misattribution)")
    ap.add_argument("--expect", nargs="*", default=[],
                    help="names the minutes record as present (silence = a cluster went unnamed)")
    ap.add_argument("--samples", type=int, default=0,
                    help="show N long sample lines per unattributed cluster, to identify it by content")
    a = ap.parse_args()
    flags = sum(audit(p, a.absent, a.expect, a.samples) for p in a.transcripts)
    print(f"\n{flags} flag(s) across {len(a.transcripts)} transcript(s)")
    return 1 if flags else 0


if __name__ == "__main__":
    sys.exit(main())
