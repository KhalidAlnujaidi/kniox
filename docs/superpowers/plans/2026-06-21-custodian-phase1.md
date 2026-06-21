# Custodian Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A one-shot `custodian run` command — a locally-run LLM overseer that surveys the framework's operational + alignment state and writes a single markdown report, read-only and brokered through the daemon.

**Architecture:** Small flat `daemon/custodian_*.py` modules (survey → model-select → report) composed by `custodian_report.run()`. Inference goes through `daemon.dispatch` (GPU-leased). Reports + state live under repo-root `custodian/`. Reuses the existing broker lease (safe in the idle slot); the always-on preemptive service is Phase 2.

**Tech Stack:** Python 3.11+ stdlib (subprocess, json, hashlib, pathlib, sqlite3), the existing daemon/lease/cluster/backends modules, Ollama backend, pytest via uv.

## Global Constraints

- **uv only** — tests run with `uv run pytest`. Ignore the harmless `libtinfo.so.6` stderr line.
- **No new deps** — stdlib + existing modules only.
- **Flat imports** — new modules in `daemon/`, importing siblings bare (`import daemon as registry`, `import lease, cluster`). Tests import the module under test bare (harness has `pythonpath=["daemon"]`).
- **No hardcoded model/hardware** — the report model is selected at runtime (largest that fits the VRAM budget via `can_load`).
- **All inference brokered** — only via `daemon.dispatch`; never call a backend directly.
- **Read-only** — the custodian writes ONLY under `custodian/` (reports + state). Never edits code/projects.
- **Honest degradation** — no fabricated output; missing data / no model / GPU busy → an explicit skipped result, never a fake report.
- **Custodian dir override** — paths derive from `KNIOX_CUSTODIAN_DIR` (default `KNIOX_HOME/custodian`), mirroring `config.py`'s `KNIOX_STATE_DIR`, so tests use a temp dir.
- **Branch/PR rule** — work on `feat/custodian`; commit per task; never push/merge without explicit OK.

---

### Task 1: Survey collectors + daemon `list_runs`

**Files:**
- Modify: `daemon/daemon.py` (add `list_runs`)
- Create: `daemon/custodian_survey.py`
- Test: `daemon/tests/test_custodian_survey.py`

**Interfaces:**
- Consumes: `daemon.list_projects/list_runs/current_slot/vram_snapshot/system_resources`, `lease.gpu_lease_status`, `cluster.cluster_facts`, `config.KNIOX_HOME`.
- Produces: `survey() -> dict` (`{"operational": {...}, "repo": {...}}`); `material_fingerprint(survey: dict) -> str`; `collect_operational() -> dict`; `collect_repo(k: int = 10) -> dict`.

- [ ] **Step 1: Write the failing test**

```python
import custodian_survey as cs
import daemon as registry
import lease, cluster

def _patch_ops(monkeypatch):
    monkeypatch.setattr(registry, "list_projects", lambda: [{"name": "p", "status": "idle"}])
    monkeypatch.setattr(registry, "list_runs", lambda n=20: [{"state": "done", "task": "t"}])
    monkeypatch.setattr(registry, "current_slot", lambda: "nightly")
    monkeypatch.setattr(registry, "vram_snapshot", lambda: {"used_gb": 1.0})
    monkeypatch.setattr(registry, "system_resources", lambda: {"cpu_percent": 5})
    monkeypatch.setattr(lease, "gpu_lease_status", lambda: None)
    monkeypatch.setattr(cluster, "cluster_facts", lambda: {"present": True})

def test_collect_operational_uses_registry(monkeypatch):
    _patch_ops(monkeypatch)
    op = cs.collect_operational()
    assert op["projects"] == [{"name": "p", "status": "idle"}]
    assert op["slot"] == "nightly" and op["cluster"] == {"present": True}

def test_collector_failure_is_isolated(monkeypatch):
    _patch_ops(monkeypatch)
    def boom(): raise RuntimeError("db down")
    monkeypatch.setattr(registry, "list_projects", boom)
    op = cs.collect_operational()
    assert "error" in op["projects"]          # isolated, not a crash
    assert op["slot"] == "nightly"            # other sections still collected

def test_fingerprint_ignores_live_noise():
    s1 = {"operational": {"resources": {"cpu": 1}, "projects": ["a"], "vram": {"u": 1}},
          "repo": {"git_status": ["x"]}}
    s2 = {"operational": {"resources": {"cpu": 99}, "projects": ["a"], "vram": {"u": 9}},
          "repo": {"git_status": ["x"]}}
    assert cs.material_fingerprint(s1) == cs.material_fingerprint(s2)

def test_fingerprint_changes_on_material():
    s1 = {"operational": {"projects": ["a"]}, "repo": {"git_status": ["x"]}}
    s2 = {"operational": {"projects": ["a"]}, "repo": {"git_status": ["y"]}}
    assert cs.material_fingerprint(s1) != cs.material_fingerprint(s2)

def test_list_runs_reads_recent(tmp_path, monkeypatch):
    registry.init_db()
    registry.record_run("proj", "task", "done")
    runs = registry.list_runs(5)
    assert runs and runs[0]["project"] == "proj" and runs[0]["state"] == "done"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest daemon/tests/test_custodian_survey.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'custodian_survey'`

