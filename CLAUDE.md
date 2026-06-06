# CLAUDE.md — TroySD BoardDocs RAG

This repo is the **retrieval** half of a RAG system over Troy School District
(Michigan) Board of Education documents. **You — Claude Code at the CLI prompt —
are the generation half.** There is no LLM API call anywhere in the tooling:
`retrieve.py` finds the relevant excerpts and you answer from them.

## Answering a question about TroySD board matters (the RAG protocol)

When the user asks a substantive question about Troy SD Board of Education
business — decisions, dates, people, budgets, policies, meetings, etc. — do
retrieval-augmented generation rather than answering from memory:

1. **Retrieve.** Run the retriever with the user's question:
   ```bash
   python retrieve.py "<the user's question>" --full -k 20
   ```
   - `--full` returns complete chunk text — ground on whole chunks, not the
     truncated previews `retrieve.py` prints by default.
   - Raise `-k` (e.g. `40`) for broad or ambiguous questions; lower it for
     narrow ones.
   - Scope by date with `--since YYYY-MM-DD` / `--until YYYY-MM-DD`.
   - Add `--grep "<literal>"` to require a term (proper nouns, "bond",
     "millage", a board member's name…).

2. **Read** the returned chunks. Each is headed with its rank, cosine score, and
   source: `meeting_date | meeting_name | file | chunk N`.

3. **Answer ONLY from the retrieved chunks.** Do not use outside knowledge about
   the district. Cite every factual claim with its source — at minimum the
   meeting date and name, e.g. *"The board approved the bond on 2024-03-19
   (Regular Meeting)."* Quote short phrases verbatim when precision matters.

4. **If the chunks don't answer it, retrieve again before giving up** — rephrase
   the query, raise `-k`, or drop filters. If the corpus still doesn't cover it,
   say so plainly rather than guessing.

5. **On conflicts, prefer the most recent meeting** and note the disagreement.

## Prerequisites (tell the user if retrieval fails)

`retrieve.py` reads a prebuilt local index that is **not** committed (several GB
of public-record PDFs). It needs:

- Python deps installed: `pip install sentence-transformers numpy`.
- A built index under `$TSD_BOE_ROOT` (default `~/tsd-boe-data`). If
  `retrieve.py` reports no index, the corpus hasn't been built yet — point the
  user at the pipeline in `README.md`: `download_troysd.py` → `extract_all.py` →
  `build_index.py`.

## Working on the tooling

Standard Python 3.10+; no build step. See `README.md` for the full pipeline and
`RAG.md` for the RAG architecture and build status. If you change retrieval,
**keep `retrieve.py`'s output format stable** — the RAG protocol above relies on
reading it to ground and cite answers.
