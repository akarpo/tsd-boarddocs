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

### Store, then prove it stored

`validate_fanout.py` **rewrites the store file each run**, so validating batches in
separate invocations leaves only the last one staged and `summarize.py` reports
`stored 1 summaries` for a wave of four. Validate every batch of a wave in ONE
invocation:

    TSD_FAN_MANIFEST=packets_manifest.json TSD_FAN_IN=packets TSD_FAN_OUT=packets_out \
      python3 scripts/validate_fanout.py --only pk_109 --only pk_110   # ...all of them
    python3 summarize.py --store-dir resummarize/stores/packets

Then confirm the write landed by comparing local and live `verbose` lengths.
**Query D1 directly — not the site API.** Turnstile now 403s any server-side call
to `/api/summary`, so `curl`/`urllib` verification silently fails:

```bash
npx wrangler d1 execute tsd-boarddocs --remote --json \
  --command "SELECT substr(url,-20) AS u, length(verbose) AS v FROM summaries
             WHERE url LIKE '%011618Org_RegMtg.pdf'"
```

The column is **`verbose`**, not `summary_verbose`; the table is
`summaries(url TEXT PRIMARY KEY, paragraph, page, verbose, updated)`.

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

### The cross-document figure trap

The validator checks each figure against **that batch's own source**, which is the
correct scope and also the one an author working through a year in order keeps
walking into. Once you have read March, it is natural to write in the December
summary that the site "moved from the 8 acres of Section 16 named in March" — and
just as natural to reach for the March dollar figure while doing it. That figure is
true, and it is *not in December's packet*, so it validates as `unknown` and the
batch fails FABRICATED.

This happened three times in the 2018-2017 waves (pk_118/119, pk_097, pk_107/108),
always the same way and always on connective narrative rather than on the packet's
own numbers. The fix is never to drop the connection — cross-meeting continuity is
most of what these summaries are for — but to make it **nominal, not numeric**:

> ✗ "the same buyer that took Section 16 for $3,383,000.00 in March"
> ✓ "the same buyer that took the Section 16 land in March"

> ✗ "would be financed with $11,000,000 of bonds in 2018"
> ✓ "would be financed by bond issue in 2018"

Figures that *are* quoted inside the packet — a minutes section reproducing last
month's resolution, a memo citing a prior award — validate fine, because they are
genuinely in the source. The rule is about where the number is printed, not where
the event happened.

Cheap pre-flight: after drafting, grep the draft for 4+-digit figures and confirm
each appears in that batch's part files before running the validator.

### What the validator cannot see, and what catches it instead

`validate_fanout.py` checks **figures**. It has no view of whether a sentence
means what the source means. On 2026-08-08 pk_092 rendered the Adair resolution as
"rescinding the Board's May 12, 1998 action to withdraw as a participant" — which
attaches "to withdraw" to the 1998 action instead of the 2016 one and thereby
reverses the district's position in a Headlee suit against the State. The source
reads: "rescinds its action of May 12, 1998 and hereby withdraws as a participant
in the Adair lawsuit, effective the date of this action, October 18, 2016." 1998
was joining; 2016 was leaving.

That sentence contains exactly one figure — 1998 — and 1998 is in the source, so
the batch validated **100% clean with the meaning inverted**. The page and verbose
tiers were both correct; only the paragraph was wrong. No check in this pipeline
can catch that class of error.

What caught it was reading the year in order. Each packet reproduces the previous
meeting's minutes on consent, so consecutive batches summarize many of the same
events from two different source documents — and the two renderings disagreed.
**That overlap is a free consistency check on the batch before**, and it is a
better argument for ascending-within-year than legibility is. When two summaries
of one event disagree, go to the source text; the answer is always there.

Watch for it hardest on rescissions, withdrawals, reversals and anything with two
dates in one sentence, where the grammar decides which party did what to whom.

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

### Working order

Batch ids are always assigned oldest-to-newest by `stage_campaign.py` (`pk_000` is
the 2010 end, `pk_150` the 2020 end). Which end the queue *works from* is a
separate question, and it is stored in the manifest:

    {"order": "newest", "batches": {...}}

`resummarize_queue.py` reads it (`TSD_FAN_ORDER` overrides; default `oldest`), so
selecting a campaign selects its order — the same reason the three campaign paths
default off the manifest stem. `stage_campaign.py --order newest|oldest` sets it.

