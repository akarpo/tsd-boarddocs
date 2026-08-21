#!/usr/bin/env bash
#
# ingest_meeting.sh — pull new BoardDocs meetings into D1 + R2, then prep summaries.
#
# Wraps the six-step incremental ingest so the two things that silently ruin a run
# can't be forgotten:
#
#   1. --skip-ingested on the crawl. The crawler's normal skip test is "is the
#      meeting folder already on disk", which is useless on a fresh corpus — it
#      would re-download the whole window and BoardDocs would rate-limit you
#      partway through. --skip-ingested also skips whatever is already in D1.
#   2. R2 before D1. upload_cloudflare.py --new-only decides what to push by
#      asking D1 and treats "already in D1" as "already in R2", so loading D1
#      first makes every new document look uploaded: R2 gets nothing and the
#      viewer 404s on documents search can find.
#
# Summaries are NOT generated here — that needs Claude Opus. This preps the batch
# files and prints the remaining two steps.
#
# Usage:
#   scripts/ingest_meeting.sh [START_DATE] [options]
#
#   The ingest-worker secret is read by tsd_secrets.py (env var, else the
#   secrets file outside the repo) — no longer passed on the command line.
#
#   START_DATE     YYYY-MM-DD; only meetings on or after it. Default: 45 days ago.
#   --dry-run      List what would be downloaded, then stop. No secret needed.
#   --no-prep      Skip the summary batch prep (ingest only).
#   -h, --help     This message.
#
# Env: TSD_BOE_ROOT (corpus root, default ~/Downloads/tsd-boe-data)
#      TSD_BATCH_DIR (default /tmp/tsd_batches), TSD_OUT_DIR (default /tmp/tsd_out)
#      BD_BROWSER (auto|always|never) — headless-Chrome fallback when BoardDocs
#        blocks the plain HTTP client; passed through to download_troysd.py
#
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BATCH_DIR="${TSD_BATCH_DIR:-/tmp/tsd_batches}"
OUT_DIR="${TSD_OUT_DIR:-/tmp/tsd_out}"
START=""
DRY_RUN=0
DO_PREP=1

die() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }
step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

usage() { sed -n '2,/^set -euo/p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//; $d'; }

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help)   usage; exit 0 ;;
    --dry-run)   DRY_RUN=1 ;;
    --no-prep)   DO_PREP=0 ;;
    -*)          die "unknown option: $1 (try --help)" ;;
    *)
      [ -n "$START" ] && die "unexpected argument: $1 (START_DATE already set to $START)"
      START="$1"
      ;;
  esac
  shift
done

# Default to a 45-day trailing window; new meetings are always recent.
if [ -z "$START" ]; then
  START="$(date -v-45d +%Y-%m-%d 2>/dev/null || date -d '45 days ago' +%Y-%m-%d)"
fi
printf '%s' "$START" | grep -qE '^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$' \
  || die "START_DATE must be a valid YYYY-MM-DD, got: $START"

cd "$REPO"
command -v python3 >/dev/null || die "python3 not found"

CORPUS="${TSD_BOE_ROOT:-$HOME/Downloads/tsd-boe-data}"
echo "repo:   $REPO"
echo "corpus: $CORPUS"
echo "window: $START -> today"

# ---------------------------------------------------------------- 1. crawl ----
if [ "$DRY_RUN" = "1" ]; then
  step "Dry run — crawl plan only"
  exec python3 download_troysd.py --start "$START" --skip-ingested --dry-run
fi

# The secret may come from the environment OR from the secrets file outside the
# repo (see tsd_secrets.py). Ask the resolver rather than testing the env var,
# which would refuse to run a perfectly configured pipeline.
python3 -c 'import sys, tsd_secrets; sys.exit(0 if tsd_secrets.get("R2PUT_SECRET") else 1)' \
  || die "R2PUT_SECRET not set and not in the secrets file (guards the tsd-ingest worker)"
command -v soffice >/dev/null || echo "WARNING: soffice not on PATH — Office->PDF previews will be skipped"

