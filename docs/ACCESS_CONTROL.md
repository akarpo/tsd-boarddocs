# Access control — who gets in, and how you let them

Everything behind `/ask` is gated, and since 2026-08-10 every gate is operable from a phone.
This file describes the whole path and the traps in it. Twilio registration and account facts
live in [TWILIO_A2P_10DLC.md](TWILIO_A2P_10DLC.md); the runner that answers questions lives in
[../assistant/README.md](../assistant/README.md).

```
  visitor                                owner's handset (+1 248 840 3123)
  ───────                                ─────────────────────────────────
  /ask → Register  ──────────────────▶   "registration #9 … reply 1 or 2"
                                          └─ 1 approves, 2 declines
  /ask → Sign in   ──── OTP by SMS ──▶   "sign-in code is 481920"
  /ask → Ask       ──────────────────▶   "Q&A #4 … reply YES 4 or NO 4"
                                          └─ YES queues it for the Opus runner
  /admin           ──── 2FA code ────▶   "admin sign-in code: 629514"
```

Four gates, in order: **registration → approval → sign-in → question moderation**, with admin
access itself two-factored. None of them can be skipped, and the last three all send SMS.

---

## The gates

### 1. Registration (`POST /register`)

Public, Turnstile-protected. Inserts a `pending` row and sends the applicant **nothing** — their
first message is a sign-in code, and only after approval. Consent for that text is a separate,
unchecked checkbox recorded with its timestamp (`sms_consent`, `sms_consent_at`).

`sms_consent` is deliberately three-valued: `1` agreed, `0` declined, `NULL` never asked. Users
who registered before the checkbox existed are `NULL` and get email — the correct default, since
nobody asked them.

The owner is texted immediately. Best-effort: the row is already committed when the notification
fires, so a Twilio outage cannot turn a completed registration into an error the applicant sees.

### 2. Approval — by text or in `/admin`

Reply **`1`** to approve, **`2`** to decline. Both accept an optional id (`1 9`, `1#9`).

A bare `1`/`2` acts on the pending registration **only when exactly one is waiting**. With
several it lists them and asks for an id rather than guessing:

```
2 pending: #3 probe@example.com, #9 alex@example.com. Reply "1 3" or "2 3".
```

That refusal is deliberate. Approving the wrong person grants archive access to somebody who was
never vetted, and no text message takes that back. Declining also clears any session, mirroring
`/admin/decide`.

### 3. Sign-in (`POST /otp/start`, `/otp/verify`)

Six digits, ten minutes, one per minute per number, Turnstile-protected.

Three things must be true to text a code: Twilio configured, the user `approved`, and
`sms_consent === 1`. **A phone number on file is not permission to use it** — texting without
opt-in revokes the 10DLC campaign and is per-message TCPA liability. Anything short of all three
falls back to email via Resend.

`/otp/start` answers `{ok:true, sent:true}` for unknown *and* unapproved numbers, so the form
cannot be used to discover who is registered. Expect "sent" and no text when an account is still
pending — that is the privacy design working, not a fault.

### 4. Question moderation (`POST /ask`)

When Twilio is configured, questions land in `awaiting_approval` and text the owner. Reply
**`YES <id>`** or **`NO <id>`** — the id is in the message. An SMS failure degrades the question
to unmoderated rather than stranding it.

### 5. Admin — two factors

`/admin` needs the admin key **and** a six-digit code texted to `twilio_to`. The key alone
authenticates nothing; it gates *sending* the code, which is what stops an unauthenticated caller
billing SMS and ringing the phone at 3am. Sessions last 12 hours. Codes are single-use, expire in
ten minutes, and allow five attempts — counted *before* the comparison, so a crash mid-verify
cannot hand out a free guess.

The browser never stores the key: it lives in a JS variable between the two steps, and only the
expiring session token is persisted.

There is no bypass header. `curl -H "x-admin-key: …"` against `/admin/*` returns 401 by design —
leaving it working would make the second factor decorative.

---

## Two reply grammars, one number

| you send | means |
|---|---|
| `1` / `2` (optional id) | approve / decline a **registration** |
| `YES <id>` / `NO <id>` | approve / decline a **question** |
| anything else | help text naming both |

Registrations use digits and questions use words, which looks arbitrary and is not.

### Why registrations use digits: reserved carrier keywords

**`YES`, `START`, `UNSTOP`, `STOP`, `CANCEL`, `QUIT`, `END` and friends are reserved opt-in and
opt-out keywords on US long codes.** Twilio and the carriers process them before your webhook's
reply ever goes out.

Observed on 2026-08-10: a bare `YES` from the owner's handset reached the Worker — the invocation
appears in `wrangler tail`, the signature validated, the handler generated correct TwiML — and
**the reply was never delivered.** No error anywhere. The Twilio message log shows the inbound
message and simply no `outbound-reply` beside it.

