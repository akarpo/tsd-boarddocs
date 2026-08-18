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
