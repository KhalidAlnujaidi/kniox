# kniox ship plan — deepseek (deepseek-v4-pro)

---

# kniox — SHIP PLAN (V1-READY)

## 1. PRE-PUBLISH CHECKLIST

### 1.1 Secret-scrub audit

**DELETE — personal session state (contains usernames, session IDs, machine hostnames):**

```bash
rm -rf .omc/
rm -rf .claude/hooks/.omc/
rm -rf daemon/.omc/
```

**DELETE — generated state containing personal hardware details:**
```bash
rm daemon/state/manifest.json    # contains hostname "Khalids-MacBook-Air.local", Apple M3 details, 17.2 GB mem
rm daemon/state/config.json      # generated default; will be recreated by `kx setup`
```

**REVIEWED — clean (no secrets):**
- `reviewers/*.py` — API keys accepted via `--key` flag only, zero hardcoded secrets
- `reviewers/final_deepseek_review.md`, `reviewers/final_gemini_review.md` — reference `kniox` (local path metadata, not a secret). Keep as project vetting trail.

### 1.2 Create `.gitignore`

```bash
cat > .gitignore <<'EOF'
# Generated state
daemon/state/manifest.json
daemon/state/config.json
daemon/state/kniox.db
daemon/state/*.tmp

# Python
__pycache__/
*.pyc
*.pyo
.venv/
*.egg-info/

# OS
.DS_Store
Thumbs.db

# Session state (Claude Code internal)
.omc/
.claude/hooks/.omc/
daemon/.omc/

# Secrets
.env
*.env
EOF
```

### 1.3 Files to add / keep / verify exist

**Must exist (create if missing):**

```bash
# Ensure daemon/state/ dir is tracked even though its contents are gitignored
mkdir -p daemon/state
touch daemon/state/.gitkeep

# Verify these exist (referenced by README + install):
test -f kx || echo "MISSING: kx launcher script"
test -f daemon/requirements.txt || echo "MISSING: daemon/requirements.txt"
```

If `daemon/requirements.txt` is missing, create it:
```
mcp>=1.0.0
psutil>=5.0.0
```

### 1.4 `git init` + first commit

```bash
cd ~/kniox
git init
git add -A
git commit -m "kniox v1: governed LLM dev environment

Four-layer governance: kx launcher → CLAUDE.md → fail-closed hooks → daemon broker.
Detect-never-assume hardware probing. Opt-in tailnet fleet. Dual-model reviewed."
```

### 1.5 Repo settings

| Field | Value |
|---|---|
| **Name** | `kniox` |
| **Description** | LLM-native dev environment — Claude Code is the guest; kniox is the governed world |
| **Topics** | `claude-code`, `llm`, `dev-environment`, `governance`, `mcp`, `fail-closed`, `uv`, `vram-broker` |
| **License** | MIT |
| **Default branch** | `main` |

### 1.6 Create LICENSE file

```bash
cat > LICENSE <<'EOF'
MIT License

Copyright (c) 2025 kniox contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
EOF
```

---

## 2. ONE-LINER INSTALLER

Create `install.sh` at the repo root:

```bash
cat > install.sh <<'INSTALL_SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
# kniox installer — safe to re-run (idempotent). Linux + macOS.
#
# One-liner:  curl -fsSL https://raw.githubusercontent.com/<user>/kniox/main/install.sh | bash
# Inspect first: curl -fsSL .../install.sh -o install.sh && less install.sh && bash install.sh

KNIOX_HOME="${KNIOX_HOME:-$HOME/kniox}"
REPO_URL="${KNIOX_REPO_URL:-https://github.com/khalidfarhan/kniox.git}"
BIN_DIR="${HOME}/.local/bin"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'
say()  { printf "${GREEN}→${NC} %s\n" "$*"; }
warn() { printf "${YELLOW}⚠${NC} %s\n" "$*" >&2; }
die()  { printf "${RED}✗${NC} %s\n" "$*" >&2; exit 1; }

# --- guard: don't run as root ---
[ "$(id -u)" -eq 0 ] && die "do not run as root; kniox is a user-level tool"

# --- platform ---
OS="$(uname -s)"
case "$OS" in
  Linux|Darwin) ;;
  *) die "unsupported OS: $OS (Linux or macOS required)";;
esac

# --- uv: detect → install if missing ---
if command -v uv >/dev/null 2>&1; then
  say "uv found: $(uv --version 2>/dev/null || echo 'ok')"
else
  say "installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.cargo/bin:$PATH"
  command -v uv >/dev/null 2>&1 || die "uv installation failed; check https://docs.astral.sh/uv/getting-started/installation/"
  say "uv installed"
fi

# --- git ---
command -v git >/dev/null 2>&1 || die "git is required — install it first"

# --- clone or detect local checkout ---
LOCAL=""
if [ -f "kx" ] && [ -f "CLAUDE.md" ] && [ -d ".claude/hooks" ]; then
  LOCAL="$(pwd)"
  KNIOX_HOME="$LOCAL"
  say "using local checkout at $KNIOX_HOME"
elif [ -d "$KNIOX_HOME/.git" ]; then
  say "kniox already cloned at $KNIOX_HOME"
elif [ -d "$KNIOX_HOME" ]; then
  die "$KNIOX_HOME exists but is not a kniox checkout — remove it or set KNIOX_HOME"
else
  say "cloning kniox → $KNIOX_HOME"
  git clone "$REPO_URL" "$KNIOX_HOME"
fi

cd "$KNIOX_HOME"

# --- python venv ---
if [ -d ".venv" ]; then
  say "venv already present"
else
  say "creating venv..."
  uv venv
fi

# --- daemon deps ---
say "installing daemon dependencies..."
uv pip install -r daemon/requirements.txt

# --- executable bits ---
say "setting permissions..."
chmod +x kx
chmod +x .claude/hooks/* 2>/dev/null || true
chmod +x .claude/skills/new-project/scaffold.sh 2>/dev/null || true
chmod +x corn/*.sh 2>/dev/null || true
chmod +x daemon/*.py 2>/dev/null || true

# --- symlink kx onto PATH ---
mkdir -p "$BIN_DIR"
ln -sf "$KNIOX_HOME/kx" "$BIN_DIR/kx"
say "kx → $BIN_DIR/kx"

# --- PATH warnings ---
checkpath() {
  if ! echo "$PATH" | tr ':' '\n' | grep -qxF "$1"; then
    warn "$1 is not on your PATH — add this to your shell rc:"
    warn "  export PATH=\"$1:\$PATH\""
  fi
}
checkpath "$BIN_DIR"
checkpath "$HOME/.cargo/bin"

# --- kx setup ---
say "running kx setup (detect hardware + backends)..."
"$KNIOX_HOME/kx" setup

# --- done ---
echo ""
say "kniox ready at $KNIOX_HOME"
echo ""
echo "  Quickstart:"
echo "    kx                  # enter the governed world"
echo "    kx new my-thing     # scaffold a project"
echo "    kx status           # VRAM, projects, slot"
echo "    kx setup --fleet    # profile your tailnet (opt-in)"
echo ""
if ! command -v claude >/dev/null 2>&1; then
  warn "Claude Code CLI not found — install it: https://docs.anthropic.com/en/docs/claude-code/overview"
  warn "(kniox works without it, but `kx` launches claude under the hood)"
fi
INSTALL_SCRIPT

chmod +x install.sh
```

### curl|bash caveats

- **The pipe hides the script.** Mitigation: the inspect-first variant above.
- **The script runs with your shell privileges.** It installs `uv` to `~/.cargo/bin` and symlinks `kx` to `~/.local/bin` — these are user-writeable paths, not system-wide.
- **No sudo is used.** Refuses to run as root.
- **Idempotent.** Safe to re-run; skips already-done steps.
- **Set `KNIOX_HOME` to override the install path** (default `~/kniox`).
- **Set `KNIOX_REPO_URL` to point at a fork** if you maintain one.

