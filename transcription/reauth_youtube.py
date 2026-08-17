#!/usr/bin/env python3
"""Mint a fresh YT_REFRESH_TOKEN and write it back into tsd-secrets.env.

Google expires refresh tokens after 7 days while the OAuth consent screen sits in
*Testing*, which is what stranded the token on 2026-08-17. The consent screen for
project `river-inquiry-309911` ("My Project 63379" -- its number, 589628968274, is
the prefix of YT_CLIENT_ID) was published to **In production** the same day, so
tokens should now be long-lived and this script should rarely be needed.

Reach for it if a call starts returning `invalid_grant`: the token is also
revoked by changing the account password, revoking access in Google Account
permissions, or 6 months of disuse. Publishing does *not* invalidate an existing
refresh token -- the one minted before the switch kept working.

Run it, approve in the browser that opens, and it rewrites the secrets file:

    python3 reauth_youtube.py
"""
from __future__ import annotations

import http.server
import json
import secrets
import socket
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path.home() / "Downloads" / "tsd-boarddocs"))
import tsd_secrets  # noqa: E402

SCOPE = "https://www.googleapis.com/auth/youtube.force-ssl"
SECRETS = tsd_secrets.SECRETS_FILE
CLIENT_ID = tsd_secrets.require("YT_CLIENT_ID")
CLIENT_SECRET = tsd_secrets.require("YT_CLIENT_SECRET")

_got: dict[str, str] = {}
_state = secrets.token_urlsafe(16)


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):                                    # noqa: N802
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _got.update({k: v[0] for k, v in q.items()})
        ok = "code" in _got and _got.get("state") == _state
        self.send_response(200)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(("<h2>%s</h2><p>You can close this tab.</p>" %
                          ("Authorized - token captured." if ok else
                           "Authorization failed.")).encode())

    def log_message(self, *a):                           # silence the access log
        pass


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def main() -> None:
    port = free_port()
    redirect = f"http://localhost:{port}/"
    srv = http.server.HTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=srv.handle_request, daemon=True).start()

    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": CLIENT_ID, "redirect_uri": redirect, "response_type": "code",
        "scope": SCOPE, "access_type": "offline", "prompt": "consent",
        "state": _state})
    print("Opening the consent screen. Approve as the account that owns the "
          "channel (akarpo@gmail.com).\n\nIf no browser opens, visit:\n" + url + "\n")
    webbrowser.open(url)

    for _ in range(600):                                  # ~5 min of patience
        if "code" in _got or "error" in _got:
            break
        threading.Event().wait(0.5)
    if "code" not in _got:
        raise SystemExit(f"no authorization code received ({_got.get('error','timeout')})")

    body = urllib.parse.urlencode({
        "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
        "code": _got["code"], "grant_type": "authorization_code",
        "redirect_uri": redirect}).encode()
    tok = json.load(urllib.request.urlopen(
        urllib.request.Request("https://oauth2.googleapis.com/token", body)))
    rt = tok.get("refresh_token")
    if not rt:
        raise SystemExit(f"no refresh_token in response: {list(tok)}")

    text = SECRETS.read_text(encoding="utf-8")
    lines, seen = [], False
    for ln in text.splitlines():
        if ln.strip().startswith("YT_REFRESH_TOKEN="):
            lines.append(f"YT_REFRESH_TOKEN={rt}")
            seen = True
        else:
            lines.append(ln)
    if not seen:
        lines.append(f"YT_REFRESH_TOKEN={rt}")
    SECRETS.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote a new YT_REFRESH_TOKEN to {SECRETS}")

    # prove it round-trips before anyone depends on it
    d = urllib.parse.urlencode({"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
                                "refresh_token": rt, "grant_type": "refresh_token"}).encode()
    at = json.load(urllib.request.urlopen(
        urllib.request.Request("https://oauth2.googleapis.com/token", d)))
    print("refresh works, access token expires in", at.get("expires_in"), "s")


if __name__ == "__main__":
    main()
