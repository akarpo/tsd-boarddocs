# RAG: architecture & build log

Tracks turning this toolset from a retriever into an end-to-end
retrieval-augmented generation (RAG) system, and records how the pieces fit.

## Architecture: the CLI prompt is the interface

```
                       ┌──────────────────────────────────────────┐
  user question  ────▶ │  Claude Code  (the CLI prompt)            │
                       │   = the GENERATION half of the RAG        │
                       └───────────────┬────────────────▲──────────┘
                                 runs  │                │  reads chunks, answers
                           retrieve.py │                │  grounded + cited
                                       ▼                │
                       ┌──────────────────────────────────────────┐
                       │  retrieve.py  →  _index/vectors.npy        │
                       │   = the RETRIEVAL half (local, no API)     │
                       └──────────────────────────────────────────┘
```

- **Retrieval** is `build_index.py` (chunk + embed with `all-MiniLM-L6-v2`) plus
  `retrieve.py` (top-k cosine search) — fully local, no API key.
- **Generation** is **Claude Code at the CLI prompt**. It runs `retrieve.py`,
  reads the excerpts, and answers grounded in them with citations. There is no
  external LLM API call — the model in the loop is the agent already at the
  prompt.
- The protocol the agent follows lives in [`CLAUDE.md`](CLAUDE.md).

This deliberately avoids an in-script Claude/OpenAI call: the interface through
which the RAG runs and touches the retrieval logic is the CLI prompt itself.

## Design decisions

- **No external API / key / SDK.** The generator is the CLI agent, not
  `anthropic`/`openai`. Nothing in the repo pays for inference.
- **`retrieve.py` is unchanged.** Its human-readable output (rank, score, source
  header, text) is exactly what the agent reads and cites. Run it with `--full`
  so the agent grounds on complete chunks rather than truncated previews.
- **Grounding + citations** are enforced by the `CLAUDE.md` protocol: answer
  only from retrieved chunks, cite meeting + date, and say so when the corpus is
  silent instead of guessing.
- **Filters carry through.** `-k`, `--since` / `--until`, and `--grep` let the
  agent scope retrieval per question.

## Status

Legend: `[x]` done · `[ ]` todo · `[~]` optional

- [x] Retrieval layer (`build_index.py`, `retrieve.py`) — pre-existing
- [x] Generation layer = CLI agent, codified as the `CLAUDE.md` RAG protocol
- [x] README documents the CLI-driven RAG flow
- [x] Corpus downloaded — 344 meetings, ~3,222 files, 3.4 GB (in-repo `tsd-boe-data/`)
- [x] Cloudflare R2 mirror — `sync_r2.py` (pull/push/manifest); public reads at
      `media.karpowitsch.org/troysd-boarddocs/`; seeded (3,222 objects + manifest)
- [x] Index cached to R2 — `sync_r2.py index` pushes `_index/` (vectors + chunks + model); seeded (189 MB) at `media.karpowitsch.org/troysd-boarddocs/_index/`
- [~] Opt-in CI upload in `verify-boarddocs.yml` (gated on a `CLOUDFLARE_API_TOKEN` secret)
- [x] Index built + RAG verified — 2,738 docs → 43,603 chunks, filtered to 42,807
      (`all-MiniLM-L6-v2`); `retrieve.py` returns relevant, well-ranked results
- [x] Coverage audit — `audit_coverage.py` cross-references every live agenda
      item against the corpus and writes `_coverage_audit.csv` (344 meetings /
      2,156 items). A fast `_index.csv` pre-filter, then a drift-proof live
      confirm of every candidate (BoardDocs regenerates id tokens on edits, so it
      matches by filename): 48 `doclike-no-file` + 2 `missed-fetchable` real gaps,
      4 drift false-positives correctly cleared (e.g. the 2024-03-05 Levinson
      Report stays flagged; the 2024-05-07 Algebra deck is correctly `ok`)
- [x] Scraper hardened to also harvest file links embedded in published minutes
      (`BD-GetMinutes`), which `BD-GetPublicFiles` never returns
- [~] `retrieve.py --json` for stricter machine parsing (text output is fine today)
- [~] A `/ask` Claude Code slash command as an explicit alternative to the
      ambient CLAUDE.md protocol
- [~] Capture good question → answer pairs as regression examples

## Progress log

- 2026-06-06 — Reframed the build around the CLI-as-generator model (dropped an
  earlier Claude-API `ask.py` direction — no external API wanted). Added the
  `CLAUDE.md` RAG protocol and this doc, and a README section. End-to-end run
  still pending a locally built index.
- 2026-06-06 — Downloaded the full BoardDocs corpus (344 meetings, 3,222 files,
  3.4 GB), moved it in-repo, and mirrored it to Cloudflare R2
  (`media/troysd-boarddocs/`, public) via the new `sync_r2.py` + manifest.
  Hardened `safe_name()` (collapse `..`) after 5 keys failed to upload on `..`.
- 2026-06-06 — Built the index: `extract_all` (2,738/3,222 docs yielded text) →
  `build_index` (43,603 chunks, `all-MiniLM-L6-v2`) → `filter_index` (kept 42,807).
  Verified `retrieve.py` against it; wrapped the cosine matmul in `np.errstate`
  to silence benign float32 FP warnings. RAG is live end-to-end.
- 2026-06-07 — Closed the coverage blind spot surfaced by the missing NSK12 /
  Levinson report. Two parts: (1) hardened `download_troysd.py` to also pull file
  links embedded in published minutes (`BD-GetMinutes`), which the public-files
  endpoint never returns; (2) added `audit_coverage.py`, which audits all 344
  meetings (2,156 agenda items) and emits `_coverage_audit.csv`. First cut judged
  capture from `_index.csv` alone and over-reported (BoardDocs regenerates item /
  file id tokens on every agenda edit, so a captured item can look uncaptured —
  e.g. the 2024-05-07 Algebra deck). Fixed with a two-pass design: fast manifest
  pre-filter, then a live confirm of each candidate that matches by filename (the
  only stable key) against disk. Result: 48 `doclike-no-file` (presented, never
  attached — Levinson among them) + 2 `missed-fetchable` (a genuinely missed
  2020-07-21 meeting BoardDocs still serves) real gaps; 4 drift false-positives
  cleared. The NSK12 re-index landed too: the Findings Report is now searchable
  under both the Dec-5-2023 and Mar-5-2024 workshops (43,713 chunks).
