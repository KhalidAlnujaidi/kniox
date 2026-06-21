#!/usr/bin/env bash
# Nightly custodian run (unified overseer; supersedes audit.sh).
# crontab:  0 9 * * * ~/kniox/corn/custodian.sh >> ~/kniox/corn/custodian.log 2>&1
set -euo pipefail
KNIOX="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$KNIOX"
exec uv run python "$KNIOX/daemon/daemon.py" custodian run
