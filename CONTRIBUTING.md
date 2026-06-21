# Contributing to kniox

Contributions are very welcome — especially on the open design items in
[`ROADMAP.md`](ROADMAP.md). These are intentionally under-specified; the design discussion *is* the
contribution. Start by commenting on a `help wanted` issue with your approach before sending a large
PR.

## The grain of the project

Keep changes aligned with kniox's core principles (they're enforced, not decorative):

- **Enforce in the right layer.** Governance belongs in the hooks (`.claude/hooks/`) or the daemon,
  not in prose the agent can ignore. Read [`docs/OVERVIEW.md`](docs/OVERVIEW.md) first.
- **Detect, never assume.** No baked-in hardware sizes, model rosters, or backend assumptions.
  Probe, write it to the manifest, read facts downstream.
- **Fail honest.** What you can't measure is `null` with a note — never a convenient zero.
- **Fail closed.** Security hooks block on unparseable input; the override
  (`KNIOX_BYPASS_HOOKS=1`) is reachable only from the launching shell, never the agent's subshell.
- **uv only** for Python. `pip`/`conda`/`venv`/`poetry` are blocked by design.

## Workflow

1. Fork and branch from `main`.
2. Make the change; run `kx doctor` to confirm the rails still come up clean.
3. If you touched a hook, drive it directly with sample JSON payloads on stdin and assert the exit
   codes (the only trustworthy test of a fail-closed guard).
4. Open a PR describing what you changed and which principle(s) it touches.

## Good first contributions

- The two roadmap items (conversation corpus, local-LLM offload) — see the `help wanted` issues.
- A CI smoke test that runs `kx doctor` on Linux + macOS.
- Hook unit tests (valid/invalid stdin → expected exit codes).

## Change workflow (rule #1)
Every set of major edits gets its own branch and is raised as a Pull Request — never
pushed or merged automatically. Sequence: branch → implement → verify it works and breaks
nothing → open a PR. Nothing reaches `main` directly; no push/merge without explicit OK.
