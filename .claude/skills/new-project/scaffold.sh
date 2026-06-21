#!/usr/bin/env bash
set -euo pipefail
name="${1:?usage: scaffold.sh <project-name>}"
# Restrict to lowercase letters, digits, hyphens (no leading hyphen). This single check
# closes BOTH the path-traversal vector (no '/' or '..' => can't escape projects/) and
# the sed-injection vector (no '/' delimiter or '&' backref in the substitution below).
case "$name" in
  *[!a-z0-9-]* | -* | "")
    echo "invalid project name '$name': use lowercase letters, digits, hyphens (no leading hyphen)" >&2
    exit 1 ;;
esac
KNIOX="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
dir="$KNIOX/projects/$name"
[[ -e "$dir" ]] && { echo "exists: $dir" >&2; exit 1; }
mkdir -p "$dir"/{src,docs,logs}
d="$(date '+%Y-%m-%d %H:%M')"
sed "s/__NAME__/$name/g; s/__DATE__/$d/g" \
  "$KNIOX/.claude/skills/new-project/next.template.md" > "$dir/next.md"
cat > "$dir/CLAUDE.md" <<EOF
# Project: $name

Project-specific context only — global rules are inherited from the root CLAUDE.md.

## What this is
TODO: one-line purpose.
EOF
( cd "$dir" && git init -q )
echo "created $dir (with next.md)"
