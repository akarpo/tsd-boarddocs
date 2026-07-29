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
import time
from pathlib import Path

SCRIPTS = Path(__file__).parent                      # where the sibling tools live
DIR = Path(os.environ.get("TSD_FAN_DIR") or          # where the batches/outputs live
           Path(__file__).resolve().parent.parent / "resummarize")

# The three paths must move together. validate_fanout.py resolves the batch-text
# dir from its OWN env var (TSD_FAN_IN), which this script never set -- so running
# a second campaign with TSD_FAN_MANIFEST/TSD_FAN_OUT left the validator reading
# the FIRST campaign's input dir, where none of the batch files exist. It died on
# FileNotFoundError, stdout came back empty, and every written batch looked failed.
# Default all three off the manifest stem so they cannot drift apart again.
MAN_NAME = os.environ.get("TSD_FAN_MANIFEST", "fanout_manifest.json")
STEM = MAN_NAME[:-len("_manifest.json")] if MAN_NAME.endswith("_manifest.json") else "fanout"
IN_NAME = os.environ.get("TSD_FAN_IN", STEM)
OUT_NAME = os.environ.get("TSD_FAN_OUT", f"{STEM}_out")
MAN = json.loads((DIR / MAN_NAME).read_text())
OUT = DIR / OUT_NAME

# Measured on wave 1 (2026-07-27): 8 agents, all completed, took the 5-hour window
# 0% -> 39%. The earlier 3.1 came from agents still in flight and was 57% low.
PTS_PER_AGENT = 4.9
# Stop releasing waves once the window passes this. Raised 75 -> 90 deliberately:
# it buys roughly three more agents per window, at the cost of most of the slack
# that absorbed a bad cost estimate. PTS_PER_AGENT is a MEAN and the variance is
# real -- a figure-dense 3-agent wave on 2026-07-28 cost 26 points, not the 15
# predicted (8.7/agent, a 73% overrun). At 75% that overrun was absorbed; at 90%
# a wave like it lands past the limit mid-write. Recoverable -- a truncated
# output fails validation and returns to pending -- but it wastes the agent.
RESERVE_PCT = 90.0
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


SNAPSHOT = Path.home() / ".claude" / "usage_snapshot.json"
MAX_AGE_S = 600           # a statusline hook rewrites the snapshot every turn


def usage():
    """Return (five_hour_pct, seven_day_pct, problem).

    `problem` is None when the reading can be trusted, else a short string
    naming why it cannot. Callers that gate work on headroom MUST treat an
    untrustworthy reading as "no headroom" rather than "no limit" -- this used
    to return (None, None) on any exception, and `next` skipped its entire
    headroom check when the value was None, so an unreadable snapshot silently
    released a full wave instead of blocking one.

    Two ways the numbers lie, in opposite directions:

    - `resets_at` in the past: the hook has not yet rewritten the file for the
      new window, so `used_percentage` still describes the window that just
      expired. Reads HIGH -- conservative, but it is not a real measurement.
    - a stale file: usage has continued since it was written. Reads LOW, which
      is the dangerous direction, because it invites releasing a wave into a
      window that is nearly spent.
    """
    try:
        s = json.loads(SNAPSHOT.read_text())
        rl = s["rate_limits"]
        five = rl["five_hour"]
        p5, p7 = five["used_percentage"], rl["seven_day"]["used_percentage"]
    except Exception as e:
        return None, None, f"snapshot unreadable ({type(e).__name__})"

    resets = five.get("resets_at")
    if isinstance(resets, (int, float)) and resets < time.time():
        return p5, p7, ("window already rolled (resets_at is in the past) -- "
                        "the percentage still describes the expired window; "
                        "re-run for a fresh reading")
    try:
        age = time.time() - SNAPSHOT.stat().st_mtime
        if age > MAX_AGE_S:
            return p5, p7, f"snapshot is {age/60:.0f} min old (usage may have continued since)"
    except OSError as e:
        return p5, p7, f"snapshot age unknown ({type(e).__name__})"
    return p5, p7, None


