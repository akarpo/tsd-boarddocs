#!/usr/bin/env python3
"""Batch-upload the speaker-attributed .srt caption tracks to the existing YouTube videos.

Uses the YouTube Data API v3 (captions.insert / captions.update — 400/450 quota
units each; the 12-meeting batch fits the 10,000/day default easily). Captions
require OAuth as the channel owner, via the TV/limited-input device flow:

One-time setup (≈5 min):
  1. console.cloud.google.com → create/select a project → "APIs & Services" →
     enable **YouTube Data API v3**.
  2. OAuth consent screen → External → Testing → add your Google account as a
     test user (no app verification needed for personal use).
  3. Credentials → Create credentials → OAuth client ID → application type
     **"Desktop app"** → copy the client ID and secret into tsd-secrets.env as
     YT_CLIENT_ID / YT_CLIENT_SECRET. (Device-flow/TV clients can't carry the
     captions scope — Google's device flow rejects youtube.force-ssl.)
  4. Run this script: it prints an accounts.google.com URL and listens on
     127.0.0.1:8765; approve in the browser once and the refresh token is
     appended to tsd-secrets.env for next time.

Usage:  python3 transcription/upload_captions.py [--dry-run] [--only 2026-06-16]
Re-runs update the existing track instead of duplicating it.
"""
from __future__ import annotations
import argparse, json, os, sys, time, urllib.parse, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tsd_secrets

