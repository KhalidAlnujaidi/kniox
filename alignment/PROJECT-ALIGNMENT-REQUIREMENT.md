# Kniox Project Alignment Requirement

_Global operational standard for all projects in the Kniox ecosystem._

## Scope
Governs all projects under `projects/`. Any directory initialized or moved here
becomes a native Kniox Project, managed by the daemon and bound by these rules.

## Privacy — personal projects stay private (hard rule)

### Two repositories
- **`KhalidAlnujaidi/kniox` — PUBLIC.** A curated, clean mirror of generic framework
  functionality only. Zero personal secrets, projects, names, or ideas.
- **`KhalidAlnujaidi/kniox-private` — PRIVATE.** The working repo (`~/kniox` points here).
  The default location for **everything**.

### Rules
1. **Default to private.** All development, project source, project progress, registrations,
   specs, experiments, logs, and anything personal lives **only** in the private repo (or each
   project's own gitignored repo under `projects/`; kniox ignores `projects/*` and `dashboard/*/`).
2. **While developing, nothing reaches the public repo** — no direct push to any branch, ever.
3. **The only thing that reaches the public repo is a generic framework enhancement or tweak to
   system functionality, and only as a pull request** — never a push, never project content,
   never a personal name, idea, secret, or key.
4. **One test before anything touches public:** *"Is this a generic framework improvement with
   zero personal or project content?"* If not certain, it stays private.
5. The public repo is already verified clean — **do not re-audit it** unless you change what it
   publishes.

A personal project's name, idea, domain, or any identifying specific MUST NEVER appear in
tracked files, commit messages, PR titles, or PR bodies that reach the public mirror.
Per-project facts live in the local daemon registry, which the dashboard reads at runtime.
Enforced by `guard-privacy.py` (a PreToolUse hook and a git pre-commit hook — enable the latter
once per clone with `git config core.hooksPath .githooks`).

## Core principle
Specialized models per task — never general-purpose models multitasking. Best
quality comes from the best specialized model for each single job, run as a
sequential pipeline in scheduled compute slots. Never saturate local VRAM with
concurrent heavy loads.

## Hardware & backends are detected, not assumed
There are **no fixed GPU sizes, model names, or backends** in this contract. The host's
real capabilities live in the generated `daemon/state/manifest.json` (run `kx setup`);
the chosen backend, VRAM budget, and task→model map live in `config.json`. The broker
reads those. Unmeasurable resources are `null`, never zero. The framework runs the same
on a laptop, a single workstation, or a workstation fronting a Tailscale fleet.

## Active project catalog & stacks
Per-deployment. **Keep this table generic in the committed doc** (see the Privacy rule):
real project names/foci stay out of version control — the live catalog is the local daemon
registry (`python daemon/daemon.py list`) plus each project's own gitignored repo. Map each
project's tasks to models the configured backend actually has (`config.json` → `task_models`).
The shape only:

| Project | Focus | text model | vision model | Slot |
|---|---|---|---|---|
| _example_ | _what it produces_ | _from your backend_ | _from your backend_ | daytime / render / nightly |

## Toolchain standards
1. **uv is the standard.** Clean `pyproject.toml` + deterministic `uv.lock`. pip-venv / conda prohibited.
2. **Execution:** run scripts via `uv run <script>`.

## Compute & VRAM (brokered by the daemon)
VRAM budget and per-accelerator capacity come from the manifest/config, not this table.
Slots are scheduling hints only:

| Slot | Allocation | Notes |
|---|---|---|
| daytime / on-demand | interactive dev | one model, fast unload |
| render window | heavy pipelines | sequential queue |
| nightly | batch jobs | unattended |

## Offload-first routing (brokered by the daemon)
All jobs go through the daemon, which classifies each by resource profile:
- **GPU work → enigma only**, serialized behind a single-GPU lease (one heavy model at a time).
- **Needs enigma-local files / interactive / RAM over worker headroom → enigma.**
- **CPU-only, self-contained, modest-RAM, non-interactive → a k3s worker (default).**

There is no shared storage: offloaded jobs fetch inputs over the network and return via
stdout. Every job script MUST start, before its imports, with a placement header:
`# kniox: placement=<enigma-gpu|enigma-local|cluster|auto> [key=value ...]`
`auto` (or no header) lets the classifier decide.

## Custodian (overseer)
A locally-run LLM **custodian** periodically surveys the whole framework (operational health
+ alignment) and writes a read-only "state of the framework" report to `custodian/reports/`.
It selects its model at runtime (largest that fits the budget), runs **brokered** through the
daemon (GPU-leased), proposes but never applies changes, and yields to real jobs. It is the unified overseer; the nightly cron is `corn/custodian.sh`, and the always-on
service is `corn/custodian.service` (systemd user unit, shipped not auto-enabled). The
custodian holds a **low-priority, revocable** GPU lease: it runs only when the GPU is idle
(no non-custodian lease holder) and yields the instant a real job preempts it.

## Working agreement — PR-only, never push to `main`
Every change lands via a **pull request**. Never push or commit directly to `main` / the main
repo; nothing merges without explicit approval. Each set of major edits gets its own branch →
verify it works and breaks nothing → open a PR → stop.

## Terse by default — execution over explanation
Inside a kx environment, agents spend tokens on doing, not narrating.
- Prioritize execution over explanation: fewer output tokens, more done.
- User-facing text is short, descriptive, minimalistic — plain language over jargon.
- Recommend a tool/library by name; skip the essay. No detail on frameworks or languages unless asked.
- Verbosity is opt-in: the user can always ask for more.

## Active alignment tasks
- [ ] Run `kx setup` on this host (and `--fleet` if it fronts a tailnet).
- [ ] Choose/install a backend and fill `config.json` → `task_models`.
- [ ] Populate the project catalog above for this deployment.

## Maintenance
Re-run `kx setup` when hardware/backends change; edit `config.json` for model/budget
decisions. Code conforms to the alignment; the alignment does not bend to un-reviewed code.
