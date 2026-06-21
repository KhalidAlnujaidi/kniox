# Custodian Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the custodian an always-on overseer that runs only when the GPU is idle and instantly yields to real jobs, via a preemptible GPU lease and a service loop.

**Architecture:** Extend `daemon/lease.py` with priority + a revoke flag (low = custodian, normal = real jobs; a normal acquire revokes a low holder and force-steals after a grace window). A new `daemon/custodian_service.py` loops: idle-check → fingerprint → acquire low lease → generate (under the held lease) → write → release. `daemon.dispatch` is unchanged (acquire defaults to normal priority, so it preempts automatically).

**Tech Stack:** Python 3.11+ stdlib (sqlite3, time), existing custodian_*/lease/backends modules, systemd user unit, pytest via uv.

## Global Constraints
- **uv only**; tests `uv run pytest`. Ignore the `libtinfo.so.6` stderr line.
- **No new deps**; stdlib + existing modules.
- **Flat imports** in `daemon/`; tests import bare; path/env patterns reuse `KNIOX_CUSTODIAN_DIR`.
- **Honest degradation**: preempted/busy/no-model/unchanged → explicit `{skipped, reason}`, never a fabricated report.
- **No hardcoded model/hardware**.
- **Backward compatible lease**: `acquire_gpu` keeps working for existing callers (new params default; `priority="normal"` default). Schema migration must be idempotent (existing DB on the host has no `priority`/`revoked` columns).
- **idle = no live non-custodian (non-low) lease holder** (per design).
- **Known limitation (coarse preemption):** force-steal frees the lease within `grace`, but an in-flight `backend.generate` keeps running until it returns; brief GPU overlap is possible. Streaming abort is deferred. Mitigated by the custodian's short lease TTL and revoke-checks around (not inside) generation.
- **Branch/PR rule**: `feat/custodian-phase2`; commit per task; never push to main; PR only.

---

### Task 1: Preemptible lease v2

**Files:**
- Modify: `daemon/lease.py` (rewrite with priority/revoked/migration/force-steal/idle)
- Test: `daemon/tests/test_lease_v2.py`

**Interfaces:**
- Produces: `acquire_gpu(holder, task, priority="normal", ttl=1800, wait=True, poll=0.05, timeout=None, grace=10.0) -> bool`; `is_revoked(holder) -> bool`; `gpu_is_idle() -> bool`. Unchanged: `release_gpu(holder)`, `gpu_lease_status()`.

- [ ] **Step 1: Write the failing test**

```python
import lease

def test_low_granted_only_when_idle():
    assert lease.acquire_gpu("cust", "c", priority="low") is True
    assert lease.gpu_is_idle() is True            # only a low holder => idle
    lease.release_gpu("cust")

def test_low_busy_when_normal_holds():
    assert lease.acquire_gpu("job", "t", priority="normal") is True
    assert lease.gpu_is_idle() is False
    assert lease.acquire_gpu("cust", "c", priority="low", wait=False) is False
    lease.release_gpu("job")

def test_normal_flags_revoke_on_low():
    assert lease.acquire_gpu("cust", "c", priority="low") is True
    # normal acquirer flags revoke then (wait=False) returns without stealing
    assert lease.acquire_gpu("job", "t", priority="normal", wait=False) is False
    assert lease.is_revoked("cust") is True
    lease.release_gpu("cust")

def test_normal_force_steals_low_after_grace():
    assert lease.acquire_gpu("cust", "c", priority="low") is True
    assert lease.acquire_gpu("job", "t", priority="normal", grace=0.05, timeout=2) is True
    assert lease.gpu_lease_status()["holder"] == "job"
    lease.release_gpu("job")

def test_normal_vs_normal_still_busy():
    assert lease.acquire_gpu("a", "t", priority="normal") is True
    assert lease.acquire_gpu("b", "t", priority="normal", wait=False) is False
    lease.release_gpu("a")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest daemon/tests/test_lease_v2.py -v`
Expected: FAIL — `TypeError: acquire_gpu() got an unexpected keyword argument 'priority'`