SCOPE = "https://www.googleapis.com/auth/youtube.force-ssl"
TRACK_NAME = "English (speaker-attributed)"
MEETINGS = [  # date, kind, youtube video id
    ("2026-01-13", "Workshop", "MBGaBQyQyMo"), ("2026-01-20", "Regular", "hmm72Km9r5k"),
    ("2026-02-03", "Workshop", "SBV4mbIzKlk"), ("2026-02-24", "Regular", "zzIARNW9Mb0"),
    ("2026-03-17", "Regular", "kSOis_ZYa68"), ("2026-04-07", "Workshop", "aCTsYLcc2Ig"),
    ("2026-04-21", "Regular", "EwTOp4oXVVM"), ("2026-04-28", "Workshop", "4r7_NtwEzLE"),
    ("2026-05-19", "Regular", "bsD_fLjzByY"), ("2026-06-01", "Workshop", "9tnu8oPKieM"),
    ("2026-06-16", "Regular", "53yIbCM0YYA"), ("2026-07-22", "Regular", "v9EHA5_yT-8"),
    ("2025-02-11", "", "1-P9EUyx9N0"),  # 2025: Workshop Meeting (rejoined single recording)
    ("2025-03-04", "", "07c94iVHEUE"),  # 2025: Workshop Meeting
    ("2025-03-18", "", "kQiUHyXn6lI"),  # 2025: Regular Meeting
    ("2025-04-01", "", "bmQU1_g5onU"),  # 2025: Workshop Meeting
    ("2025-04-22", "", "BGOW_NIRTfQ"),  # 2025: Regular Meeting
    ("2025-05-20", "", "GayEpU-LXHE"),  # 2025: Regular Meeting
    ("2025-06-03", "", "XM0MoYkdd9g"),  # 2025: Workshop Meeting
    ("2025-06-17", "", "IZ0c7Wyax34"),  # 2025: Regular Meeting
    ("2025-09-02", "", "G_CB0Jo_0ig"),  # 2025: Workshop Meeting
    ("2025-09-16", "", "WxP2_S6zn8w"),  # 2025: Regular Meeting
    ("2025-10-07", "", "_loP9DZspq4"),  # 2025: Workshop Meeting
    ("2025-11-11", "", "kXSehoFagAQ"),  # 2025: Workshop Meeting
    ("2025-12-09", "", "MNKHsdr5otw"),  # 2025: Workshop Meeting
    ("2025-02-25", "", "uhNHN8v5O2g"),  # 2025: Regular Meeting
    ("2025-11-18", "", "MpmAQMClpiA"),  # 2025: Regular Meeting
    ("2025-01-21", "", "sTzIheFJq-A"),  # 2025: Organizational and Regular Meeting
    ("2025-12-16", "", "t1a1rKAYn4E"),  # 2025: Regular Meeting
    ("2025-10-14", "", "cjjyxD3_Z8A"),  # 2025: Regular Meeting
    ("2025-03-08", "", "ePCmC8TTgrw"),  # 2025: Winter Retreat
    ("2024-01-16", "", "42C3J23nSgY"),  # 2024: Organizational and Regular Meeting
    ("2024-02-27", "", "UOpDDauFT3Q"),  # 2024: Standing Meeting
    ("2024-03-19", "", "kya2LJZ7JZA"),  # 2024: Standing Meeting
    ("2024-04-16", "", "E8b2gueTz9E"),  # 2024: Standing Meeting
    ("2024-05-21", "", "x5TY4kPciXA"),  # 2024: Standing Meeting
    ("2024-06-20", "", "i08-yMRkGNE"),  # 2024: Standing Meeting
    ("2024-09-17", "", "C2VBgy4VYrQ"),  # 2024: Standing Meeting
    ("2024-10-15", "", "YhO8yLFhrAU"),  # 2024: Standing Meeting
    ("2024-11-19", "", "8CQe-v76DBE"),  # 2024: Standing Meeting
    ("2024-12-17", "", "y_9zekv7j2Y"),  # 2024: Standing Meeting
]
SRT_DIR = Path(__file__).resolve().parent.parent / "transcripts"
TITLE_BY_VID = {
"42C3J23nSgY": "2024-01-16 - Troy (MI) School District - Board of Education - Organizational and Regular Meeting",
"UOpDDauFT3Q": "2024-02-27 - Troy (MI) School District - Board of Education - Standing Meeting",
"kya2LJZ7JZA": "2024-03-19 - Troy (MI) School District - Board of Education - Standing Meeting",
"E8b2gueTz9E": "2024-04-16 - Troy (MI) School District - Board of Education - Standing Meeting",
"x5TY4kPciXA": "2024-05-21 - Troy (MI) School District - Board of Education - Standing Meeting",
"i08-yMRkGNE": "2024-06-20 - Troy (MI) School District - Board of Education - Standing Meeting",
"C2VBgy4VYrQ": "2024-09-17 - Troy (MI) School District - Board of Education - Standing Meeting",
"YhO8yLFhrAU": "2024-10-15 - Troy (MI) School District - Board of Education - Standing Meeting",
"8CQe-v76DBE": "2024-11-19 - Troy (MI) School District - Board of Education - Standing Meeting",
"y_9zekv7j2Y": "2024-12-17 - Troy (MI) School District - Board of Education - Standing Meeting",
"1-P9EUyx9N0": "2025-02-11 - Troy (MI) School District - Board of Education - Workshop Meeting",
"ePCmC8TTgrw": "2025-03-08 - Troy (MI) School District - Board of Education - Winter Retreat",
"cjjyxD3_Z8A": "2025-10-14 - Troy (MI) School District - Board of Education - Regular Meeting",
"t1a1rKAYn4E": "2025-12-16 - Troy (MI) School District - Board of Education - Regular Meeting",
"sTzIheFJq-A": "2025-01-21 - Troy (MI) School District - Board of Education - Organizational and Regular Meeting",
"MpmAQMClpiA": "2025-11-18 - Troy (MI) School District - Board of Education - Regular Meeting",
"uhNHN8v5O2g": "2025-02-25 - Troy (MI) School District - Board of Education - Regular Meeting",
"uorMc9xlNH4": "2025-02-11 - Troy (MI) School District - Board of Education - Workshop Meeting - Part 1",
"4GUnzjMBZuA": "2025-02-11 - Troy (MI) School District - Board of Education - Workshop Meeting - Part 2",
"07c94iVHEUE": "2025-03-04 - Troy (MI) School District - Board of Education - Workshop Meeting",
"kQiUHyXn6lI": "2025-03-18 - Troy (MI) School District - Board of Education - Regular Meeting",
"bmQU1_g5onU": "2025-04-01 - Troy (MI) School District - Board of Education - Workshop Meeting",
"BGOW_NIRTfQ": "2025-04-22 - Troy (MI) School District - Board of Education - Regular Meeting",
"GayEpU-LXHE": "2025-05-20 - Troy (MI) School District - Board of Education - Regular Meeting",
"XM0MoYkdd9g": "2025-06-03 - Troy (MI) School District - Board of Education - Workshop Meeting",
"IZ0c7Wyax34": "2025-06-17 - Troy (MI) School District - Board of Education - Regular Meeting",
"G_CB0Jo_0ig": "2025-09-02 - Troy (MI) School District - Board of Education - Workshop Meeting",
"WxP2_S6zn8w": "2025-09-16 - Troy (MI) School District - Board of Education - Regular Meeting",
"_loP9DZspq4": "2025-10-07 - Troy (MI) School District - Board of Education - Workshop Meeting",
"kXSehoFagAQ": "2025-11-11 - Troy (MI) School District - Board of Education - Workshop Meeting",
"MNKHsdr5otw": "2025-12-09 - Troy (MI) School District - Board of Education - Workshop Meeting"
}


def http(url, data=None, headers=None, method=None):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.load(r) if r.headers.get("content-type", "").startswith("application/json") else {}
    except urllib.error.HTTPError as e:
        raise SystemExit(f"HTTP {e.code} {url}\n{e.read().decode('utf-8', 'replace')[:400]}")


