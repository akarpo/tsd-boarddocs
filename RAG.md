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
- [ ] Index cache to R2 (re-upload on corpus change) — pending the first index build
- [~] Opt-in CI upload in `verify-boarddocs.yml` (gated on a `CLOUDFLARE_API_TOKEN` secret)
- [ ] Exercise end-to-end against a built index (needs `sentence-transformers`
      installed and a corpus built under `$TSD_BOE_ROOT`)
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
