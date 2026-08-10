# Inbound SMS routing across projects

One Twilio number, one webhook, several projects behind it.

A phone number has exactly **one** `sms_url`. Whichever project owns it owns *all* inbound
traffic to that number — there is no second slot. `+1 248 927 1666` points at
`tsd-boarddocs`, so this Worker is the router, and other projects receive their messages by
relay rather than by pointing the number at themselves.

Pointing the number somewhere else does not share it; it takes it. Doing so silently breaks the
`1`/`2` and `YES <id>` flows here, the same way the factory demo URL did.

## Why this exists

While the only sender was the owner, everything else could be a 403 and nobody noticed. That
stops working the moment a second project texts **members of the public** — as
`tsdfeedback-2026` does with survey phone verification — because those people reply. They text
STOP, or a question, or the code back. Under the old handler every one of those got a silent
403 and the owning project never saw them.

## How a message is routed

1. **Twilio signature is validated first, unconditionally.** This is the one check that cannot
   be delegated: it needs the account auth token, which is exactly what peers are not given.
   Fail → `403`.
2. The first **enabled** route, by ascending `priority`, whose `to_number`, `from_number` and
   `pattern` all match. `NULL` means "any" in each.
3. `endpoint IS NULL` → handled in this Worker (the tsd-boarddocs flows).
4. `endpoint` set → relayed to that project (below).
5. **No route matches → `403`**, preserving the pre-routing behaviour. Replying to unclaimed
   traffic would put an outbound message on a campaign that never described one.

| column | meaning |
|---|---|
| `to_number` | E.164 destination — which of our numbers was texted |
| `from_number` | E.164 sender, or the literal `$owner` = `bot_config.twilio_to` |
| `pattern` | JS regex source, tested case-insensitively against the trimmed body |
| `endpoint` | `NULL` = local; otherwise an **https** URL to relay to |
| `secret` | per-route HMAC secret, never returned by the admin API |
| `priority` | lower wins; seeded 10/20/900 with gaps to slot projects between |

Seeded routes reproduce exactly what the handler did before routing existed:

```
10   tsd-boarddocs  $owner  ^[12](\s*#?\s*\d+)?$        local   registration approve/decline
20   tsd-boarddocs  $owner  ^(yes|no|y|n)\s*#?\s*\d+    local   question moderation
900  tsd-boarddocs  $owner  (any)                       local   help text
```

A route whose `pattern` will not compile is skipped and logged, never thrown — one bad regex
must not take the webhook down for every other project.

---

## The relay contract

What a peer project must implement to receive its messages.

### Request

```
POST <endpoint>                     (https only)
content-type: application/json
x-sms-relay-project:    tsdfeedback-2026
x-sms-relay-timestamp:  1786500000            unix seconds
x-sms-relay-signature:  sha256=<hex>

{"project":"tsdfeedback-2026","from":"+12485551234","to":"+12489271666",
 "body":"STOP","message_sid":"SM…","received_at":"2026-08-10T22:15:00.000Z"}
```

`x-sms-relay-signature` is `HMAC-SHA256(secret, timestamp + "." + rawBody)`, hex, prefixed
`sha256=`. The timestamp is inside the signed material specifically so a captured POST cannot be
replayed later — verify it is recent (±5 minutes) as well as correctly signed.

### Response

| you return | the sender gets |
|---|---|
| `200 {"reply":"text"}` | that text, as an SMS |
| `200 {}` or empty body | nothing — silent acknowledgement |
| `401` / `403` | a "service unreachable" apology; the check endpoint reports *secrets differ* |
| anything else, or >5s | a "service unreachable" apology |

Timeout is **5 seconds**, chosen to stay well inside Twilio's ~10s webhook abandonment. Be fast
or be silent; do the slow part after responding.

### Verifying on the peer side

```js
async function verifyRelay(request, rawBody, secret) {
  const got = (request.headers.get("x-sms-relay-signature") || "").replace(/^sha256=/, "");
  const ts  = request.headers.get("x-sms-relay-timestamp") || "";
  if (!/^\d+$/.test(ts) || Math.abs(Date.now() / 1000 - Number(ts)) > 300) return false;
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const mac = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(`${ts}.${rawBody}`));
  const want = [...new Uint8Array(mac)].map(b => b.toString(16).padStart(2, "0")).join("");
  // constant-time compare
  if (got.length !== want.length) return false;
  let d = 0;
  for (let i = 0; i < got.length; i++) d |= got.charCodeAt(i) ^ want.charCodeAt(i);
  return d === 0;
}
```

Read the body **once** as text and verify against those exact bytes — re-serializing parsed JSON
will not reproduce the signature.

### Health probe

`POST /admin/sms-routes/check` sends the same signed shape with `{"probe":true,...}` and no
message fields. Treat it as a credential test: verify the signature and return `{"ok":true}`.
It carries no message and can approve or change nothing, so it is safe to run any time.

---

## Operating it

All of these need an admin session (`x-admin-session`), not the admin key — see
[ACCESS_CONTROL.md](ACCESS_CONTROL.md).

```
GET  /api/assistant/admin/sms-routes           list (secrets shown only as a length)
POST /api/assistant/admin/sms-routes           create, or update by passing id
POST /api/assistant/admin/sms-routes/delete    {id}
POST /api/assistant/admin/sms-routes/check     {} for all, or {id} for one
```

Adding a project:

```json
{ "project": "tsdfeedback-2026",
  "from_number": null,
  "pattern": "^(stop|start|help|\\d{6})",
  "endpoint": "https://tsdfeedback-2026.karpowitsch.org/api/sms/inbound",
  "secret": "<long random string, same value both sides>",
  "priority": 50,
  "note": "survey phone verification replies" }
```

`secret` is write-only: omit it on an update to leave it unchanged. Then run the check endpoint
and expect `peer accepted the signature`.

### Choosing a pattern

Routes are matched in priority order and **the first match wins**, so a broad pattern at a low
priority silently swallows everything below it. The owner's routes sit at 10 and 20 precisely so
a project added at 50 cannot capture `1` or `YES 4`.

Prefer routing on `from_number` where you can. It is the honest discriminator: a survey
respondent is not the owner, and no amount of body-pattern cleverness distinguishes two projects
that both want to receive the word "STOP". Body patterns are for splitting traffic *within* one
sender, not between strangers.

### Carrier-reserved words

`STOP`, `START`, `YES`, `UNSTOP`, `CANCEL`, `QUIT`, `END` are handled by the carrier before your
reply is delivered. A bare one of these produces a webhook hit, a correct TwiML reply, and no
delivered message — with no error anywhere. Do not build a flow whose only command is a bare
reserved word; see
[ACCESS_CONTROL.md](ACCESS_CONTROL.md#why-registrations-use-digits-reserved-carrier-keywords).

### Shared throughput

Sole Proprietor brand: AT&T **0.25 msg/sec**, T-Mobile STARTER ≈2,000/day, and the account holds
**one campaign and one number** — that limit is per sole-proprietor entity, so a second campaign
is not available under this brand. Every project shares that budget. A burst from one starves
sign-in codes in another, and OTPs are the latency-sensitive ones.