- [ ] **Step 3: Rewrite `daemon/lease.py`**

```python
"""Single-GPU lease with priorities + preemption. low = custodian (idle-only, yields);
normal = real jobs (preempt a low holder: flag revoke, wait a grace window, then force-steal).
SQLite-backed; TTL backstops a dead holder. NULL priority (legacy rows) is treated as normal."""
from __future__ import annotations
import contextlib, sqlite3, time
from config import DB_PATH

_SCHEMA = """CREATE TABLE IF NOT EXISTS gpu_lease(
  id INTEGER PRIMARY KEY CHECK (id=1), holder TEXT, task TEXT,
  acquired_at REAL, expires_at REAL, priority TEXT, revoked INTEGER DEFAULT 0);"""


def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute(_SCHEMA)
    for col, decl in (("priority", "TEXT"), ("revoked", "INTEGER DEFAULT 0")):
        try:
            c.execute(f"ALTER TABLE gpu_lease ADD COLUMN {col} {decl}")  # idempotent migration
        except sqlite3.OperationalError:
            pass
    return c


def _upsert(c, holder, task, now, ttl, priority):
    c.execute("INSERT INTO gpu_lease(id,holder,task,acquired_at,expires_at,priority,revoked) "
              "VALUES(1,?,?,?,?,?,0) ON CONFLICT(id) DO UPDATE SET holder=excluded.holder, "
              "task=excluded.task, acquired_at=excluded.acquired_at, expires_at=excluded.expires_at, "
              "priority=excluded.priority, revoked=0",
              (holder, task, now, now + ttl, priority))


def _try_once(holder, task, ttl, priority) -> str:  # "ok" | "busy" | "revoking"
    now = time.time()
    with contextlib.closing(_conn()) as c:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute("SELECT holder, expires_at, priority FROM gpu_lease WHERE id=1").fetchone()
        live = bool(row) and row["expires_at"] > now
        if live and row["holder"] != holder:
            if priority == "normal" and row["priority"] == "low":
                c.execute("UPDATE gpu_lease SET revoked=1 WHERE id=1")
                c.execute("COMMIT")
                return "revoking"
            c.execute("ROLLBACK")
            return "busy"
        _upsert(c, holder, task, now, ttl, priority)
        c.execute("COMMIT")
        return "ok"


def _force_steal(holder, task, ttl, priority):
    now = time.time()
    with contextlib.closing(_conn()) as c:
        c.execute("BEGIN IMMEDIATE")
        _upsert(c, holder, task, now, ttl, priority)
        c.execute("COMMIT")


def acquire_gpu(holder, task, priority="normal", ttl=1800, wait=True, poll=0.05,
                timeout=None, grace=10.0) -> bool:
    deadline = None if timeout is None else time.time() + timeout
    revoke_deadline = None
    while True:
        res = _try_once(holder, task, ttl, priority)
        if res == "ok":
            return True
        if res == "revoking":
            if revoke_deadline is None:
                revoke_deadline = time.time() + grace
            if time.time() >= revoke_deadline:
                _force_steal(holder, task, ttl, priority)
                return True
        if not wait or (deadline is not None and time.time() >= deadline):
            return False
        time.sleep(poll)


def release_gpu(holder) -> None:
    with contextlib.closing(_conn()) as c, c:
        c.execute("DELETE FROM gpu_lease WHERE id=1 AND holder=?", (holder,))


def is_revoked(holder) -> bool:
    with contextlib.closing(_conn()) as c:
        row = c.execute("SELECT holder, revoked, expires_at FROM gpu_lease WHERE id=1").fetchone()
    return bool(row and row["holder"] == holder and row["expires_at"] > time.time() and row["revoked"])


def gpu_is_idle() -> bool:
    now = time.time()
    with contextlib.closing(_conn()) as c:
        row = c.execute("SELECT priority, expires_at FROM gpu_lease WHERE id=1").fetchone()
    if not row or row["expires_at"] <= now:
        return True
    return row["priority"] == "low"


def gpu_lease_status() -> dict | None:
    now = time.time()
    with contextlib.closing(_conn()) as c:
        row = c.execute("SELECT * FROM gpu_lease WHERE id=1").fetchone()
    if not row or row["expires_at"] <= now:
        return None
    return dict(row)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest daemon/tests/test_lease_v2.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Regression — existing lease + dispatch tests still pass**

Run: `uv run pytest daemon/tests/test_lease.py daemon/tests/test_dispatch_lease.py -v`
Expected: PASS (existing behavior intact; `acquire_gpu`'s new params are defaulted)

- [ ] **Step 6: Commit**

```bash
git add daemon/lease.py daemon/tests/test_lease_v2.py
git commit -m "feat: preemptible GPU lease v2 (priority + revoke + force-steal + gpu_is_idle)"
```

---

### Task 2: Custodian service loop

**Files:**
- Create: `daemon/custodian_service.py`
- Test: `daemon/tests/test_custodian_service.py`

**Interfaces:**
- Consumes: `lease.gpu_is_idle/acquire_gpu/is_revoked/release_gpu`, `custodian_survey.survey/material_fingerprint`, `custodian_model.select_model`, `custodian_report._load_state/_save_state/_write_report/_reports_dir/build_prompt/_alignment_text`, `backends.get_backend`, `config.load_config`.
- Produces: `run_once() -> dict`; `serve(poll_idle=30, rest=1800, once=False)`; `_generate(model, survey) -> str`; `HOLDER = "custodian"`.

- [ ] **Step 1: Write the failing test**

```python
import custodian_service as cs
import custodian_report as report

