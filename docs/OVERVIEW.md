# kniox — a governed world for an autonomous coding agent

## The one-sentence idea

**kniox inverts the usual setup.** Normally Claude Code is the environment and your project
is the guest. In kniox, *Claude Code is the guest* and **kniox is the world it runs in** — a
sandboxed, self-describing operating environment with laws (hooks), a constitution
(`CLAUDE.md`), a census of its own resources (the manifest), and a quartermaster that rations
scarce compute (the daemon).

It is an **LLM-native dev environment**: built from the ground up assuming the primary "user"
of the filesystem is an AI agent, not a human typing commands.

---

## The mental model — four concentric layers

```
        ┌─────────────────────────────────────────────┐
        │  kx launcher  — injects context, enters world │   ← the airlock
        │  ┌───────────────────────────────────────┐   │
        │  │  CLAUDE.md  — the always-on constitution│   │   ← the floor
        │  │  ┌─────────────────────────────────┐   │   │
        │  │  │  Hooks — hard laws, fail-closed  │   │   │   ← the police
        │  │  │  ┌───────────────────────────┐   │   │   │
        │  │  │  │  Daemon — resource broker  │   │   │   │   ← the quartermaster
        │  │  │  │  (manifest + config +     │   │   │   │
        │  │  │  │   VRAM gate + dispatch)   │   │   │   │
        │  │  │  └───────────────────────────┘   │   │   │
        │  │  └─────────────────────────────────┘   │   │
        │  └───────────────────────────────────────┘   │
        └─────────────────────────────────────────────┘
```

Each layer is independent and **defends even if the outer one is skipped**:

- Launch plain `claude` instead of `kx`? `CLAUDE.md` still loads.
- Agent ignores `CLAUDE.md`? Hooks still fire.
- This is defense-in-depth, not a single gate.

---

## The gears — what each layer actually does

### 1. `kx` — the launcher / airlock

- A thin shell wrapper you run **instead of `claude`**.
- **Injects pre-context** every session: the alignment contract + the current project's
  `next.md` (its working memory) straight into the system prompt.
- Adds `--dangerously-skip-permissions` **only inside the kniox tree** — the agent moves
  freely at home, not in the wild.
- Subcommands are the whole UX: `kx new <project>`, `kx <project>` (enter it), `kx status`,
  `kx setup`, `kx doctor`.

### 2. `CLAUDE.md` — the constitution / floor

- The always-on behavioral floor that loads no matter how the agent starts.
- States the non-negotiables in plain language **so the agent doesn't waste cycles fighting
  the hooks**: uv-only, one specialized model per task, detect-don't-assume, every project
  must be registered and carry a `next.md`.
- `@import`s the full operational standard (`alignment/PROJECT-ALIGNMENT-REQUIREMENT.md`).

### 3. Hooks — the hard laws (the innovative core)

These are **OS-level Python/shell gates** wired into Claude Code's hook system. They fire
*even under skip-permissions* — this is what makes "give the agent full autonomy safely"
actually true.

- **`guard-uv.py`** (PreToolUse / Bash) — blocks destructive commands, bans bare
  `pip`/`conda`/`venv`/`poetry`, blocks remote-exec vectors (`uv run <url>`, `uvx`), enforces
  the uv toolchain.
- **`guard-state.py`** (PreToolUse / Edit) — protects the *rails themselves*: the agent
  cannot edit `.claude/`, `kx`, the hooks, or the alignment files. The world's laws are out of
  the prisoner's reach.
- **`cap-nextmd.py`** (Stop) — hard-caps the project's working memory so context never
  silently bloats every future session.
- **`session-end-append.py`** (Stop) — logs telemetry *out of* the prompt context.
- **`subagent-align.sh`** (SubagentStart) — injects the alignment digest into **every**
  subagent. Governance is inherited, not just top-level.

**Two defining properties:**

- **Fail-closed** — if a hook can't parse its input (e.g. a Claude Code schema change), it
  *blocks* rather than silently opening. The safe failure direction.
- **One-way override** — `KNIOX_BYPASS_HOOKS=1` must be set in the *launching* shell; the
  agent's own Bash subshell can't set it, **so the agent cannot disable its own guards**.

### 4. The daemon — the quartermaster

- A registry + resource broker exposed to the agent as the **`dispatch` MCP tool**.
- **Capability manifest (facts) vs config (decisions)** — two generated files:
  - `manifest.json` = *detected* hardware, accelerators, backends, optional fleet.
    Regenerated, never hand-edited.
  - `config.json` = *chosen* backend, VRAM budget, task→model map. Human-refined.
- **VRAM broker** — before any heavy model loads, the daemon checks it against a budget.
  "One specialized model per task" is enforced, not hoped.
