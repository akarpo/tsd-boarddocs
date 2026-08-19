#!/usr/bin/env python3
"""Push queued description rebuilds once the YouTube daily quota resets.

Anchor writes land in D1 (no YouTube quota); only the description rebuild costs
units, so the two are decoupled -- anchors keep being corrected while writes are
blocked, and this drains the backlog afterwards. videos.update is 50 units, so
~200 pushes fit in a day.

  python3 push_pending.py            # drain the queue
  python3 push_pending.py --list
"""
import json, sys, time, urllib.error
from pathlib import Path
HERE = Path(__file__).resolve().parent
Q = HERE / "pending_push.json"
sys.path.insert(0, str(HERE))
import push_desc

def load(): return json.load(open(Q)) if Q.exists() else []
def save(x): json.dump(sorted(set(x)), open(Q, "w"), indent=1)

def main():
    q = load()
    if "--list" in sys.argv:
        print(f"{len(q)} pending: {q}"); return 0
    if not q:
        print("queue empty"); return 0
    left = []
    for date in q:
        try:
            push_desc.main_for(date)
        except urllib.error.HTTPError as e:
            b = e.read().decode()
            if "quotaExceeded" in b:
                print(f"{date}: quota still exhausted — stopping, {len(q)-len(left)} left")
                left += q[q.index(date):]
                break
            print(f"{date}: HTTP {e.code}"); left.append(date)
        except Exception as e:                       # noqa: BLE001
            # The type alone is not a diagnosis. An unattended run that printed
            # bare "2024-01-16: KeyError" gave no way to tell a corrupt meeting
            # from a transient D1 blip -- which is what it turned out to be.
            print(f"{date}: {type(e).__name__}: {e}"); left.append(date)
        time.sleep(1)
    save(left)
    print(f"\n{len(q)-len(left)} pushed, {len(left)} still queued")
    return 0

if __name__ == "__main__":
    sys.exit(main())
