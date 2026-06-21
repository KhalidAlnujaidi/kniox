# Custodian Phase 2 — Design (preemptible lease + always-on service)

_Date: 2026-06-21 · Status: approved design_

## Problem
Phase 1 custodian is one-shot, reusing the broker lease (safe only in idle slots). Phase 2
makes it an always-on overseer that runs whenever the GPU is idle and **instantly yields**
to real jobs. This needs a preemptible GPU lease and a long-running service loop.

## Goals
- A real job preempts an idle custodian within a short grace window.
- Custodian runs continuously, lowest priority, only when the GPU is idle and state changed.
- No fabricated report on abort; honest degradation throughout.
- Reuse Phase 1 survey/model/report; minimal change to `dispatch`.

## Non-goals
- Streaming/instant token-level abort (coarse grace is enough; revisit later).
- Auto-enabling the systemd unit (host action).
- Gating idle on running `runs` (idle = no non-custodian lease holder).

## Lease v2 (`daemon/lease.py`)
- Schema gains `priority TEXT` and `revoked INTEGER` columns (migration: `ALTER TABLE ... ADD COLUMN` guarded by a try/except, or recreate — see plan).
- `acquire_gpu(holder, task, priority="normal", ttl=1800, wait=True, poll=0.05, timeout=None, grace=10.0) -> bool`:
  - **low** priority (custodian): granted only when no live holder (`gpu_is_idle`). Never preempts.
  - **normal** priority (real jobs): against a live **low** holder → set that holder's `revoked=1`, wait up to `grace` for it to release, then **force-steal** (overwrite). Against a live **normal** holder → existing bounded-wait behavior.
- `is_revoked(holder) -> bool` — the low holder polls this to yield.
- `gpu_is_idle() -> bool` — True when no live holder, OR the only live holder is `low` priority (custodian). i.e. no live **non-custodian** holder.
- `release_gpu(holder)` clears the row (unchanged, holder-scoped).
- `dispatch` (daemon.py) acquires with `priority="normal"` (the default) — so real jobs preempt automatically.

## Custodian service (`daemon/custodian_service.py`)
- `serve(poll_idle=30, rest=1800, once=False)`: loop —
  1. if not `gpu_is_idle()` → sleep `poll_idle`, continue.
  2. survey + fingerprint; unchanged → sleep `rest`, continue.
  3. `acquire_gpu(holder="custodian", task="custodian", priority="low")`; if not granted → sleep `poll_idle`, continue.
  4. run report with a revoke-check callback (`lease.is_revoked("custodian")`); on revoke → discard, release, sleep `poll_idle`, continue.
  5. write report, save fingerprint, release, sleep `rest`.
- `once=True` runs a single iteration (testable; also what cron uses).

## custodian_report change
- `run(force=False, revoked=None)`: `revoked` is a zero-arg callable. Check it before `select_model`, before `dispatch`, and use the existing `dispatch` busy/error path. If `revoked()` is true at a checkpoint → `{"skipped": True, "reason": "preempted"}` (no report written). The custodian holds the lease itself, so `run` here dispatches with an explicit model and the lease already held — to avoid double-lease, the service path calls report generation that does NOT re-acquire (dispatch's normal-priority acquire would also try to preempt the custodian's own low lease). **Decision:** the service calls a lease-free generation helper `custodian_report.generate_report(model, survey, revoked)` that calls `backend.generate` via the configured backend directly under the already-held custodian lease — NOT `daemon.dispatch`. Phase 1 `run()` (cron/CLI one-shot) keeps using `dispatch`.

## Packaging
- Ship `corn/custodian.service` (systemd **user** unit: `ExecStart=… daemon.py custodian serve`, `Restart=always`, `Nice=19`). Not auto-enabled; `dashboard/README` or `corn/` note documents `systemctl --user enable --now custodian`.
- `daemon.py custodian serve [--once]` CLI; the nightly `corn/custodian.sh` can call `serve --once`.

## Honest degradation
- Preempted → skipped "preempted", no report. Lease force-steal bounded by `grace`; low holder also has a short TTL backstop.
- No model / no backend → skipped (Phase 1 behavior).

## Testing
- lease: low granted only when idle; normal preempts low (sets revoked, steals after grace); normal-vs-normal unchanged; `is_revoked`; `gpu_is_idle` true with only a low holder, false with a normal holder.
- service: `serve(once=True)` — not-idle → no run; unchanged fingerprint → no run; happy path → acquire(low)+generate+write+release; revoked mid-run → discard+release, no report.
- report: `generate_report` aborts when `revoked()` true; does not call dispatch (no double-lease).
- preempt integration (gated/real): custodian holds low lease; a `priority="normal"` acquire steals within grace.

## Phasing
Single PR. (Streaming abort + a lease force-release admin surface remain future polish.)
