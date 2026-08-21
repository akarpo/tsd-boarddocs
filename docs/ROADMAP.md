# Roadmap

Open work, newest planning first. This is the single forward-looking list — `CHANGELOG.md`
records what happened, this records what has not. When an item ships, move a line to the
changelog and delete it here rather than leaving a checked box behind.

Last reviewed **2026-08-21**.

---

## Where things stand

Everything SMS-related is built and verified. The YouTube channel is finished too, as of
2026-08-19: all 41 descriptions rebuilt from the corrected D1 anchors, the thumbnail backlog
cleared with `thumbnails.py --audit` reading 51/51 crest cards, and the agenda numbering fixed
and gated by a check that can now see the class of error that slipped past it.

**The re-summarization campaign finished 2026-08-21.** All five campaigns are complete —
fanout 26/26, remainder 76/76, wave2 121/121, orphans 4/4, packets 151/151 — across 720
document urls, median live `verbose` 10,489 characters. Closing it out turned up eight
documents that every campaign counter reported as done and that had never reached D1,
including the FY24 and FY25 budget books and the 0623 and 0624 ACFRs; those are stored and
verified now. See [RESUMMARIZE.md](RESUMMARIZE.md) for why the done-count could not see them.

Nothing is half-finished; the items below are new work, not loose ends.

- A2P campaign VERIFIED, SMS armed, delivery proven to a real handset.
- Sign-in codes by text; registration approval by replying `1`; question moderation by
  `YES <id>`; admin login behind two factors.
- Inbound is a router: `tsd-boarddocs` handles the owner's commands, `tsdfeedback-2026` receives
  survey replies by relay, and every message is logged to `/admin`.

---

## Now

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

### Re-extract the PEPS report so it is actually searchable
`TSD PEPS Report - March 2025` (wave2 `w2_053`) is in the archive but not really in it.
The PDF extracts as CID font-glyph indices rather than text — an embedded subset font with
no ToUnicode CMap — so its 96KB of source is unreadable and its summary is a 3,444-character
description of the header. It validated clean because text that asserts no figures cannot
fail figure validation.

It is the **only** file of its kind in all 720 campaign documents, so this is one document,
not a class. Fixing it means OCR-ing the PDF and re-running that single batch, not changing
the pipeline. Worth doing because a PEPS report is exactly the kind of document someone
would search for and find nothing.

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
