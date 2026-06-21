#!/usr/bin/env bash
set -euo pipefail
# kniox installer — safe to re-run (idempotent). Linux + macOS.
#
# One-liner:
#   curl -fsSL https://raw.githubusercontent.com/KhalidAlnujaidi/kniox/main/install.sh | bash
#
# Inspect first (recommended):
#   curl -fsSL https://raw.githubusercontent.com/KhalidAlnujaidi/kniox/main/install.sh -o install.sh
#   less install.sh && bash install.sh
#
# Overrides:
#   KNIOX_HOME=~/somewhere      install location (default ~/kniox)
#   KNIOX_REPO_URL=<git url>    install from a fork

KNIOX_HOME="${KNIOX_HOME:-$HOME/kniox}"
REPO_URL="${KNIOX_REPO_URL:-https://github.com/KhalidAlnujaidi/kniox.git}"
BIN_DIR="$HOME/.local/bin"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
say()  { printf "${GREEN}→${NC} %s\n" "$*"; }
warn() { printf "${YELLOW}⚠${NC} %s\n" "$*" >&2; }
die()  { printf "${RED}✗${NC} %s\n" "$*" >&2; exit 1; }

# --- never as root: kniox is a user-level tool ---
[ "$(id -u)" -eq 0 ] && die "do not run as root; kniox installs into your home dir"

# --- platform ---
OS="$(uname -s)"
case "$OS" in
  Linux|Darwin) ;;
  *) die "unsupported OS: $OS (Linux or macOS required)";;
esac

# --- git is required ---
command -v git >/dev/null 2>&1 || die "git is required — install it first, then re-run"

# --- uv: detect, install if missing ---
ensure_uv_on_path() {
  # uv's installer lands in ~/.local/bin (and writes an env file); older builds used ~/.cargo/bin.
  [ -f "$HOME/.local/bin/env" ] && . "$HOME/.local/bin/env" 2>/dev/null || true
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
}
if command -v uv >/dev/null 2>&1; then
  say "uv found: $(uv --version 2>/dev/null || echo ok)"
else
  say "uv not found — installing..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ensure_uv_on_path
  command -v uv >/dev/null 2>&1 || die "uv install failed — see https://docs.astral.sh/uv/getting-started/installation/"
  say "uv installed"
fi

# --- clone, update, or use a local checkout ---
if [ -f "kx" ] && [ -f "CLAUDE.md" ] && [ -d ".claude/hooks" ]; then
  KNIOX_HOME="$(pwd -P)"
  say "using local checkout at $KNIOX_HOME"
elif [ -d "$KNIOX_HOME/.git" ]; then
  say "updating existing install at $KNIOX_HOME"
  git -C "$KNIOX_HOME" pull --ff-only || warn "git pull skipped (local changes or detached) — continuing"
elif [ -e "$KNIOX_HOME" ]; then
  die "$KNIOX_HOME exists but is not a kniox checkout — remove it or set KNIOX_HOME"
else
  say "cloning kniox → $KNIOX_HOME"
  git clone --depth 1 "$REPO_URL" "$KNIOX_HOME"
fi

cd "$KNIOX_HOME"

# --- python venv (uv-only, per the alignment contract) ---
if [ -d ".venv" ]; then say "venv present"; else say "creating venv..."; uv venv; fi

say "installing daemon dependencies..."
uv pip install -r daemon/requirements.txt

# --- executable bits ---
say "setting permissions..."
chmod +x kx
chmod +x .claude/hooks/*                          2>/dev/null || true
chmod +x .claude/skills/new-project/scaffold.sh   2>/dev/null || true
chmod +x corn/*.sh                                2>/dev/null || true
chmod +x daemon/*.py                              2>/dev/null || true

# --- put kx on PATH ---
mkdir -p "$BIN_DIR"
ln -sf "$KNIOX_HOME/kx" "$BIN_DIR/kx"
say "kx → $BIN_DIR/kx"

checkpath() {
  case ":$PATH:" in *":$1:"*) ;; *)
    warn "$1 is not on your PATH. Add to your shell rc (~/.bashrc or ~/.zshrc):"
    warn "  export PATH=\"$1:\$PATH\"" ;;
  esac
}
checkpath "$BIN_DIR"

# --- detect hardware + backends (never installs anything) ---
say "running kx setup (detect hardware + backends)..."
"$KNIOX_HOME/kx" setup || warn "kx setup reported an issue — run 'kx doctor' to diagnose"

echo ""
say "kniox ready at $KNIOX_HOME"
echo ""
echo "  Quickstart:"
echo "    kx                  # enter the governed world"
echo "    kx new my-project   # scaffold + register a project"
echo "    kx status           # VRAM, projects, current compute slot"
echo "    kx doctor           # health-check hooks + daemon + backend"
echo "    kx setup --fleet    # profile your tailnet as a resource pool (opt-in)"
echo ""
if ! command -v claude >/dev/null 2>&1; then
  warn "Claude Code CLI not found — kx launches it under the hood."
  warn "Install: https://docs.anthropic.com/en/docs/claude-code/overview"
fi
