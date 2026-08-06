#!/usr/bin/env python3
"""Stage the documents that no campaign manifest covers into a new campaign.

The re-summarization campaign was staged in two ad-hoc passes (`fanout`, then
`wave2`), and between them they cover 391 of the 786 documents that exceeded the
old 6,000-char cap. The other 395 were never staged, so `resummarize_queue.py`
reports "queue empty" with half the campaign untouched. This builds the third
manifest from the corpus itself rather than by hand, so the boundary is derived
and checkable instead of remembered.

Selection: every document whose extracted text exceeds the cap, minus anything
already in a manifest, minus check registers (deliberately out of scope -- a
prose summary of a few thousand payment rows is the wrong instrument, and that
data is queryable in the separate check-register project).

Batching mirrors what wave2 used: pack to ~24K tokens per batch, give an
oversized document its own agent, and split a giant into sections the workflow
summarizes separately then synthesizes.

    python3 scripts/stage_campaign.py --name wave3 --dry-run
    python3 scripts/stage_campaign.py --name wave3
"""
from __future__ import annotations

import argparse
import json
import os
import re
import collections
import math
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ROOT = Path(os.environ.get("TSD_BOE_ROOT") or REPO / "data" / "tsd-boe-data")
STAGE = Path(os.environ.get("TSD_FAN_DIR") or REPO / "resummarize")
CAP = 6000                     # the old TEXT_CAP this campaign exists to undo
SEP = "=" * 70
CHARS_PER_TOKEN = 4            # rough, and only used for packing
BATCH_TOKENS = 24_000          # target per batch (one agent)
BIG_TOKENS = 40_000            # above this a document gets its own agent
# Defaults for the 2023-2026 material. The packet era needs far more aggressive
# splitting -- see --split-over / --section. A single agent compressing 150K
# tokens into ~1,600 words is re-enacting, at a larger scale, the very lossiness
# this campaign exists to undo.
GIANT_TOKENS = 170_000         # above this it is split into sections
CHECK_RE = re.compile(r'check\s*register|checkregister', re.I)


def load_index():
    """url -> {len, title, date, source, type} from the chunk index."""
    idx = ROOT / "_index" / "chunks.jsonl"
    if not idx.exists():
        raise SystemExit(f"missing {idx} — run build_index.py first")
    ln = collections.Counter()
    meta = {}
    for line in idx.open(encoding="utf-8"):
        try:
            c = json.loads(line)
        except Exception:
            continue
        if str(c.get("id", "")).startswith("sum:"):
            continue
        u = c.get("url")
        if not u:
            continue
        ln[u] += len(c.get("text") or "")
        meta.setdefault(u, {"title": c.get("title") or "", "date": c.get("meeting_date") or "",
                            "source": c.get("source") or "", "file": c.get("file") or ""})
    for u, m in meta.items():
        m["len"] = ln[u]
    return meta


def covered_urls():
    """Documents actually reachable by a batch -- NOT merely listed in urlmap.

    This read `urlmap` directly, which counts a document as covered the moment it
    is catalogued, even if staging then dropped it. `fanout` has 24 such entries
    (every 2024 monthly financial statement, the 23-24 budget amendment, the ACFR
    management letter): listed, assigned to no batch, so nothing would ever
    process them -- and `fanout` still reports 26/26 done, truthfully, because
    its batches are all finished. The documents simply were not in any of them.

    Counting only batch-reachable documents makes a dropped document look
    uncovered, so the next staging run picks it up instead of skipping it forever.
    """
    out = set()
    for man in STAGE.glob("*_manifest.json"):
        try:
            m = json.loads(man.read_text())
        except Exception:
            continue
        urlmap = m.get("urlmap", {})
        for keys in m.get("batches", {}).values():
            for k in keys:
                out.update(urlmap.get(k, []))
    return out


def doc_key(idx, u, m):
    """Stable, filesystem-safe key: <year>_<nnn>_<slug>, matching the earlier passes."""
    stem = Path(m["file"] or m["title"]).stem
    slug = re.sub(r'[^a-z0-9]+', '_', stem.lower()).strip('_')[:48]
    return f"{(m['date'] or '0000')[:4]}_{idx:03d}_{slug}"


