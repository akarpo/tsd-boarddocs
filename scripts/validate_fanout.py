#!/usr/bin/env python3
"""Validate agent-written summaries against their source text, then stage for D1.

The fan-out moves the writing to subagents; verification stays here. Every figure
of 4+ digits an agent asserted is classified against the batch file it actually read:

  exact    present verbatim
  spaced   present but split by the extractor -- "886, 000", "1, 046,471"
  derived  absent, but computable from two figures that ARE present
  unknown  absent and not computable -- a fabrication

The first two pass. `derived` is now a FAILURE, not a pass: the agent prompt forbids
arithmetic outright, because a plausible-looking computed figure is exactly the kind
of error this campaign exists to remove, and "it happens to be arithmetically right"
is not the same as "the document says it". `unknown` is always a failure.

Matching is by substring against a comma/space-stripped copy of the source. The
earlier tokenized approach (re.findall on the stripped text) destroyed digit
boundaries wherever two numbers sat adjacent, and flagged real figures as missing.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

DIR = Path(os.environ.get("TSD_FAN_DIR") or
           Path.home() / "Downloads" / "tsd_resummarize_staging")
IN  = DIR / os.environ.get("TSD_FAN_IN",  "fanout")
OUT = DIR / os.environ.get("TSD_FAN_OUT", "fanout_out")
MAN = json.loads((DIR / os.environ.get("TSD_FAN_MANIFEST", "fanout_manifest.json")).read_text())
TIERS = ("paragraph", "page", "verbose")
FIG = re.compile(r"\$?([\d]{1,3}(?:,\d{3})+(?:\.\d+)?)")


def source_for(batch):
    split = MAN.get("split", {})
    if batch in split:
        return "".join((IN / f"{p}.txt").read_text(encoding="utf-8", errors="replace")
                       for p in split[batch]["parts"])
    return (IN / f"{batch}.txt").read_text(encoding="utf-8", errors="replace")


def classify(src):
    """Return a function mapping a bare digit string to exact|spaced|derived|unknown."""
    exact = set(re.findall(r"\d{4,}", src.replace(",", "")))
    flat = re.sub(r"[,\s]", "", src)            # substring space, boundary-free
    nums = sorted({int(x) for x in exact if x.isdigit() and len(x) <= 15})
    nset = set(nums)

    def f(n: str):
        if n in exact:
            return "exact"
        if n in flat:                            # split by the extractor
            return "spaced"
        v = int(n)
        for a in nums:                           # a-b or a+b from source figures
            if (a - v) in nset or (a + v) in nset:
                return "derived"
        return "unknown"
    return f


def check(batch, expected):
    p = OUT / f"{batch}.json"
    if not p.exists():
        return {"batch": batch, "status": "MISSING", "detail": "no output file"}
    try:
        raw = p.read_text(encoding="utf-8").strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        data = json.loads(raw)
    except Exception as e:
        return {"batch": batch, "status": "BAD_JSON", "detail": str(e)[:120]}

    got, want = set(data), set(expected)
    problems = []
    if want - got:
        problems.append(f"missing keys: {sorted(want - got)[:4]}")
    if got - want:
        problems.append(f"unexpected keys: {sorted(got - want)[:4]}")
    for k, v in data.items():
        if set(v) != set(TIERS):
            problems.append(f"{k}: tier keys {sorted(v)}")
        for t in TIERS:
            if not str(v.get(t, "")).strip():
                problems.append(f"{k}: empty {t}")

    # A missing batch-text file used to raise straight out of main(), killing the
    # run and returning zero OK lines -- which the queue reads as "every batch
    # failed" and requeues known-good work. Report it as this batch's status.
    try:
        cls = classify(source_for(batch))
    except FileNotFoundError as e:
        return {"batch": batch, "status": "NO_SOURCE", "detail": str(e)[:120]}
    tally = {"exact": 0, "spaced": 0, "derived": 0, "unknown": 0}
    flagged = []
    for k, v in data.items():
        for m in FIG.findall(" ".join(str(v.get(t, "")) for t in TIERS)):
            n = m.replace(",", "").split(".")[0]
            if len(n) < 4:
                continue
            c = cls(n)
            tally[c] += 1
            if c in ("derived", "unknown"):
                flagged.append((c, k, m))

    tot = sum(tally.values())
    good = tally["exact"] + tally["spaced"]
    status = "OK"
    if problems:
        status = "STRUCT"
    elif tally["unknown"]:
        status = "FABRICATED"
    elif tally["derived"]:
        status = "DERIVED"
    return {"batch": batch, "status": status, "docs": len(data), "figures": tot,
            "verified": good, "pct": round(100 * good / tot, 1) if tot else 100.0,
            "tally": tally, "problems": problems[:6],
            "flagged": sorted(set(flagged))[:12]}


def main():
    batches = MAN["batches"]
    only = [a for a in sys.argv[1:] if not a.startswith("-")] or sorted(batches)
    # An output can exist for a batch no longer in the manifest -- e.g. a batch
    # summarized before a filter removed it. Skip those rather than KeyError,
    # which would abort the whole run and make every batch look failed.
    unknown = [b for b in only if b not in batches]
    rows = [check(b, batches[b]) for b in only if b in batches]
    ok = [r for r in rows if r["status"] == "OK"]

    for r in rows:
        if r["status"] in ("MISSING", "BAD_JSON", "NO_SOURCE"):
            print(f"  {r['batch']:12s} {r['status']:11s}  -- {r['detail']}")
            continue
        t = r["tally"]
        print(f"  {r['batch']:12s} {r['status']:11s} {r['docs']:3d} docs  "
              f"{r['figures']:5d} figs  exact {t['exact']:5d}  spaced {t['spaced']:4d}  "
              f"derived {t['derived']:3d}  unknown {t['unknown']:3d}")
        for p in r["problems"]:
            print(f"       ! {p}")
        for c, k, m in r["flagged"]:
            print(f"       {'~' if c=='derived' else 'X'} {c:8s} {k[:42]}: {m}")

    if unknown:
        print(f"  (skipped {len(unknown)} output(s) not in manifest: {' '.join(sorted(unknown)[:4])})")
    print(f"\n{len(ok)}/{len(rows)} batches clean")
    agg = {k: sum(r.get("tally", {}).get(k, 0) for r in rows)
           for k in ("exact", "spaced", "derived", "unknown")}
    tot = sum(agg.values())
    if tot:
        print(f"figures {tot:,}: exact {agg['exact']:,} · spaced {agg['spaced']:,} · "
              f"derived {agg['derived']:,} · unknown {agg['unknown']:,}  "
              f"({100*(agg['exact']+agg['spaced'])/tot:.2f}% clean)")

    urlmap, dupes = MAN["urlmap"], MAN.get("dupes", {})
    rows_out, staged = {}, 0
    for r in ok:
        data = json.loads((OUT / f"{r['batch']}.json").read_text(encoding="utf-8"))
        for k, v in data.items():
            staged += 1
            for u in urlmap.get(k, []):
                rows_out[u] = v
            for dk, target in dupes.items():
                if target == k:
                    for u in urlmap.get(dk, []):
                        rows_out[u] = v
    if rows_out:
        d = Path(os.path.expanduser(os.environ.get("TSD_STORE_DIR", "~/Downloads/tsd_store_fanout")))
        d.mkdir(parents=True, exist_ok=True)
        (d / "batch_000.json").write_text(
            json.dumps(rows_out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"staged {staged} docs -> {len(rows_out)} urls -> {d}")
    bad = [r["batch"] for r in rows if r["status"] != "OK"]
    if bad:
        print(f"\nrequeue: {' '.join(bad)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