- [ ] **Step 3a: Add `list_runs` to `daemon/daemon.py`**

Add next to `record_run`:

```python
def list_runs(limit=20):
    with contextlib.closing(_conn()) as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,))]
```

- [ ] **Step 3b: Create `daemon/custodian_survey.py`**

```python
"""Snapshot the whole framework's operational + repo state for the custodian.

Every collector is failure-isolated: a section that errors becomes {"error": ...} rather
than crashing the survey. material_fingerprint() hashes only the fields whose change should
trigger a new report (excludes live noise like CPU%/VRAM usage)."""
from __future__ import annotations
import hashlib, json, subprocess
from config import KNIOX_HOME
import lease, cluster


def _safe(fn):
    try:
        return fn()
    except Exception as e:
        return {"error": str(e)}


def _run_git(args):
    return subprocess.run(["git", "-C", str(KNIOX_HOME), *args],
                          capture_output=True, text=True, timeout=15).stdout


def collect_operational() -> dict:
    import daemon as registry
    return {
        "projects": _safe(registry.list_projects),
        "runs": _safe(lambda: registry.list_runs(20)),
        "slot": _safe(registry.current_slot),
        "gpu_lease": _safe(lease.gpu_lease_status),
        "vram": _safe(registry.vram_snapshot),
        "resources": _safe(registry.system_resources),
        "cluster": _safe(cluster.cluster_facts),
    }


def collect_repo(k: int = 10) -> dict:
    repo = {"git_status": _safe(lambda: _run_git(["status", "--porcelain"]).splitlines())}

    def _by_mtime():
        files = _run_git(["ls-files"]).splitlines()
        stamped = []
        for f in files:
            try:
                stamped.append(((KNIOX_HOME / f).stat().st_mtime, f))
            except OSError:
                pass
        stamped.sort()
        return {"most_stale": [f for _, f in stamped[:k]],
                "recently_modified": [f for _, f in stamped[-k:]][::-1]}

    repo.update(_safe(_by_mtime))

    def _next_md():
        pdir = KNIOX_HOME / "projects"
        return {p.name: (p / "next.md").exists() for p in pdir.iterdir() if p.is_dir()}

    repo["projects_next_md"] = _safe(_next_md)
    return repo


def survey() -> dict:
    return {"operational": collect_operational(), "repo": collect_repo()}


def material_fingerprint(survey: dict) -> str:
    op = survey.get("operational", {})
    repo = survey.get("repo", {})
    material = {
        "projects": op.get("projects"),
        "runs": op.get("runs"),
        "slot": op.get("slot"),
        "git_status": repo.get("git_status"),
        "recently_modified": repo.get("recently_modified"),
        "projects_next_md": repo.get("projects_next_md"),
    }
    blob = json.dumps(material, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest daemon/tests/test_custodian_survey.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add daemon/daemon.py daemon/custodian_survey.py daemon/tests/test_custodian_survey.py
git commit -m "feat: custodian survey collectors + daemon list_runs"
```

---

### Task 2: Runtime model selection

