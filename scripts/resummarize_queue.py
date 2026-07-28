#!/usr/bin/env python3
"""Wave-based queue for the re-summarization fan-out.

The first attempt launched all 35 agents at once and burned 40 points of the
5-hour window in 11 minutes -- more than a window holds. Measured cost was
~3.1 points per agent, so a window worked to 90% fits roughly 29 agents. The fix
is not a smaller total, it is releasing the queue in waves and checking the meter
between them, so the wall can never land mid-write.

State is derived, never stored: a batch is DONE when its output file exists and
passes validation. Nothing to drift, and a batch that fails validation returns to
pending automatically.

  python3 queue.py status            # what's done / failed / pending, with cost estimate
  python3 queue.py next [N]          # emit Workflow args for the next wave (default: fit the window)
  python3 queue.py plan              # full wave schedule against current headroom
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

DIR = Path(__file__).parent
MAN = json.loads((DIR / "fanout_manifest.json").read_text())
OUT = DIR / "fanout_out"

# Measured on wave 1 (2026-07-27): 8 agents, all completed, took the 5-hour window
# 0% -> 39%. The earlier 3.1 came from agents still in flight and was 57% low.
PTS_PER_AGENT = 4.9
RESERVE_PCT = 75.0        # stop releasing waves once the window passes this
WAVE = 8                  # AGENTS per wave, not batches -- a split budget book is 5-6


def pack(batches):
    """Group into waves by agent count, never two split budget books in one wave.

    Packing by batch count was the flaw in the first plan: a giant drags 4-6
    section agents behind a single batch id, so "6 batches" meant 6 agents in one
    wave and 11 in another. Pack by the thing that actually costs -- agents -- and
    keep the giants apart so no wave carries two long read-heavy tails.
    """
    split = MAN.get("split", {})
    cost = lambda b: len(split[b]["parts"]) + 1 if b in split else 1
    giants = [b for b in batches if b in split]
    normal = [b for b in batches if b not in split]
    waves = []
    # seed one wave per giant, then fill each to the agent target with normals
    for g in giants:
        waves.append([g])
    if not waves:
        waves.append([])
    i = 0
    for b in normal:
        placed = False
        for w in waves:
            if sum(cost(x) for x in w) + 1 <= WAVE:
                w.append(b)
                placed = True
                break
        if not placed:
            waves.append([b])
    return [w for w in waves if w]


def usage():
    try:
        s = json.loads((Path.home() / ".claude" / "usage_snapshot.json").read_text())
        rl = s["rate_limits"]
        return rl["five_hour"]["used_percentage"], rl["seven_day"]["used_percentage"]
    except Exception:
        return None, None


def validated():
    """Batches whose output exists and passes validation."""
    if not OUT.exists():
        return set()
    have = [p.stem for p in OUT.glob("*.json")]
    if not have:
        return set()
    r = subprocess.run([sys.executable, str(DIR / "validate_fanout.py"), *have],
                       capture_output=True, text=True)
    clean = set()
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].startswith("batch_") and parts[1] == "OK":
            clean.add(parts[0])
    return clean


def state():
    all_b = sorted(MAN["batches"])
    done = validated()
    written = {p.stem for p in OUT.glob("*.json")} if OUT.exists() else set()
    failed = sorted(written - done)
    pending = [b for b in all_b if b not in done and b not in failed]
    return all_b, sorted(done), failed, pending


def as_args(batches):
    """Split a batch list into the workflow's normal/giants argument shape."""
    split = MAN.get("split", {})
    normal = [b for b in batches if b not in split]
    giants = [{"batch": b, "key": split[b]["key"], "parts": split[b]["parts"]}
              for b in batches if b in split]
    return {"normal": normal, "giants": giants}


def agent_count(batches):
    split = MAN.get("split", {})
    return sum(len(split[b]["parts"]) + 1 if b in split else 1 for b in batches)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    all_b, done, failed, pending = state()
    p5, p7 = usage()

    if cmd == "status":
        print(f"batches: {len(all_b)}  done {len(done)}  failed {len(failed)}  pending {len(pending)}")
        if done:
            print(f"  done:    {' '.join(done)}")
        if failed:
            print(f"  requeue: {' '.join(failed)}")
        n = agent_count(pending + failed)
        print(f"\nremaining work: {len(pending)+len(failed)} batches = {n} agents "
              f"~= {n*PTS_PER_AGENT:.0f} points of a 5-hour window")
        if p5 is not None:
            room = max(0.0, RESERVE_PCT - p5)
            print(f"5h now {p5}%  headroom to {RESERVE_PCT:.0f}% = {room:.0f} points "
                  f"= {int(room / PTS_PER_AGENT)} agents")
            print(f"7d now {p7}%")
        return 0

    if cmd == "plan":
        q = failed + pending
        waves = pack(q)
        print(f"{len(q)} batches -> {len(waves)} waves of <= {WAVE} agents")
        for i, w in enumerate(waves, 1):
            n = agent_count(w)
            print(f"  wave {i}: {len(w)} batches, {n:2d} agents, ~{n*PTS_PER_AGENT:4.0f} pts  {' '.join(w)}")
        total = agent_count(q)
        print(f"\ntotal {total} agents ~= {total*PTS_PER_AGENT:.0f} points "
              f"~= {total*PTS_PER_AGENT/ (RESERVE_PCT):.1f} windows at {RESERVE_PCT:.0f}%")
        return 0

    if cmd == "next":
        q = failed + pending           # retry failures first -- they are known-sized
        if not q:
            print("queue empty", file=sys.stderr)
            return 1
        wave = pack(q)[0]
        if p5 is not None:
            room = max(0.0, RESERVE_PCT - p5)
            fit = int(room / PTS_PER_AGENT)
            if fit <= 0:
                print(f"5h at {p5}% -- at or past the {RESERVE_PCT:.0f}% release line; "
                      f"wait for reset", file=sys.stderr)
                return 2
            while agent_count(wave) > fit and len(wave) > 1:
                wave = wave[:-1]
        a = as_args(wave)
        print(json.dumps(a))
        print(f"\nwave: {len(wave)} batches, {agent_count(wave)} agents, "
              f"~{agent_count(wave)*PTS_PER_AGENT:.0f} points   ({' '.join(wave)})",
              file=sys.stderr)
        return 0

    print(f"unknown command: {cmd}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
