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

`inDir`/`outDir` are relative to the scratchpad; batch text and agent output live
outside the repo (see "State" below).

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
emit a wave once the 5-hour window passes **75%**, leaving headroom so the limit
can never land mid-write.

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
| 5h at or past 75% | genuinely out of headroom |

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

## Scope

788 documents exceeded the cap. 203 are done: the post-2018 budget-and-policy set,
plus part of a newest-first pass over 2026-2023.

**Check registers are deliberately excluded.** They are 17% of the remaining
documents but 42% of the tokens (median 45,709 vs 3,885 for everything else), and
a prose summary of a few thousand payment rows is the wrong instrument — that data
is already queryable in the separate check-register project.