def _common(monkeypatch, tmp_path, fp_state):
    monkeypatch.setenv("KNIOX_CUSTODIAN_DIR", str(tmp_path / "custodian"))
    monkeypatch.setattr(cs.lease, "gpu_is_idle", lambda: True)
    monkeypatch.setattr(cs.custodian_survey, "survey", lambda: {"x": 1})
    monkeypatch.setattr(cs.custodian_survey, "material_fingerprint", lambda s: "fp")
    monkeypatch.setattr(cs.report, "_load_state", lambda: fp_state)
    monkeypatch.setattr(cs.custodian_model, "select_model", lambda: ("m", "r"))

def test_skips_when_busy(monkeypatch):
    monkeypatch.setattr(cs.lease, "gpu_is_idle", lambda: False)
    out = cs.run_once()
    assert out["skipped"] and "busy" in out["reason"]

def test_skips_when_unchanged(monkeypatch, tmp_path):
    _common(monkeypatch, tmp_path, {"fingerprint": "fp"})
    out = cs.run_once()
    assert out["skipped"] and out["reason"] == "no change"

def test_happy_path_writes_and_releases(monkeypatch, tmp_path):
    _common(monkeypatch, tmp_path, {})
    monkeypatch.setattr(cs.lease, "acquire_gpu", lambda *a, **k: True)
    monkeypatch.setattr(cs.lease, "is_revoked", lambda h: False)
    monkeypatch.setattr(cs, "_generate", lambda model, survey: "REPORT")
    rel = {}
    monkeypatch.setattr(cs.lease, "release_gpu", lambda h: rel.__setitem__("h", h))
    out = cs.run_once()
    assert out["written"] and out["model"] == "m"
    assert rel["h"] == "custodian"
    assert (report._reports_dir() / "latest.md").read_text() == "REPORT"

def test_preempted_discards_and_releases(monkeypatch, tmp_path):
    _common(monkeypatch, tmp_path, {})
    monkeypatch.setattr(cs.lease, "acquire_gpu", lambda *a, **k: True)
    monkeypatch.setattr(cs.lease, "is_revoked", lambda h: True)     # revoked immediately
    rel = {}
    monkeypatch.setattr(cs.lease, "release_gpu", lambda h: rel.__setitem__("h", h))
    out = cs.run_once()
    assert out["skipped"] and out["reason"] == "preempted" and rel["h"] == "custodian"

