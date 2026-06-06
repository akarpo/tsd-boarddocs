"""Sync the TroySD corpus between the local tree and Cloudflare R2.

R2 is the durable mirror of the (multi-GB, uncommitted) corpus. Reads are
public and credential-free; only uploads need a credential.

  Bucket / prefix : media/troysd-boarddocs/<meeting>/<file>   (mirrors local layout)
  Public reads    : https://media.karpowitsch.org/troysd-boarddocs/<key>   (no creds)
  Writes          : `wrangler r2 object put ... --remote`   (needs CLOUDFLARE_API_TOKEN)
  Manifest        : troysd-boarddocs/_manifest.json   (public list of keys on R2, so
                    the diff and hydrate work without any credential)

Modes:
  pull              download R2 objects missing locally (hydrate; no creds)
  push              upload local files missing from the manifest (needs token)
  reconcile         pull, then push (default)
  rebuild-manifest  set the manifest to the current local file set and upload it
                    (seed/repair; needs token)

The routine from the design = download_troysd.py (BoardDocs -> local, net-new)
sandwiched between `pull` (hydrate first, credential-free) and `push` (publish
net-new). See README "Mirroring to Cloudflare R2".

Usage:
  python sync_r2.py pull
  python sync_r2.py push
  python sync_r2.py reconcile
  CLOUDFLARE_API_TOKEN=... python sync_r2.py push      # non-interactive (CI / secret)
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(os.environ.get("TSD_BOE_ROOT") or Path(__file__).resolve().parent / "tsd-boe-data")
BUCKET = "media"
PREFIX = "troysd-boarddocs"
PUBLIC_BASE = "https://media.karpowitsch.org/troysd-boarddocs"
MANIFEST_REL = "_manifest.json"            # R2 key = <PREFIX>/_manifest.json
WORKERS = 8
UA = "Mozilla/5.0 (tools-troysdboarddocs sync_r2/1.0)"  # Cloudflare 403s the default urllib UA

# Derived/transient files that are NOT part of the mirrored document set.
EXCLUDE_DIRS = {"_text", "_index"}         # derived locally; not mirrored here
EXCLUDE_NAMES = {".DS_Store", "_download.log", MANIFEST_REL}


def local_keys() -> list[str]:
    """Relative POSIX paths of the corpus files we mirror (docs, minutes, _index.csv)."""
    out = []
    if not ROOT.is_dir():
        return out
    for p in ROOT.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(ROOT)
        if rel.parts[0] in EXCLUDE_DIRS:
            continue
        if p.name in EXCLUDE_NAMES or p.name.startswith("._") or p.name.endswith(".log"):
            continue
        out.append(rel.as_posix())
    return sorted(out)


def public_url(rel: str) -> str:
    return f"{PUBLIC_BASE}/" + urllib.parse.quote(rel)


def fetch_manifest() -> set[str]:
    """Keys currently on R2, read from the public manifest. Empty on first run (404).
    Any other failure raises, so callers can refuse to act on bad information."""
    req = urllib.request.Request(f"{PUBLIC_BASE}/{MANIFEST_REL}", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return set(json.loads(r.read().decode("utf-8")).get("keys", []))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return set()
        raise


# --------------------------------------------------------------------------
# wrangler (writes) — the only credentialed path
# --------------------------------------------------------------------------
def ensure_token() -> None:
    if os.environ.get("CLOUDFLARE_API_TOKEN"):
        return
    if not sys.stdin.isatty():
        sys.exit("Uploads need CLOUDFLARE_API_TOKEN. Set it as an env var (or a "
                 "GitHub Actions secret) for non-interactive runs.")
    os.environ["CLOUDFLARE_API_TOKEN"] = getpass.getpass(
        "Cloudflare R2 API token (input hidden): ").strip()


def wrangler_put(rel: str) -> bool:
    key = f"{BUCKET}/{PREFIX}/{rel}"
    for _ in range(2):
        p = subprocess.run(["wrangler", "r2", "object", "put", key,
                            "--file", str(ROOT / rel), "--remote"],
                           capture_output=True, text=True)
        if p.returncode == 0:
            return True
    return False


def upload_manifest(keys) -> None:
    keys = sorted(keys)
    tmp = ROOT / MANIFEST_REL
    tmp.write_text(json.dumps({"prefix": PREFIX, "count": len(keys), "keys": keys}),
                   encoding="utf-8")
    p = subprocess.run(["wrangler", "r2", "object", "put",
                        f"{BUCKET}/{PREFIX}/{MANIFEST_REL}", "--file", str(tmp), "--remote"],
                       capture_output=True, text=True)
    if p.returncode != 0:
        sys.exit(f"manifest upload failed: {p.stderr.strip()[:300]}")
    print(f"manifest updated: {len(keys)} keys")


def _parallel(fn, items):
    ok = 0
    fails = []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(fn, it): it for it in items}
        for f in as_completed(futs):
            if f.result():
                ok += 1
            else:
                fails.append(futs[f])
    return ok, fails


# --------------------------------------------------------------------------
# Modes
# --------------------------------------------------------------------------
def do_pull() -> None:
    manifest = fetch_manifest()
    have = set(local_keys())
    missing = sorted(manifest - have)
    print(f"pull: {len(manifest)} on R2 | {len(have)} local | {len(missing)} to fetch")
    if not missing:
        return

    def fetch(rel: str) -> bool:
        dest = ROOT / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            req = urllib.request.Request(public_url(rel), headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=180) as r:
                dest.write_bytes(r.read())
            return True
        except Exception as e:
            print(f"  ! {rel}: {e}")
            return False

    ok, fails = _parallel(fetch, missing)
    print(f"pull done: {ok}/{len(missing)} fetched"
          + (f"; {len(fails)} failed" if fails else ""))


def do_push() -> None:
    try:
        manifest = fetch_manifest()
    except Exception as e:
        sys.exit(f"could not read R2 manifest ({e}); refusing to push to avoid a mass "
                 f"re-upload. If the manifest is missing or corrupt, run rebuild-manifest.")
    have = set(local_keys())
    new = sorted(have - manifest)
    print(f"push: {len(have)} local | {len(manifest)} on R2 | {len(new)} net-new")
    if not new:
        print("push: nothing to upload")
        return
    ensure_token()
    ok, fails = _parallel(wrangler_put, new)
    uploaded = set(new) - set(fails)
    if uploaded:
        upload_manifest(manifest | uploaded)
    print(f"push done: {ok}/{len(new)} uploaded"
          + (f"; {len(fails)} failed" if fails else ""))
    for rel in fails:
        print(f"  FAIL {rel}")


def do_rebuild_manifest() -> None:
    keys = local_keys()
    print(f"rebuild-manifest: {len(keys)} local keys -> R2 manifest")
    ensure_token()
    upload_manifest(keys)


def main():
    ap = argparse.ArgumentParser(description="Sync the TroySD corpus with Cloudflare R2.")
    ap.add_argument("mode", nargs="?", default="reconcile",
                    choices=["pull", "push", "reconcile", "rebuild-manifest"],
                    help="pull (hydrate from R2, no creds), push (upload net-new, "
                         "needs token), reconcile (pull then push; default), "
                         "rebuild-manifest (set manifest to the local set)")
    args = ap.parse_args()
    if args.mode == "pull":
        do_pull()
    elif args.mode == "push":
        do_push()
    elif args.mode == "rebuild-manifest":
        do_rebuild_manifest()
    else:
        do_pull()
        do_push()
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
