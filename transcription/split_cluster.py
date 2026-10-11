#!/usr/bin/env python3
"""Split one diarization cluster that holds two or more people, from voice embeddings.

    scratch/venv-voice/bin/python transcription/split_cluster.py 2026-10-06 --cluster B \\
        --seed "Audra Melton=2:31:08,0:51:58,0:57:43" \\
        --seed "Stephanie Zendler=2:45:56,0:58:44,0:59:52" [--write]

AssemblyAI sometimes hears two people as one voice. On 2026-09-01 and 2026-10-06 it put
Zendler and Melton in one cluster all evening, interleaved line by line, which a time `split`
cannot express. This does what those two evenings did by hand (worked examples in
transcription/examples/2026-09-01/ and 2026-10-06/voice_split/):

  1. a speechbrain ECAPA voiceprint for every utterance of 0.8 s or more, and for 4-s windows
     (hop 2 s) over the cluster's turns longer than 8 s -- cached next to the transcript, so
     a re-run with other seeds takes seconds;
  2. one centroid per person from the SEED turns you give (times inside the cluster's turns),
     and one per other cluster, named from the spec's mapping, as "sinks";
  3. each turn goes to the closer seed when the margin is clear (0.08; 0.15 for turns under
     3 s), to a sink when a staff voice is clearly closer (>= 0.6 and 0.15 above every seed),
     and is otherwise listed for review;
  4. a long turn whose windows run one person then the other is a mid-turn hand-off: it is cut
     at the word boundary with the longest pause in the hand-off window (`utterance_splits`);
  5. turns filed under OTHER clusters that sound clearly like a seed are proposed too (on
     2026-10-06 four of Melton's lines sat under staff clusters).

THE SEEDS ARE THE EVIDENCE. Pick them from moments where a name plate is on camera, the
Teams active-speaker label is lit, or the chair has just called the person by name -- never
from what a line says (docs/TRANSCRIPTION.md, "grab a frame before a mapping"). The report
prints the seed lines and how far apart the seed voices are; if the people's own seeds are
not more alike than the two people are, the seeds are wrong and nothing else is worth reading.

Without --write it only reports. With --write it merges into the speaker spec
(transcription/examples/<date>/speakers.json): its own reassign rows and splits are tagged
"_split_cluster" and replaced on the next run, and they go FIRST, so any hand-made row for
the same line wins. Then re-run transcribe_meeting.py with --transcript-id to re-attribute,
audit_attribution.py, and upload_transcript.py.

Run it with the venv that has speechbrain (scratch/venv-voice; see docs/TRANSCRIPTION.md).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WORKDIR = REPO / "scratch" / "tsd-transcripts"
MODEL = "speechbrain/spkrec-ecapa-voxceleb"
MIN_MS, WIN_S, HOP_S, LONG_MS = 800, 4, 2, 8000


def hms(t: float) -> str:
    t = int(t)
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}"


def secs(s: str) -> float:
    parts = [float(x) for x in s.strip().split(":")]
    return sum(p * m for p, m in zip(reversed(parts), (1, 60, 3600)))


# ---------------------------------------------------------------- embeddings (cached)
def wav16k(audio: Path, cache: Path) -> Path:
    if not cache.exists():
        subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(audio),
                        "-ac", "1", "-ar", "16000", str(cache)], check=True)
    return cache


def embeddings(utts, cluster: str, wav: Path, cache: Path) -> dict:
    """{"utts": {start_ms: vec}, "wins": {start_ms: [[t, vec], ...]}} -- computed only where missing."""
    data = json.loads(cache.read_text()) if cache.exists() else {"model": MODEL, "utts": {}, "wins": {}}
    need_u = [u for u in utts if u["end"] - u["start"] >= MIN_MS and str(u["start"]) not in data["utts"]]
    need_w = [u for u in utts if u["speaker"] == cluster and u["end"] - u["start"] > LONG_MS
              and str(u["start"]) not in data["wins"]]
    if need_u or need_w:
        import warnings
        warnings.filterwarnings("ignore")
        import soundfile as sf
        import torch
        from speechbrain.inference.speaker import EncoderClassifier
        audio, sr = sf.read(str(wav), dtype="float32")
        assert sr == 16000, sr
        enc = EncoderClassifier.from_hparams(source=MODEL, savedir=str(cache.parent / ".ecapa-model"),
                                             run_opts={"device": "cpu"})

        def emb(a, b):
            with torch.no_grad():
                return enc.encode_batch(torch.from_numpy(audio[a:b]).unsqueeze(0)).squeeze().tolist()
        print(f"embedding {len(need_u)} utterances + windows for {len(need_w)} long turns "
              f"(about a second each on CPU) ...", flush=True)
        for i, u in enumerate(need_u, 1):
            data["utts"][str(u["start"])] = emb(int(u["start"] * 16), int(u["end"] * 16))
            if i % 100 == 0:
                print(f"  {i}/{len(need_u)}", flush=True)
                cache.write_text(json.dumps(data))
        for u in need_w:
            s, e = int(u["start"] * 16), int(u["end"] * 16)
            data["wins"][str(u["start"])] = [[a / 16000, emb(a, a + WIN_S * 16000)]
                                             for a in range(s, e - WIN_S * 16000 + 1, HOP_S * 16000)]
        cache.write_text(json.dumps(data))
    return data


# ---------------------------------------------------------------- analysis
def analyse(utts, cluster, seeds, names, E, margin, short_margin, short_s, scan_others=True):
    import numpy as np
    n = lambda v: np.asarray(v) / np.linalg.norm(v)
    V = {int(k): n(v) for k, v in E["utts"].items()}
    by_start = {u["start"]: u for u in utts}
    mine = [u for u in utts if u["speaker"] == cluster]

    # seeds -> the cluster's turns that contain (or sit nearest) each time
    seed_utts = {}
    for name, times in seeds.items():
        picked = []
        for t in times:
            ms = t * 1000
            # A seed time means, in order: the line LABELLED with that second in the attributed
            # transcript (labels are floored, so its start is in [t, t+1)); else the line that
            # contains it (a time read off a video frame); else the nearest line within 2 s.
            # Tolerance-first picked the neighbour on the first test -- 0:58:44 became Melton's
            # 0:58:41 "that is it", which ends a fraction before Zendler's answer starts -- and
            # the seed check flagged the poisoned centroid.
            cand = ([u for u in mine if ms <= u["start"] < ms + 1000 and u["start"] in V] or
                    [u for u in mine if u["start"] <= ms <= u["end"] and u["start"] in V] or
                    [u for u in mine if u["start"] - 2000 <= ms <= u["end"] + 2000 and u["start"] in V])
            if not cand:
                near = min((u for u in mine if u["start"] in V), key=lambda u: abs(u["start"] - ms))
                if abs(near["start"] - ms) > 5000:
                    sys.exit(f"seed {name}={hms(t)}: no embedded turn of cluster {cluster} within 5 s")
                cand = [near]
            picked.append(min(cand, key=lambda u: abs((u["start"] + u["end"]) / 2 - ms)))
        seed_utts[name] = picked
    cent = {name: n(np.mean([V[u["start"]] for u in us], 0)) for name, us in seed_utts.items()}
    sinks = {}
    for k in sorted({u["speaker"] for u in utts} - {cluster}):
        vs = [V[u["start"]] for u in utts if u["speaker"] == k and u["end"] - u["start"] >= 3000 and u["start"] in V]
        if vs:
            sinks[names.get(k, f"Speaker {k}")] = (k, n(np.mean(vs, 0)))

    # seed separation: each person's seed turns must be more alike than the people are
    within = [float(V[a["start"]] @ V[b["start"]]) for us in seed_utts.values()
              for i, a in enumerate(us) for b in us[i + 1:]]
    across = [float(V[a["start"]] @ V[b["start"]]) for i, (na, ua) in enumerate(seed_utts.items())
              for nb, ub in list(seed_utts.items())[i + 1:] for a in ua for b in ub]

    # `reassign` pins lines by start_ms, and the API can emit two utterances with the same start
    # (2026-10-06 0:13:20: a B "Okay." and a Trudel line). Pinning one would move both, so a
    # line whose start is shared is never proposed -- it goes to review.
    starts = {}
    for u in utts:
        starts[u["start"]] = starts.get(u["start"], 0) + 1
    shared = {k for k, c in starts.items() if c > 1}

    rows, splits, review = [], [], []
    for u in mine:
        if u["start"] in shared:
            review.append((u, "start time shared with another utterance; reassign cannot single it out"))
            continue
        if u["start"] not in V:
            review.append((u, "too short to embed"))
            continue
        v, dur = V[u["start"]], (u["end"] - u["start"]) / 1000
        s = {nm: float(v @ c) for nm, c in cent.items()}
        order = sorted(s, key=s.get, reverse=True)
        best, gap = order[0], s[order[0]] - (s[order[1]] if len(order) > 1 else -1)
        sink = max(sinks, key=lambda nm: float(v @ sinks[nm][1])) if sinks else None
        ssim = float(v @ sinks[sink][1]) if sink else -1
        label, why = None, ""
        if sink and ssim >= 0.6 and ssim - s[best] >= 0.15:
            label, why = sink, f"staff voice {ssim:.2f}"
        elif gap >= (margin if dur >= short_s else short_margin):
            label, why = best, f"{s[best]:.2f} vs {s[order[1]]:.2f}" if len(order) > 1 else ""
        # mid-turn hand-off from the window scan
        W = E["wins"].get(str(u["start"])) or []
        lab = []
        for t, w in W:
            ws = {nm: float(n(w) @ c) for nm, c in cent.items()}
            o = sorted(ws, key=ws.get, reverse=True)
            lab.append(o[0] if len(o) == 1 or ws[o[0]] - ws[o[1]] > 0.05 else None)
        runs = []
        for i, x in enumerate(lab):
            if x is None:
                continue
            if runs and runs[-1][0] == x:
                runs[-1][2] = i
            else:
                runs.append([x, i, i])
        runs = [r for r in runs if r[2] - r[1] + 1 >= 3]
        merged = []
        for r in runs:
            if merged and merged[-1][0] == r[0]:
                merged[-1][2] = r[2]
            else:
                merged.append(r)
        if len(merged) == 2:
            k = merged[1][1]
            lo, hi = W[merged[0][2]][0] + 2, W[k][0] + WIN_S
            words = u.get("words") or []
            best_w, best_gap = None, -1.0
            for i, w in enumerate(words[1:], 1):
                if lo - 1 <= w["start"] / 1000 <= hi:
                    g = w["start"] - words[i - 1]["end"]
                    if g > best_gap:
                        best_w, best_gap = w, g
            if best_w:
                splits.append({"start_ms": u["start"], "at_ms": best_w["start"], "before": merged[0][0],
                               "after": merged[1][0], "word": best_w["text"],
                               "windows": "".join("·" if x is None else x[0] for x in lab)})
                label, why = merged[0][0], "head of a hand-off"
        elif len(merged) > 2:
            review.append((u, "several hand-offs inside one turn: " + "".join("·" if x is None else x[0] for x in lab)))
        if label:
            rows.append((u, label, why))
        else:
            review.append((u, f"no clear voice ({s[best]:.2f} {best} vs {s[order[1]]:.2f})" if len(order) > 1 else "no clear voice"))

    others = []
    if scan_others:
        for u in utts:
            if u["speaker"] == cluster or u["start"] not in V or u["end"] - u["start"] < 3000 or u["start"] in shared:
                continue
            v = V[u["start"]]
            own_name = names.get(u["speaker"], f"Speaker {u['speaker']}")
            own = float(v @ sinks[own_name][1]) if own_name in sinks else 0
            best = max(cent, key=lambda nm: float(v @ cent[nm]))
            sb = float(v @ cent[best])
            if sb >= 0.6 and sb - own >= 0.15:
                others.append((u, best, f"{sb:.2f} vs own {u['speaker']} {own:.2f}"))
    return dict(seed_utts=seed_utts, within=within, across=across, rows=rows, splits=splits,
                review=review, others=others, by_start=by_start)


# ---------------------------------------------------------------- spec merge
def write_spec(spec_path: Path, cluster: str, default: str, res) -> None:
    spec = json.loads(spec_path.read_text())
    spec.setdefault("mapping", {})[cluster] = default
    keep = [r for r in spec.get("reassign", []) if r.get("_split_cluster") != cluster]
    mine = {}
    for u, name, _ in res["rows"] + res["others"]:
        if name != default or u["speaker"] != cluster:
            mine.setdefault(name, []).append(u["start"])
    rows = [{"name": nm, "start_ms": sorted(v), "_split_cluster": cluster} for nm, v in sorted(mine.items())]
    spec["reassign"] = rows + keep          # hand-made rows come later and win
    old = [s for s in spec.get("utterance_splits", []) if s.get("_split_cluster") != cluster]
    have = {int(s["start_ms"]) for s in old}
    new = [{"start_ms": s["start_ms"], "at_ms": s["at_ms"], "after": s["after"], "_split_cluster": cluster,
            "note": f"{hms(s['start_ms'] / 1000)} {s['before']} then {s['after']} from '{s['word']}'"}
           for s in res["splits"] if s["start_ms"] not in have]
    spec["utterance_splits"] = old + new
    spec_path.write_text(json.dumps(spec, indent=1, ensure_ascii=False))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("date")
    ap.add_argument("--cluster", required=True, help="the merged cluster's letter")
    ap.add_argument("--seed", action="append", required=True, metavar="NAME=H:MM:SS[,H:MM:SS…]",
                    help="a person and one or more times inside their own turns; repeat per person")
    ap.add_argument("--default", help="name the cluster's leftover lines keep (default: the seed with most lines)")
    ap.add_argument("--transcript", help="default: <workdir>/Troy School Board Meeting - DATE.transcript.json")
    ap.add_argument("--audio", help="default: <workdir>/tsd_DATE.mp3")
    ap.add_argument("--spec", help="default: transcription/examples/DATE/speakers.json")
    ap.add_argument("--workdir", default=str(WORKDIR))
    ap.add_argument("--margin", type=float, default=0.08)
    ap.add_argument("--short-margin", type=float, default=0.15)
    ap.add_argument("--short", type=float, default=3.0, help="seconds below which --short-margin applies")
    ap.add_argument("--no-scan-others", action="store_true")
    ap.add_argument("--json", help="also write the proposal here")
    ap.add_argument("--write", action="store_true", help="merge the proposal into the spec")
    a = ap.parse_args()

    wd = Path(a.workdir)
    base = f"Troy School Board Meeting - {a.date}"
    tpath = Path(a.transcript or wd / f"{base}.transcript.json")
    apath = Path(a.audio or wd / f"tsd_{a.date}.mp3")
    spath = Path(a.spec or REPO / "transcription" / "examples" / a.date / "speakers.json")
    utts = json.loads(tpath.read_text())["utterances"]
    names = json.loads(spath.read_text()).get("mapping", {}) if spath.exists() else {}
    seeds = {}
    for s in a.seed:
        name, _, times = s.partition("=")
        if not times:
            sys.exit(f"--seed needs NAME=H:MM:SS, got {s!r}")
        seeds.setdefault(name.strip(), []).extend(secs(t) for t in times.split(","))
    if len(seeds) < 2:
        sys.exit("give seeds for at least two people")
    if a.cluster not in {u["speaker"] for u in utts}:
        sys.exit(f"no cluster {a.cluster} in {tpath.name}")
    wav = wav16k(apath, tpath.with_name(tpath.name.replace(".transcript.json", ".16k.wav")))
    E = embeddings(utts, a.cluster, wav, tpath.with_name(tpath.name.replace(".transcript.json", ".ecapa.json")))
    res = analyse(utts, a.cluster, seeds, names, E, a.margin, a.short_margin, a.short, not a.no_scan_others)

    # ---- report
    print(f"\n{a.date} cluster {a.cluster}: {sum(1 for u in utts if u['speaker'] == a.cluster)} turns")
    for name, us in res["seed_utts"].items():
        for u in us:
            print(f"  seed {name:20} {hms(u['start'] / 1000)}  {u['text'][:70]}")
    wmin = min(res["within"]) if res["within"] else 1
    amax = max(res["across"]) if res["across"] else -1
    print(f"  seed check: same-person cosine >= {wmin:.2f}, different-person <= {amax:.2f}"
          + ("" if wmin > amax else "   ** SEEDS DO NOT SEPARATE -- check them on camera before reading on **"))
    counts = {}
    for _, nm, _ in res["rows"]:
        counts[nm] = counts.get(nm, 0) + 1
    default = a.default or max((nm for nm in seeds), key=lambda nm: counts.get(nm, 0))
    print("  assigned: " + ", ".join(f"{nm} {c}" for nm, c in sorted(counts.items(), key=lambda x: -x[1]))
          + f"; review {len(res['review'])}; cluster default -> {default}")
    for s in res["splits"]:
        print(f"  hand-off {hms(s['start_ms'] / 1000)}: {s['before']} -> {s['after']} at {hms(s['at_ms'] / 1000)} "
              f"('{s['word']}')  windows {s['windows']}")
    for u, nm, why in res["rows"]:
        if nm not in seeds:
            print(f"  staff    {hms(u['start'] / 1000)} -> {nm} ({why})  {u['text'][:60]}")
    for u, nm, why in res["others"]:
        print(f"  other    {hms(u['start'] / 1000)} {u['speaker']} -> {nm} ({why})  {u['text'][:55]}")
    for u, why in res["review"]:
        if (u["end"] - u["start"]) >= 1500:
            print(f"  review   {hms(u['start'] / 1000)} {(u['end'] - u['start']) / 1000:4.1f}s {why}  {u['text'][:50]}")
    short = sum(1 for u, _ in res["review"] if (u["end"] - u["start"]) < 1500)
    if short:
        print(f"  ({short} interjections under 1.5 s keep the cluster default)")

    prop = {"cluster": a.cluster, "default": default,
            "assign": [{"start_ms": u["start"], "name": nm, "why": why} for u, nm, why in res["rows"] + res["others"]],
            "utterance_splits": res["splits"],
            "review": [{"start_ms": u["start"], "why": why} for u, why in res["review"]]}
    if a.json:
        Path(a.json).write_text(json.dumps(prop, indent=1))
    if a.write:
        write_spec(spath, a.cluster, default, res)
        print(f"\nwrote {spath.relative_to(REPO) if spath.is_relative_to(REPO) else spath} -- now re-run "
              f"transcribe_meeting.py --transcript-id …, audit_attribution.py, upload_transcript.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
