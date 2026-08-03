# Ask the Archive — Mac Mini runner

The public Q&A at `/ask` is answered by THIS runner, not by the Cloudflare Worker.
The Worker only holds the queue (D1) and the gates: registration → **manual
approval** in `/admin` → session → question. The runner polls outbound from the
owner's machine, drives a local **Claude Code** instance (Opus 5) restricted to
`curl` against the archive's own public API, and posts answers back.

```
visitor → /ask  → D1 queue ← poll ─ runner.py (Mac Mini) ─ claude -p (Opus 5)
approval → /admin ↑                    └ topic gate (Haiku) · ≤100K tokens/question
```

## Mac Mini setup

1. Prereqs: `claude` CLI installed and signed in (`claude login`), Python 3.9+,
   this repo cloned, and `tsd-secrets.env` present (outside the repo — see
   `tsd_secrets.py`) containing `ASSISTANT_AGENT_KEY=<value from bot_config>`.
2. Test one question end-to-end:
   `python3 assistant/runner.py --once`
3. Always-on: copy `assistant/com.tsd.assistant.plist` to
   `~/Library/LaunchAgents/`, fix the two absolute paths inside, then
   `launchctl load ~/Library/LaunchAgents/com.tsd.assistant.plist`.
   Logs land in `/tmp/tsd-assistant.log`.

## Guardrails

- **Approval gate**: nobody asks anything until you approve them at `/admin`
  (key = `ASSISTANT_ADMIN_KEY`; stored in the D1 `bot_config` table).
- **Topic gate**: every question first passes a Haiku classifier — strictly Troy
  School District / board business, or it gets a one-line decline (a few hundred
  tokens, no Opus run).
- **Token cap**: the runner kills the Opus run the moment the per-question total
  passes `ASSISTANT_TOKEN_CAP` (default 100,000 **price-weighted** tokens:
  input x1, cache-write x1.25, cache-read x0.1, output x5). Weighted is the
  honest cost meter — a good cited answer measures ~42K weighted (~114K raw,
  dominated by re-reading the CLI's own cached baseline each turn, which is why
  a raw cap can never bind sanely). Totals are recorded per question and shown
  in `/admin`.
- **Tool cage**: the answering agent may only run `curl` (allowed-tools pattern
  `Bash(curl:*)`) against the site's public search API; question text is
  declared untrusted in the prompt.
- **Rate caps** (Worker-side): 2 open questions, 10 per day per user, 600 chars.

## SMS question moderation (Twilio, optional)

With Twilio configured, every question from an approved account holds in
`awaiting_approval` and you get an SMS with the question text — reply
**`YES 12`** to release it to the runner or **`NO 12`** to decline (the `/admin`
panel has equivalent buttons). Unconfigured, questions flow straight through.

Enable it (run yourself; the values never need to leave your machine):

```bash
wrangler d1 execute tsd-boarddocs --remote --yes --command "INSERT OR REPLACE INTO bot_config VALUES
  ('twilio_sid','ACxxxxxxxx'), ('twilio_token','your_auth_token'),
  ('twilio_from','+1248xxxxxxx'), ('twilio_to','+1248yyyyyyy');"
```

- `twilio_from` = your Twilio number, `twilio_to` = your cell.
- Use the **Auth Token** (not an API key) — inbound replies are verified against
  it via `X-Twilio-Signature`, and only texts from `twilio_to` are honored.
- In the Twilio console, set the number's messaging webhook (POST) to
  `https://tsd-boarddocs.karpowitsch.org/api/assistant/twilio/inbound`.
- Config is cached ~60 s in the Worker; changes apply without a redeploy.
- If an SMS send fails, the question degrades to unmoderated rather than
  stranding the asker.

## Email sign-in codes (Resend, optional)

Chosen path (2026-08-03): **Resend** — the Karpowitsch M365 tenant has no
Exchange subscription, so Graph had nothing to send as. Setup:

1. resend.com → Domains → add `karpowitsch.org`. It shows 3 records (a DKIM
   TXT `resend._domainkey`, and an MX + TXT on `send.karpowitsch.org` for the
   return path). Add them in the Cloudflare zone, DNS-only. **Apex MX and SPF
   stay untouched — iCloud receiving is unaffected.**
2. Create an API key (Sending access only), then enable:

```bash
wrangler d1 execute tsd-boarddocs --remote --yes --command "INSERT OR REPLACE INTO bot_config VALUES
  ('resend_api_key','re_…'), ('mail_from','admin@karpowitsch.org');"
```

The channel ladder becomes: SMS when Twilio is armed → Resend email meanwhile.
The Graph path below remains implemented (used only if `resend_api_key` is
absent and `graph_*` rows are present) should the Microsoft route ever return.

## Email sign-in codes (Microsoft Graph, dormant alternative)

Sign-in codes follow a channel ladder: **SMS when Twilio is armed → email via
Microsoft Graph meanwhile → closed if neither**. The email path mirrors the
FoxHall mailer: an Entra app with the `Mail.Send` application permission sends
as `admin@karpowitsch.org` (a shared mailbox — no license needed).

**karpowitsch.org's inbound mail lives on iCloud (alex@…) — NEVER change MX.**
Microsoft here is send-only; the domain verification is a TXT record and does
not affect routing. If you want replies to admin@ to arrive, add `admin` as an
address in your iCloud custom-domain settings.

One-time setup:

1. **Cloudflare DNS** (karpowitsch.org zone, all records DNS-only/grey-cloud):
   - add the `MS=msXXXXXXXX` TXT (value from step 2's wizard);
   - **replace** the SPF TXT `v=spf1 redirect=icloud.com` with
     `v=spf1 include:icloud.com include:spf.protection.outlook.com ~all`;
   - do NOT add MX or autodiscover records;
   - later, optionally: the two DKIM CNAMEs from Defender → Email auth → DKIM,
     and a `_dmarc` TXT `v=DMARC1; p=none; rua=mailto:akarpo@gmail.com`.
2. **M365 admin** (admin.microsoft.com, same tenant as FoxHall): Settings →
   Domains → Add `karpowitsch.org` → verify by TXT → on the records step choose
   to manage DNS yourself and SKIP the Exchange/MX records. Then Teams & groups
   → Shared mailboxes → add `admin@karpowitsch.org`.
3. **Entra** (entra.microsoft.com): App registrations → new app
   ("tsd-boarddocs mailer") → API permissions → Microsoft Graph → Application →
   `Mail.Send` → Grant admin consent → Certificates & secrets → new secret
   (24 months; calendar a renewal reminder — see the FoxHall renewal doc, the
   procedure is identical).
4. Enable (run yourself; values never leave your machine):

```bash
wrangler d1 execute tsd-boarddocs --remote --yes --command "INSERT OR REPLACE INTO bot_config VALUES
  ('graph_tenant_id','45f44120-8603-4386-a285-85358109286b'),
  ('graph_client_id','<new app id>'), ('graph_client_secret','<secret value>'),
  ('mail_from','admin@karpowitsch.org');"
```

The Worker picks it up within a minute. (The FoxHall app's Mail.Send is
tenant-wide, so reusing its app+secret also works — but a separate app keeps
rotation and revocation independent, and either app can be locked to specific
mailboxes later with an Exchange application access policy.)

## Ops notes

- Questions stuck in `answering` >20 min (runner crash) are re-served to the
  next poll automatically.
- Revoke a user: deny them in `/admin` (also kills their sessions).
- Rotate keys: update the `bot_config` rows in D1 and `tsd-secrets.env`.
