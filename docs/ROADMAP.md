# Roadmap

Open work, newest planning first. This is the single forward-looking list — `CHANGELOG.md`
records what happened, this records what has not. When an item ships, move a line to the
changelog and delete it here rather than leaving a checked box behind.

Last reviewed **2026-08-18**.

---

## Where things stand

Everything SMS-related is built and verified. Nothing is half-finished; the items below are new
work, not loose ends.

- A2P campaign VERIFIED, SMS armed, delivery proven to a real handset.
- Sign-in codes by text; registration approval by replying `1`; question moderation by
  `YES <id>`; admin login behind two factors.
- Inbound is a router: `tsd-boarddocs` handles the owner's commands, `tsdfeedback-2026` receives
  survey replies by relay, and every message is logged to `/admin`.

---

## Now

### Drain the YouTube backlog (thumbnails + descriptions)
**Blocked only on YouTube's daily quota — no decision needed, nothing to design.**
Both backlogs exist because the corrections outran the API, not because anything is unresolved.

| outstanding | count | command |
|---|---|---|
| Descriptions to rebuild from current D1 anchors | **41 (all of them)** | `python3 transcription/anchors/push_pending.py` |
| Thumbnails still showing the crest smear | **10** | `nohup python3 transcription/set_thumbnails.py --daemon >/dev/null 2>&1 &` |

It is all 41, not the 21 an earlier version of this item said: every chapter label changed when
the agenda numbering was added on 2026-08-18, so every description needs regenerating from D1.
Cost is ~2,550 units against the 10,000/day ceiling, so both fit in a single window.

**`--list` reports state; `--check` does not exist and is not read-only.** Neither script
defines it, so `push_pending.py --check` falls through to the drain path and pushes the whole
queue for real — it only *looked* like a status flag on 2026-08-18 because the quota was
exhausted and the first call failed. Use `--list`. Both scripts are resumable and save progress
after every success, so an interrupted run costs nothing.
`scratch/anchors-rebuild/pending_push.json` is a symlink to the committed queue, so the armed
job and the committed tool cannot report different backlogs.

**The armed job dies with the machine, and that has now happened twice.**
`scratch/anchors-rebuild/finish_youtube.py` (drains descriptions, then thumbnails) waits for the
03:34 EDT reset in memory — nothing on disk, no launchd job. The Mac rebooted at ~14:42 EDT on
2026-08-18 while it was waiting, and the separate thumbnail drip died with it; neither left a
trace beyond a log that simply stops. **Check `uptime` against the tail of
`finish_youtube.log` before assuming the drain is armed** — a log that ends mid-countdown means
it is not. Re-arm with `nohup python3 scratch/anchors-rebuild/finish_youtube.py &`, plus
`caffeinate -imsu -t 50400` or the Mac sleeps through the window. Re-armed 2026-08-18 14:52 EDT.

Two limits, and they are different things:

- **Daily quota, 10,000 units.** `videos.update` and `thumbnails.set` are 50 each. Resets
  midnight Pacific. This is what is blocking the 41 descriptions.
- **A rolling per-user cap on `thumbnails.set`**, separate from the quota and far longer-lived:
  ~100 sets on 2026-08-17 exhausted it and it still refused 20 hours later, in a run where
  playlist writes succeeded 5/5. **Failed attempts count against it**, so retrying hard makes it
  worse — 65 retries over 80 minutes recovered nothing. Hence the one-at-a-time drip with an
  hour of silence per 429.

**Done, for the record — do not redo any of this.** All 41 meetings' agenda anchors were
re-authored (540 anchors, up from 422; zero prose, truncated or duplicate-prefix labels) and
then **numbered from the published BoardDocs outline** — 518 of 540 carry their agenda number.
`chunks.agenda_item` is **not** the authority here — it only exists for items
with an attachment and its scheme disagrees with the outline (2026-01-13's purchase items are
4.a/4.b/4.c there, 3.A/3.B/3.C on BoardDocs). The four year playlists are complete (2023: 11,
2024: 19, 2025: 20, 2026: 12 = 62). Eleven redundant uploads were **permanently deleted** on
2026-08-18 (YouTube has no undo) — the two-part halves of the 2025-01-14, 2025-02-11, 2025-06-03
and 2025-11-11 workshops, a duplicate 2025-03-08 retreat plus the sibling stuck in
`processingStatus`, and `vptCAUB52ZQ`; `transcription/deleted_videos.json` is the only surviving
record of what they were.

**When the two commands report empty, verify and close this item:**

```
python3 transcription/thumbnails.py --audit          # only the 2 candidate forums
                                                     # + 1 advocacy clip may read WRONG;
                                                     # those are deliberately left alone
python3 transcription/anchors/qa_numbers.py          # 0 EXISTS / UNIQUE / SEMANTIC / ORDER
```