def validated():
    """Batches whose output exists and passes validation."""
    if not OUT.exists():
        return set()
    have = [p.stem for p in OUT.glob("*.json")]
    if not have:
        return set()
    r = subprocess.run([sys.executable, str(SCRIPTS / "validate_fanout.py"), *have],
                       capture_output=True, text=True,
                       env={**os.environ, "TSD_FAN_IN": IN_NAME,
                            "TSD_FAN_OUT": OUT_NAME, "TSD_FAN_MANIFEST": MAN_NAME})
    if r.returncode != 0:
        # A crashed validator returns no OK lines, which is indistinguishable from
        # "everything failed" -- the exact bug above. Say so instead of silently
        # requeuing clean work.
        print(f"validate_fanout.py exited {r.returncode}:\n{r.stderr.strip()[-400:]}",
              file=sys.stderr)
    clean = set()
    for line in r.stdout.splitlines():
        parts = line.split()
        # Batch ids vary by campaign ("batch_003", "w2_017"); match on the
        # OK column rather than a name prefix, which silently matched nothing
        # when the wave2 ids were introduced and made every batch look failed.
        if len(parts) >= 2 and parts[1] == "OK" and parts[0] in MAN["batches"]:
            clean.add(parts[0])
    return clean


def state():
    all_b = sorted(MAN["batches"])
    done = validated()
    written = {p.stem for p in OUT.glob("*.json")} if OUT.exists() else set()
    # An output whose batch is no longer in the manifest is EXCLUDED, not failed
    # (e.g. summarized before a filter dropped it). Requeuing it would KeyError.
    failed = sorted((written - done) & set(all_b))
    pending = [b for b in all_b if b not in done and b not in failed]
    return all_b, sorted(done), failed, pending


def as_args(batches):
    """Split a batch list into the workflow's normal/giants argument shape.

    inDir/outDir are emitted explicitly. The workflow defaults them to the FIRST
    campaign ('fanout'/'fanout_out'), so a wave launched from a second campaign's
    `next` without them sends every agent to read a directory that does not hold
    its batches -- the same drift this script's path defaults now prevent.
    """
    split = MAN.get("split", {})
    normal = [b for b in batches if b not in split]
    giants = [{"batch": b, "key": split[b]["key"], "parts": split[b]["parts"]}
              for b in batches if b in split]
    return {"dir": str(DIR), "inDir": IN_NAME, "outDir": OUT_NAME,
            "normal": normal, "giants": giants}


def agent_count(batches):
    split = MAN.get("split", {})
    return sum(len(split[b]["parts"]) + 1 if b in split else 1 for b in batches)


def main():
    argv = [a for a in sys.argv[1:]]
    force = "--force" in argv or os.environ.get("TSD_QUEUE_FORCE") == "1"
    argv = [a for a in argv if a != "--force"]
    cmd = argv[0] if argv else "status"
    all_b, done, failed, pending = state()
    p5, p7, problem = usage()

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
        if problem:
            print(f"\n!! usage reading NOT trustworthy: {problem}\n"
                  f"   `next` will refuse to release a wave until this clears "
                  f"(override with --force).")
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
        # FAIL CLOSED. An unusable reading is not permission to skip the check:
        # without a trustworthy number there is no way to know a wave fits, and
        # the failure mode of guessing wrong is a rate limit landing mid-write.
        untrusted = problem or (p5 is None and "no usage reading available")
        if untrusted and not force:
            print(f"refusing to release a wave: {untrusted}", file=sys.stderr)
            if p5 is not None:
                print(f"  (last value read was 5h {p5}%, 7d {p7}%)", file=sys.stderr)
            print("  re-run once the snapshot refreshes, or override with --force.",
                  file=sys.stderr)
            return 2
        if untrusted:
            # Forced past an untrustworthy reading: emit the wave UNTRIMMED, but
            # say so. Trimming against a number we just declared unreliable would
            # dress a guess up as a measurement.
            print(f"WARNING: --force with an untrustworthy usage reading "
                  f"({untrusted}); wave is not sized against headroom.",
                  file=sys.stderr)
        else:
            room = max(0.0, RESERVE_PCT - p5)
            fit = int(room / PTS_PER_AGENT)
            if fit <= 0:
                if not force:
                    print(f"5h at {p5}% -- at or past the {RESERVE_PCT:.0f}% release "
                          f"line; wait for reset", file=sys.stderr)
                    return 2
                print(f"WARNING: --force past the {RESERVE_PCT:.0f}% release line "
                      f"(5h at {p5}%).", file=sys.stderr)
            else:
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