def read_text(m):
    p = ROOT / "_text" / (m["source"] + ".txt")
    if p.exists():
        return p.read_text(encoding="utf-8", errors="replace")
    return ""


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", default="remainder", help="campaign name (dir + manifest stem)")
    ap.add_argument("--prefix", default="rm", help="batch-id prefix; must not collide with an "
                    "existing manifest (wave2_manifest.json already owns w2_* AND w3_*)")
    ap.add_argument("--dry-run", action="store_true", help="report the plan, write nothing")
    ap.add_argument("--include-check-registers", action="store_true")
    ap.add_argument("--years", help="only stage these meeting years, e.g. 2010-2020 or 2021,2022")
    ap.add_argument("--split-over", type=int, default=GIANT_TOKENS,
                    help="split any document above this many tokens into sections")
    ap.add_argument("--section", type=int, default=None,
                    help="target tokens per section (default: half of --split-over)")
    ap.add_argument("--order", choices=("newest", "oldest"), default="oldest",
                    help="which end of the campaign resummarize_queue.py works from. "
                         "Batch ids are always assigned oldest-to-newest; this only "
                         "picks the end the queue starts at. Stored IN the manifest so "
                         "the queue cannot disagree with how the campaign is being run")
    a = ap.parse_args()

    section = a.section or a.split_over // 2

    def in_years(m):
        if not a.years:
            return True
        y = (m["date"] or "")[:4]
        for part in a.years.split(","):
            part = part.strip()
            if "-" in part:
                lo, hi = part.split("-", 1)
                if lo <= y <= hi:
                    return True
            elif y == part:
                return True
        return False

    meta = load_index()
    done = covered_urls()
    sel = {u: m for u, m in meta.items()
           if m["len"] > CAP and u not in done and in_years(m)
           and (a.include_check_registers or not CHECK_RE.search(m["title"]))}
    skipped_cr = sum(1 for u, m in meta.items()
                     if m["len"] > CAP and u not in done and CHECK_RE.search(m["title"]))

    order = sorted(sel, key=lambda u: (sel[u]["date"], sel[u]["title"]))
    print(f"corpus documents           : {len(meta):,}")
    print(f"exceeded the {CAP}-char cap : {sum(1 for m in meta.values() if m['len']>CAP):,}")
    print(f"already covered            : {len(done & set(meta)):,}")
    print(f"check registers skipped    : {skipped_cr:,}")
    print(f"to stage                   : {len(order):,}")

    # pack: giants and bigs alone, everything else to the token target
    batches, split, cur, cur_tok, n = {}, {}, [], 0, 0
    keys = {}
    for i, u in enumerate(order):
        m = sel[u]
        keys[u] = doc_key(i, u, m)
    def flush():
        nonlocal cur, cur_tok, n
        if cur:
            batches[f"{a.prefix}_{n:03d}"] = cur
            n += 1
            cur, cur_tok = [], 0
    for u in order:
        m, k = sel[u], keys[u]
        tok = m["len"] / CHARS_PER_TOKEN
        if tok > BIG_TOKENS or tok > a.split_over:
            flush()
            bid = f"{a.prefix}_{n:03d}"; n += 1
            batches[bid] = [k]
            if tok > a.split_over:
                parts = max(2, math.ceil(tok / section))
                split[bid] = {"key": k, "parts": [f"{bid}_part{p+1}" for p in range(parts)]}
            continue
        if cur_tok + tok > BATCH_TOKENS and cur:
            flush()
        cur.append(k); cur_tok += tok
    flush()

    agents = sum(len(split[b]["parts"]) + 1 if b in split else 1 for b in batches)
    print(f"\nbatches                    : {len(batches):,}")
    oversized = sum(1 for u in order if sel[u]["len"] / CHARS_PER_TOKEN > BIG_TOKENS)
    tot_tok = sum(sel[u]["len"] for u in order) / CHARS_PER_TOKEN
    print(f"  oversized (own agent)    : {oversized:,}")
    print(f"  split into sections      : {len(split):,}")
    print(f"source to read             : {tot_tok/1e6:.1f}M tokens")
    print(f"agents required            : {agents:,}  (~{agents/8:.0f} waves of 8)")
    if a.dry_run:
        print("\n--dry-run: nothing written")
        return 0

    outdir = STAGE / a.name
    outdir.mkdir(parents=True, exist_ok=True)
    urlmap = {}
    written = 0
    for bid, ks in batches.items():
        chunks = []
        for k in ks:
            u = next(x for x in order if keys[x] == k)
            m = sel[u]
            urlmap[k] = [u]
            body = read_text(m)
            if not body:
                continue
            pct = min(100.0, 100.0 * CAP / max(1, m["len"]))
            chunks.append(f"### DOCUMENT KEY: {k}\nTITLE: {m['title']}\n"
                          f"MEETING DATE: {m['date']}\nTYPE: {Path(m['file']).suffix.lstrip('.').upper() or 'PDF'}\n"
                          f"PREVIOUSLY SUMMARIZED FROM: {pct:.1f}%\n{SEP}\n{body}\n")
        text = "\n".join(chunks)
        if bid in split:
            # write the sections the workflow expects, plus the whole file
            parts = split[bid]["parts"]
            step = max(1, len(text) // len(parts))
            for i, p in enumerate(parts):
                seg = text[i*step:(i+1)*step] if i < len(parts)-1 else text[i*step:]
                (outdir / f"{p}.txt").write_text(seg, encoding="utf-8")
        (outdir / f"{bid}.txt").write_text(text, encoding="utf-8")
        written += 1

    man = {"order": a.order,
           "batches": batches, "urlmap": urlmap, "split": split,
           "excluded_check_registers": sorted(
               m["title"] for u, m in meta.items()
               if m["len"] > CAP and u not in done and CHECK_RE.search(m["title"]))}
    mp = STAGE / f"{a.name}_manifest.json"
    mp.write_text(json.dumps(man, ensure_ascii=False), encoding="utf-8")
    (STAGE / f"{a.name}_out").mkdir(exist_ok=True)
    print(f"\nwrote {written} batch files -> {outdir}")
    print(f"wrote manifest              -> {mp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