**Files:**
- Create: `daemon/custodian_model.py`
- Test: `daemon/tests/test_custodian_model.py`

**Interfaces:**
- Consumes: `config.load_config`, `backends.get_backend` (`backend.name`, `backend.present()`, `backend.models()`), `daemon.can_load`.
- Produces: `select_model(config: dict | None = None) -> tuple[str | None, str]` — `(model_name, reason)` or `(None, reason)`.

- [ ] **Step 1: Write the failing test**

```python
import custodian_model as cm
import daemon as registry
import backends, config

class _FakeBackend:
    name = "ollama"
    def __init__(self, models): self._m = models
    def present(self): return True
    def models(self): return self._m

def _setup(monkeypatch, models, ok_by_name):
    monkeypatch.setattr(config, "load_config", lambda: {"backend": "ollama"})
    monkeypatch.setattr(backends, "get_backend", lambda cfg: _FakeBackend(models))
    monkeypatch.setattr(registry, "can_load", lambda name: {"ok": ok_by_name.get(name)})

def test_picks_largest_that_fits(monkeypatch):
    models = [{"name": "big", "size_gb": 19}, {"name": "mid", "size_gb": 9}, {"name": "sm", "size_gb": 2}]
    _setup(monkeypatch, models, {"big": False, "mid": True, "sm": True})
    name, reason = cm.select_model()
    assert name == "mid"            # big doesn't fit; mid is the largest that does

def test_none_fits_returns_none(monkeypatch):
    models = [{"name": "big", "size_gb": 19}]
    _setup(monkeypatch, models, {"big": False})
    name, reason = cm.select_model()
    assert name is None and "fit" in reason.lower()

def test_no_backend_returns_none(monkeypatch):
    monkeypatch.setattr(config, "load_config", lambda: {})
    class _None:
        name = "none"
        def present(self): return True
        def models(self): return []
    monkeypatch.setattr(backends, "get_backend", lambda cfg: _None())
    name, reason = cm.select_model()
    assert name is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest daemon/tests/test_custodian_model.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'custodian_model'`

- [ ] **Step 3: Create `daemon/custodian_model.py`**

```python
"""Pick the report model at runtime — the largest backend model that fits the VRAM budget.
No hardcoded model names (alignment rule). Honest: returns (None, reason) when nothing fits."""
from __future__ import annotations
from config import load_config
from backends import get_backend


def select_model(config: dict | None = None):
    import daemon as registry
    config = config if config is not None else load_config()
    backend = get_backend(config)
    if backend.name == "none" or not backend.present():
        return None, "no inference backend available"
    sized = [m for m in backend.models() if m.get("size_gb")]
    if not sized:
        return None, "backend reports no models with known sizes"
    unknown = []
    for m in sorted(sized, key=lambda x: x["size_gb"], reverse=True):
        ok = registry.can_load(m["name"]).get("ok")
        if ok is True:
            return m["name"], f"largest model fitting the VRAM budget ({m['size_gb']} GB)"
        if ok is None:
            unknown.append(m)
    if unknown:
        m = unknown[0]
        return m["name"], f"largest model; VRAM fit unverified ({m['size_gb']} GB)"
    return None, "no model fits the VRAM budget"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest daemon/tests/test_custodian_model.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add daemon/custodian_model.py daemon/tests/test_custodian_model.py
git commit -m "feat: custodian runtime model selection (largest fit, no hardcode)"
```

---

### Task 3: Report orchestration

**Files:**
- Create: `daemon/custodian_report.py`
- Test: `daemon/tests/test_custodian_report.py`

**Interfaces:**
- Consumes: `custodian_survey.survey/material_fingerprint`, `custodian_model.select_model`, `daemon.dispatch`, `config.KNIOX_HOME`.
- Produces: `build_prompt(survey: dict, alignment_text: str) -> str`; `run(force: bool = False) -> dict` (keys: `written|skipped`, `path?`, `reason?`, `model?`); path helpers `_custodian_dir()`, `_reports_dir()`, `_state_path()` (resolve `KNIOX_CUSTODIAN_DIR` per call, so tests just set the env — no reload).

- [ ] **Step 1: Write the failing test**

