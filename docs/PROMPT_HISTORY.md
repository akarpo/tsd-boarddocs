# Prompt History

A running record of the prompts that shaped this project, with the outcome of
each. The initial entries were reconstructed from the build session on
**2026-07-04**; new prompts are appended automatically by a `UserPromptSubmit`
hook (see `docs/OPERATIONS.md` / `.claude/`).

> This is a paraphrased-but-faithful log of user requests + results, not a full
> transcript. It exists so the project's *intent and history* travel with the code.

## Session 1 — 2026-07-04 (build)

1. **"Head to my repo and clone tsd-boarddocs to my Downloads folder."**
   → No exact `tsd-boarddocs` repo existed; identified `akarpo/tools-troysdboarddocs` as the only BoardDocs repo and cloned it.
2. **"Read the .md file."** → Summarized the README (local download→extract→index→retrieve pipeline).
3. **"Wondering if we can make a searchable site with an integrated RAG, large files to Cloudflare R2."** → Proposed a Cloudflare-native RAG site (Pages/Worker + Vectorize + Workers AI + R2).
4. **"Actually maybe build an MCP site (supported in Chrome 149)."** → Grounded **WebMCP** (Chrome 149 origin trial, `document.modelContext`); reframed as one retrieval core behind a website + remote MCP + WebMCP. Decisions: **both server + WebMCP page**, **open to anyone**.
5. **"I already have the board docs in R2 in folder 'troysd-boarddocs'" (R2 token pasted).** → Flagged the live credential; found bucket `media`; later determined the docs weren't actually there (silent `--remote` no-op) and re-uploaded via the pipeline.
6. **"Rename this to tsd-boarddocs on GitHub; one tool that downloads/builds a website + GitHub Actions like tsd-cotpermits."** → Renamed the repo; adopted the cot-permits pattern (one repo, Action-driven, R2 for large files).
7. **"Look at the desktop screenshot (WebMCP trial) + the .md file; does it align?"** → Answered the origin-trial form (apex origin + subdomain match, uncheck third-party, 0–10k usage); confirmed the design doc aligned; adopted `search`/`fetch` + "copy context" fallback + hybrid-search idea.
8. **(WebMCP origin-trial token pasted.)** → Decoded/verified it; wired into `index.html` `<head>`.
9. **"Wrangler is now logged in."** → Created the Vectorize index; validated the pipeline on a 2026 slice (1,742 chunks); deployed to `pages.dev`; MCP + search verified.
10. **"Is this ready to connect Pages + add the domain?"** → Yes; guided Git-connect. The Git flow created a **Worker**, not Pages → restructured the repo to Worker + Static Assets.
11. **"Where are bindings set?" / "What line to edit?" (binding-dialog screenshot).** → Confirmed it's a Worker; moved bindings into `wrangler.toml`.
12. **"It deployed successfully."** → Verified site + `/api/search` + `/mcp` live on `tsd-boarddocs.karpowitsch.org`.
13. **"'Open source PDF' gives a 404."** → Diagnosed `wrangler`'s `#`-key truncation; built the `tsd-ingest` exact-key uploader; all 278 citations fixed.
14. **"Start indexing all the old years."** → Downloaded all 346 meetings (2010–2026); ran the full extract→chunk→embed→R2 pipeline.
15. **"Refactor search results — date, meeting type, agenda position, embed PDF/PPTX/DOCX viewer, AI summaries."** → Agreed; chose **convert-to-PDF** viewing and **local, resumable summaries** with a pending-flag. Baked `meeting_type` + `agenda_item` into the chunker; built the card + PDF-viewer UI.
16. **"Use Opus 4.8 for summaries, over multiple days; monitor tokens (at ~50%)."** → Set summaries as a resumable, budget-controlled multi-day Opus task.
17. **"Build part of the UI now."** → Shipped the card redesign + inline PDF viewer + metadata passthrough (v0.3.0).
18. **"Fully document this project — multiple .md files, prompt history (captured going forward), tooling with version tracking, all on GitHub."** → This documentation set + `CHANGELOG.md` + prompt-capture hook.
