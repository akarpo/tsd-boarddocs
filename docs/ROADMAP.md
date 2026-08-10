# Roadmap

Open work, newest planning first. This is the single forward-looking list — `CHANGELOG.md`
records what happened, this records what has not. When an item ships, move a line to the
changelog and delete it here rather than leaving a checked box behind.

Last reviewed **2026-08-10**.

---

## Now

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
Balance was $21.14 on 2026-08-10 against a $2/month campaign fee and ~$0.0083 a segment. The
failure worth avoiding is not a bounced text — it is the A2P registration lapsing for want of two
dollars, after the work it took to get it approved.

### Finish the re-summarization campaign
`packets` at **79/151**; the other four campaigns are complete (fanout 26/26, remainder 76/76,
wave2 121/121, orphans 4/4). Years 2016–2026 are done; **2010–2015 remain**, next up `pk_079`.
Method, ordering rules and the figure-validation traps: [RESUMMARIZE.md](RESUMMARIZE.md).

---

## Next

### Tell approved applicants they are approved
Nothing notifies them. They register, wait, and have to guess when to come back — and approval now
takes five seconds by text, so the silence is more conspicuous than it was. Resend is already live
and `sendEmail()` exists; this is a few lines in `/admin/decide` and in the SMS approval branch of
`/twilio/inbound`. Pre-existing gap, not a regression.

### Split the Twilio credentials so the auth token can rotate
Rotation has been an open item for a while and is now harder: the token lives in **both**
`tsd-secrets.env` and `bot_config` and they must change together.

It cannot simply move to an `SK…` API key, despite the advice in `scripts/a2p_resubmit.sh`:
`twilioSigValid()` HMACs inbound webhooks with the **account auth token**, which is what Twilio
signs with, and `twilioSend()` reuses `twilio_sid` as both Basic-auth username and URL account.
Doing it properly means separate config for send credentials and the webhook validation token.

### Make the plist PATH robust rather than documented
The fix committed on 2026-08-10 swaps a silent failure for a documented one, but a half-edited
plist still leaves a literal `/Users/CHANGEME/.local/bin` — a nonexistent directory, harmlessly
skipped, and back to `command not found`. A launcher script that resolves `claude` at startup and
fails loudly would remove the class of error. Only worth it if it bites again.

---

## Later

### Access-control housekeeping
- **`/admin/users` is capped at `LIMIT 200`** and truncates silently, sorted pending-first. Fine
  at single digits; it will mislead long before it complains.
- **Deletes are permanent** — no soft-delete, no audit table, so a removed registration leaves no
  trace it ever existed. Denying preserves the row; deleting does not. Worth a decision about
  whether the archive should be able to show who ever applied.

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