```python
import os, json
import custodian_report as cr
import custodian_survey, custodian_model
import daemon as registry

FAKE_SURVEY = {"operational": {"projects": ["p"]}, "repo": {"git_status": ["M x"]}}

def _patch(monkeypatch, tmp_path, dispatch_result, fp="fp1"):
    monkeypatch.setenv("KNIOX_CUSTODIAN_DIR", str(tmp_path / "custodian"))
    monkeypatch.setattr(cr.custodian_survey, "survey", lambda: FAKE_SURVEY)
    monkeypatch.setattr(cr.custodian_survey, "material_fingerprint", lambda s: fp)
    monkeypatch.setattr(cr.custodian_model, "select_model", lambda: ("m", "largest"))
    monkeypatch.setattr(cr.registry, "dispatch", lambda *a, **k: dispatch_result)

def test_build_prompt_has_instruction_and_alignment():
    p = cr.build_prompt(FAKE_SURVEY, "ALIGNMENT-CONTRACT-TEXT")
    assert "ALIGNMENT-CONTRACT-TEXT" in p
    assert "propose" in p.lower() and "do not apply" in p.lower()
    assert "git_status" in p   # survey digest present

def test_run_writes_report_and_latest_and_state(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path, {"response": "ALL GOOD"})
    out = cr.run(force=True)
    assert out["written"] is True
    assert os.path.exists(out["path"])
    assert (cr._reports_dir() / "latest.md").read_text() == "ALL GOOD"
    assert json.loads(cr._state_path().read_text())["fingerprint"] == "fp1"

def test_run_skips_when_fingerprint_unchanged(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path, {"response": "X"})
    cr._state_path().parent.mkdir(parents=True, exist_ok=True)
    cr._state_path().write_text(json.dumps({"fingerprint": "fp1"}))
    def _boom(*a, **k): raise AssertionError("dispatch must not be called")
    monkeypatch.setattr(cr.registry, "dispatch", _boom)
    out = cr.run(force=False)
    assert out["skipped"] is True and "change" in out["reason"].lower()

def test_run_skips_on_gpu_busy(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path, {"error": "GPU busy: another job holds the lease"})
    out = cr.run(force=True)
    assert out["skipped"] is True and "busy" in out["reason"].lower()

def test_run_writes_only_under_custodian_dir(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path, {"response": "R"})
    out = cr.run(force=True)
    assert str(cr._custodian_dir()) in out["path"]   # report lives under the custodian dir
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest daemon/tests/test_custodian_report.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'custodian_report'`

- [ ] **Step 3: Create `daemon/custodian_report.py`**

```python
"""Orchestrate one custodian run: survey -> fingerprint skip -> pick model -> brokered
dispatch -> write a markdown report. Read-only: writes only under CUSTODIAN_DIR."""
from __future__ import annotations
import datetime, json, os
from pathlib import Path
from config import KNIOX_HOME
import custodian_survey, custodian_model
import daemon as registry

_ALIGNMENT = KNIOX_HOME / "alignment" / "PROJECT-ALIGNMENT-REQUIREMENT.md"

_INSTRUCTION = ("You are the kniox custodian. Review the framework state below against the "
                "alignment contract. Report ONLY: misalignments, easy wins, bugs, and "
                "optimizations. Propose changes; do NOT apply them. Be concise and specific.")


def _custodian_dir() -> Path:
    return Path(os.environ.get("KNIOX_CUSTODIAN_DIR", KNIOX_HOME / "custodian"))


def _reports_dir() -> Path:
    return _custodian_dir() / "reports"


def _state_path() -> Path:
    return _custodian_dir() / "state.json"


def _alignment_text():
    try:
        return _ALIGNMENT.read_text()
    except OSError:
        return "(alignment contract unavailable)"


def build_prompt(survey: dict, alignment_text: str) -> str:
    digest = json.dumps(survey, indent=2, default=str)
    return (f"{_INSTRUCTION}\n\n## Alignment contract\n{alignment_text}\n\n"
            f"## Framework state (survey)\n{digest}\n")


def _load_state() -> dict:
    try:
        return json.loads(_state_path().read_text())
    except (OSError, ValueError):
        return {}


def _save_state(state: dict):
    _custodian_dir().mkdir(parents=True, exist_ok=True)
    _state_path().write_text(json.dumps(state, indent=2))


def _write_report(text: str) -> Path:
    reports = _reports_dir()
    reports.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%d%m%y")
    path = reports / f"custodian_{stamp}.md"
    path.write_text(text)
    (reports / "latest.md").write_text(text)
    return path


def run(force: bool = False) -> dict:
    survey = custodian_survey.survey()
    fp = custodian_survey.material_fingerprint(survey)
    if not force and _load_state().get("fingerprint") == fp:
        return {"skipped": True, "reason": "no change since last report"}
    model, reason = custodian_model.select_model()
    if not model:
        return {"skipped": True, "reason": reason}
    out = registry.dispatch("custodian", build_prompt(survey, _alignment_text()), model)
    if out.get("error"):
        return {"skipped": True, "reason": out["error"], "model": model}
    path = _write_report(out.get("response", ""))
    _save_state({"fingerprint": fp})
    return {"written": True, "path": str(path), "model": model}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest daemon/tests/test_custodian_report.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add daemon/custodian_report.py daemon/tests/test_custodian_report.py
git commit -m "feat: custodian report orchestration (survey->model->brokered dispatch->report)"
```

