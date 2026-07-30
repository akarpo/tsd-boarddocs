# Re-summarization campaign

## Why this exists

`summarize.py` carried `TEXT_CAP = 6000`: only the first 6,000 characters of a
document were ever handed to the model. Most board documents are short enough
that this was harmless. The ones that matter most are not — a 100-page budget
book was summarized from its cover page and table of contents. **788 documents**
were affected; the worst were summarized from under 2% of their text.

Nothing failed. Every document had a fluent, accurate-looking summary. The bug is
only visible if you ask "how much of the source did this summary actually see?"

Measured improvement over the 203 documents redone so far:

| | old | new |
|---|---|---|
| verbose length (median) | 3,048 chars | 7,458 |
| distinct dollar figures (median) | 26 | 93 |
| total distinct figures | 6,293 | 19,878 |

Several single-audit reports went from **zero** retrievable figures to 300+.

## How it runs

Documents are staged into batch files of ~24K tokens, one agent per batch, via
`scripts/resummarize_workflow.js` (a Workflow script — see `docs/TOOLING.md`).
Oversized documents (>40K tokens) get their own agent; the two ISD budget books
over 170K tokens are split into sections, summarized separately, then synthesized.

    Workflow({scriptPath: 'scripts/resummarize_workflow.js',
              args: {inDir, outDir, normal: [...], giants: [...]}})

`dir`/`inDir`/`outDir` are emitted by `resummarize_queue.py next`; everything
lives under `resummarize/` in the repo (see "State" below).

## The two rules that make it safe

