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

## Ops notes

- Questions stuck in `answering` >20 min (runner crash) are re-served to the
  next poll automatically.
- Revoke a user: deny them in `/admin` (also kills their sessions).
- Rotate keys: update the `bot_config` rows in D1 and `tsd-secrets.env`.