def test_serve_once_returns_run_once(monkeypatch):
    monkeypatch.setattr(cs, "run_once", lambda: {"skipped": True, "reason": "z"})
    assert cs.serve(once=True)["reason"] == "z"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest daemon/tests/test_custodian_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'custodian_service'`

- [ ] **Step 3: Create `daemon/custodian_service.py`**

```python
"""Always-on custodian: runs only when the GPU is idle and state changed, holds a low-priority
revocable lease, and yields the instant a real job revokes it. Lowest priority on the bus."""
from __future__ import annotations
import time
import lease, custodian_survey, custodian_model
import custodian_report as report
from backends import get_backend
from config import load_config

HOLDER = "custodian"


def _generate(model, survey) -> str:
    # Runs UNDER the already-held custodian lease (still brokered by the lease, not via dispatch,
    # to avoid the normal-priority dispatch acquire preempting our own low lease).
    backend = get_backend(load_config())
    return backend.generate(model, report.build_prompt(survey, report._alignment_text()))


def run_once() -> dict:
    if not lease.gpu_is_idle():
        return {"skipped": True, "reason": "gpu busy"}
    survey = custodian_survey.survey()
    fp = custodian_survey.material_fingerprint(survey)
    if report._load_state().get("fingerprint") == fp:
        return {"skipped": True, "reason": "no change"}
    model, reason = custodian_model.select_model()
    if not model:
        return {"skipped": True, "reason": reason}
    if not lease.acquire_gpu(HOLDER, "custodian", priority="low", ttl=600, wait=False):
        return {"skipped": True, "reason": "lease not idle"}
    try:
        if lease.is_revoked(HOLDER):
            return {"skipped": True, "reason": "preempted"}
        text = _generate(model, survey)
        if lease.is_revoked(HOLDER):
            return {"skipped": True, "reason": "preempted"}
        path = report._write_report(text)
        report._save_state({"fingerprint": fp})
        return {"written": True, "path": str(path), "model": model}
    finally:
        lease.release_gpu(HOLDER)


def serve(poll_idle=30, rest=1800, once=False):
    while True:
        res = run_once()
        if once:
            return res
        # rest after real work or a clean no-change; poll sooner when just waiting for idle
        nap = rest if (res.get("written") or res.get("reason") == "no change") else poll_idle
        time.sleep(nap)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest daemon/tests/test_custodian_service.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add daemon/custodian_service.py daemon/tests/test_custodian_service.py
git commit -m "feat: custodian service loop (idle-gated, low-lease, yields on revoke)"
```

---

### Task 3: CLI `serve` + systemd unit

**Files:**
- Modify: `daemon/daemon.py` (extend the `custodian` subparser with `serve` + `--once`)
- Create: `corn/custodian.service`
- Create: `corn/README.md` (enable instructions)
- Test: `daemon/tests/test_custodian_serve_cli.py`

**Interfaces:**
- Consumes: `custodian_service.serve`.
- Produces: CLI `python daemon/daemon.py custodian serve [--once]`.

- [ ] **Step 1: Write the failing test**

```python
import daemon as registry

def test_cli_serve_once(monkeypatch):
    import custodian_service
    monkeypatch.setattr(custodian_service, "serve", lambda once=False: {"once": once})
    assert registry.cli_custodian_serve(once=True) == {"once": True}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest daemon/tests/test_custodian_serve_cli.py -v`
Expected: FAIL — `AttributeError: module 'daemon' has no attribute 'cli_custodian_serve'`

- [ ] **Step 3a: Extend `daemon/daemon.py`**

Add a helper near `cli_custodian`:

```python
def cli_custodian_serve(once=False):
    import custodian_service
    return custodian_service.serve(once=once)
```

Change the `custodian` subparser action choices to include `serve` and add `--once`:

```python
    cu = s.add_parser("custodian"); cu.add_argument("action", choices=["run", "serve"])
    cu.add_argument("--force", action="store_true"); cu.add_argument("--once", action="store_true")
```

Replace the `custodian` handler branch with:

```python
    elif a.cmd == "custodian":
        if a.action == "serve":
            res = cli_custodian_serve(once=a.once)
            if a.once:
                print(json.dumps(res, indent=2))
        else:
            print(json.dumps(cli_custodian(force=a.force), indent=2))
