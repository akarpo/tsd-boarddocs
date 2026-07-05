# Prompt History

A running record of the prompts that shaped this project, with the outcome of
each. New prompts are appended automatically by a `UserPromptSubmit` hook when
running under the Claude Code CLI in this repo (see `.claude/`); sessions driven
another way are reconstructed by hand — as Session 1 and Session 2 below were.

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

## Session 2 — 2026-07-05 (D1 migration, summaries, filters, browse)

19. **"If we're doing our own summaries, why do we need Workers AI at all?"** → Dropped Workers AI + Vectorize; moved search to **D1 FTS5 / BM25** (v0.4), free tier, no neuron cap.
20. **"Proceed with the refactor for the live site."** → Shipped the D1-backed site: search join, `/api/summary`, and `/doc` serving R2 **same-origin** (fixed the cross-origin PDF embed).
21. **"What about the Opus summaries?" / "The three summaries made 10MB? No — find a technical way; it's all text."** → Corrected the framing (summaries are tiny text in D1, not a storage problem); built the `summaries` table + resumable harness; **search leverages the verbose summary** via a per-doc `sum:` row.
22. **"Do summaries for 2025–2026." / "Start with 50." / "another 100." / "another 150."** → Built batch-prep + an Opus fan-out **workflow**; generated in waves. Found + fixed a bug where `args` arrived as a JSON string (batch counts silently capped at 10).
23. **"Stop; we'll do the last 50 later." / "Complete the last batch — were all uploaded?"** → Stopped cleanly, verified every summary was stored + indexed (308; 2026 complete), finished the dropped batches.
24. **"Add a meeting-type toggle; Back should return to results; year multi-select dropdown."** → Meeting-type segmented filter + year multi-select; viewer **Back** returns to the prior results via history state + URL sync.
25. **"Put the other ~370 into a 'Special' tag, included in 'All'."** → Added the **Special** segment (`meeting_type NOT IN (Regular,Workshop)`).
26. **"What other search UX would you suggest?" / "Meeting dates should match BoardDocs + linked docs."** → Proposed the Tier-1/Tier-2 roadmap; diagnosed + fixed **130 mis-dated packet-era docs** (date+type recovered from filenames; `build_index.py` root-fixed).
27. **"Build the Tier-1 three + wire the BoardDocs deep-link."** → Document-type filter, sort (relevance/newest/oldest), group-by-meeting, and per-result **BoardDocs deep-links** (`bd_links.js`, 100% coverage).
28. **"Go tackle the Tier-2 stuff."** → Acronym/synonym expansion + the **meeting-browse timeline**; decision/outcome badges evaluated and **deferred** (vote data is motion-level in sparse minutes, not per-doc).
29. **"Summarize 30 more."** → Ran another Opus summary wave (2025).
30. **"Fix the meeting time — colon for half/quarter hours, truncate to '7PM' on the hour."** → Added `fmtTime()` across the UI.
31. **"Make sure all documentation, tooling, and .md files are updated and on GitHub."** → This refresh: README, ARCHITECTURE, OPERATIONS, **TOOLING** (new), CHANGELOG (v0.5–0.7), and this Session-2 history; stale Vectorize docstrings corrected.
