#!/usr/bin/env bash
# UserPromptSubmit hook — append each submitted prompt to docs/PROMPT_HISTORY.md.
# Fires when Claude Code runs inside this repo. Prompts stay LOCAL until you
# commit + push, so nothing becomes public automatically. Never blocks a prompt.
ROOT="$(cd "$(dirname "$0")/../.." 2>/dev/null && pwd)"
LOG="$ROOT/docs/PROMPT_HISTORY.md"
prompt="$(python3 -c 'import sys,json
try:
    print(json.load(sys.stdin).get("prompt","") or "")
except Exception:
    pass' 2>/dev/null)"
# The image-proxy hook (~/.claude/hooks/png-safe-read.sh) runs a subprocess Claude
# whose prompt also fires this hook; 2026-09-25 logged eleven of them. Skip those.
[ -n "$CLAUDE_IMAGE_PROXY" ] && exit 0
case "$prompt" in *"/tmp/claude-safe-"*|"Below is a conversation excerpt for context"*) exit 0 ;; esac
[ -n "$prompt" ] && [ -d "$ROOT/docs" ] && \
  printf '\n- **(%s)** %s\n' "$(date -u "+%Y-%m-%d %H:%M UTC")" "$prompt" >> "$LOG" 2>/dev/null
exit 0
