# Twilio A2P 10DLC — registration state and playbook

Sign-in codes for **Ask the Archive** (`/ask`) go out by SMS once this registration completes.
Until then the Worker falls back to email via Resend, which is live — see `assistant/README.md`.

`scripts/a2p_resubmit.sh` holds the corrected campaign payload and is the thing you actually run.
This file explains what state we are in and why.

---

## Which Twilio account

**`tsd-boarddocs` uses the akarpo@gmail.com account ("Alex's Account").** The `foxhalltroy`
project uses a completely separate account under `admin@foxhalltroy.com`. The two run
near-identical passwordless SMS-OTP designs, so their campaigns, samples and consent copy look
alike — and acting on the wrong one edits a live carrier registration for the wrong project.

Before reading or changing anything, confirm **all three**:

| check | where |
|---|---|
| login email | avatar menu, top right |
| Account SID | Manage account → General settings |
| Messaging Service SID | on the campaign itself (`MG125c5d71…` for this project) |

## Verified state — 2026-08-10

Read from the API (`./scripts/a2p_resubmit.sh status`), not the console.

| stage | status |
|---|---|
| 1. Starter Customer Profile | ✅ Approved |
| 2. Sole Proprietor Brand | ✅ Registered — `BN350b79…`, brand "Alex Karpowitsch" |
| 3. Sole Proprietor Campaign | ✅ **VERIFIED** — 0 errors, carrier review passed |

**Campaign `CM83307937aa2983ca225bf6af8474ab99`** (compliance record `QE2c6890…`, TCR campaign id
`CJ6Z6E9`), created 2026-08-05, linked to `MG125c5d71…`. The corrected payload is what carriers
approved: both distinct samples, no embedded links or phone, blank opt-in keywords.

Note `date_updated` still reads `2026-08-05T19:22:20Z` — the same as `date_created`. **Twilio does
not stamp the record when a campaign transitions to VERIFIED**, so an unchanged `date_updated` is
not evidence that nothing happened. Read `campaign_status`, never the timestamp.

Throughput granted (`rate_limits`): AT&T **0.25 msg/sec**, T-Mobile brand tier **STARTER**
(≈2,000/day). Ample for sign-in codes; not a broadcast channel.

**Approval does not arm anything.** The campaign being VERIFIED only means carriers will stop
filtering. What still gates SMS is listed under Open items below — as of 2026-08-10 the Worker has
no `twilio_*` config at all and is still on the Resend email ladder.

The original campaign `CM1084cf…` (submitted 2026-08-02) carried the placeholder payload
described below and could not be edited — Twilio refuses updates outside a FAILURE state, so a
submission known to be wrong had to fail first. Rather than wait ~3 weeks for a near-certain
rejection and then resubmit, it was **deleted and recreated** with the corrected payload on
2026-08-05. The brand survived the delete as Registered, so only the campaign fee was re-incurred
(~$15 verification + $2/month); Trust Hub and brand vetting were not repeated.

> **The banner is stage 3, not a regression.** "You have an unfinished A2P 10DLC registration"
> shows on the A2P Overview for as long as the campaign is unapproved — including right now, with
> a clean submission in review. Steps 1 and 2 are done and do not need redoing. The Campaigns list
> is the honest signal: it shows a campaign exists and is pending, which the Overview's
> "Not registered" does not distinguish from "never submitted".

### What the delete actually touches

The confirmation warns that deleting de-registers any numbers on the linked Messaging Service and
removes them from A2P routes. That was safe here because no A2P traffic was flowing — SMS has
never been armed and sign-in codes go out by email. **Do not assume that holds later.** Once SMS
is live, deleting a campaign takes the sending path down with it.

## What was wrong with the 2026-08-02 submission — and what replaced it

| field | was (`CM1084cf…`) | now (`CM8330793…`) |
|---|---|---|
| Description | "Two Factor Auth / Query validation for access to AI Prompt" | describes the archive and its sign-in codes |
| Sample #1 | `Example: Your one time passcode is 123456` | `Your Troy SD Archive sign-in code is 481920. It expires in 10 minutes.` |
| Sample #2 | *identical to #1* | `…736154…` — distinct, names the brand |
| Embedded links | Yes | **No** |
| Embedded phone | Yes | **No** |
| Opt-in description | "End users opt in by going to tsd-boarddocs.karpowitsch.org and going to the AI Prompt mechanism and entering their phone number." | quotes the live `/ask` consent checkbox verbatim |
| Opt-in keywords | `START` | *blank* |

