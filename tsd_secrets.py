"""Read pipeline secrets from a file kept OUTSIDE the repository.

The ingest worker's shared secret previously existed only as a literal in
`_tsd_ingest/worker.js` and had to be pasted onto every command line. Now that
the corpus and campaign artifacts live *inside* `tsd-boarddocs/`, a secret
anywhere under the repo is one `git add -A` away from GitHub -- so it is stored
in a single file outside the tree instead.

Resolution order, first hit wins:

  1. the environment (`R2PUT_SECRET=... python3 upload_d1.py` still works)
  2. `$TSD_SECRETS_FILE`
  3. `~/Downloads/tsd-boardocs-keysandsupportingfiles/tsd-secrets.env`

That folder also holds `_tsd_ingest/` (the ingest Worker). Both live outside the
repository for the same reason: the Worker string-compares an inline secret, so
anything under `tsd-boarddocs/` would be one `git add -A` from GitHub.

The file is `KEY=value` lines; `#` comments and blank lines are ignored.
"""
from __future__ import annotations

import os
from pathlib import Path

SUPPORT_DIR = Path.home() / "Downloads" / "tsd-boardocs-keysandsupportingfiles"
SECRETS_FILE = Path(os.environ.get("TSD_SECRETS_FILE") or
                    SUPPORT_DIR / "tsd-secrets.env")


def get(name: str, default: str = "") -> str:
    """Return secret `name` from the environment, else the secrets file."""
    v = os.environ.get(name)
    if v:
        return v
    try:
        text = SECRETS_FILE.read_text(encoding="utf-8")
    except (FileNotFoundError, NotADirectoryError, PermissionError):
        return default
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, val = line.partition("=")
        if k.strip() == name:
            return val.strip().strip('"').strip("'")
    return default


def require(name: str) -> str:
    """Like get(), but fail with an actionable message instead of a 403 later."""
    v = get(name)
    if not v:
        raise SystemExit(
            f"ERROR: {name} not set and not found in {SECRETS_FILE}.\n"
            f"       Add a line `{name}=<value>` to that file, or export it.\n"
            f"       Without it every ingest-worker call returns HTTP 403.")
    return v
