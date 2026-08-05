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

## Verified state — 2026-08-05

Read directly from the console.

| stage | status |
|---|---|
| 1. Starter Customer Profile | ✅ Approved |
| 2. Sole Proprietor Brand | ✅ Registered — `BN350b79…`, brand "Alex Karpowitsch" |
| 3. Sole Proprietor Campaign | ❌ **Not registered** |

Campaign `CM1084cf…`, created **2026-08-02**, status **In progress** — under carrier review,
quoted at 2-3 weeks. `Compliance Registration SID` and `External Campaign ID` are both null,
which is normal until registration completes.

> **The banner is stage 3, not a regression.** "You have an unfinished A2P 10DLC registration"
> shows on the A2P Overview for as long as the campaign is unapproved. Steps 1 and 2 are done and
> do not need redoing. The Campaigns list is the honest signal — it shows a campaign exists and is
> pending, which the Overview's "Not registered" does not distinguish from "never submitted".

## What is wrong with the submission under review

The payload currently before the carrier is the placeholder one, not the corrected one:

| field | submitted | should be |
|---|---|---|
| Description | "Two Factor Auth / Query validation for access to AI Prompt" | describes this archive and its sign-in codes |
| Sample #1 | `Example: Your one time passcode is 123456` | copied byte-for-byte from `worker.js` |
| Sample #2 | *identical to #1* | distinct, and naming the brand |
| Embedded links | Yes | **No** — the OTP contains none |
| Embedded phone | Yes | **No** — the OTP contains none |
| Opt-in description | "End users opt in by going to tsd-boarddocs.karpowitsch.org and going to the AI Prompt mechanism and entering their phone number." | quote the consent checkbox now live on `/ask` |

That last row is the expensive one. A phone number typed into a form is **not** consent, and a
human reviewer visits the URL to check. Duplicate samples drive **30893**; an unverifiable call to
action drives **30909**.

**The live page is already correct.** `/ask` renders an unchecked "Text me my sign-in codes"
checkbox with the sender named, frequency ("roughly 2–4 messages a month"), "never marketing",
"Msg & data rates may apply", STOP/HELP, "Consent is not a condition of access", and links to
Terms and Privacy. The `MessageFlow` in `scripts/a2p_resubmit.sh` quotes it almost byte-for-byte.
Only the *submission* is stale.

## Why it has not been fixed yet

Twilio refuses updates outside a FAILURE state:

```
400 Campaign update is allowed only for FAILURE state(s).
    It is not allowed in the current state PENDING_DCA1_REVIEW
```

So a submission you *know* is wrong cannot be corrected — it has to fail first. Keep the corrected
payload ready to fire the moment the failure lands. **Get the payload right before submitting**,
because the cost of a mistake is a whole review cycle, not an edit.

The console's **Edit Campaign** modal exposes every field the script sets, plus an "I agree the
above information is correct" attestation tied to the vetting fee. It is a second route to the
same API, so expect the same refusal — but it is free to try and needs no secrets file.

### The decision worth making

Waiting means ~3 weeks to a near-certain rejection, then resubmit, then wait again. Deleting and
recreating with the corrected payload starts a clean review now, at the cost of the ~$15 campaign
verification fee and possible re-vetting. Neither is obviously right; decide deliberately rather
than by default.

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

- [ ] **Campaign payload is stale.** Wait for FAILURE then run `scripts/a2p_resubmit.sh submit`,
      or delete-and-recreate to start a clean review sooner. See the decision above.
- [ ] **Turnstile is not live.** `assistant/README.md` says `/ask` renders a *visible* Cloudflare
      Turnstile widget — "a human check a 10DLC reviewer expects to see in front of anything that
      triggers SMS". As of 2026-08-05 no widget renders on the live page, so
      `scripts/turnstile_enable.sh` has not been run and `turnstile_sitekey`/`turnstile_secret`
      are unset in `bot_config`. Run it before the next review cycle.
- [ ] Secrets file `tsd-boarddocs-keysandsupportingfiles/tsd-secrets.env` is macOS-side only; the
      `status`/`submit` subcommands cannot run from the Windows box.