**The numbering was not clean, and the gate said it was.** Reviewed 2026-08-18: `qa_numbers.py`
reported 0 EXISTS / 0 UNIQUE / 0 SEMANTIC while **seven anchors carried the wrong agenda
number**, because every wrong claim happened to share a word with the item it claimed —
"Furniture purchase — elementaries & middle schools" numbered 2.B, *"State Schools of Character -
Larson **Middle School**"*; "**Closed** session" numbered 4.D, *"Schools **Closed** to Open
Enrollment"*. A vocabulary test cannot separate those, and the two claims about coverage the
earlier version of this section made — "zero discussed-but-unanchored items", "QA is clean" —
were both reporting the gate's silence rather than the corpus's state.

What actually separates them is position. A board working out of sequence moves a whole section
and stays there; a number on the wrong chapter leaves one anchor sitting below the anchors on
both sides of it. `qa_numbers.py` now has an **ORDER** pass for exactly that shape, plus a
sentinel past the last anchor so a meeting ending below where it had got to is caught too. It
finds all seven. The seven are fixed in `authored/` and in D1; ten ORDER flags remain and were
each checked by hand against the outline — all are the board genuinely taking a section out of
sequence, and ORDER is an eyeball flag like SEMANTIC, not a gate that must read zero.

Left deliberately, as judgement calls rather than errors: 16 COVERED flags, mostly items
discussed within a neighbouring chapter (two of them seconds into the video, where YouTube's
10-second minimum makes a chapter impossible), and 2024-06-20's opening chapter, numbered 5.G
where the published outline opens with 2.A *PUBLIC HEARING: 2024/2025 Proposed Budget* — the
chapter covers both the hearing and the adoption, so which number it should carry is a real
question and not a mistake to quietly overwrite.

### Decide whether the SMS layer is worth its cost
**Raised 2026-08-11 and not yet answered.** The honest question is whether phone verification
earns its keep, and it splits in two:

- **Owner-facing SMS is cheap and clearly worth it.** Approving a registration by replying `1`
  takes five seconds against unlocking a panel; admin 2FA is a real security gain. Costs
  pennies. Keep.
- **Respondent-facing phone verification is the doubtful half.** It is the largest friction
  increase available on a survey, it collects a phone number from every participant, it carries
  the shared-campaign risk, and `tsdfeedback-2026` had **zero responses** when it was built. That
  project's own notes say distribution, not code, is the open problem — and verification makes
  distribution harder, not easier.

`tsdfeedback-2026/docs/DECISIONS.md` already names the cost and records the reversal path: the
gate is one `readGrant()` check in `functions/api/submit.js`, making it advisory is a two-line
change, and the schema already tolerates a null `phone_hash`. **Reverse if the response rate says
so** — which means the decision needs response data, and there is none yet. Revisit once the
survey has actually been distributed.

### Stand up the Mac Mini runner
Nothing answers questions until this runs. `/ask` accepts and queues them, moderation texts work,
and the queue then sits there. Setup is five steps in
[../assistant/README.md](../assistant/README.md); a self-contained copy for emailing is on the
Desktop as `Ask-the-Archive-Mac-Mini-Setup.docx`.

The trap is the launchd `PATH`: `claude` installs to `~/.local/bin`, which a shell profile adds
interactively and launchd never does. Three `/Users/CHANGEME/` paths in the plist need replacing,
not two, and the failure is silent — the runner polls, claims a question, marks it `answering`,
then dies on `claude: command not found` and the question hangs 20 minutes.

### Turn on Twilio auto-recharge
Still not configured. Console → **Billing → Billing Overview → Enable auto recharge**; suggested
`$10` trigger, recharge to `$25`. Balance was $21.14 with a burn of roughly $3.15/month fixed
($2 campaign + ~$1.15 number), so nothing fires immediately — this is arming it for later. The
failure worth avoiding is not a bounced text but the A2P registration lapsing for want of two
dollars, after the work it took to get approved.

### Finish the re-summarization campaign
`packets` at **125/151**; the other four campaigns are complete (fanout 26/26, remainder 76/76,
wave2 121/121, orphans 4/4). Years 2012–2026 are done; **2010–2011 remain** — 26 batches / 91
agents — next up `pk_017` (2011-03-01), ascending within the year.

Size the wave that reaches `pk_021` around its seven sections rather than off the preceding
wave's rate; section count within a wave, not split count, is what moves the price. Method,
ordering rules and the figure-validation traps: [RESUMMARIZE.md](RESUMMARIZE.md).

---

## Next

### Tell approved applicants they are approved
Nothing notifies them. They register, wait, and have to guess when to come back — and approval
now takes five seconds by text, so the silence is more conspicuous than it was. Resend is live
and `sendEmail()` exists; this is a few lines in `/admin/decide` and in the registration branch
of `ownerCommandReply()`. Pre-existing gap, not a regression.

