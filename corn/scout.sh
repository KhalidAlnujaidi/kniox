#!/usr/bin/env bash
# kniox scout — scheduled Claude run that turns framework findings into GitHub issues.
# Spends the paid Claude quota productively (issues only; never edits code or opens PRs).
#
# crontab (a few times/day, idle/render/nightly slots):
#   0 13,18 * * * ~/kniox/corn/scout.sh >> ~/kniox/corn/scout.log 2>&1
#   30 23   * * * ~/kniox/corn/scout.sh >> ~/kniox/corn/scout.log 2>&1
#
# Install both this and the custodian cron via:  ~/kniox/corn/install-cron.sh
set -euo pipefail
KNIOX="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$KNIOX"
PROMPT_FILE="$KNIOX/corn/scout.prompt.md"
LOCK="$KNIOX/corn/.scout.lock"

command -v claude >/dev/null 2>&1 || { echo "$(date -Is) scout: claude CLI not found"; exit 1; }
command -v gh    >/dev/null 2>&1 || { echo "$(date -Is) scout: gh CLI not found"; exit 1; }
gh auth status >/dev/null 2>&1   || { echo "$(date -Is) scout: gh not authenticated"; exit 1; }
[[ -f "$PROMPT_FILE" ]]          || { echo "$(date -Is) scout: missing $PROMPT_FILE"; exit 1; }

# Never let two scout runs overlap (a few-times-a-day schedule + slow runs can collide).
exec 9>"$LOCK"
flock -n 9 || { echo "$(date -Is) scout: another run holds the lock; skipping"; exit 0; }

echo "$(date -Is) scout: starting (slot via kx)"
# kx anchors to KNIOX, injects the alignment contract as system prompt, and adds
# --dangerously-skip-permissions for headless tool use. `-p` runs Claude non-interactively.
exec "$KNIOX/kx" -p "$(cat "$PROMPT_FILE")"
