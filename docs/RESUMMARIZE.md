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

Measured cost: **~4.4 points of a 5-hour window per agent**. An earlier estimate
of 3.1 came from agents still in flight and was 57% low — estimate from completed
work only.

## State

Nothing needed to resume lives in the session scratchpad:

| what | where |
|---|---|
| manifests (batch -> keys, key -> urls) | `resummarize/*_manifest.json` (in repo) |
| staged batch text + agent output | `~/Downloads/tsd_resummarize_staging/` |
| stored summaries | `~/Downloads/tsd_store_*/batch_*.json` |
| pre-campaign summaries (for comparison) | `~/Downloads/tsd_summaries_backup_*.jsonl` |

Batch text is regenerable from the manifest's urlmap plus the corpus, but keeping
it avoids a slow re-stage.

## Scope

788 documents exceeded the cap. 203 are done: the post-2018 budget-and-policy set,
plus part of a newest-first pass over 2026-2023.

**Check registers are deliberately excluded.** They are 17% of the remaining
documents but 42% of the tokens (median 45,709 vs 3,885 for everything else), and
a prose summary of a few thousand payment rows is the wrong instrument — that data
is already queryable in the separate check-register project.
