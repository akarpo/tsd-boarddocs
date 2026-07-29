export const meta = {
  name: 'tsd-resummarize',
  description: 'Re-summarize Troy SD BoardDocs documents from FULL text (fixing the 6000-char truncation), one agent per batch; oversized budget books split into sections then synthesized',
  phases: [
    { title: 'Batches',  detail: 'one agent per multi-document batch file' },
    { title: 'Sections', detail: 'section notes for the two oversized ISD budget books' },
    { title: 'Synthesis', detail: 'assemble each oversized book into three tiers from its section notes' },
  ],
}

// Durable staging root -- deliberately NOT the session scratchpad, which is
// wiped between sessions and has a different path each time. Override with
// args.dir if the batches live somewhere else.
//
// The default is a LITERAL path: workflow scripts have no Node API (no __dirname,
// no process.env), so it cannot be derived from the checkout location the way the
// Python tools do. The previous `process.env.HOME` fallback threw "process is not
// defined" and killed the run before any agent started; it survived unnoticed
// because every launch passed args.dir, which short-circuits the `||`.
// `resummarize_queue.py next` now emits `dir` explicitly, so this literal is only
// reached on a hand-written launch.
const A0R = typeof args === 'string' ? JSON.parse(args || '{}') : (args || {})
const DIR = A0R.dir || '/Users/Alex/Downloads/tsd-boarddocs/resummarize'
const IN  = `${DIR}/${A0R.inDir  || 'fanout'}`
const OUT = `${DIR}/${A0R.outDir || 'fanout_out'}`

const A       = typeof args === 'string' ? JSON.parse(args || '{}') : (args || {})
const normal  = A.normal || []     // ["batch_003", ...]
const giants  = A.giants || []     // [{batch, key, parts:[...]}, ...]

const TIERS = `Write three tiers per document, in neutral factual prose. Do NOT open with "This document".
- "paragraph": 2-4 sentences (~60-110 words). What it is, plus the single most consequential fact.
- "page": a structured single-page summary (~350-600 words). Short labeled sections; use markdown tables for figure sets where they help. Separate lines with \\n.
- "verbose": thorough (~900-1600 words) capturing all substantive content — every dollar amount, date, name, vote, contract party, address, policy number, millage rate, fund balance. This is what search indexes, so be dense with proper nouns and figures.

ACCURACY IS THE ENTIRE POINT of this task. These documents were previously summarized from only a truncated prefix of their text (some as little as 1.6%), and the whole purpose of redoing them is fidelity to the full document. Every summary you write is machine-checked against the source text you were given, figure by figure.

**Do not write any number that does not literally appear in your source text.**
- NO arithmetic. Do not compute month-over-month changes, year-over-year deltas, totals, subtotals, variances, percentages, per-pupil figures, or "X is Y under budget". Even when the calculation is trivially correct and obviously useful, a derived number is a FAILURE here and will be flagged.
- These are largely monthly financial statements where cumulative figures invite comparison across periods. Resist it. Report what each statement states.
- You may describe a relationship in words without quantifying it — "expenditure exceeded revenue", "the figure rose sharply", "well ahead of the calendar" are all fine. What you may not do is put a number on it that the source does not print.
- Never round silently, never carry a figure over from a similar document, never reconstruct a figure you expect to be there.
- The PDF extraction sometimes splits a number with an internal space ("886, 000") or glues two together ("12,05012,022"). Read them correctly and write them normally — that is transcription, not derivation.
- If a document is thin or purely administrative, write proportionally shorter tiers rather than padding.`

phase('Batches')
const batchWork = normal.map((b) => () =>
  agent(
`Read ${IN}/${b}.txt in full with the Read tool — every line, using offset/limit if it exceeds one read. It contains one or more Troy School District (Michigan) Board of Education documents concatenated. Each begins with a header block:

### DOCUMENT KEY: <key>
TITLE: ... / MEETING DATE: ... / TYPE: ... / PREVIOUSLY SUMMARIZED FROM: ...%
======================================================================

${TIERS}

Then use the Write tool to save ${OUT}/${b}.json as a single JSON object keyed by the EXACT "### DOCUMENT KEY:" value (not the title, not the url).

If that file ALREADY EXISTS, you are re-running a batch whose previous output failed verification — overwrite it. Do not read it, do not treat its presence as "already done", and do not skip the write. A batch that is re-run without its file being rewritten fails identically forever and burns one agent per wave.
{"<document key>": {"paragraph": "...", "page": "...", "verbose": "..."}, ...}

Include every document in the file. Valid JSON only — properly escaped strings, no trailing commas, no markdown fences.

Return one line: the number of documents summarized and the output path.`,
    { label: b, phase: 'Batches' })
)

// The two oversized ISD budget books: section notes in parallel, then one synthesis
// agent per book. Splitting keeps each agent's context small enough that the read
// stays cheap, and the synthesis agent never has to hold the whole book.
const giantWork = giants.map((g) => async () => {
  const notes = await parallel(
    g.parts.map((p, i) => () =>
      agent(
`Read ${IN}/${p}.txt in full with the Read tool — every line, using offset/limit as needed. This is section ${i + 1} of ${g.parts.length} of a single large Michigan intermediate school district budget book.

Produce DETAILED STRUCTURED NOTES on this section only — not a polished summary. Capture every fund name, dollar amount, percentage, millage rate, FTE count, fund balance, policy citation, program name and date that appears. Preserve the document's own structure and labels. Dense and specific; length is not a concern. State only what is in this section.

Return the notes as your final message (do not write a file).`,
        { label: `${g.batch} s${i + 1}`, phase: 'Sections' })
    )
  )
  const good = notes.filter(Boolean)
  if (!good.length) return null
  return agent(
`Below are section-by-section notes covering one complete Michigan intermediate school district budget book, in order. They are the only source available to you — work solely from them.

${good.map((n, i) => `===== SECTION ${i + 1} NOTES =====\n${n}`).join('\n\n')}

${TIERS}

Write the tiers for this single document, whose key is exactly: ${g.key}

Use the Write tool to save ${OUT}/${g.batch}.json as:
{"${g.key}": {"paragraph": "...", "page": "...", "verbose": "..."}}

Valid JSON only. Return one line confirming the path.`,
    { label: `${g.batch} synth`, phase: 'Synthesis' })
})

const results = await parallel([...batchWork, ...giantWork])
const ok = results.filter(Boolean).length
log(`completed ${ok}/${results.length} units (${normal.length} batches + ${giants.length} oversized books)`)
return { requested: results.length, completed: ok }