This was missing until 2026-08-06, and it is worth understanding why it mattered.
`packets` is documented as worked newest-first, and its first two waves *were* —
but they had been launched from hand-picked batch lists, not from `next`, which
only ever walked ascending. The two had disagreed from the start and nothing said
so. The next `next` would have handed out **2010** while 2019 sat half-finished,
and every signal would still have looked healthy: the done-count climbs, each
batch validates clean, the campaign completes eventually. Only the *order* would
have been wrong, and order is the one thing no per-batch check can see.

The same shape as the path drift above and the orphan gap below — the tooling
faithfully reports what it processed and has no opinion about what it was supposed
to process. Putting the order in the manifest removes the second thing to remember.

#### What the 2018-2017 waves actually did: descend by year, ascend within it

`next` packs a wave off the manifest order. From 2026-08-07 the waves stopped using
it, because `pack()` seeds one wave per split batch and then fills with singles —
and by 2018 *every* remaining batch is a split, so the packer kept reaching past
the year in hand. The working rule became:

**Go down the ladder by year, up it within the year.** 2019, then 2018, then 2017,
then 2016 — but January to December inside each. A year read in order is a year
whose story is legible: the March resolution that sites a building, the December
one that moves it, the January one that corrects a contractor's name. Read
newest-first those are three unrelated items.

That means claiming batches by hand rather than via `next`. There is no `claim`
subcommand; take the lease directly:

```python
import sys, os
sys.path.insert(0, 'scripts'); os.environ['TSD_FAN_MANIFEST'] = 'packets_manifest.json'
import resummarize_queue as q
q.take_lease(['pk_109', 'pk_110'])
```

`release` still clears them, `status` still shows them as in-flight. The only thing
skipped is the headroom guardrail, so check `status` for the 5h reading first.

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

Status as of 2026-08-16:

| campaign | scope | batches | status |
|---|---|---|---|
| `fanout` | first hand-staged pass | 26 | **complete** |
| `wave2` | second hand-staged pass | 121 | **complete** |
| `orphans` | 2024 documents dropped during `fanout` staging | 4 | **complete** |
| `remainder` | 2021-2026 | 76 | **complete** |
| `packets` | 2010-2020 packet era | 151 | **84 done, 67 pending** |

**Every year from 2015 onward is complete.** Coverage by year, reconciled across
*all five* manifests rather than any single campaign's done-count:

| year | done/total | campaign(s) |
|---|---|---|
| 2015-2026 | **complete** | `packets` (2015-2020) + the four finished campaigns |
| 2010-2014 | 0/67 | `packets` |

The one-line check, which is the only tally worth trusting:

```bash
python3 - <<'EOF'
import json, collections, glob, os
b = json.load(open('resummarize/packets_manifest.json'))['batches']
done = {os.path.basename(p)[:-5] for p in glob.glob('resummarize/packets_out/pk_*.json')}
yr = collections.defaultdict(lambda: [0, 0])
for bid, keys in b.items():
    y = keys[0][:4]; yr[y][1] += 1; yr[y][0] += bid in done
for y in sorted(yr): print(f"{y}: {yr[y][0]}/{yr[y][1]}")
EOF
```

Note it keys the year off the **document key** (`2018_117_...`), not the URL path —
see the folder-date warning below.

**Count the packet era by filename date, not by folder date.** The 2010-12 and
2018-19 packet folders carry placeholder dates (`YYYY-01-01`), which `build_index.py`
repairs via `filename_meeting()` — so `101519RegMtg.pdf` is 2019-10-15 even though
its folder says 2019-01-01. Batch ids were assigned off the *repaired* dates and are
correctly chronological, but any tally computed from the url path is not: doing that
put ten 2018 meetings in 2019 and reported 2019 complete when six batches remained.

Remaining after wave 27 (2026-08-16), batches/agents by filename date:

| year | batches | agents |
|---|---|---|
| 2014 | 14 | 48 |
| 2013 | 12 | 38 |
| 2012 | 13 | 45 |
| 2011 | 13 | 48 |
| 2010 | 15 | 50 |
| **total** | **67** | **229** |

Ascending within 2014 starts at `pk_053`.

### `packets` is chunked far more finely

Staged with `--split-over 80000 --section 40000`, so 96 of its 151 batches fan
into sections rather than handing one agent a 150K-token read. The packet era is
83% of the campaign's tokens at a median 96K tokens per document; under the
default 170K threshold, 79 documents would each have had a single agent compress
40-170K tokens into ~1,600 words — re-enacting, at a larger scale, the lossiness
this campaign exists to undo. Capping reads at 59K costs 552 agents instead of
220. Going finer buys nothing: below an 80K threshold the binding constraint
becomes the unsplit 40-59K documents, so max read stays 59K.