```

- [ ] **Step 3b: Create `corn/custodian.service`**

```ini
[Unit]
Description=kniox custodian — idle-GPU framework overseer
After=network.target

[Service]
Type=simple
WorkingDirectory=%h/kniox
ExecStart=/usr/bin/env uv run python %h/kniox/daemon/daemon.py custodian serve
Restart=always
RestartSec=30
Nice=19

[Install]
WantedBy=default.target
```

- [ ] **Step 3c: Create `corn/README.md`**

```markdown
# corn/ — kniox scheduled jobs

- `custodian.sh` — nightly one-shot custodian run (cron).
- `custodian.service` — always-on custodian service (systemd **user** unit). Shipped, **not**
  auto-enabled. To enable:

      mkdir -p ~/.config/systemd/user
      cp ~/kniox/corn/custodian.service ~/.config/systemd/user/
      systemctl --user daemon-reload
      systemctl --user enable --now custodian

  It runs lowest-priority, only when the GPU is idle, and yields to real jobs.
```

- [ ] **Step 4: Run test + verify the service runs one iteration**

Run: `uv run pytest daemon/tests/test_custodian_serve_cli.py -v`
Expected: PASS (1 passed)
Run: `uv run python daemon/daemon.py custodian serve --once`
Expected: JSON — `{"written": ...}` or `{"skipped": ..., "reason": ...}`. Either is PASS; capture it. (Real run; may load a model.)

- [ ] **Step 5: Commit**

```bash
git add daemon/daemon.py corn/custodian.service corn/README.md daemon/tests/test_custodian_serve_cli.py
git commit -m "feat: custodian serve CLI + systemd user unit (ship, not auto-enabled)"
```

---

### Task 4: Alignment doc note

**Files:**
- Modify: `alignment/PROJECT-ALIGNMENT-REQUIREMENT.md` (update the Custodian section)

**Interfaces:** none (docs).

- [ ] **Step 1: Update the Custodian section** (guarded rail — if the Edit tool is blocked, apply via `KNIOX_BYPASS_HOOKS=1`, the documented escape hatch). Replace the final sentence of the "## Custodian (overseer)" section with:

```markdown
It is the unified overseer; the nightly cron is `corn/custodian.sh`, and the always-on
service is `corn/custodian.service` (systemd user unit, shipped not auto-enabled). The
custodian holds a **low-priority, revocable** GPU lease: it runs only when the GPU is idle
(no non-custodian lease holder) and yields the instant a real job preempts it.
```

- [ ] **Step 2: Verify + commit**

Run: `grep -n "low-priority, revocable" alignment/PROJECT-ALIGNMENT-REQUIREMENT.md`
Expected: one match.

```bash
git add alignment/PROJECT-ALIGNMENT-REQUIREMENT.md
git commit -m "docs: note custodian preemptible lease + always-on service in alignment"
```

---

## Self-Review
**Spec coverage:** lease priority/revoke/force-steal/is_revoked/gpu_is_idle + migration (T1) ✓ · service loop idle-gate/fingerprint/low-lease/revoke-yield/write (T2) ✓ · lease-free `_generate` under held lease, no double-lease (T2) ✓ · CLI serve + systemd unit shipped-not-enabled (T3) ✓ · alignment note (T4) ✓ · dispatch preempts automatically via default normal priority (no change needed; covered by T1 regression in Step 5) ✓ · honest degradation (busy/no-model/preempted/unchanged) (T2) ✓.

**Placeholder scan:** none — full code per step; exact commands + expected outputs.

**Type consistency:** `acquire_gpu(... priority=, grace=)` defined T1, called by service T2 + unchanged dispatch; `is_revoked/gpu_is_idle` defined T1, used T2; `run_once`/`serve(once=)` defined T2, called by CLI T3; service reuses `custodian_report._write_report/_save_state/_load_state/_reports_dir/build_prompt/_alignment_text` (existing Phase-1 names).
