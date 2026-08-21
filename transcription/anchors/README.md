# Agenda anchors — how a meeting's chapters get built

`transcript_anchors` drives both the meeting page's chapter chips and the YouTube
description's clickable agenda. Getting them right is the difference between a
three-hour recording you can navigate and one you can only scrub.

## Why this is not fully automatic

`make_anchors.py` produces a *draft*. It cannot be trusted as a final answer,
because the evidence that decides where an agenda item was actually taken up is
conversational:

> "we're just gonna tackle these 2 purchase items first, and then we'll jump into
> budget" — 2026-01-13, which is why the board took 4.c and 4.b before 4.a

Left alone, the heuristic produced 54 labels that were raw transcript prose, 73
truncated into ellipses, 19 with duplicated prefixes, and whole agenda items with
no anchor at all. So a human (or an agent reading carefully) authors the final
set, and tooling checks the claim.

**Agenda items appearing out of numeric order is usually NOT an error.** Chapters
are chronological. Leave them in the order things happened.

## First time anchoring a NEW meeting

`brief.py` reads a workdir (`scratch/anchors-rebuild/`, or `ANCHORS_DATA`) that is
regenerable from D1 and therefore not committed. For a meeting that has never been
anchored it simply raises `FileNotFoundError`, which reads like a broken tool
rather than a missing input. Build the two files first:

```bash
python3 anchors/fetch_agenda.py 2026-08-18        # the full numbered outline
# agendas.json  <- {"<date>": {"name": ..., "agenda": [{"item","title"}, ...]}}
# cur_<date>.json <- SELECT start_ms,label FROM transcript_anchors WHERE meeting_date=...
```

Note that BoardDocs' own outline carries typos ("Budget Reducations Update",
"Bond Projecgts Status Update"). Spell the chapter labels correctly; they are what
the public reads in the YouTube description.

## The loop

```
python3 anchors/brief.py 2026-01-13        # agenda + current anchors + transcript digest
#   ... read it, author anchors_2026-01-13.json as [{"t":"H:MM:SS","label":"..."}]
python3 anchors/apply_anchors.py 2026-01-13 anchors/authored/anchors_2026-01-13.json
python3 anchors/push_pending.py            # rebuild the YouTube descriptions
```

`brief.py` compresses ~800 utterances to ~70 that carry a signal — motions, votes,
transitions, item references, and each agenda item's own distinctive words.

`apply_anchors.py` refuses to write unless the set is sane: first anchor at 0:00,
ascending, no duplicate timestamps, ≥3 chapters, ≥10s apart, inside the recording,
and no truncated / duplicate-prefixed / lowercase-prose labels. Then it runs the
coverage gate and queues the description rebuild.

## The coverage gate

`coverage.py` answers the question hand-authoring cannot: *was this agenda item
actually skipped, or did I just miss it?* Every item in `chunks` is searched for in
the transcript by its own distinctive words and classified:

| verdict | meaning |
|---|---|
| `DISCUSSED` | a cluster of mentions — **must** have an anchor |
| `MENTIONED` | in passing, usually swept through the consent agenda |
| `IN CONSENT` | appears inside the consent-agenda block |
| `ABSENT` | no trace — genuinely tabled or pulled |
| `UNSEARCHABLE` | the title is a filename (`24680 …-0625-AUD-Final`) with no searchable words; ABSENT would be meaningless |

Run `coverage.py --all` for a corpus sweep. It found 18 meetings with a discussed
agenda item that had no anchor — including two that had already been hand-authored
and signed off: 2025-12-16's roof replacement, and 2025-11-18, where an anchor was
on the wrong item entirely (1:22:21 is the traffic signal, not security systems).

## Quota

Anchor writes go to D1 and cost no YouTube quota; only the description rebuild
does (`videos.update`, 50 units). That is why they are decoupled — keep correcting
anchors while writes are blocked, then drain `pending_push.json`.

## Agenda numbering

Every chapter carries its BoardDocs agenda number — `8.A`, `4.G`, `6` — because a
partly-numbered chapter list reads as an oversight. 518 of 540 anchors are
numbered; the 22 that are not are meeting bookends (Call to Order, Adjournment) on
workshop agendas that genuinely have no such item, and inventing one for them
would assert something false.

**The numbers come from BoardDocs, not from `chunks`.** `chunks.agenda_item` only
exists for items that carry an attachment, so numbering from it covered about a
fifth of chapters — Pledge, Recognition, Public Communication and Adjournment have
no document and therefore no number anywhere in D1. `fetch_agenda.py` reads
`BD-GetAgenda` for the complete outline, structural items included. Where the two
disagree the outline wins: 2026-01-13's purchase items are 4.a/4.b/4.c in `chunks`
and **3.A/3.B/3.C** on BoardDocs.

```
python3 anchors/fetch_agenda.py 2026-07-22          # one meeting's outline
python3 anchors/fetch_agenda.py --all -o agenda_outlines.json
python3 anchors/number_anchors.py 2026-01-13        # preview the assignment
python3 anchors/number_anchors.py --all --write     # write `items` into authored/
python3 anchors/qa_numbers.py                       # QA the whole corpus
```

Assignment is a global best-pairing, not sequential: matching in order mis-assigned
in both directions, penalising 2026-01-13's 3.B because the board took 3.C first
(they really did jump) and handing 2.B to the chapter before the one that matched
it. Titles are compared after alias expansion and light stemming — "THS Main & Aux
Gym Remodel" and "Athens & Troy High gym renovations" otherwise shared one word.

The authored file keeps `items` and a clean `label`; `apply_anchors.py` joins them
when writing to D1, so the site's chapter chips and the YouTube description show
the same numbering a viewer sees on BoardDocs.

### What `qa_numbers.py` checks

| check | question |
|---|---|
| EXISTS | is every number an anchor claims really in that meeting's outline? |
| UNIQUE | is any sub-item claimed by two chapters? |
| SEMANTIC | does the chapter share vocabulary with the outline title it claims? |
| COVERED | does every outline sub-item the transcript discusses have a chapter? |

There is deliberately **no order check**. Boards work the agenda out of sequence —
2026-01-13 took 3.C and 3.B before 3.A, and workshops routinely take public
communication after business. Chapters are chronological, so a "regression" is
usually the meeting, not an error.

Corpus QA: **0 EXISTS, 0 UNIQUE, 0 SEMANTIC**. The 15 remaining COVERED flags are
brief procedural items (electing an acting chair, a first reading) folded into a
neighbouring chapter rather than given their own — a judgement call, not an error.
