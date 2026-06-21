# kniox — Alignment Contract

This repo is **kniox**. You (Claude Code) operate inside it. Projects live under
`projects/` and inherit this file automatically via the directory walk-up.

## Non-negotiables (enforced by hooks; stated here so you don't fight them)
- **uv only.** All Python env/package/run ops use `uv` (`uv add`, `uv sync`, `uv run`).
  pip / conda / venv / poetry are blocked.
- **One specialized model per task.** Never co-load heavy models past the VRAM budget.
  Dispatch heavy generation through the daemon (`dispatch` MCP tool), which brokers VRAM.
- **Detect, never assume hardware/backends.** There are no baked-in GPU sizes, model
  rosters, or backend assumptions. The broker reads detected facts from
  `daemon/state/manifest.json` and decisions from `config.json` (run `kx setup` to
  generate them). Unmeasurable resources are `null`, not zero — treat unknown as unknown.
- **Framework state required.** Every project under `projects/` must be registered and
  carry a `next.md`. Edits inside an unprepared project are blocked. `next.md` is injected
  every session and hard-capped on Stop — keep it small and **overwrite, don't append**.
- **PR-only; never push to `main`.** Every change lands via a pull request. Never push or
  commit directly to `main` / the main repo; nothing merges without explicit approval. Each
  set of major edits gets its own branch → verify it works and breaks nothing → open a PR → stop.
- **Personal projects never touch this repo.** kniox is a PUBLIC framework. A project's
  name, idea, domain, or any identifying specifics MUST NOT appear in tracked files, commit
  messages, PR titles, or PR bodies here. All project specifics live only in the project's
  own gitignored repo under `projects/` plus the local daemon registry; the dashboard reads
  projects dynamically at runtime. Only generic framework enhancements are proposed as PRs.
  Enforced by `guard-privacy.py` (PreToolUse + git pre-commit) and the `projects/*`,
  `dashboard/*/` gitignores.
- **Terse by default — execution over explanation.** Spend tokens doing, not narrating.
  User-facing text is short, plain, minimal: the result and the next step, not a lecture.
  Recommend a tool by name; skip the essay. No framework/language detail unless asked.
  Verbosity is opt-in.

## Per session
- The `kx` launcher injects this alignment + the current project's `next.md` as
  pre-context. Before finishing, update the project's `next.md` Session Log with a
  one-line summary (a Stop hook also appends a timestamp as a safety net).

## Full operational standard
@import ./alignment/PROJECT-ALIGNMENT-REQUIREMENT.md