That is the nastiest shape of failure available: every log says healthy. If a reply seems to
vanish, check the word against the reserved list before you debug your own code.

Digits are not reserved, which is why the registration flow uses them. The question flow keeps
`YES <id>` and works fine — the trailing id is what carries it past the filter, since only a
*bare* keyword is intercepted.

---

## What configuration gates what

`twilioReady()` is true only when all four of `twilio_sid`, `twilio_token`, `twilio_from`,
`twilio_to` are in `bot_config`. It is read in **three** places, and arming it flips all three:

| call site | effect |
|---|---|
| `/otp/start` | sign-in codes go by SMS instead of email |
| `/register` | the owner gets a registration notification |
| `/ask` | **question moderation turns on for every user** |

The third is easy to miss when reasoning about it as "an OTP change". Staging the token last
makes arming one deliberate statement rather than a side effect of a four-row write.

`twilio_from` is the archive's Twilio number; `twilio_to` is the owner's pocket phone. Both are
Michigan 248 numbers, which is a reliable source of confusion.

---

## Verifying the inbound webhook without a handset

The webhook lives at **`/api/assistant/twilio/inbound`**. The bare `/twilio/inbound` written in
`worker.js` is the path *after* `handleAssistant` slices the `/api/assistant` prefix — it is not a
URL and it 404s. Copying it into the Twilio console produces a dead webhook.

You can exercise the whole handler by computing a signature, which is the only way to test it
without a phone:

```bash
. ~/Downloads/tsd-boarddocs-keysandsupportingfiles/tsd-secrets.env
BODY="1 999"
URL=https://tsd-boarddocs.karpowitsch.org/api/assistant/twilio/inbound
SIG=$(python3 - "$TWILIO_AUTH_TOKEN" "$BODY" <<'PY'
import sys, hmac, hashlib, base64
tok, body = sys.argv[1].encode(), sys.argv[2]
url = "https://tsd-boarddocs.karpowitsch.org/api/assistant/twilio/inbound"
p = {"From": "+12488403123", "Body": body}
data = url + "".join(k + p[k] for k in sorted(p))
print(base64.b64encode(hmac.new(tok, data.encode(), hashlib.sha1).digest()).decode())
PY
)
curl -sS -X POST "$URL" -H "x-twilio-signature: $SIG" \
  --data-urlencode "From=+12488403123" --data-urlencode "Body=$BODY"
```

Use a nonexistent id (`999`) so the probe cannot approve anyone. Expect
`<Message>No registration #999.</Message>`.

`twilioSigValid()` HMAC-SHA1s over `url.origin + url.pathname` plus sorted `key+value` pairs. A
403 means one of: bad signature, `From` not equal to `twilio_to`, or Twilio not configured — the
handler cannot distinguish them for the caller, on purpose.

Note `urllib` gets Cloudflare error **1010** (bot signature) where `curl` passes through. That is
the bot-integrity check keying on the client, not Turnstile, which only guards `/register` and
`/otp/start`.

---

## Break glass

**Locked out of `/admin` because SMS is down.** Insert a session directly and send it as
`x-admin-session`:

```bash
npx wrangler d1 execute tsd-boarddocs --remote --command \
  "INSERT INTO admin_sessions (token,created_at,expires) VALUES ('<random-string>', \
   strftime('%Y-%m-%dT%H:%M:%fZ','now'), strftime('%Y-%m-%dT%H:%M:%fZ','now','+1 hour'))"
```

**A question is stuck in `awaiting_approval`.** `/admin/moderate` takes `{id, decision}` with a
valid admin session. Or set `status='pending'` in D1 and the runner picks it up.

**Approve somebody without a phone.** `/admin` still has Approve/Deny buttons; the text is a
convenience, not the only path.

---

## Gotchas

- **Deploy propagation is slow enough to fool a verification sweep.** For several minutes after
  `wrangler deploy` the custom domain serves old and new code interleaved — an auth change looked
  ~⅓ open while `*.workers.dev` was already consistently correct. `deployments status` reporting
  100% on one version does *not* mean propagation finished. Sample dozens of times over minutes
  before believing an auth result.
- **`wrangler d1 execute --file` cannot apply migrations with the current token.** It uses D1's
  import endpoint and fails `Authentication error [code: 10000]`; `--command` works against the
  query endpoint with the same credentials.
- **D1 `--remote` reads can lag a write by seconds.** A row read back as `pending` moments after
  being approved was a stale replica, not a failed write.
- **`201 queued` proves nothing.** Only the message resource's later `status` does. Every test
  message here reported `queued` on POST and `delivered` on the follow-up read.
- **Deletes are permanent.** No soft-delete, no audit table. Denying preserves the row; deleting
  does not. `/admin/users` is also capped at `LIMIT 200` and truncates silently.
- **`phone` carries a UNIQUE index** (`idx_bot_users_phone`), so re-registering a number requires
  deleting the old row first.
