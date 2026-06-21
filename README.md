# kniox

> **Don't let your tokens gather dust.** Your AI coding agent is the *guest*, not the host —
> run it through `kx` and let it work inside fail-closed guards, a local-GPU broker, and hardware
> it detects instead of assumes.

**[▶ Watch the walkthrough](https://khalidalnujaidi.github.io/kniox/)** ·
[Install](#one-liner-install) · [Roadmap](ROADMAP.md) · [Contributing](#contributing--good-first-issues)

[![kniox — a narrated walkthrough of the governance layers](docs/kniox-demo.gif)](https://khalidalnujaidi.github.io/kniox/)

A governance layer for [Claude Code](https://docs.anthropic.com/en/docs/claude-code/overview).
You run the agent through `kx` instead of `claude`; kniox wraps the session in fail-closed guards,
brokers local GPU memory, and detects your hardware instead of assuming it. Projects live under
`projects/` and inherit one alignment contract.

It is **defense-in-depth, not a sandbox.** The hooks are a strong speed bump on top of
`--dangerously-skip-permissions` — they block the common destructive paths and protect their own
rails, but a determined agent or a shell-obfuscation trick can still get around a regex guard. If you
need true isolation, run the whole thing in a container or VM. kniox is what makes skip-permissions
*less reckless*, not safe.

Optionally, rival commercial models (DeepSeek + Gemini) review the work and push it from rough to
finished — their scripts ship in [`reviewers/`](reviewers/).

## How it governs a session (four layers)
- **Launcher `kx`** — injects alignment + the project's `next.md` as pre-context, and
  adds `--dangerously-skip-permissions` only inside `~/kniox`. Run `kx` instead of `claude`.
- **`CLAUDE.md`** (+ `@import` alignment) — the always-on floor; loads no matter how you launch.
- **Hooks** (`.claude/settings.json`) — the hard gates, which fire even under skip-permissions
  and **fail closed** on unparseable input (a schema break blocks rather than silently opens):
  - `guard-uv.py` — blocks the common destructive commands + bare pip/conda/venv/poetry (`uv pip`
    is allowed); blocks remote `uv run <url>` and `uvx`/`uv tool run`; VRAM check on `ollama run`.
    Known gaps it does **not** catch: separated flags (`rm -r -f`), shell obfuscation
    (`eval`, `base64`, `$IFS`), and stdin pipes (`curl … | uv run -`). Documented on purpose.
  - `guard-state.py` — protects the rails (`.claude/`, `kx`, `alignment/`, root `CLAUDE.md`, `.mcp.json`)
    from agent edits, and blocks edits inside a project with no `next.md`.
  - `session-end-append.py` (Stop) — appends a timestamp to the project's `logs/sessions.log`
    (out of prompt context).
  - `cap-nextmd.py` (Stop) — **hard-caps** the project's `next.md` (last ~60 lines / 6 KB).
    `next.md` is injected verbatim every session, so overwrite discipline is a mechanism, not a hope.
  - `subagent-align.sh` (SubagentStart) — injects the digest into every subagent, including plugin ones.
  - **Manual override:** `export KNIOX_BYPASS_HOOKS=1` in the shell that launches `kx` disables the
    guards for that session (e.g. to edit the rails, or to work past a schema break). The agent's own
    Bash subshell can't set it, so it can't disable its own guards.
- **Daemon** — registry + VRAM broker + `dispatch` (specialized model per task), via MCP.

## No hardware or backend assumptions — everything is detected
kniox assumes nothing about your machine or which inference backend you run. `kx setup` probes the
host (OS, CPU, RAM, GPU/accelerator, installed backends) and writes a **capability manifest** plus a
derived **config**; the broker reads those instead of any baked-in constants. Unmeasurable values are
recorded as `null`, never a fabricated zero (an earlier broker read 0 used-VRAM on any non-NVIDIA box
and "approved" everything). A backend (Ollama / vLLM / llama.cpp / none) is **detected, then optionally
installed** — never required. See [`docs/MANIFEST.md`](docs/MANIFEST.md). Runs the same on a lone
laptop, a single workstation, or a workstation fronting a Tailscale fleet — setup discovers which.

### Optional: tailnet fleet as a resource pool
If `tailscale` is present, `kx setup --fleet` enumerates peers and best-effort profiles each (SSH-runs
the probe for real specs; falls back to tailscale-reported info), merging them into the manifest as a
documented fleet inventory. Entirely opt-in; absence keeps kniox a clean single-machine tool.

## Specialized models: dispatch, not a proxy
"Best model per task" is the `dispatch` MCP tool on the daemon — backend- and VRAM-aware, inspectable,
and deliberately NOT an inference proxy. A proxy that impersonates the Anthropic API is fragile (it
must reproduce Claude Code's exact streaming events) and would route the agent's brain away from Claude.
If you ever want cost-routing for the agent's own model, configure the existing `claude-code-router`
instead.

## Setup

**Requirements:** macOS or Linux, `git`, `curl`. `uv` is installed automatically if missing;
the [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code/overview) and `tailscale`
are optional (detected, never required).

### One-liner install
```bash
curl -fsSL https://raw.githubusercontent.com/KhalidAlnujaidi/kniox/main/install.sh | bash
```
Prefer to read it first (recommended for any `curl | bash`):
```bash
curl -fsSL https://raw.githubusercontent.com/KhalidAlnujaidi/kniox/main/install.sh -o install.sh
less install.sh && bash install.sh
```
Custom location: `KNIOX_HOME=~/my-kniox bash install.sh` · install from a fork:
`KNIOX_REPO_URL=<git-url> bash install.sh`

The installer detects your OS, installs `uv` if missing, clones kniox to `~/kniox`, creates a
`uv` venv, installs daemon deps, symlinks `kx` onto your PATH, and runs `kx setup` (detect
hardware + backend → `manifest.json` + `config.json`; it never installs a backend). It's
idempotent — safe to re-run.

### Manual install
```bash
cd ~/kniox
uv venv && uv pip install -r daemon/requirements.txt   # uv, per alignment (mcp/psutil optional)
chmod +x kx .claude/hooks/* .claude/skills/new-project/scaffold.sh corn/*.sh daemon/*.py
ln -s "$PWD/kx" ~/.local/bin/kx                         # so `kx` is on PATH
kx setup                                                # detect hardware + backend -> manifest/config
#   kx setup --fleet     # also profile the tailnet (optional)
```

Then, from anywhere: `kx` (drops you into ~/kniox), `kx new web-app`, `kx <project>`, `kx status`,
or `kx doctor` (health-checks claude, hooks, daemon, manifest, and the detected backend).

## Notes
- Config is `~/.claude/` + project `.claude/` + `.mcp.json` (root). There is no
  `~/.config/claude/config.json` or `.clauderc`. Verify: `ls ~/.claude`, `/doctor`.
- Hook JSON schema shifts between versions; if a hook doesn't fire, run `/doctor`. Whether
  `PreToolUse` fires on **subagent** tool calls is version-dependent — verify it deliberately,
  because the skip-permissions safety model leans on it. `kx doctor` reminds you to check.
- Guards **fail closed**; if a schema break locks you out, `export KNIOX_BYPASS_HOOKS=1` to recover.
- Tune the VRAM budget and task→model map in `daemon/state/config.json` (re-run `kx setup` to refresh
  detected facts; your config decisions are preserved). `KNIOX_VRAM_BUDGET_GB` env overrides the budget.
- Context comes from `kx`. If you launch plain `claude`, `CLAUDE.md` is still the floor.

## Scope, honestly
kniox is a single-machine personal tool, tied to Claude Code's hook schema (which moves between
versions). It is not a product, not a service, and not a sandbox. What it's good at: making an
autonomous coding agent run under rules you wrote, with local-GPU work brokered instead of guessed,
and failures reported honestly instead of papered over.

## Contributing & good first issues

kniox is young, MIT-licensed, and built to grow with contributors. The architecture is deliberately
modular — **a hook is one Python file, a daemon backend is one adapter, a `kx` verb is one function** —
so most contributions are self-contained and reviewable.

**Good places to start** (see the [`good first issue`](https://github.com/KhalidAlnujaidi/kniox/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) label):
- **A new daemon backend** — add an adapter alongside Ollama / vLLM / llama.cpp (e.g. LM Studio, MLX).
- **A new fail-closed hook** — guards are single files in `.claude/hooks/`; bring your own policy.
- **A `kx` subcommand** — small, composable verbs (`kx <project>`, `kx status`, `kx doctor`).
- **Detection coverage** — teach `kx setup` about more hardware / accelerators (detect, never assume).
- **Docs & repros** — run the install on your OS and file what drifted.

Before a PR: read [`CONTRIBUTING.md`](CONTRIBUTING.md) and the [`ROADMAP.md`](ROADMAP.md) (corpus
capture, mandatory local-LLM offload, and terse-by-default are the current big rocks). Open an issue
or a [Discussion](https://github.com/KhalidAlnujaidi/kniox/discussions) first for anything large —
the fail-closed safety model means changes to the rails get scrutiny. Small, honest PRs welcome.

---

## Part of something larger
kniox is the userspace prototype of a bigger idea I'm working toward: an OS-level environment for
running agents, where governance and resource control live at the hardware/system layer instead of
being bolted on as userspace hooks. The hooks here are a stand-in for guarantees that really belong
lower in the stack.

If that direction interests you — to use it, build on it, or just talk it through — email me:
**khalidnujaidi@gmail.com**

## License
MIT