---

### Task 4: CLI + MCP surface

**Files:**
- Modify: `daemon/daemon.py` (add `custodian` CLI subcommand)
- Modify: `daemon/mcp_server.py` (add `custodian_run` + `custodian_report` tools)
- Test: `daemon/tests/test_custodian_cli.py`

**Interfaces:**
- Consumes: `custodian_report.run`, `custodian_report._reports_dir`.
- Produces: CLI `python daemon/daemon.py custodian run [--force]`; MCP tools `custodian_run(force=False)`, `custodian_report()`.

- [ ] **Step 1: Write the failing test**

```python
import daemon as registry

def test_cli_custodian_run_dispatches(monkeypatch, capsys):
    import custodian_report
    monkeypatch.setattr(custodian_report, "run", lambda force=False: {"skipped": True, "reason": "no model"})
    rc = registry.cli_custodian(force=True)   # thin helper the CLI handler calls
    assert rc["skipped"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest daemon/tests/test_custodian_cli.py -v`
Expected: FAIL — `AttributeError: module 'daemon' has no attribute 'cli_custodian'`

- [ ] **Step 3a: Add the CLI to `daemon/daemon.py`**

Add a helper near `submit_job`:

```python
def cli_custodian(force=False):
    import custodian_report
    return custodian_report.run(force=force)
```

In `_cli()`, add the subparser (next to the others):

```python
    cu = s.add_parser("custodian"); cu.add_argument("action", choices=["run"])
    cu.add_argument("--force", action="store_true")
```

and the handler (next to the other `elif a.cmd ==` branches):

```python
    elif a.cmd == "custodian":
        print(json.dumps(cli_custodian(force=a.force), indent=2))
```

- [ ] **Step 3b: Add MCP tools to `daemon/mcp_server.py`** (before `if __name__`)

```python
@mcp.tool()
def custodian_run(force: bool = False) -> dict:
    """Run the custodian: survey the framework, have a local model report on it (brokered).
    Returns whether a report was written or why it was skipped (no model / GPU busy / no change)."""
    return registry.cli_custodian(force=force)


@mcp.tool()
def custodian_report() -> dict:
    """Return the latest custodian report text (or a note if none exists yet)."""
    import custodian_report as cr
    latest = cr._reports_dir() / "latest.md"
    try:
        return {"report": latest.read_text(), "path": str(latest)}
    except OSError:
        return {"report": None, "path": str(latest), "note": "no report yet; run the custodian"}
```

- [ ] **Step 4: Run tests + import check**

Run: `uv run pytest daemon/tests/test_custodian_cli.py -v`
Expected: PASS (1 passed)
Run: `uv run python -c "import sys; sys.path.insert(0,'daemon'); import mcp_server; print('ok')"`
Expected: `ok`

- [ ] **Step 4b: Gitignore generated custodian artifacts (before the smoke run writes any)**

