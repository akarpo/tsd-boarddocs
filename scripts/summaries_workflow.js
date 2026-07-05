export const meta = {
  name: 'tsd-summaries',
  description: 'Generate 3-tier Opus summaries for a prepped set of Troy SD BoardDocs batch files (args.batches = file count)',
  phases: [{ title: 'Summarize', detail: 'one Opus agent per batch file, writing tiers to /tmp/tsd_out' }],
}

const N = (args && args.batches) || 10
const inDir = (args && args.inDir) || '/tmp/tsd_batches'
const outDir = (args && args.outDir) || '/tmp/tsd_out'
const pad = (i) => String(i).padStart(3, '0')

const prompt = (i) => `You are writing archival summaries of Troy School District (Michigan) Board of Education documents for a public search-and-AI site. Accuracy and specificity matter — these are the primary searchable artifact for each document.

Read the file ${inDir}/batch_${pad(i)}.json with the Read tool. It is a JSON array of documents; each has: url, title, meeting_date, meeting_type, meeting_name, agenda_item, and text (the document's extracted text — may be OCR, may be truncated at 6000 chars).

For EACH document write three summary tiers, in neutral factual prose (do NOT start with "This document"):
- "paragraph": 2-4 sentences (~60-90 words). What the document is plus its most important fact(s). Shown in search results.
- "page": a structured single-page summary (~200-320 words). Use short labeled sections and bullets where natural (e.g. "What it is", key figures/decisions, who/what, "Purpose"). Separate lines with \\n.
- "verbose": a thorough summary (~400-650 words) capturing all substantive content: names, dollar amounts, dates, vote outcomes, resolution text, contract parties, addresses, policy numbers. Be rich and specific with proper nouns and figures — this is what search indexes.

Only state facts present in the text; never invent. If a document is thin or purely administrative, make the tiers proportionally shorter rather than padding.

Then use the Write tool to save your results to ${outDir}/batch_${pad(i)}.json as a single JSON object mapping each document's url to its tiers:
{"<url>": {"paragraph": "...", "page": "...", "verbose": "..."}, ...}
Include every document from the batch. Ensure it is valid JSON (properly escaped strings, no trailing commas, no markdown fences).

Return one line: how many documents you summarized and the output path.`

phase('Summarize')
const results = await parallel(
  Array.from({ length: N }, (_, i) => () =>
    agent(prompt(i), { label: `batch ${pad(i)}`, phase: 'Summarize' })
  )
)
const ok = results.filter(Boolean).length
log(`completed ${ok}/${N} batches`)
return { batches: N, completed: ok }