**The split path is proven.** The first two `packets` waves included 9 split
batches (up to 7 sections for the Dec 2019 packet); all validated clean, so
section-notes-then-synthesise preserves figure fidelity.

## Measured costs

Everything below is measured, not modelled. `PTS_PER_AGENT = 4.9` in the queue is
conservative for most material and should be read as a ceiling, not an estimate.

| material | pts/agent | tokens/agent | notes |
|---|---|---|---|
| `wave2` small documents | ~1.9 | ~85K | median 3,885-char docs |
| `remainder` 2021-2022 | 2.35 | ~78K | lightest measured |
| `remainder` 2023-2026 | 3.2 | ~105K | figure-dense financials |
| `packets`, few splits | 2.92 | ~91K | 4 splits of 11 batches |
| `packets`, split-heavy | **3.20** | ~97K | 5 splits of 6 batches |
| `packets` 2015, split-heavy | 2.14 | ~92K | 4 splits of 5 batches, 21 agents |

The 2015 figure is the cheapest split-heavy wave measured and cuts against reading
`--split-over` as the cost driver: wave 27 was 4 splits of 5 batches — the same
shape as the 3.20 row — and ran a third cheaper. What moved was the material, not
the fan-out. Size a year off its own first wave rather than off the split ratio.

**Agent spend runs ~3.6x the batch's source tokens** — measured across four waves
(3.2x, 3.5x, 3.7x, 4.0x). Use that to project a year: 2018's 1.47M source tokens
is ~5.2M spent.

### Per-agent cost falls as the wave gets bigger

The 2016 waves of 2026-08-08, measured off the 5-hour meter:

| wave | agents | points | pts/agent | subagent tokens |
|---|---|---|---|---|
| 18 (pk_081-083) | 10 | 30 | 3.0 | 1.02M |
| 19 (pk_084-086) | 11 | 29 | 2.6 | 0.96M |
| 20 (pk_087) | 1 | 4 | 4.0 | 0.19M |

Wave 20 burned 4 points for a single agent because **a wave costs 1-1.5 points
before any agent runs**. Validation, the D1 store, the read-back, reading the
summaries to write the commit and the commit itself are all main-loop turns
against a large cached context, and they cost the same whether the wave held one
batch or eleven. In tokens per point: 34K on wave 18, 49K on wave 20.

So prefer the biggest wave the headroom allows, and treat a one-batch wave as
what it is — a way to spend a remainder that would otherwise expire at the window
roll, not an efficient unit of work. Sizing at 2.6-3.0 pts/agent held for the
10-11 agent waves here, below the 3.2-3.5 the split-heavy 2017 waves needed;
2016's packets split into 4-5 sections where 2017's ran to 7.

**Size split-heavy waves at 3.2-3.5 pts/agent.** Sizing a 30-agent split-heavy
wave at the 2.92 measured on a split-light one overshot the 90% release line and
landed at 96%. Nothing was lost, but the margin was thinner than intended --
section agents read ~40K each against ~24K for a normal batch.

Split batches also **serialise**: every section must finish before its synthesis
agent starts, so a split-heavy wave takes ~28 minutes where a comparable
`remainder` wave takes ~10.

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

Measured from the corpus, reconciled 2026-07-30:

| | docs |
|---|---|
| exceeded the 6,000-char cap | **786** |
| re-summarized | 359 + all of `remainder` and `orphans` |
| remaining (all packet era) | 134 batches / 496 agents |
| check registers, out of scope | 69 |

**Check registers are deliberately excluded.** A prose summary of a few thousand
payment rows is the wrong instrument — that data is queryable in the separate
check-register project.

Three separate gaps were found by reconciling *what was supposed to be processed*
against *what was*, rather than trusting any campaign's own done-count:

1. **395 documents in no manifest at all** — `fanout` and `wave2` were staged by
   hand and between them missed half the affected set. The queue reported "empty".
2. **24 documents catalogued but never batched** (the orphan gap below).
3. **14 clean batches reported as failed** — a path-coupling bug, not bad data.

Each looked like completed work from the outside. `stage_campaign.py --dry-run`
now reproduces the reconciliation on demand, and re-running it surfaces anything
newly qualifying, so the gap cannot silently reopen.