Append to `.gitignore`:
```
# custodian generated reports + state (artifacts, like daemon/state)
custodian/
```
Then: `git add .gitignore && git commit -m "chore: gitignore custodian generated artifacts"`

- [ ] **Step 5: Smoke test (real run, idle slot)**

Run: `uv run python daemon/daemon.py custodian run --force`
Expected: JSON — either `{"written": true, "path": "...custodian_*.md", "model": "..."}` (a model fit and the GPU was free) OR an honest `{"skipped": true, "reason": "..."}` (no model fits / GPU busy). Either is a PASS; capture the output. If `written`, confirm the file exists: `ls custodian/reports/`.

- [ ] **Step 6: Commit**

```bash
git add daemon/daemon.py daemon/mcp_server.py daemon/tests/test_custodian_cli.py
git commit -m "feat: custodian CLI + MCP tools"
```

---

### Task 5: Cron + alignment doc

**Files:**
- Create: `corn/custodian.sh`
- Delete: `corn/audit.sh` (superseded by the unified overseer)
- Modify: `alignment/PROJECT-ALIGNMENT-REQUIREMENT.md` (note the custodian)

**Interfaces:** none (ops + docs).

- [ ] **Step 1: Create `corn/custodian.sh`**

```bash
#!/usr/bin/env bash
# Nightly custodian run (unified overseer; supersedes audit.sh).
# crontab:  0 9 * * * ~/kniox/corn/custodian.sh >> ~/kniox/corn/custodian.log 2>&1
set -euo pipefail
KNIOX="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$KNIOX"
exec uv run python "$KNIOX/daemon/daemon.py" custodian run
```

- [ ] **Step 2: Make it executable + remove the old audit cron**

```bash
chmod +x corn/custodian.sh
git rm corn/audit.sh
```

- [ ] **Step 3: Note the custodian in the alignment doc**

Add to `alignment/PROJECT-ALIGNMENT-REQUIREMENT.md` after the "Offload-first routing" section (this file is a guarded rail — if the Edit tool is blocked, write it via `KNIOX_BYPASS_HOOKS=1`, the documented escape hatch for intentional rail edits):

```markdown
## Custodian (overseer)
A locally-run LLM **custodian** periodically surveys the whole framework (operational health
+ alignment) and writes a read-only "state of the framework" report to `custodian/reports/`.
It selects its model at runtime (largest that fits the budget), runs **brokered** through the
daemon (GPU-leased), proposes but never applies changes, and yields to real jobs. It is the
unified overseer; the nightly cron is `corn/custodian.sh`.
```

- [ ] **Step 4: Verify + commit**

Run: `ls corn/ && test ! -f corn/audit.sh && echo "audit.sh removed"`
Expected: lists `custodian.sh`, prints `audit.sh removed`

```bash
git add corn/custodian.sh alignment/PROJECT-ALIGNMENT-REQUIREMENT.md
git commit -m "ops: custodian nightly cron (replaces audit.sh) + alignment note"
```

---

## Self-Review

**Spec coverage:** survey collectors + fingerprint (T1) ✓ · runtime model select, no hardcode (T2) ✓ · report orchestration, brokered dispatch, fingerprint/GPU-busy/no-model skips, read-only writes (T3) ✓ · CLI + MCP (T4) ✓ · cron replacing audit.sh + alignment note (T5) ✓ · honest degradation throughout (T2/T3) ✓ · Phase-2 items (systemd service, preemptible lease v2) intentionally out of scope.

**Placeholder scan:** none — every code step has full code; every run step has an exact command + expected result.

**Type consistency:** `survey()` dict shape (`operational`/`repo`) consumed by `material_fingerprint` (T1) and `build_prompt` (T3); `select_model()` returns `(name|None, reason)` consumed by `run` (T3); `run()` returns `{written|skipped,...}` surfaced by the CLI/MCP (T4) and asserted in T3 tests; the path helpers `_reports_dir()`/`_custodian_dir()`/`_state_path()` defined in T3 and read in T4's MCP tool + T3 tests. `cli_custodian(force)` defined in T4 and called by the CLI handler + MCP tools.