The opt-in row was the expensive one. A phone number typed into a form is **not** consent, and a
human reviewer visits the URL to check. Duplicate samples drive **30893**; an unverifiable call to
action drives **30909**. Twilio's own registration form now says as much inline: *"Most Campaigns
that fail or are rejected are due to incorrect information being submitted in the 'How do
end-users consent to receive messages?' section."*

**Opt-in keywords are deliberately blank**, which differs from the `OptInKeywords=START` in
`scripts/a2p_resubmit.sh`. Opt-in here happens on the website, never by text, and the console is
explicit: *"If you do not support opt-in via text, please leave this blank."* Declaring `START`
would claim a path that does not exist — the same class of mistake as the original submission.
Twilio still handles STOP/START/HELP automatically on US long codes, so consent is honoured
either way. If `a2p_resubmit.sh` is ever used to update this campaign, drop those two fields.

**The live page was already correct.** `/ask` renders an unchecked "Text me my sign-in codes"
checkbox with the sender named, frequency ("roughly 2–4 messages a month"), "never marketing",
"Msg & data rates may apply", STOP/HELP, "Consent is not a condition of access", and links to
Terms and Privacy. Only the submission was ever stale.

## Why a bad submission cannot simply be edited

Twilio refuses updates outside a FAILURE state:

```
400 Campaign update is allowed only for FAILURE state(s).
    It is not allowed in the current state PENDING_DCA1_REVIEW
```

So a submission you *know* is wrong cannot be corrected — it has to fail first. **Get the payload
right before submitting**, because the cost of a mistake is a whole review cycle, not an edit.

The console's **Edit Campaign** modal exposes every field `scripts/a2p_resubmit.sh` sets, plus an
"I agree the above information is correct" attestation tied to the vetting fee. It is a second
route to the same API, so expect the same refusal while the state is not FAILURE — but it is free
to try and needs no secrets file.

### Wait, or delete and recreate?

Waiting means weeks to a likely rejection, then resubmit, then wait again. Deleting and recreating
starts a clean review immediately, at the cost of the ~$15 campaign verification fee and $2/month.
**On 2026-08-05 the second path was taken**, because the payload in review was known-bad and the
brand — the expensive part to re-vet — survives a campaign delete untouched.

Recreating is only cheap while no SMS is flowing. Once the campaign is approved and codes are
going out by text, deleting it takes the sending path down; fix forward from FAILURE instead.

## Two identifiers, easily confused

- **`CM…`** — what the console calls the Campaign SID (`CM1084cf…` here).
- **`QE…`** — what `GET /Services/$MG/Compliance/Usa2p` returns as `sid`: the *compliance record*,
  not the campaign. The console separately reports `Compliance Registration SID: null`, so do not
  expect the two to correspond.

A 2026-08-04 note claimed a `QE…` value collided across two unrelated accounts. That has not been
re-verified, and Twilio sids are meant to be globally unique — treat it as unconfirmed. The safe
rule holds either way: **identify a campaign by `MG…` + credentials, never by `QE…`.**

## Error codes worth handling by name

| code | meaning | not a bug in your code |
|---|---|---|
| 21608 | Trial account: destination not verified | verify the number, or upgrade |
| 30034 | Sender not registered for A2P 10DLC | carriers filter this — finish registration |
| 30893 | Campaign rejected: invalid sample content | samples must be distinct and match reality |
| 30909 | Campaign rejected: CTA unverifiable | the live opt-in does not match what you described |
| 20003 | Not authorised | usually an unapproved Trust Hub profile, not bad credentials |

> **Unregistered A2P traffic fails silently.** Twilio returns `201 queued`; the carrier drops it.
> An API success proves nothing — the only meaningful test is a message arriving on a handset.

## Order of operations

1. Trust Hub customer profile (KYC) — blocks everything else.
2. **Ship the visible opt-in UI first**, with consent and its timestamp stored, plus the SMS
   sections in Terms and Privacy. *Before* registering — the reviewer checks it.
3. Create a Messaging Service (free, needs no numbers).
4. Register the brand (Sole Proprietor needs no EIN; expect an OTP to a personal mobile).
5. Register the campaign against that service.
6. Acquire the number — in parallel with 4 and 5, not before.
7. Point the code at the Messaging Service SID, redeploy, test to a real handset.

## Open items

- [x] ~~Campaign payload is stale.~~ Deleted and recreated clean on 2026-08-05 as
      `CM83307937aa2983ca225bf6af8474ab99`. Now waiting on carrier review (2-3 weeks).
- [x] ~~Watch the new campaign.~~ **VERIFIED, 0 errors** — confirmed 2026-08-10, five days after
      submission rather than the 2-3 weeks budgeted. `a2p_resubmit.sh submit` is now moot unless
      the campaign is ever re-opened; it only ever worked from FAILURE.
