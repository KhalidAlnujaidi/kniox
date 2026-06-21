# kniox Custodian — Design (Phase 1: one-shot overseer)

_Date: 2026-06-21 · Status: approved design_

## Problem

kniox has rich operational state (daemon registry, runs, GPU lease, VRAM snapshot, k3s
cluster facts, compute slot) and a nightly `kx audit` that only checks alignment drift.
There is no single, local, intelligent overseer that looks at the *whole* operation —
health + alignment + improvement opportunities — and reports it. The custodian fills that
gap: a locally-run LLM that surveys the framework and writes one "state of the framework"
report. Read-only — it proposes, never applies.

## Goals

- One command surveys the framework's operational + alignment state and produces a single
  markdown report via a **local** model.
- Model choice is made **at runtime** (largest backend model that fits the VRAM budget) —
  never hardcoded (alignment rule).
- All heavy inference goes **through the daemon broker** (GPU-leased), never direct.
- **Read-only**: writes only under `custodian/`; never edits code or projects.
- Honest degradation everywhere: no fabricated success; missing data is reported as such.
- Absorbs the nightly alignment audit into one unified report.

## Non-goals (Phase 2, separate PR)

- The always-on systemd service, idle-poll loop, `gpu_is_idle`, and **preemptible lease v2**.
- Acting on findings (applying fixes). The custodian only reports.
- A served dashboard UI.

## Decisions

- **Code placement:** flat `daemon/custodian_*.py` modules (consistent with the broker;
  reuses the `pythonpath=["daemon"]` test harness). Reports + state at repo-root
  `custodian/` (`custodian/reports/`, `custodian/state.json`).
- **Cron:** the custodian's cron **replaces** `corn/audit.sh` (one overseer).

## Components

### 1. `daemon/custodian_survey.py`
Isolated collectors snapshot framework state into one dict. Each collector is wrapped so a
failure yields `{"error": "..."}` for that section (honest), not a crash:
- **operational:** `daemon.list_projects()`, recent `runs` grouped by state, `current_slot()`,
  `lease.gpu_lease_status()`, `daemon.vram_snapshot()` / `system_resources()`, cluster facts
  (`cluster.cluster_facts()`).
- **repo/work:** `git status --porcelain`, K most-recently-modified files, K most-stale
  files, per-project `next.md` presence.
- Exposes `survey() -> dict` and `material_fingerprint(survey) -> str` (a stable hash over
  the fields that should trigger a new report — excludes always-changing noise like live
  CPU%).

### 2. `daemon/custodian_model.py`
`select_model(config=None) -> (name|None, reason)`. Picks the **largest** model the backend
has that fits the VRAM budget, using `backend.models()` sizes and `daemon.can_load`. Returns
`(None, reason)` when nothing fits or no backend — caller degrades honestly. No hardcoded
model names.

### 3. `daemon/custodian_report.py`
- `build_prompt(survey, alignment_text) -> str` — alignment-contract digest + survey digest
  + fixed instruction: "Report only: misalignments, easy wins, bugs, optimizations. Propose,
  do not apply."
- `run(force=False) -> dict` — orchestrates: survey → fingerprint skip (unless `force`) →
  select_model → `daemon.dispatch(task="custodian", prompt, model=selected)` (brokered +
  GPU-leased) → write `custodian/reports/custodian_DDMMYY.md`, update `custodian/reports/latest.md`,
  persist fingerprint to `custodian/state.json`. Returns a status dict
  (`{written, path, skipped?, reason?, model?}`).

### 4. CLI + MCP + cron
- `daemon.py custodian run [--force]` subcommand → `custodian_report.run`.
- MCP tools: `custodian_report()` (return latest report text/path) and
  `custodian_run(force=False)` (trigger a run).
- `corn/custodian.sh` runs `kx`-style in the idle/nightly slot; replaces `audit.sh`.

## Data flow

```
custodian run [--force]
  → survey()                        (operational + repo state, honest nulls)
  → fingerprint vs custodian/state.json   → skip if unchanged and not --force
  → select_model()                  (largest fit; None → honest skip)
  → build_prompt(survey, alignment) → daemon.dispatch(task="custodian", model=…)  [leased]
  → write custodian/reports/custodian_DDMMYY.md + latest.md + state.json
```

## Honest degradation

- No backend / no model fits → return `{skipped: true, reason: "no model fits budget"}`; no fake report.
- **GPU busy** → `dispatch` returns its busy error → custodian returns `{skipped: true, reason: "GPU busy"}` and exits cleanly (lowest priority; yields to real work).
- A collector error → that survey section carries `{"error": …}`; the report still generates.
- Fingerprint unchanged → `{skipped: true, reason: "no change since last report"}`.

## Read-only guarantee

The custodian writes only under `custodian/` (reports + `state.json`). A unit test asserts
`run()` (with `dispatch` mocked) touches no path outside `custodian/`.

## Testing

- `custodian_survey`: each collector with daemon functions monkeypatched; a failing collector
  yields an `{"error": …}` section, not a crash; `material_fingerprint` is stable across
  noise-only changes and changes on material changes.
- `custodian_model`: largest-fit selection; none-fit → `(None, reason)`; no backend → `(None, reason)`.
- `custodian_report`: `build_prompt` includes the instruction + alignment digest; `run`
  writes the dated report + `latest.md` + `state.json` (dispatch mocked); fingerprint skip
  path returns skipped without dispatching; GPU-busy path returns skipped.
- Read-only test: `run` (dispatch mocked) writes nothing outside `custodian/`.
- Gated end-to-end: a real `custodian run` produces a non-empty report when a model is
  available (skipped otherwise), mirroring the broker's live test.

## Alignment changes

Add the custodian to the alignment doc (it is the unified overseer; the nightly cron is now
`custodian run`). Note it is read-only and brokered.

## Phasing

- **Phase 1 (this PR):** everything above — one-shot `custodian run`, survey, model-select,
  report, MCP, cron (replacing audit.sh). Reuses the broker's existing lease (safe in the
  idle slot).
- **Phase 2 (separate PR):** always-on systemd service + preemptible lease v2 + `gpu_is_idle`
  + idle-poll loop + fingerprint-driven rest interval (the full original sketch).