- **`dispatch` is deliberately NOT an inference proxy** — it routes *specialized* generation
  jobs (vision, image, batch) to local models, while the agent's own brain stays Claude. It
  refuses to impersonate the Anthropic streaming API.

---

## What it presents — the experience

- **For the human:** a handful of `kx` verbs and a project folder. You don't manage the
  agent's environment by hand — you describe the laws once, and the world enforces them.
- **For the agent:** a self-describing world. It can *ask the daemon* what hardware exists,
  what models are available, and whether a load will fit — instead of guessing.
- **Per project:** a `next.md` that *is* the agent's persistent working memory — injected
  every session and auto-capped so it stays a tight, curated state file rather than an
  ever-growing log.

---

## Why it's innovative

- **Inversion of host/guest.** The agent is the sandboxed process; the framework is the OS.
  Almost all "AI coding" tooling does the opposite (agent orchestrates the environment). This
  is what lets autonomy be *safe* rather than *scary*.
- **Governance that survives the agent ignoring it.** Four independent layers, each enforcing
  even if the outer is bypassed. The laws live where the prisoner can't reach them.
- **"Detect, never assume."** Zero baked-in hardware/model/backend constants. A probe writes a
  manifest; everything downstream reads facts, not guesses. Runs identically on a laptop, a
  single workstation, or a workstation fronting a Tailscale fleet.
- **"Fail honest" as a first-class principle.** What can't be measured is recorded as `null`
  with a note — *never* a convenient zero. (The bug that birthed this: the old broker read
  "0 GB used" on any non-NVIDIA box and approved every load. Honesty over false confidence.)
- **Fail-closed security with a one-directional escape hatch.** Guards block on the safe side,
  and the override is structurally unreachable by the agent itself.
- **Specialized-model dispatch without proxy fragility.** Best-model-per-task routing that
  refuses to masquerade as the agent's own model API — keeping the brain Claude while
  offloading narrow jobs locally.
- **Opt-in cluster abstraction.** A personal Tailscale fleet becomes a documented, brokered
  resource pool — but it's an *opportunistic bonus layer*, never a requirement. The framework
  never assumes you have more than one machine.

---

## In one breath

> **kniox is an operating environment that treats an autonomous coding agent as a powerful but
> untrusted process** — giving it real freedom inside hard, fail-closed, self-protecting laws,
> a truthful map of its own machine, and a broker that rations scarce GPU memory — so "let the
> AI run with the keys" becomes a governed, reproducible, hardware-agnostic system instead of a
> leap of faith.

---

## How kniox is vetted — adversarial dual-model review

> This is **not** a fifth runtime layer — it's a *development-time* check that lives outside
> the agent's world. But it earns a place here because it practises the same philosophy kniox
> preaches: **don't trust a single judge; cross-check, and fail honest.**

The repo carries its own review harness in [`../reviewers/`](../reviewers/) — two standalone,
dependency-free scripts that ship the whole codebase to **two independent commercial models**
and collect their verdicts separately:

```
                 ┌──────────────────────────┐
   kniox repo ──►│  deepseek_review.py       │──► DeepSeek (chunked, ~30k-tok calls)
        │        └──────────────────────────┘            │
        │                                                 ├─► two independent verdicts
        │        ┌──────────────────────────┐            │   reconciled by hand
        └───────►│  gemini_review.py         │──► Gemini (~1M-tok window, one shot)
                 └──────────────────────────┘
```

- **Deliberately low-overlap.** The two models are run independently and tend to catch
  *different classes* of problem — in the last pass DeepSeek surfaced shell-script security
  issues while Gemini caught runtime correctness/reliability bugs, and they *independently
  converged* on the single most important regression. Agreement is signal; divergence is
  coverage.
- **Direct-to-cloud, on purpose.** These scripts call the DeepSeek / Gemini APIs directly
  (their own key resolution, no third-party deps) rather than going through the daemon's
  `dispatch` — they vet kniox from *outside* the governed world, so they don't inherit its
  rails.
- **Findings are verified, not trusted.** Every reported issue is checked against the real
  source before action; the reconciled outcome lives in
  [`../reviewers/response_to_reviewers.md`](../reviewers/response_to_reviewers.md).

---

## Where to go next

- **Set it up:** [`../README.md`](../README.md) — install, `kx setup`, the four-layer detail.
- **The source of truth:** [`MANIFEST.md`](MANIFEST.md) — manifest/config schema and the
  honesty rule.
- **The contract:** [`../CLAUDE.md`](../CLAUDE.md) +
  [`../alignment/PROJECT-ALIGNMENT-REQUIREMENT.md`](../alignment/PROJECT-ALIGNMENT-REQUIREMENT.md).
- **How it's vetted:** [`../reviewers/`](../reviewers/) — the dual-model review scripts and the
  reconciled [`response_to_reviewers.md`](../reviewers/response_to_reviewers.md).