- [ ] **Arm SMS.** Four `bot_config` rows, none of which exist yet — `SELECT k FROM bot_config`
      returns only `admin_key`, `agent_key`, `mail_from`, `resend_api_key`, `turnstile_secret`,
      `turnstile_sitekey`. `twilioReady()` needs **all four** or the Worker stays on email:

      | key | value |
      |---|---|
      | `twilio_sid` | `ACf591b5dc…` (account sid; also goes in the Messages URL) |
      | `twilio_token` | the auth token — see the rotation note below |
      | `twilio_from` | `+12489271666` |
      | `twilio_to` | the owner's mobile, E.164 — the moderation/approval handset |

      Test to a real handset afterwards; `201 queued` proves nothing.
- [x] ~~Point the number's webhook at the Worker.~~ **Done 2026-08-10.** `+12489271666` had the
      factory default `sms_url = https://demo.twilio.com/welcome/sms/reply`; it is now
      `https://tsd-boarddocs.karpowitsch.org/api/assistant/twilio/inbound` (POST). Left as the
      demo URL, every `YES 12` / `NO 12` reply would have hit Twilio's demo responder and
      questions would have sat in `awaiting_approval` forever. The Messaging Service has
      `use_inbound_webhook_on_number = true` and no `inbound_request_url`, so the **number-level**
      setting is the one that matters.

      **Mind the `/api/assistant` prefix.** `worker.js` routes on
      `p = url.pathname.slice("/api/assistant".length)`, so the handler's `"/twilio/inbound"` is
      reached at `/api/assistant/twilio/inbound`. The bare `/twilio/inbound` written in the source
      is the *sliced* path, not a URL — it 404s. Probe before trusting it:

      ```
      POST /api/assistant/twilio/inbound  -> 403 forbidden   # correct: exists, fails closed
      POST /twilio/inbound                -> 404             # what the handler string looks like
      ```

      403 is the right answer to an unsigned probe, and it is what an unarmed Worker returns too —
      `twilioSigValid` is only called when `twilioReady()` is true, so `expected` is empty and the
      request is refused. A 403 therefore confirms the route exists but says nothing about whether
      signature validation works; only a real signed webhook does that.
- [ ] **Balance is $1.14.** The campaign carries a $2/month fee on top of per-message cost. Top up
      or confirm auto-recharge, or the registration just bought could lapse for want of $2.

### Arming flips question moderation on, too

`twilioReady()` is read in two places, and the second one is easy to miss. In `/ask`,
`const moderate = twilioReady(cfgA)` — so the moment those four rows exist, submitted questions
land in `awaiting_approval` instead of `pending` and each one texts the owner for a YES/NO. That
is the intended design, but it is a **live behaviour change for every user**, independent of OTP
delivery, and it is why the webhook URL has to be right *first*.

For sign-in codes specifically, arming changes nothing today: all three `bot_users` rows have
`sms_consent` NULL or 0, and `/otp/start` texts only on `sms_consent === 1`. The first SMS this
project sends will be a moderation alert to the owner, not a user's code.

### The auth token cannot simply be swapped for an API key

The header of `a2p_resubmit.sh` recommends an `SK…` Standard key over the root auth token, and for
that script it is right. It does **not** generalise to the Worker: `twilioSigValid()` validates
inbound webhooks as `HMAC-SHA1(cfg.twilio_token, …)`, and Twilio signs webhooks with the **account
auth token** — an API key secret produces a signature that never matches. `twilioSend()` also
reuses `twilio_sid` as both the Basic-auth username and the account in the URL, which an `SK…`
pair breaks. So rotating to an API key means splitting the config into separate send credentials
and a validation token, in code. Until then `twilio_token` must hold the real auth token, and
rotating it means rotating in `bot_config` and `tsd-secrets.env` together.
- [x] ~~Turnstile is not live.~~ **Armed 2026-08-05 and verified.** A **Managed** widget named
      `tsd-boarddocs` (hostname `tsd-boarddocs.karpowitsch.org`, pre-clearance off) was created and
      its keys written to `bot_config`; `/api/assistant/me` returns the sitekey and the widget
      renders on `/ask` showing "Success!". Note Cloudflare is a **single account for both this
      project and `foxhalltroy`** (unlike Twilio, which is two separate accounts) — read the widget
      name before editing anything there. The widget takes a few seconds to appear after page load,
      so an immediate look at `/ask` can wrongly suggest it is missing.
- [ ] Secrets file `tsd-boarddocs-keysandsupportingfiles/tsd-secrets.env` is macOS-side only; the
      `status`/`submit` subcommands cannot run from the Windows box.