---

## 3. README QUICKSTART

Replace the current `## Setup` section with:

```markdown
### Requirements
`git` · `uv` (auto-installed if missing) · optionally `claude` (Claude Code CLI) and `tailscale`

### Quick install
```bash
curl -fsSL https://raw.githubusercontent.com/<user>/kniox/main/install.sh | bash
```
Prefer to inspect first?
```bash
curl -fsSL https://raw.githubusercontent.com/<user>/kniox/main/install.sh -o install.sh
less install.sh   # read it
bash install.sh
```
Custom path:
```bash
KNIOX_HOME=~/my-kniox bash install.sh
```

### Next
```bash
kx                  # enter the governed world
kx new my-project   # scaffold a project
kx status           # VRAM snapshot, loaded models, projects
kx doctor           # health-check hooks + daemon + backend
kx setup --fleet    # profile your tailnet (opt-in)
```

The installer: detects your OS · installs `uv` if missing · clones kniox · creates a
`uv` venv · installs daemon deps · symlinks `kx` onto PATH · runs `kx setup` (detects
hardware + backends, writes `manifest.json` + `config.json` — never installs backends).

Read [`docs/OVERVIEW.md`](docs/OVERVIEW.md) for the full architecture.
```

---

## 4. ANNOUNCEMENT

**Title:** kniox — an operating environment that treats your AI coding agent as a guest

---

Most "AI dev tooling" puts the agent in charge and hopes for the best.

**kniox flips that.** Claude Code is the guest. kniox is the governed world — a sandboxed, self-describing OS with laws, a census of its own hardware, and a quartermaster that rations GPU memory.

The four layers, each independent:

1. **`kx` launcher** — injects the constitution + project state before every session
2. **`CLAUDE.md`** — the always-on floor, loads no matter how the agent starts
3. **Fail-closed hooks** — Python guards that fire *even under `--dangerously-skip-permissions`*. Block `pip`/`conda`, protect the rails from agent edits, hard-cap context windows. The agent cannot disable its own guards — the override is structurally unreachable from its subshell.
4. **Daemon broker** — VRAM gate, `dispatch` to local specialized models. "One model per task" is enforced, not hoped.

**Detect, never assume.** Zero baked-in GPU sizes or model rosters. The probe writes a manifest of your actual hardware; the broker reads facts, not guesses. Unmeasurable resources are `null` with a note — never a convenient zero.

**Opt-in tailnet fleet.** If you have `tailscale`, `kx setup --fleet` enumerates peers and SSH-probes their real specs. One workstation can broker dispatch across your machines. No cluster? It's a clean single-machine tool.

MIT license. V1. Dual-model reviewed (DeepSeek + Gemini).

Repo: `github.com/<user>/kniox`

---

## 5. NICE-TO-HAVES (ranked)

| # | Item | Why |
|---|---|---|
| 1 | **GitHub Actions CI** — run `kx doctor` on macOS + Linux, verify hooks parse correctly against known-good Claude Code JSON payloads, check `uv pip install -r daemon/requirements.txt` succeeds | Catch schema breaks early; prove cross-platform |
| 2 | **`kx doctor` smoke test** — already referenced in README. Formalize: unit tests that drive each hook with valid/invalid stdin JSON and assert exit codes (0/2/3). Run via `kx doctor --ci` for machine-readable output | The only truly trustable verification of the fail-closed guarantee |
| 3 | **Release tags** — `v1.0.0` on first public commit; semver thereafter. Add a `VERSION` file read by `kx --version` | Users can pin; `install.sh` can check out a tag |
| 4 | **Shell completions** — bash/zsh/fish for `kx` subcommands | Low effort, high quality-of-life |
| 5 | **`reviewers/` CI** — run the dual-model review on PRs (requires API keys in GitHub secrets) | Dogfoods the project's own vetting philosophy |
| 6 | **Docker one-liner** — for users who want isolation without installing anything locally | Broadens audience; avoids PATH/venv concerns |

SHIP-PLAN: READY