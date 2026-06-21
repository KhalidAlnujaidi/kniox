# Shadow-Git Gate — design

**Status:** implemented (Phase 1) · **Branch:** `feat/shadow-git` · **Date:** 2026-06-21

## Problem
Agent edits hit the real working tree immediately; tests run *after*, so a bad change is
already live before it's caught. Recovery means `git reset` archaeology, and unattended
workers (nightly jobs) can leave the tree broken with no one watching.

## Gate: propose → isolate → verify → apply
`daemon/shadow.py :: shadow_run(repo, change_cmd, verify_cmd, apply=True, keep=False)`

1. **Isolate** — `git worktree add -b shadow/<id> .kniox/shadow/<id> <HEAD>`. A throwaway
   checkout on its own branch, backed by the same `.git` (no repo copy).
2. **Change** — run `change_cmd` *inside the worktree*. Non-zero exit → stop, real tree
   untouched (`stage: change`).
3. **Verify** — commit the edits on the shadow branch, run `verify_cmd` there
   (e.g. `uv run pytest`). Red → discard worktree+branch, real tree untouched
   (`stage: verify`).
4. **Apply** — green only: diff `base..HEAD`, `git apply --3way --binary` into the real
   working tree, left **uncommitted** for the normal PR step (`applied: true`).

Cleanup is automatic. The shadow branch is dropped on clean success/red; it is **kept**
(the only copy of a good change) when `apply=False`, an apply fails, or `keep=True`.

## Surfaces
- CLI: `python daemon/daemon.py shadow "<change>" "<verify>" [--repo .] [--no-apply] [--keep]`
- MCP: `shadow_run(change_cmd, verify_cmd, repo, apply, keep)`

## Alignment (does not bend the contract)
- **PR-only / never main** — refuses to apply onto `main`/`master` (`stage: protected-branch`);
  apply target is the current feature branch. The gate *is* the pre-PR verify step.
- **GPU / one-model-per-task** — pure git + CPU, **no model, no VRAM, no lease**. Cannot
  contend with real jobs. Eligible to run on a k3s worker later (offload-first).
- **uv** — verify command is `uv run …`; complements `guard-uv`.
- **Daemon-owned** — lifecycle (create/verify/apply/cleanup) lives in the daemon, so it
  stays the single broker. No parallel execution path.

## Deliberately out of scope (Phase 1)
- Transparent interception of the agent's own `Edit`/`Write` tools — fragile (absolute
  paths to the real tree). The gate is **opt-in per job**, invoked around a change command;
  it does not force every interactive edit through isolation.
- Binary/large-file patches rely on `git apply --binary`; very large blobs untested.

## Value
High safety-per-hour, zero VRAM cost. Best fit: the unattended nightly workers — they can
run "generate + edit" behind the gate so a failed run never corrupts the tree. For purely
interactive sessions where every edit is watched, it's a nice-to-have, not essential.