step "1/6 Crawl BoardDocs (skipping anything already on disk or in D1)"
CRAWL_LOG="$(mktemp -t tsd-crawl)"
trap 'rm -f "$CRAWL_LOG"' EXIT
python3 download_troysd.py --start "$START" --yes --skip-ingested 2>&1 | tee "$CRAWL_LOG"

# "DONE downloaded=N skipped=M failed=K" is the crawler's stable final line.
SUMMARY_LINE="$(grep -o 'DONE downloaded=[0-9]* skipped=[0-9]* failed=[0-9]*' "$CRAWL_LOG" | tail -1 || true)"
DOWNLOADED="$(printf '%s' "$SUMMARY_LINE" | sed -n 's/.*downloaded=\([0-9]*\).*/\1/p')"
FAILED="$(printf '%s' "$SUMMARY_LINE" | sed -n 's/.*failed=\([0-9]*\).*/\1/p')"
DOWNLOADED="${DOWNLOADED:-0}"; FAILED="${FAILED:-0}"

if [ "$FAILED" -gt 0 ]; then
  echo
  echo "WARNING: $FAILED item(s) failed to download (usually BoardDocs 403s)."
  echo "         Re-run to pick them up, or use --recheck to re-walk the meeting."
fi

if [ "$DOWNLOADED" = "0" ]; then
  step "Nothing new downloaded — no new meetings to ingest"
  echo "If you expected a meeting, check that it is posted publicly on BoardDocs"
  echo "and that its date falls on/after $START."
  exit 0
fi

# ------------------------------------------------- 2-3. extract and index ----
step "2/6 Extract text ($DOWNLOADED new file(s))"
python3 extract_all.py

step "3/6 Rebuild the chunk index"
python3 build_index.py

# ------------------------------------------------------------- 4-5. upload ----
# ORDER IS LOAD-BEARING: R2 first. See the header comment.
step "4/6 Upload source documents to R2"
python3 upload_cloudflare.py --r2 --new-only

step "5/6 Load chunks into D1"
python3 upload_d1.py --all --new-only

step "6/7 Convert new Office documents to preview PDFs"
if command -v soffice >/dev/null; then
  python3 scripts/convert_office.py
else
  echo "skipped — soffice not on PATH"
fi

step "7/7 Check for a new monthly check register"
# BoardDocs posts the Pentamation register as an ordinary attachment, so it lands
# in this archive as one more PDF and nothing tells the spending site about it.
# Report-only here: staging and parsing rewrite a second repo's committed
# deliverables, which is not something an ingest run should do unasked.
python3 scripts/check_register_handoff.py || true

# ------------------------------------------------------------ summary prep ----
if [ "$DO_PREP" = "0" ]; then
  step "Ingest complete (summary prep skipped)"
  exit 0
fi

step "Checking for documents that still need summaries"
STATS="$(python3 summarize.py --stats 2>/dev/null | tail -1)"
echo "$STATS"
PENDING="$(printf '%s' "$STATS" | sed -n 's/.*pending: *\([0-9,]*\).*/\1/p' | tr -d ',')"
PENDING="${PENDING:-0}"

if [ "$PENDING" = "0" ]; then
  step "Done — everything ingested and already summarized"
  exit 0
fi

rm -rf "$OUT_DIR" && mkdir -p "$OUT_DIR"
python3 summarize.py --prep-batches "$PENDING" --batch-chars 96000 --batch-dir "$BATCH_DIR"

cat <<EOF

$(printf '\033[1m==> Ingest complete. %s document(s) need summaries.\033[0m' "$PENDING")

Batch files: $BATCH_DIR/batch_NNN.json
Write tiers to: $OUT_DIR/batch_NNN.json
  as {"<url>": {"paragraph": "...", "page": "...", "verbose": "..."}, ...}

  Small batch (roughly one meeting) — write them inline, no subagents needed.
  Large drip (~150 docs)            — scripts/summaries_workflow.js, args {batches: N}

Then store them (chunks are already in D1, so /summaryput can build the sum: rows):

  python3 summarize.py --store-dir $OUT_DIR

EOF
