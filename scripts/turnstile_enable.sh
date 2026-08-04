#!/usr/bin/env bash
# turnstile_enable.sh — switch the /ask human check on, atomically.
#
# Both values go in together on purpose. verifyTurnstile() fails CLOSED: with a sitekey present
# and no secret it returns 503 rather than accepting unverified submissions, which is the correct
# safety behaviour but means a half-configured widget takes the register and sign-in forms down.
# Setting them in one statement removes that window.
#
# Get the pair from the Cloudflare dashboard: Turnstile -> Add widget.
#   Widget mode : Managed
#   Hostnames   : tsd-boarddocs.karpowitsch.org
#   (add 127.0.0.1 too if you want it to work under `wrangler dev`)
#
#   ./scripts/turnstile_enable.sh 0x4AAA... 0x4AAA-secret...
#   ./scripts/turnstile_enable.sh --off          # remove both, forms revert to unguarded
#
# Config is cached in the worker for 60s, so allow a minute before testing.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

DB=tsd-boarddocs

if [[ "${1:-}" == "--off" ]]; then
  npx wrangler d1 execute "$DB" --remote --yes \
    --command "DELETE FROM bot_config WHERE k IN ('turnstile_sitekey','turnstile_secret')"
  echo "Turnstile disabled — /ask forms are unguarded again."
  exit 0
fi

SITEKEY="${1:-}"; SECRET="${2:-}"
if [[ -z "$SITEKEY" || -z "$SECRET" ]]; then
  echo "usage: $0 <sitekey> <secret>   |   $0 --off" >&2
  exit 2
fi
# Sitekeys and secrets both start 0x… ; catch the common paste-the-same-value-twice mistake.
if [[ "$SITEKEY" == "$SECRET" ]]; then
  echo "sitekey and secret are identical — you have pasted the same value twice" >&2
  exit 2
fi

npx wrangler d1 execute "$DB" --remote --yes --command "
  INSERT INTO bot_config (k,v) VALUES ('turnstile_sitekey','$SITEKEY')
    ON CONFLICT(k) DO UPDATE SET v=excluded.v;
  INSERT INTO bot_config (k,v) VALUES ('turnstile_secret','$SECRET')
    ON CONFLICT(k) DO UPDATE SET v=excluded.v;"

echo
echo "Turnstile enabled. Verify in ~60s (config is cached):"
echo "  curl -s https://tsd-boarddocs.karpowitsch.org/api/assistant/me | python3 -m json.tool"
echo "  -> turnstile_sitekey should be your sitekey, not null"
echo "Then load /ask: a visible widget should appear above both buttons."