def loopback_flow(cid, csec):
    """Desktop-app OAuth via localhost redirect (the flow that supports the captions scope)."""
    import http.server as _hs
    import threading
    port, got = 8765, {}
    class H(_hs.BaseHTTPRequestHandler):
        def do_GET(self):
            got["code"] = (urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                           .get("code") or [None])[0]
            self.send_response(200); self.send_header("content-type", "text/html"); self.end_headers()
            self.wfile.write(b"<h2>Authorized \xe2\x9c\x93 \xe2\x80\x94 you can close this tab.</h2>")
        def log_message(self, *a): pass
    srv = _hs.HTTPServer(("127.0.0.1", port), H)
    t = threading.Thread(target=srv.handle_request, daemon=True); t.start()
    redirect = f"http://127.0.0.1:{port}"
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": cid, "redirect_uri": redirect, "response_type": "code",
        "scope": SCOPE, "access_type": "offline", "prompt": "consent"})
    print(f"\n→ Open and approve (listening on {redirect}):\n{url}\n", flush=True)
    t.join(timeout=600)
    if not got.get("code"):
        raise SystemExit("no auth code received (timed out?)")
    return http("https://oauth2.googleapis.com/token", urllib.parse.urlencode({
        "client_id": cid, "client_secret": csec, "code": got["code"],
        "redirect_uri": redirect, "grant_type": "authorization_code"}).encode())


def access_token():
    cid = tsd_secrets.require("YT_CLIENT_ID")
    csec = tsd_secrets.require("YT_CLIENT_SECRET")
    rt = tsd_secrets.get("YT_REFRESH_TOKEN")
    if not rt:
        tok = loopback_flow(cid, csec)
        rt = tok.get("refresh_token")
        if rt:
            with open(tsd_secrets.SECRETS_FILE, "a") as f:
                f.write(f"\n# YouTube captions uploader (created {time.strftime('%Y-%m-%d')})\nYT_REFRESH_TOKEN={rt}\n")
            print("refresh token saved to tsd-secrets.env")
        return tok["access_token"]
    d = http("https://oauth2.googleapis.com/token",
             urllib.parse.urlencode({"client_id": cid, "client_secret": csec,
                                     "refresh_token": rt, "grant_type": "refresh_token"}).encode())
    return d["access_token"]


def existing_track(tok, vid):
    d = http(f"https://www.googleapis.com/youtube/v3/captions?part=snippet&videoId={vid}",
             headers={"authorization": f"Bearer {tok}"})
    for it in d.get("items", []):
        sn = it["snippet"]
        if sn.get("trackKind") != "asr" and sn.get("name") == TRACK_NAME:
            return it["id"]
    return None


def multipart(meta, srt_bytes):
    b = "captionboundary1729"
    body = (f"--{b}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{json.dumps(meta)}\r\n"
            f"--{b}\r\nContent-Type: application/octet-stream\r\n\r\n").encode() + srt_bytes + f"\r\n--{b}--".encode()
    return body, f"multipart/related; boundary={b}"


def upload(tok, vid, srt_path):
    srt = srt_path.read_bytes()
    cap_id = existing_track(tok, vid)
    if cap_id:
        body, ctype = multipart({"id": cap_id}, srt)
        http(f"https://www.googleapis.com/upload/youtube/v3/captions?part=id&uploadType=multipart",
             body, {"authorization": f"Bearer {tok}", "content-type": ctype}, method="PUT")
        return "updated"
    meta = {"snippet": {"videoId": vid, "language": "en", "name": TRACK_NAME, "isDraft": False}}
    body, ctype = multipart(meta, srt)
    http("https://www.googleapis.com/upload/youtube/v3/captions?part=snippet&uploadType=multipart",
         body, {"authorization": f"Bearer {tok}", "content-type": ctype})
    return "inserted"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", help="one meeting date, e.g. 2026-06-16")
    a = ap.parse_args()
    jobs = [(d, k, v) for d, k, v in MEETINGS if not a.only or d == a.only]
    for d, k, v in jobs:
        srt = SRT_DIR / (f"{TITLE_BY_VID[v]}.srt" if v in TITLE_BY_VID
                         else f"{d} - Troy (MI) School District - Board of Education - {k} Meeting.srt")
        if not srt.exists():
            print(f"{d}  MISSING {srt.name}"); continue
        if a.dry_run:
            print(f"{d}  would upload {srt.name} → video {v}"); continue
        tok = access_token()
        print(f"{d}  {upload(tok, v, srt)} → https://youtu.be/{v}", flush=True)
    print("done")


if __name__ == "__main__":
    main()
