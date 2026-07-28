# The dataset artifacts

Four downloadable files, built by `scripts/build_dataset.py` from the D1
`summaries` table plus the local chunk index, and served gzipped from R2:

    https://media.karpowitsch.org/troysd-boarddocs/dataset/<name>.gz

| file | rows | raw | gz | what it is |
|---|---|---|---|---|
| `corpus-map.jsonl` | 2,798 | 2.6 MB | 0.5 MB | one line per document: paragraph summary + metadata |
| `summaries-full.jsonl` | 2,798 | 13.6 MB | 3.5 MB | all three summary tiers per document |
| `figures.csv` | 334,163 | 65.0 MB | 8.0 MB | every currency figure in the source text, with its label |
| `documents.csv` | 2,798 | 0.9 MB | 0.1 MB | `doc_id` → url, title, meeting; join key for `figures.csv` |

## Why `corpus-map.jsonl` is the interesting one

At ~2.6 MB / **~370K tokens**, every paragraph summary in the district's entire
board history fits inside a single model context. That is a different capability
from search, not a smaller one:

- **Search** answers *"which document mentions X"* — it ranks and returns a few.
- **The corpus map** answers *"across fifteen years, when did this recur, and
  which meetings do I need"* — because the model holds all 2,798 documents at
  once and can reason over the whole set before fetching anything.

Typical use: load the map, let the model pick the handful of relevant documents,
then pull their full text from `/api/fetch` or the source PDF in R2.

## `figures.csv` — and the rule it follows

The summaries are prose, and prose is useless for budget analysis: *"the general
fund balance was $12,450,891"* is retrievable text but you cannot sum it, trend
it, or chart it. `figures.csv` is the structured layer.

| column | |
|---|---|
| `amount` | the figure exactly as it appears in the source |
| `label` | the words immediately preceding it (`Total Expenditures`, `Debt Service`) |
| `meeting_date` | the meeting the document belongs to |
| `doc_id` | join key into `documents.csv` |
| `context` | ±80 characters around the figure, so any row can be eyeballed |
| `chunk_id` | the exact indexed chunk it came from |

**Nothing in this file is computed.** No deltas, no totals, no percentages, no
per-pupil figures. Every `amount` is a string that appears verbatim in the chunk
it is attributed to, and `--verify` re-reads the source to prove it:

    python3 scripts/build_dataset.py --figures --verify
    #   verified verbatim: 334,163   NOT found: 0

This is the same discipline the re-summarization campaign runs on, for a sharper
reason: a derived number in a CSV is more dangerous than one in a paragraph,
because it looks authoritative and gets charted. Consumers do their own
arithmetic, on rows they can trace back to a document.

Bare 4-digit numbers are excluded deliberately — they are overwhelmingly years,
policy numbers and codes, and including them buries the real figures in noise.
A figure must have at least one thousands separator.

### Worked example

*"How much has the budget grown from 2018-19 to 2025-26?"* — filter
`label = "Total Expenditures"`, take figures over $100M:

    2018-09-18   154,129,663      2025-09-16   194,285,613
    2018-10-16   154,129,663      2025-10-14   194,285,613
    2018-11-20   154,129,663      2025-11-18   194,285,613

The figure repeating across consecutive monthly statements is the cross-check
that you have the adopted budget and not a one-off. The subtraction is yours to
do; the dataset's job is to hand you two traceable numbers, not a conclusion.

## Rebuilding

    python3 scripts/build_dataset.py --all --verify --refresh   # --refresh re-pulls D1

Output goes to `dataset/` (gitignored — 82 MB raw, and rebuildable in about a
minute). Upload is a gzip + `PUT /r2put` per file; see OPERATIONS.

## Known gap: the packet era

Documents before 2020 are **full-meeting packets** — one bundled PDF per meeting,
named like `022718RegMtg` — not individual titled documents. Their content is
fully indexed and appears in `figures.csv`, but a title-based filter finds
nothing for those years:

    year   chunks   budget-titled documents
    2018    2,439        0
    2019    2,738        0
    2021    2,825      540

The figures are there; the *titles* are not. Filter pre-2020 material by `label`
and `context`, not by document title.
