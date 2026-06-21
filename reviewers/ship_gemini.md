# kniox ship plan — gemini (gemini-3.1-pro-preview)

---

### 1. PRE-PUBLISH CHECKLIST

**Secret-Scrub Audit**
No secrets are committed in the provided source. The reviewer scripts (`reviewers/*.py`) correctly resolve keys via runtime arguments or local environment variables (`$DEEPSEEK_API_KEY`, `$GEMINI_API_KEY`, `~/.config/free-claude-code/.env`). 

**Files to Delete**
Delete the local Claude Code state directories that leaked into the repo dump before committing:
- `.claude/hooks/.omc/`
- `.omc/`
- `daemon/.omc/`

**`.gitignore` Additions**
Create or append to `.gitignore` at the repository root:
```text
# Claude Code state
.omc/
.claude/hooks/.omc/

# Python
__pycache__/
*.pyc
.venv/

# kniox state & user data
daemon/state/manifest.json
daemon/state/config.json
daemon/state/kniox.db
projects/
logs/
corn/*.log
```

**`git init` + First Commit**
```bash
git init
git add .
git commit -m "Initial commit: kniox V1"
git branch -M main
git remote add origin https://github.com/<user>/kniox.git
git push -u origin main
```

**Repo Metadata**
- **Name:** `kniox`
- **Description:** LLM-native dev environment. Claude Code is the guest; kniox is the governed world.
- **Topics:** `claude-code`, `ai-agents`, `dev-environment`, `mcp`, `governance`, `llm`
- **License:** MIT License (permissive, standard for tooling, limits liability for agent actions).

---

### 2. ONE-LINER INSTALLER

Create `install.sh` at the repository root. 

**Caveat:** `curl | bash` executes remote code blindly. It is standard for dev tools but inherently risky. The README must provide the inspect-first variant alongside the one-liner.

**`install.sh`**
```bash
#!/usr/bin/env bash
set -euo pipefail

echo "=> Starting kniox installation..."

KNIOX_HOME="${KNIOX_HOME:-$HOME/kniox}"
REPO_URL="https://github.com/<user>/kniox.git" # TODO: Replace <user> before publishing

# 1. Check base dependencies
command -v git >/dev/null 2>&1 || { echo >&2 "Error: git is required."; exit 1; }
command -v curl >/dev/null 2>&1 || { echo >&2 "Error: curl is required."; exit 1; }

# 2. Detect/Install uv
if ! command -v uv >/dev/null 2>&1; then
    echo "=> uv not found. Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # Source uv environment for the remainder of this script
    source "$HOME/.local/bin/env" 2>/dev/null || export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"
fi

# 3. Clone or update kniox
if [ -d "$KNIOX_HOME/.git" ]; then
    echo "=> Updating existing kniox installation at $KNIOX_HOME..."
    cd "$KNIOX_HOME"
    git pull --ff-only
else
    echo "=> Cloning kniox to $KNIOX_HOME..."
    git clone "$REPO_URL" "$KNIOX_HOME"
    cd "$KNIOX_HOME"
fi

# 4. Setup Python environment
echo "=> Setting up uv venv and daemon dependencies..."
uv venv
if [ -f "daemon/requirements.txt" ]; then
    uv pip install -r daemon/requirements.txt
else
    uv pip install mcp psutil
fi

# 5. Permissions
echo "=> Setting executable permissions..."
chmod +x kx .claude/hooks/* .claude/skills/new-project/scaffold.sh corn/*.sh daemon/*.py

# 6. Symlink kx
echo "=> Linking kx to ~/.local/bin/kx..."
mkdir -p "$HOME/.local/bin"
ln -sf "$KNIOX_HOME/kx" "$HOME/.local/bin/kx"
export PATH="$HOME/.local/bin:$PATH"

# 7. Detect optional tools
if ! command -v claude >/dev/null 2>&1; then
    echo "=> Note: 'claude' (Claude Code CLI) not found on PATH. You will need it to run the agent."
fi

# 8. Run setup
echo "=> Running kx setup..."
"$KNIOX_HOME/kx" setup

echo ""
echo "=> kniox installation complete!"
echo "=> Next steps:"
echo "   1. Ensure ~/.local/bin is in your PATH."
echo "   2. Run 'kx new <project-name>' to scaffold your first project."
echo "   3. Run 'kx <project-name>' to start a governed session."
```

---

### 3. README QUICKSTART

Replace the current `## Setup` section in `README.md` with:

```markdown
## Setup

**Requirements:** macOS or Linux, `git`, and `curl`. (`uv` and `claude` will be detected; `uv` is installed automatically if missing).

Install kniox via the automated script:

```bash
# Inspect first (recommended)
curl -fsSL https://raw.githubusercontent.com/<user>/kniox/main/install.sh -o install.sh
less install.sh
bash install.sh

# Or one-liner
curl -fsSL https://raw.githubusercontent.com/<user>/kniox/main/install.sh | bash
```

The installer clones kniox to `~/kniox` (override via `$KNIOX_HOME`), sets up the `uv` environment, symlinks `kx` to `~/.local/bin/kx`, and runs `kx setup` to detect your hardware and backends.

Then, from anywhere:
- `kx new web-app` — scaffold a new project
- `kx web-app` — drop the agent into the governed project
- `kx status` — view active projects and VRAM pressure
- `kx doctor` — health-check the framework, hooks, and backends

*(Optional)* If you run Tailscale, you can profile your tailnet as a resource pool:
```bash
kx setup --fleet
```
```

---

### 4. ANNOUNCEMENT

**Title:** Show HN: kniox – An LLM-native dev environment where the agent is the guest

**Body:**
Most AI coding tools treat your project as the guest and the agent as the orchestrator. `kniox` inverts this. 

`kniox` is an operating environment for Claude Code. Claude is the untrusted process; `kniox` is the world it runs in. It provides:
- **Fail-closed Governance:** OS-level Python/shell hooks that block destructive commands, ban legacy package managers (`pip`/`conda`), and protect the framework's own rules from being edited by the agent.
- **Detect, Don't Assume:** Zero baked-in hardware or model assumptions. A probe writes a capability manifest of your machine (and optionally, your Tailscale fleet). Unmeasurable resources are reported as `null`, never a fabricated zero.
- **The Quartermaster:** A daemon that brokers VRAM. "One specialized model per task" is enforced via an MCP `dispatch` tool that routes heavy jobs to local models (Ollama/vLLM/llama.cpp) based on a strict VRAM budget, keeping Claude's brain free for reasoning.

It's defense-in-depth for autonomous agents. Code, docs, and the dual-model adversarial review logs are in the repo.

---

### 5. NICE-TO-HAVES (Ranked)

1. **`kx doctor` Smoke Test in CI:** Add a `.github/workflows/test.yml` that runs the installer, executes `kx doctor`, and asserts a `0` exit code. Guarantees the installer and basic Python environment never bit-rot.
2. **Release Tags (SemVer):** Tag `v1.0.0`. Pin the `curl` installer command in the README to a specific tag (e.g., `.../v1.0.0/install.sh`) so upstream `main` changes don't break user installs.
3. **Uninstall Script:** Provide a `uninstall.sh` or `kx uninstall` command that cleanly removes `~/.local/bin/kx`, `~/kniox`, and restores any modified shell profiles. 

SHIP-PLAN: READY