**1. Agents may not do arithmetic.** The prompt forbids writing any number that
does not literally appear in the source — no month-over-month deltas, no totals,
no "X is Y under budget". An earlier, softer rule ("both operands must be
present") produced six fabricated figures in 2023 monthly statements, because a
reader cannot tell a computed figure from a reported one. Re-running that batch
under the ban gave 873/873 exact — and *more* figures than before, not fewer.

**2. Verification stays central.** `scripts/validate_fanout.py` re-reads each
batch's source and classifies every 4+-digit figure the agent asserted:

    exact    present verbatim
    spaced   present but split by the extractor -- "886, 000"
    derived  absent, computable from two present figures -- FAILS
    unknown  absent and not computable -- FAILS

Only clean batches are staged for D1. A failed batch is re-run alone.

Matching is **substring** against a comma/space-stripped copy of the source. An
earlier tokenized version destroyed digit boundaries where two numbers sat
adjacent and produced 46 false alarms that hid 6 real ones.

## Pacing

`scripts/resummarize_queue.py` derives state from disk — a batch is done when its
output exists and validates clean, so failures return to pending automatically.

    python3 scripts/resummarize_queue.py status   # done / failed / pending
    python3 scripts/resummarize_queue.py plan     # wave schedule
    python3 scripts/resummarize_queue.py next     # emit args for the next wave

Work is released in **waves of ~8 agents**, sized by agent count rather than batch
count (a split budget book is 5-6 agents behind one batch id). `next` refuses to
emit a wave once the 5-hour window passes **90%** (`RESERVE_PCT`). It was 75%
until 2026-07-28; the higher line buys ~3 more agents per window but spends most
of the slack that absorbed a bad cost estimate, and `PTS_PER_AGENT` is a mean
with real variance.

### In-flight leases

`next` writes a lease per batch it hands out (`resummarize/<campaign>_inflight.json`)
and excludes leased batches from the next wave.

State is otherwise derived from disk, which cannot see work that is *running but
has not written yet* — an agent spends most of its life reading, so a batch handed
out a minute ago still looks pending. Sequential waves hid this completely, because
the previous wave had always finished. Running two concurrently on 2026-07-29,
`next` re-emitted `w3_029` and `w3_031` while their agents were mid-flight; launching
that verbatim would have put two agents on one batch, racing the same output file.

- Leases expire (`TSD_LEASE_TTL`, default 45 min), so a dead agent frees its batch
  instead of wedging the queue.
- `next --dry-run` inspects without claiming.
- `release` clears all leases — the escape hatch after a killed run.
- `requeue` drops a failed batch's lease along with its stale output.

Leases are live process state, not campaign state, so they are gitignored: a fresh
clone should never inherit a claim from another machine.

### The guardrail fails closed

`next` refuses whenever it cannot *trust* the usage reading, not just when the
reading says "full". It previously skipped the headroom check entirely if the
snapshot could not be read, so a corrupt or missing file released a full wave.

Refused (exit 2), each with the reason on stderr:

| condition | why the number lies |
|---|---|
| snapshot unreadable / malformed | no reading at all |
| `resets_at` in the past | the hook has not rewritten the file for the new window, so the percentage still describes the **expired** one — reads *high* |
| snapshot older than 10 min | usage continued after it was written — reads *low*, the dangerous direction |
| 5h at or past `RESERVE_PCT` (90%) | genuinely out of headroom |

`--force` (or `TSD_QUEUE_FORCE=1`) overrides. Forced past an *untrustworthy*
reading the wave is emitted **untrimmed**, with a warning — sizing a wave against
a number just declared unreliable would dress a guess up as a measurement.

A fresh file mtime does **not** mean the numbers are current: the hook can rewrite
the snapshot while `used_percentage` still describes the window that just rolled.
`resets_at` is the field that tells you, not the mtime.

Measured cost: **~4.4 points of a 5-hour window per agent**. An earlier estimate
of 3.1 came from agents still in flight and was 57% low — estimate from completed
work only.

## State

Nothing needed to resume lives in the session scratchpad. Since v0.9.0 it all
lives under the repo, split by whether it reaches GitHub:

| what | where | in git? |
|---|---|---|
| manifests (batch -> keys, key -> urls) | `resummarize/*_manifest.json` | yes |
| agent output | `resummarize/<campaign>_out/*.json` | **yes** |
| stored summaries (what was pushed to D1) | `resummarize/stores/<campaign>/batch_*.json` | yes |
| staged batch text | `resummarize/<campaign>/*.txt` | no — regenerable |
| corpus | `data/tsd-boe-data/` | no — 3.7 GB |
| pre-campaign summaries, chunk + text backups | `data/backups/` | no — large |

**Agent output is committed deliberately.** It is the one artifact that cannot be
rebuilt without paying for Opus again, and `resummarize_queue.py` derives its
done/pending state from it — so a fresh clone resumes the campaign at the right
place instead of re-running finished batches. Batch text is excluded because a
manifest's urlmap plus the corpus regenerates it; keeping it locally just avoids a
slow re-stage.

The three campaign paths (`<campaign>/`, `<campaign>_out/`, `<campaign>_manifest.json`)
all default off the manifest stem, so `TSD_FAN_MANIFEST=wave2_manifest.json` alone
selects a campaign. Setting them piecemeal is what silently broke wave2 — see the
v0.8.9 changelog entry.

## Campaigns

| campaign | scope | batches | agents |
|---|---|---|---|
| `fanout` | first hand-staged pass | 26 | done |
| `wave2` | second hand-staged pass | 121 | done |
| `remainder` | 2021-2026 | 76 | 68 outstanding |
| `orphans` | 2024 documents dropped during `fanout` staging | 4 | 4 |
| `packets` | 2010-2020 packet era | 151 | **552** |

**`packets` is chunked far more finely than the others**: `--split-over 80000
--section 40000`, so 96 of its 151 batches fan into sections rather than handing
one agent a 150K-token read. The packet era is 83% of the campaign's tokens at a
median 96K tokens per document; under the default 170K threshold, 79 documents
would each have had a single agent compress 40-170K tokens into ~1,600 words --
re-enacting, at a larger scale, the lossiness this campaign exists to undo.
Capping reads at 59K costs 552 agents instead of 220. Going finer buys nothing:
below an 80K threshold the binding constraint becomes the unsplit 40-59K
documents, so the max read stays 59K.

### The orphan gap

`covered_urls()` counted anything listed in a manifest's `urlmap` as covered.
Staging can catalogue a document and then drop it, and `fanout` did exactly that
to **24** documents -- every 2024 monthly financial statement, the 23-24 budget
amendment resolution, the ACFR management letter, the 2024 operating millage
analysis. `fanout` still reports 26/26 done, truthfully: its batches *are*
finished; those documents simply were not in any of them, and nothing in the
tooling counted what it was *supposed* to process.

Coverage is now computed from batch membership, so a dropped document reads as
uncovered and the next staging run recovers it. Verified: 0 affected documents
are unreachable by a batch.

## Scope

Measured from the corpus (`stage_campaign.py --dry-run` reproduces it):

| | docs |
|---|---|
| exceeded the 6,000-char cap | **786** |
| covered by `fanout` + `wave2` | 391 |
| staged as `remainder` (2026-07-28) | 367 |
| check registers, out of scope | 28 |

The first two passes were staged by hand and between them missed **395**
documents — the queue reported "empty" with half the campaign untouched. The
`remainder` campaign closes that gap, and because its selection is derived from
the corpus rather than remembered, the same command re-run later will surface
anything new that qualifies.

`remainder` is the expensive half: **17.0M tokens of source, 280 agents (~35
waves)**, median document 45,541 chars against 3,885 for what came before. 144
of its documents are packet-era (2010-2019) bundles.

**Check registers are deliberately excluded.** They are 17% of the remaining
documents but 42% of the tokens (median 45,709 vs 3,885 for everything else), and
a prose summary of a few thousand payment rows is the wrong instrument — that data
is already queryable in the separate check-register project.
