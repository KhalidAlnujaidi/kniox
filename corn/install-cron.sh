#!/usr/bin/env bash
# Install kniox's scheduled jobs into the user crontab — idempotently.
# Manages ONLY a marked block; any other crontab entries (radar, REDACTED, …) are preserved.
# Re-run any time to update the schedule; run with `--remove` to delete the kniox block.
#
#   ~/kniox/corn/install-cron.sh            # install/update
#   ~/kniox/corn/install-cron.sh --remove   # remove the kniox block
set -euo pipefail
KNIOX="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BEGIN="# >>> kniox corn (managed) >>>"
END="# <<< kniox corn (managed) <<<"

# The managed block. custodian = LOCAL llm overseer (free, idle-gated), nightly.
# scout = paid Claude tokens -> GitHub issues, a few times/day across the idle/render/nightly slots.
read -r -d '' BLOCK <<EOF || true
$BEGIN
# custodian: local-LLM framework overseer, nightly (idle-gated; yields to real GPU work)
0 3 * * *      $KNIOX/corn/custodian.sh >> $KNIOX/corn/custodian.log 2>&1
# scout: Claude -> GitHub issues, a few times/day (deduped + self-capped; never edits code)
0 13,18 * * *  $KNIOX/corn/scout.sh >> $KNIOX/corn/scout.log 2>&1
30 23 * * *    $KNIOX/corn/scout.sh >> $KNIOX/corn/scout.log 2>&1
$END
EOF

# Current crontab minus any existing managed block (awk drops BEGIN..END inclusive).
current="$(crontab -l 2>/dev/null || true)"
stripped="$(printf '%s\n' "$current" | awk -v b="$BEGIN" -v e="$END" '
  $0==b {skip=1} skip && $0==e {skip=0; next} !skip {print}')"

if [[ "${1:-}" == "--remove" ]]; then
  printf '%s\n' "$stripped" | sed '/^$/N;/^\n$/D' | crontab -
  echo "kniox corn block removed."
  crontab -l 2>/dev/null | sed -n "/$(printf '%s' "$BEGIN" | sed 's/[][\.*^$/]/\\&/g')/,/$(printf '%s' "$END" | sed 's/[][\.*^$/]/\\&/g')/p" || true
  exit 0
fi

{ printf '%s\n' "$stripped" | sed '/^$/N;/^\n$/D'; printf '%s\n' "$BLOCK"; } | crontab -
echo "kniox corn installed/updated:"
crontab -l | sed -n "/$(printf '%s' "$BEGIN" | sed 's/[][\.*^$/]/\\&/g')/,/$(printf '%s' "$END" | sed 's/[][\.*^$/]/\\&/g')/p"