### Record inbound STOP against `sms_consent`
`sms_consent` only clears when a *send* fails with 21610. An archive user who texts STOP is
opted out at the carrier — correctly — but this project's row still says `1`, so it keeps trying
SMS first and silently falls back to email every time. Now that inbound is logged, the fix is
small: on an `unrouted` or `local` inbound matching a STOP keyword, clear consent for that number.

### Split the Twilio credentials so the auth token can rotate
Rotation has been open a while and is now harder: the token lives in **both** `tsd-secrets.env`
and `bot_config`, and they must change together. It cannot simply move to an `SK…` API key —
`twilioSigValid()` HMACs inbound webhooks with the **account auth token**, which is what Twilio
signs with, and `twilioSend()` reuses `twilio_sid` as both Basic-auth username and URL account.
Doing it properly means separate config for send credentials and the webhook validation token.
(`tsdfeedback-2026` already sends with an API key, which is the safer pattern — it has no inbound
webhook to validate.)

### Make the plist PATH robust rather than documented
The 2026-08-10 fix swaps a silent failure for a documented one, but a half-edited plist still
leaves a literal `/Users/CHANGEME/.local/bin` — a nonexistent directory, harmlessly skipped, and
back to `command not found`. A launcher script that resolves `claude` at startup and fails loudly
would remove the class of error. Only worth it if it bites again.

---

## Later

### Access-control and logging housekeeping
- **`/admin/users` is capped at `LIMIT 200`** and truncates silently, sorted pending-first. Fine
  at single digits; it will mislead long before it complains.
- **Deletes are permanent** — no soft-delete, no audit table, so a removed registration leaves no
  trace it ever existed. Denying preserves the row; deleting does not.
- **`sms_inbound` has no retention policy.** Volume is a handful of messages a month so it will
  not matter for years, but it grows without bound and stores senders' numbers in full.
- **Peer senders are stored in clear here.** `tsdfeedback-2026` hashes survey respondents'
  numbers in its own copy; because all inbound flows through this router, the same numbers land
  here unhashed. Hashing relayed senders would honour that project's choice — a small change to
  `logSmsInbound()`.

### Viewer and legacy code
- Convert the remaining source format the viewer links out (XLSX) if inline preview is ever
  wanted.
- Prune the legacy `--vectors` / `retrieve.py` code paths, superseded since v0.4.

### Secrets are macOS-only
`tsd-boarddocs-keysandsupportingfiles/tsd-secrets.env` lives on the Mac side, so the `status` and
`submit` subcommands of `scripts/a2p_resubmit.sh` cannot run from the Windows box.

---

## Deliberately not doing

- **A bypass header for `/admin/*`.** `x-admin-key` alone returning 401 is the feature; an escape
  hatch would make the second factor decorative. Scripted reads go to D1 directly, and
  [ACCESS_CONTROL.md](ACCESS_CONTROL.md#break-glass) documents inserting an `admin_sessions` row
  when SMS is unavailable.
- **Sending with `MessagingServiceSid` instead of `From`.** Tested 2026-08-10: the number is
  campaign-associated, delivery is confirmed, and the existing 21610 handling works. First thing
  to try if delivery ever degrades, but not a change to make speculatively.
- **Bare `1`/`2` guessing which registration you mean** when several are pending. It lists them
  and asks instead. Approving the wrong person grants archive access to somebody never vetted.
- **Repointing the number's `sms_url` at another project.** A number has one webhook; doing this
  takes it rather than shares it, and fails silently. Peers receive by relay —
  [SMS_ROUTING.md](SMS_ROUTING.md).
- **A second A2P campaign for `tsdfeedback-2026`.** Verified against Twilio's docs: a Sole
  Proprietor entity is limited to one campaign and one number. Not available under this brand.

---

## If you are picking this up cold

Read in this order:

1. **[ACCESS_CONTROL.md](ACCESS_CONTROL.md)** — how anyone gets into `/ask` or `/admin`, and the
   traps (carrier-reserved keywords, the `/api/assistant` route prefix).
2. **[SMS_ROUTING.md](SMS_ROUTING.md)** — one number, several projects, and the relay contract.
3. **[TWILIO_A2P_10DLC.md](TWILIO_A2P_10DLC.md)** — carrier registration state and error codes.
4. **[OPERATIONS.md](OPERATIONS.md)** — ingest, summaries, deploy.

Two habits this project learned the hard way, both in `CHANGELOG.md` with the evidence:

- **Never trust one sample after a deploy.** Cloudflare serves old and new code interleaved for
  several minutes. It made an auth change look one-third open, and made a working log look like
  it was dropping writes. `deployments status` reporting 100% on one version does not mean
  propagation finished. Sample dozens of times, over minutes.
- **`201 queued` proves nothing.** Only a message resource's later `status` does.
