#!/usr/bin/env python3
"""Render /transcription's link-preview card and stamp it into the page's share tags.

    python3 scripts/build_transcription_card.py

Screenshots public/transcription-card.html at 1200x630 in headless Chrome (once the page sets
body.dataset.ready), writes public/transcription-og.png, and rewrites the ?v= on every
transcription-og.png URL in public/transcription.html to the PNG's sha256[:10], so Facebook and
the rest re-fetch the image whenever it changes. Needs websocket-client.
"""
from __future__ import annotations
import base64, functools, hashlib, http.server, json, os, re, shutil, socket, subprocess, sys
import tempfile, threading, time, urllib.request
from pathlib import Path

import websocket

REPO = Path(__file__).resolve().parent.parent
PUBLIC = REPO / "public"
CHROME = os.environ.get("CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
W, H = 1200, 630


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def screenshot(page):
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(PUBLIC)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port, profile = free_port(), tempfile.mkdtemp(prefix="tsd-card-")
    chrome = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
                               "--no-first-run", "--hide-scrollbars", "about:blank"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1)
                break
            except OSError:
                time.sleep(0.1)
        tab = json.loads(urllib.request.urlopen(urllib.request.Request(
            f"http://127.0.0.1:{port}/json/new?about:blank", method="PUT")).read())
        ws = websocket.create_connection(tab["webSocketDebuggerUrl"], suppress_origin=True, timeout=30)
        n = [0]

        def call(method, **params):
            n[0] += 1
            ws.send(json.dumps({"id": n[0], "method": method, "params": params}))
            while True:
                m = json.loads(ws.recv())
                if m.get("id") == n[0]:
                    if "error" in m:
                        raise RuntimeError(f"{method}: {m['error']}")
                    return m.get("result", {})

        call("Emulation.setDeviceMetricsOverride", width=W, height=H, deviceScaleFactor=1, mobile=False)
        call("Page.navigate", url=f"http://127.0.0.1:{srv.server_address[1]}/{page}")
        state = ""
        for _ in range(150):
            state = call("Runtime.evaluate", expression="document.body && document.body.dataset.ready || ''",
                         returnByValue=True)["result"].get("value", "")
            if state:
                break
            time.sleep(0.1)
        if state != "1":
            raise RuntimeError(f"{page} did not draw: {state or 'timed out'}")
        time.sleep(0.3)
        shot = call("Page.captureScreenshot", format="png", clip={"x": 0, "y": 0, "width": W, "height": H, "scale": 1})
        ws.close()
        return base64.b64decode(shot["data"])
    finally:
        chrome.kill()
        chrome.wait(timeout=10)
        srv.shutdown()
        shutil.rmtree(profile, ignore_errors=True)


def main() -> int:
    png = screenshot("transcription-card.html")
    if png[:8] != b"\x89PNG\r\n\x1a\n":
        raise RuntimeError("screenshot is not a PNG")
    size = int.from_bytes(png[16:20], "big"), int.from_bytes(png[20:24], "big")
    if size != (W, H):
        raise RuntimeError(f"card is {size}, want {(W, H)}")
    (PUBLIC / "transcription-og.png").write_bytes(png)
    v = hashlib.sha256(png).hexdigest()[:10]
    page = PUBLIC / "transcription.html"
    html, k = re.subn(r"transcription-og\.png\?v=[0-9a-f]*", f"transcription-og.png?v={v}", page.read_text())
    if k < 2:
        raise RuntimeError(f"expected og:image and twitter:image URLs in {page.name}, found {k}")
    page.write_text(html)
    print(f"transcription-og.png {size[0]}x{size[1]}, {len(png) // 1024} KB, v={v} ({k} URLs stamped)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
