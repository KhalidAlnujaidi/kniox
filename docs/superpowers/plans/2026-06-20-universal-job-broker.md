# Universal Job Broker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the kniox daemon the single broker that routes every job by resource profile — GPU work serialized on enigma behind a lease, CPU-eligible/self-contained work offloaded to idle k3s workers.

**Architecture:** Small, pure, independently-testable modules in the existing flat `daemon/` layout — a placement-header parser, a Job descriptor, a pure classifier, a SQLite-backed GPU lease, and a k3s cluster adapter — composed by one `run_job()` router. Honest degradation: if k3s is unreachable, `cluster` jobs fall back to local execution with a surfaced note.

**Tech Stack:** Python 3.11+ stdlib only (urllib, sqlite3, subprocess, json, dataclasses), `kubectl` against `/etc/rancher/k3s/k3s.yaml`, Ollama backend (existing), pytest via uv.

## Global Constraints

- **uv only** — all env/package/run ops via uv; tests run with `uv run pytest`. (verbatim from CLAUDE.md)
- **No new heavy deps** — stdlib + existing `mcp`/`psutil` only; no kubernetes client lib (shell out to `kubectl`).
- **Detect, never assume** — no hardcoded GPU sizes/model names; read facts at runtime. Unmeasurable = `None`, never `0`.
- **Honest degradation** — never fake success; missing backend/cluster returns an actionable error or a surfaced fallback note (match `daemon.py` style).
- **Flat import style** — new modules live in `daemon/` and import siblings bare (`from lease import ...`), matching `daemon.py`'s `from config import ...`.
- **KUBECONFIG default** — `/etc/rancher/k3s/k3s.yaml`; overridable via `KNIOX_KUBECONFIG` env.
- **Branch/PR rule** — this work lives on `feat/universal-job-broker`; commit per task; never push/merge without explicit OK.

---

### Task 1: Test scaffolding (uv + pytest)

**Files:**
- Create: `pyproject.toml`
- Create: `daemon/tests/__init__.py` (empty)
- Create: `daemon/tests/conftest.py`

**Interfaces:**
- Produces: a working `uv run pytest` that can import `daemon/` modules bare (`import placement`).

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "kniox"
version = "0.1.0"
description = "kniox alignment framework + job broker"
requires-python = ">=3.11"
dependencies = ["mcp", "psutil"]

[dependency-groups]
dev = ["pytest>=8"]

[tool.pytest.ini_options]
pythonpath = ["daemon"]
testpaths = ["daemon/tests"]
```

- [ ] **Step 2: Create `daemon/tests/conftest.py`**

```python
# Ensures sqlite-backed modules use a throwaway DB per test session.
import os, tempfile, pathlib
os.environ.setdefault("KNIOX_STATE_DIR", tempfile.mkdtemp(prefix="kniox-test-"))
pathlib.Path(os.environ["KNIOX_STATE_DIR"]).mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 3: Create empty `daemon/tests/__init__.py`**

- [ ] **Step 4: Verify the harness runs**

Run: `uv run pytest -q`
Expected: `no tests ran` (exit 5) or `collected 0 items` — confirms collection works with no errors.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml daemon/tests/
git commit -m "test: add uv+pytest scaffolding for daemon modules"
```

---

### Task 2: Placement-header parser (`placement.py`)

**Files:**
- Create: `daemon/placement.py`
- Test: `daemon/tests/test_placement.py`

**Interfaces:**
- Produces: `parse_placement(text: str) -> dict | None` returning `{"placement": str, "hints": dict}` or `None` when no header. `VALID_PLACEMENTS: set[str]`.

- [ ] **Step 1: Write the failing test**

```python
import placement

def test_parses_simple_header():
    assert placement.parse_placement("# kniox: placement=cluster\nimport os\n") == {
        "placement": "cluster", "hints": {}}

def test_parses_hints():
    out = placement.parse_placement("#!/usr/bin/env python\n# kniox: placement=cluster mem=2G task=scrape\n")
    assert out == {"placement": "cluster", "hints": {"mem": "2G", "task": "scrape"}}

def test_missing_header_returns_none():
    assert placement.parse_placement("import os\nprint(1)\n") is None

def test_invalid_placement_returns_none():
    assert placement.parse_placement("# kniox: placement=mars\n") is None

def test_only_scans_first_20_lines():
    body = "\n" * 25 + "# kniox: placement=cluster\n"
    assert placement.parse_placement(body) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest daemon/tests/test_placement.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'placement'`

- [ ] **Step 3: Write minimal implementation**

```python
"""Parse the kniox placement pragma from a script header.

Convention: before the imports, a single comment declares where a job runs:
    # kniox: placement=<enigma-gpu|enigma-local|cluster|auto> [key=value ...]
This is the scheduler's fast path — one cheap read instead of inference.
"""
from __future__ import annotations
import re

VALID_PLACEMENTS = {"enigma-gpu", "enigma-local", "cluster", "auto"}
_HEADER = re.compile(r"#\s*kniox:\s*placement=(?P<p>[\w-]+)(?P<rest>.*)$")


def parse_placement(text: str) -> dict | None:
    for line in text.splitlines()[:20]:
        m = _HEADER.match(line.strip())
        if not m:
            continue
        p = m.group("p")
        if p not in VALID_PLACEMENTS:
            return None
        hints = dict(kv.split("=", 1) for kv in m.group("rest").split() if "=" in kv)
        return {"placement": p, "hints": hints}
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest daemon/tests/test_placement.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add daemon/placement.py daemon/tests/test_placement.py
git commit -m "feat: placement-header parser"
```

---

### Task 3: Job descriptor (`jobspec.py`)

**Files:**
- Create: `daemon/jobspec.py`
- Test: `daemon/tests/test_jobspec.py`

**Interfaces:**
- Consumes: `placement.parse_placement` (Task 2).
- Produces: `Job` dataclass with fields `task, command, env, needs_gpu, est_mem_gb, est_vram_gb, local_paths, interactive, schedule, placement, prompt`; classmethod `Job.from_script(path: str, task: str | None = None) -> Job`.

- [ ] **Step 1: Write the failing test**

```python
import jobspec

def test_defaults_are_safe():
    j = jobspec.Job(task="x")
    assert j.needs_gpu is False and j.local_paths == [] and j.placement is None

def test_from_script_reads_header(tmp_path):
    f = tmp_path / "job.py"
    f.write_text("# kniox: placement=cluster mem=2G\nimport os\n")
    j = jobspec.Job.from_script(str(f), task="scrape")
    assert j.placement == "cluster" and j.command == ["uv", "run", str(f)]
    assert j.est_mem_gb == 2.0
    assert "import os" in j.source

def test_from_script_no_header_leaves_placement_none(tmp_path):
    f = tmp_path / "job.py"
    f.write_text("import os\n")
    j = jobspec.Job.from_script(str(f))
    assert j.placement is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest daemon/tests/test_jobspec.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'jobspec'`

- [ ] **Step 3: Write minimal implementation**

```python
"""The single Job descriptor every caller hands the broker."""
from __future__ import annotations
from dataclasses import dataclass, field
import placement as _placement


def _mem_to_gb(v: str | None) -> float | None:
    if not v:
        return None
    v = v.strip().upper().rstrip("B")
    try:
        if v.endswith("G"):
            return float(v[:-1])
        if v.endswith("M"):
            return round(float(v[:-1]) / 1024, 3)
        return float(v)
    except ValueError:
        return None


@dataclass
class Job:
    task: str
    command: list[str] | None = None
    env: dict = field(default_factory=dict)
    needs_gpu: bool = False
    est_mem_gb: float | None = None
    est_vram_gb: float | None = None
    local_paths: list = field(default_factory=list)
    interactive: bool = False
    schedule: str | None = None
    placement: str | None = None   # explicit override or parsed header (non-auto)
    prompt: str | None = None      # for backend/LLM tasks
    source: str | None = None      # script text, embedded for self-contained cluster runs

    @classmethod
    def from_script(cls, path: str, task: str | None = None) -> "Job":
        with open(path) as f:
            text = f.read()
        parsed = _placement.parse_placement(text)
        placement_val = None
        mem = None
        if parsed and parsed["placement"] != "auto":
            placement_val = parsed["placement"]
        if parsed:
            mem = _mem_to_gb(parsed["hints"].get("mem"))
            task = task or parsed["hints"].get("task")
        return cls(task=task or "script", command=["uv", "run", path],
                   source=text, placement=placement_val, est_mem_gb=mem)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest daemon/tests/test_jobspec.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add daemon/jobspec.py daemon/tests/test_jobspec.py
git commit -m "feat: Job descriptor with header-driven from_script"
```

---

### Task 4: Classifier (`classifier.py`)

**Files:**
- Create: `daemon/classifier.py`
- Test: `daemon/tests/test_classifier.py`

**Interfaces:**
- Consumes: `Job` (Task 3).
- Produces: `classify(job: Job, facts: dict) -> dict` returning `{"placement": "enigma-gpu"|"enigma-local"|"cluster", "reason": str}`. `facts` shape: `{"worker_free_mem_gb": float | None}`.

- [ ] **Step 1: Write the failing test**

```python
import classifier
from jobspec import Job

FACTS = {"worker_free_mem_gb": 7.0}

def test_gpu_job_pinned_to_enigma():
    assert classifier.classify(Job(task="t", needs_gpu=True), FACTS)["placement"] == "enigma-gpu"

def test_local_paths_force_enigma_local():
    r = classifier.classify(Job(task="t", local_paths=["/home/x"]), FACTS)
    assert r["placement"] == "enigma-local"

def test_interactive_forces_enigma_local():
    assert classifier.classify(Job(task="t", interactive=True), FACTS)["placement"] == "enigma-local"

def test_big_mem_forces_enigma_local():
    assert classifier.classify(Job(task="t", est_mem_gb=16), FACTS)["placement"] == "enigma-local"

def test_plain_cpu_job_goes_to_cluster():
    assert classifier.classify(Job(task="t"), FACTS)["placement"] == "cluster"

def test_header_cluster_honored():
    assert classifier.classify(Job(task="t", placement="cluster"), FACTS)["placement"] == "cluster"

def test_safety_rule_header_cluster_but_local_paths_downgrades():
    r = classifier.classify(Job(task="t", placement="cluster", local_paths=["/x"]), FACTS)
    assert r["placement"] == "enigma-local"
    assert "local_paths" in r["reason"]

def test_unknown_worker_mem_does_not_block_small_job():
    assert classifier.classify(Job(task="t"), {"worker_free_mem_gb": None})["placement"] == "cluster"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest daemon/tests/test_classifier.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'classifier'`

- [ ] **Step 3: Write minimal implementation**

```python
"""Pure placement decision. No I/O — facts are passed in, so this is fully testable.

Precedence:
  1. explicit/header placement (non-auto), subject to the safety rule
  2. needs_gpu               -> enigma-gpu
  3. local_paths / interactive / mem over worker headroom -> enigma-local
  4. otherwise               -> cluster
The safety rule: a job tagged 'cluster' that actually declares local_paths cannot run on
a worker (no shared storage) — downgrade to enigma-local and say why.
"""
from __future__ import annotations


def _enigma_local_reason(job) -> str | None:
    if job.local_paths:
        return "declares local_paths (no shared storage on workers)"
    if job.interactive:
        return "interactive job"
    return None


def classify(job, facts: dict) -> dict:
    worker_mem = facts.get("worker_free_mem_gb")

    if job.placement and job.placement != "auto":
        if job.placement == "cluster":
            reason = _enigma_local_reason(job)
            if reason:
                return {"placement": "enigma-local", "reason": f"header=cluster but {reason}"}
        return {"placement": job.placement, "reason": "explicit header/override"}

    if job.needs_gpu:
        return {"placement": "enigma-gpu", "reason": "needs GPU"}

    reason = _enigma_local_reason(job)
    if reason:
        return {"placement": "enigma-local", "reason": reason}
    if job.est_mem_gb is not None and worker_mem is not None and job.est_mem_gb > worker_mem:
        return {"placement": "enigma-local",
                "reason": f"est_mem_gb {job.est_mem_gb} > worker headroom {worker_mem}"}

    return {"placement": "cluster", "reason": "CPU-eligible, self-contained"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest daemon/tests/test_classifier.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
git add daemon/classifier.py daemon/tests/test_classifier.py
git commit -m "feat: pure placement classifier with safety rule"
```

---

### Task 5: GPU lease (`lease.py`)

**Files:**
- Create: `daemon/lease.py`
- Test: `daemon/tests/test_lease.py`

**Interfaces:**
- Consumes: `config.DB_PATH` (existing).
- Produces: `acquire_gpu(holder: str, task: str, ttl: int = 1800, wait: bool = True, poll: float = 0.05, timeout: float | None = None) -> bool`; `release_gpu(holder: str) -> None`; `gpu_lease_status() -> dict | None`.

- [ ] **Step 1: Write the failing test**

```python
import time
import lease

def test_acquire_and_release(monkeypatch):
    assert lease.acquire_gpu("a", "text") is True
    assert lease.gpu_lease_status()["holder"] == "a"
    lease.release_gpu("a")
    assert lease.gpu_lease_status() is None

def test_second_holder_blocked_until_timeout():
    assert lease.acquire_gpu("a", "text") is True
    assert lease.acquire_gpu("b", "img", wait=True, timeout=0.2) is False
    lease.release_gpu("a")

def test_expired_lease_is_reclaimed():
    assert lease.acquire_gpu("a", "text", ttl=0) is True
    time.sleep(0.01)
    assert lease.acquire_gpu("b", "img", wait=False) is True   # a's lease expired
    lease.release_gpu("b")
```

(Note: tests share the temp DB from conftest; `release_gpu` at the end of each keeps them independent. Run with `-p no:randomly`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest daemon/tests/test_lease.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lease'`

- [ ] **Step 3: Write minimal implementation**

```python
"""Single-GPU lease (enigma has exactly one A4500). Converts 'one heavy model at a time'
from discipline into enforcement across concurrent kx sessions. SQLite-backed with a TTL
so a dead holder can't deadlock the GPU."""
from __future__ import annotations
import contextlib, sqlite3, time
from config import DB_PATH

_SCHEMA = """CREATE TABLE IF NOT EXISTS gpu_lease(
  id INTEGER PRIMARY KEY CHECK (id=1), holder TEXT, task TEXT,
  acquired_at REAL, expires_at REAL);"""


def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute(_SCHEMA)
    return c


def _try_once(holder, task, ttl) -> bool:
    now = time.time()
    with contextlib.closing(_conn()) as c:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute("SELECT holder, expires_at FROM gpu_lease WHERE id=1").fetchone()
        active = row and row["expires_at"] > now and row["holder"] != holder
        if active:
            c.execute("ROLLBACK")
            return False
        c.execute("INSERT INTO gpu_lease(id,holder,task,acquired_at,expires_at) VALUES(1,?,?,?,?) "
                  "ON CONFLICT(id) DO UPDATE SET holder=excluded.holder, task=excluded.task, "
                  "acquired_at=excluded.acquired_at, expires_at=excluded.expires_at",
                  (holder, task, now, now + ttl))
        c.execute("COMMIT")
        return True


def acquire_gpu(holder, task, ttl=1800, wait=True, poll=0.05, timeout=None) -> bool:
    deadline = None if timeout is None else time.time() + timeout
    while True:
        if _try_once(holder, task, ttl):
            return True
        if not wait or (deadline is not None and time.time() >= deadline):
            return False
        time.sleep(poll)


def release_gpu(holder) -> None:
    with contextlib.closing(_conn()) as c, c:
        c.execute("DELETE FROM gpu_lease WHERE id=1 AND holder=?", (holder,))


def gpu_lease_status() -> dict | None:
    now = time.time()
    with contextlib.closing(_conn()) as c:
        row = c.execute("SELECT holder, task, acquired_at, expires_at FROM gpu_lease WHERE id=1").fetchone()
    if not row or row["expires_at"] <= now:
        return None
    return dict(row)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest daemon/tests/test_lease.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add daemon/lease.py daemon/tests/test_lease.py
git commit -m "feat: SQLite GPU lease with TTL"
```

---

### Task 6: k3s cluster adapter (`cluster.py`)

**Files:**
- Create: `daemon/cluster.py`
- Test: `daemon/tests/test_cluster.py`

**Interfaces:**
- Produces: `kubectl_available() -> bool`; `cluster_facts() -> dict` (`{"present": bool, "nodes": [...], "worker_free_mem_gb": float | None}`); `parse_nodes(kubectl_json: dict) -> list[dict]` (pure, testable); `submit_cluster_job(name, image, command, env=None, cpu="500m", mem="512Mi", timeout=600) -> dict` (`{"exit_code": int, "stdout": str, "node": str|None, "error": str|None}`).

- [ ] **Step 1: Write the failing test (pure node parsing)**

```python
import cluster

SAMPLE = {"items": [
  {"metadata": {"name": "enigma", "labels": {"node-role.kubernetes.io/control-plane": "true"}},
   "status": {"capacity": {"cpu": "16", "memory": "63375384Ki"},
              "allocatable": {"memory": "60000000Ki"},
              "conditions": [{"type": "Ready", "status": "True"}]}},
  {"metadata": {"name": "node1", "labels": {}},
   "status": {"capacity": {"cpu": "12", "memory": "7795408Ki"},
              "allocatable": {"memory": "7000000Ki"},
              "conditions": [{"type": "Ready", "status": "True"}]}},
]}

def test_parse_nodes_marks_roles_and_workers():
    nodes = cluster.parse_nodes(SAMPLE)
    by = {n["name"]: n for n in nodes}
    assert by["enigma"]["control_plane"] is True
    assert by["node1"]["control_plane"] is False
    assert by["node1"]["ready"] is True
    assert round(by["node1"]["alloc_mem_gb"], 1) == 6.7  # 7000000Ki -> GiB
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest daemon/tests/test_cluster.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cluster'`

- [ ] **Step 3: Write minimal implementation**

```python
"""k3s adapter — shells out to kubectl (no python kube client dependency).

Worker = any Ready node WITHOUT the control-plane role label (enigma is control-plane).
Cluster jobs get anti-affinity to the control-plane so they land on node1/2/3.
"""
from __future__ import annotations
import json, os, shutil, subprocess

KUBECONFIG = os.environ.get("KNIOX_KUBECONFIG", "/etc/rancher/k3s/k3s.yaml")
_CP_LABEL = "node-role.kubernetes.io/control-plane"


def _ki_to_gb(s: str | None) -> float | None:
    # KiB -> GiB (matches the existing manifest convention, e.g. 63375384Ki -> 60.4)
    if not s or not s.endswith("Ki"):
        return None
    return round(int(s[:-2]) / 1048576, 3)


def _kubectl(*args, timeout=20):
    return subprocess.run(["kubectl", "--kubeconfig", KUBECONFIG, *args],
                          capture_output=True, text=True, timeout=timeout)


def kubectl_available() -> bool:
    if not shutil.which("kubectl") or not os.path.exists(KUBECONFIG):
        return False
    try:
        return _kubectl("get", "nodes", "-o", "name", timeout=8).returncode == 0
    except Exception:
        return False


def parse_nodes(kubectl_json: dict) -> list[dict]:
    out = []
    for item in kubectl_json.get("items", []):
        meta, status = item.get("metadata", {}), item.get("status", {})
        labels = meta.get("labels", {})
        ready = any(c.get("type") == "Ready" and c.get("status") == "True"
                    for c in status.get("conditions", []))
        out.append({
            "name": meta.get("name"),
            "control_plane": _CP_LABEL in labels,
            "ready": ready,
            "cpu": status.get("capacity", {}).get("cpu"),
            "alloc_mem_gb": _ki_to_gb(status.get("allocatable", {}).get("memory")),
        })
    return out


def cluster_facts() -> dict:
    if not kubectl_available():
        return {"present": False, "nodes": [], "worker_free_mem_gb": None}
    try:
        res = _kubectl("get", "nodes", "-o", "json", timeout=15)
        nodes = parse_nodes(json.loads(res.stdout))
    except Exception:
        return {"present": False, "nodes": [], "worker_free_mem_gb": None}
    workers = [n for n in nodes if n["ready"] and not n["control_plane"]]
    mems = [n["alloc_mem_gb"] for n in workers if n["alloc_mem_gb"]]
    return {"present": True, "nodes": nodes,
            "worker_free_mem_gb": max(mems) if mems else None}


def submit_cluster_job(name, image, command, env=None, cpu="500m", mem="512Mi", timeout=600) -> dict:
    """Create a one-shot k8s Job anti-affined to the control-plane, wait, capture logs, delete."""
    manifest = {
        "apiVersion": "batch/v1", "kind": "Job",
        "metadata": {"name": name, "namespace": "default", "labels": {"app": "kniox-job"}},
        "spec": {"backoffLimit": 0, "ttlSecondsAfterFinished": 120,
                 "template": {"spec": {
                     "restartPolicy": "Never",
                     "affinity": {"nodeAffinity": {"requiredDuringSchedulingIgnoredDuringExecution": {
                         "nodeSelectorTerms": [{"matchExpressions": [
                             {"key": _CP_LABEL, "operator": "DoesNotExist"}]}]}}},
                     "containers": [{
                         "name": "job", "image": image, "command": command,
                         "env": [{"name": k, "value": str(v)} for k, v in (env or {}).items()],
                         "resources": {"requests": {"cpu": cpu, "memory": mem},
                                       "limits": {"memory": mem}}}]}}}}
    try:
        create = subprocess.run(
            ["kubectl", "--kubeconfig", KUBECONFIG, "apply", "-f", "-"],
            input=json.dumps(manifest), text=True, capture_output=True, timeout=20)
        if create.returncode != 0:
            return {"exit_code": 1, "stdout": "", "node": None, "error": create.stderr.strip()}
        _kubectl("wait", f"job/{name}", "--for=condition=complete",
                 f"--timeout={timeout}s", timeout=timeout + 10)
        logs = _kubectl("logs", f"job/{name}", timeout=20)
        pod = _kubectl("get", "pods", "-l", f"job-name={name}",
                       "-o", "jsonpath={.items[0].spec.nodeName}", timeout=10)
        return {"exit_code": 0, "stdout": logs.stdout, "node": pod.stdout.strip() or None, "error": None}
    except subprocess.TimeoutExpired:
        return {"exit_code": 124, "stdout": "", "node": None, "error": "job timed out"}
    finally:
        _kubectl("delete", "job", name, "--ignore-not-found", timeout=20)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest daemon/tests/test_cluster.py -v`
Expected: PASS (1 passed) — pure `parse_nodes` covered; live `submit_cluster_job` is exercised in Task 7's integration test.

- [ ] **Step 5: Commit**

```bash
git add daemon/cluster.py daemon/tests/test_cluster.py
git commit -m "feat: k3s cluster adapter (facts + worker-affined job submit)"
```

---

### Task 7: Router + executors (`executors.py`)

**Files:**
- Create: `daemon/executors.py`
- Test: `daemon/tests/test_executors.py`

**Interfaces:**
- Consumes: `classifier.classify`, `cluster.cluster_facts`, `cluster.submit_cluster_job`, `cluster.kubectl_available`, `Job`. (The GPU lease lives only in `daemon.dispatch` — Task 8 — which the GPU path delegates to; `run_job` must NOT acquire the lease itself, or it self-deadlocks.)
- Produces: `run_job(job: Job, facts: dict | None = None) -> dict` returning `{"placement", "reason", "node", "exit_code", "stdout", "error", "fallback"?}`.

- [ ] **Step 1: Write the failing test (routing + fallback, all mocked)**

```python
import executors
from jobspec import Job

def test_cluster_job_runs_on_worker(monkeypatch):
    monkeypatch.setattr(executors.cluster, "cluster_facts",
                        lambda: {"present": True, "worker_free_mem_gb": 7.0})
    monkeypatch.setattr(executors.cluster, "submit_cluster_job",
                        lambda **k: {"exit_code": 0, "stdout": "hi", "node": "node2", "error": None})
    r = executors.run_job(Job(task="t", command=["echo", "hi"]))
    assert r["placement"] == "cluster" and r["node"] == "node2" and r["stdout"] == "hi"

def test_cluster_falls_back_to_local_when_k3s_down(monkeypatch):
    monkeypatch.setattr(executors.cluster, "cluster_facts",
                        lambda: {"present": False, "worker_free_mem_gb": None})
    monkeypatch.setattr(executors, "_run_local",
                        lambda job: {"exit_code": 0, "stdout": "local", "node": "enigma", "error": None})
    r = executors.run_job(Job(task="t", command=["echo", "hi"]))
    assert r["placement"] == "enigma-local" and r["fallback"] is True

def test_gpu_job_delegates_to_backend(monkeypatch):
    # The GPU lease lives in daemon.dispatch (which _run_gpu_backend calls), NOT here.
    monkeypatch.setattr(executors, "_run_gpu_backend",
                        lambda job: {"exit_code": 0, "stdout": "gen", "node": "enigma", "error": None})
    r = executors.run_job(Job(task="text", needs_gpu=True, prompt="hi"))
    assert r["placement"] == "enigma-gpu" and r["stdout"] == "gen"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest daemon/tests/test_executors.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'executors'`

- [ ] **Step 3: Write minimal implementation**

```python
"""Route a Job to the right executor; degrade honestly when the cluster is unavailable.

The GPU lease is NOT held here — the enigma-gpu path delegates to daemon.dispatch (Task 8),
which owns the lease. Holding it here too would self-deadlock (run_job -> dispatch, both
waiting on the same single lease).
"""
from __future__ import annotations
import os, re, subprocess
import cluster, classifier


def _safe_name(task: str) -> str:
    base = re.sub(r"[^a-z0-9-]", "-", (task or "job").lower()).strip("-")[:40] or "job"
    return f"kniox-{base}"


def _run_local(job) -> dict:
    try:
        p = subprocess.run(job.command, capture_output=True, text=True, timeout=3600,
                           env={**os.environ, **job.env})
        return {"exit_code": p.returncode, "stdout": p.stdout, "node": "enigma",
                "error": p.stderr.strip() or None}
    except Exception as e:
        return {"exit_code": 1, "stdout": "", "node": "enigma", "error": str(e)}


def _run_cluster(job) -> dict:
    # Self-contained code delivery without shared storage: embed the script source as
    # `python -c <source>` in a stock python image. (A custom runner image is Phase 2.)
    if job.source is not None:
        command, image = ["python", "-c", job.source], "python:3.12-slim"
    else:
        command, image = job.command, "python:3.12-slim"
    return cluster.submit_cluster_job(
        name=_safe_name(job.task), image=image, command=command, env=job.env,
        mem=f"{int((job.est_mem_gb or 0.5) * 1024)}Mi")


def _run_gpu_backend(job) -> dict:
    # Imported lazily to avoid a hard daemon import at module load. dispatch() owns the lease.
    import daemon as registry
    out = registry.dispatch(job.task, job.prompt or "", None)
    err = out.get("error")
    return {"exit_code": 1 if err else 0, "stdout": out.get("response", ""),
            "node": "enigma", "error": err}


def run_job(job, facts=None) -> dict:
    if facts is None:
        cf = cluster.cluster_facts()
        facts = {"worker_free_mem_gb": cf.get("worker_free_mem_gb")}
    else:
        cf = {"present": cluster.kubectl_available()}

    decision = classifier.classify(job, facts)
    placement = decision["placement"]
    result = {"placement": placement, "reason": decision["reason"]}

    if placement == "enigma-gpu":
        result.update(_run_gpu_backend(job))
        return result

    if placement == "cluster":
        if not cf.get("present", cluster.kubectl_available()):
            result.update(_run_local(job))
            result.update({"placement": "enigma-local", "fallback": True,
                           "reason": "k3s unavailable; ran locally"})
            return result
        result.update(_run_cluster(job))
        return result

    result.update(_run_local(job))
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest daemon/tests/test_executors.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Live integration test (real cluster — gated)**

Create `daemon/tests/test_cluster_live.py`:

```python
import os, pytest, cluster
pytestmark = pytest.mark.skipif(not cluster.kubectl_available(), reason="no k3s")

def test_echo_job_lands_on_worker():
    r = cluster.submit_cluster_job(name="kniox-itest", image="busybox:1.36",
                                   command=["sh", "-c", "echo hello-from-$(hostname)"], timeout=120)
    assert r["exit_code"] == 0
    assert "hello-from-" in r["stdout"]
    assert r["node"] in ("node1", "node2", "node3")   # never enigma
```

Run: `uv run pytest daemon/tests/test_cluster_live.py -v`
Expected: PASS on enigma (job lands on a worker); SKIPPED elsewhere.

- [ ] **Step 6: Commit**

```bash
git add daemon/executors.py daemon/tests/test_executors.py daemon/tests/test_cluster_live.py
git commit -m "feat: job router with executors + honest cluster fallback"
```

---

### Task 8: Daemon integration (`daemon.py`)

**Files:**
- Modify: `daemon/daemon.py` (add `submit_job`; wrap `dispatch` GPU path with the lease; add CLI `submit`)
- Test: `daemon/tests/test_daemon_submit.py`

**Interfaces:**
- Consumes: `executors.run_job`, `jobspec.Job`, `lease`.
- Produces: `submit_job(job: Job) -> dict` (thin wrapper over `executors.run_job`); `dispatch` acquires/releases the GPU lease around `backend.generate`.

- [ ] **Step 1: Write the failing test**

```python
import daemon as registry
from jobspec import Job

def test_submit_job_routes_via_executors(monkeypatch):
    import executors
    monkeypatch.setattr(executors, "run_job", lambda job, **k: {"placement": "cluster", "ok": True})
    assert registry.submit_job(Job(task="t", command=["echo", "x"]))["placement"] == "cluster"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest daemon/tests/test_daemon_submit.py -v`
Expected: FAIL — `AttributeError: module 'daemon' has no attribute 'submit_job'`

- [ ] **Step 3: Implement**

Add to `daemon/daemon.py` (near `dispatch`):

```python
def submit_job(job):
    """Single broker entry point: classify + execute a Job."""
    import executors
    return executors.run_job(job)
```

Wrap the GPU section of `dispatch` (replace the `backend.generate` call site) so it holds the lease:

```python
    import lease
    holder = f"dispatch:{task}"
    lease.acquire_gpu(holder, task, ttl=1800)
    try:
        text = backend.generate(model, prompt)
    except Exception as e:
        return {"error": f"generation failed: {e}", "backend": backend.name, "model": model}
    finally:
        lease.release_gpu(holder)
```

Add a CLI subcommand in `_cli()`:

```python
    sj = s.add_parser("submit"); sj.add_argument("script"); sj.add_argument("--task", default=None)
```

and the handler:

```python
    elif a.cmd == "submit":
        from jobspec import Job
        print(json.dumps(submit_job(Job.from_script(a.script, a.task)), indent=2))
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest daemon/tests/ -v`
Expected: PASS (all suites green)

- [ ] **Step 5: Smoke-test the CLI end to end**

Create `/tmp/hello_job.py`:
```python
# kniox: placement=cluster
print("hello from a worker")
```
Run: `uv run python daemon/daemon.py submit /tmp/hello_job.py --task hello`
Expected (on enigma): JSON with `"placement": "cluster"`, `"node": "node1|node2|node3"`, stdout containing `hello from a worker`.

- [ ] **Step 6: Commit**

```bash
git add daemon/daemon.py daemon/tests/test_daemon_submit.py
git commit -m "feat: daemon submit_job entry + GPU-lease-guarded dispatch"
```

---

### Task 9: k3s-aware manifest (`probe.py`)

**Files:**
- Modify: `daemon/probe.py` (add k3s nodes to the manifest)
- Test: `daemon/tests/test_probe_k3s.py`

**Interfaces:**
- Consumes: `cluster.cluster_facts`.
- Produces: `build_manifest(...)` output gains a `"cluster"` key: `{"present": bool, "nodes": [...], "worker_free_mem_gb": ...}`.

- [ ] **Step 1: Write the failing test**

```python
import probe

def test_manifest_includes_cluster(monkeypatch):
    monkeypatch.setattr(probe.cluster, "cluster_facts",
                        lambda: {"present": True, "nodes": [{"name": "node1"}], "worker_free_mem_gb": 6.7})
    m = probe.build_manifest("2026-06-20T00:00:00", with_fleet=False)
    assert m["cluster"]["present"] is True
    assert m["cluster"]["worker_free_mem_gb"] == 6.7
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest daemon/tests/test_probe_k3s.py -v`
Expected: FAIL — `KeyError: 'cluster'` (or AttributeError if `probe.cluster` not imported)

- [ ] **Step 3: Implement**

At the top of `daemon/probe.py` add `import cluster`. In `build_manifest`, before returning the manifest dict, add:

```python
    manifest["cluster"] = cluster.cluster_facts()
```

(Place it so it sits alongside the existing `host`/`fleet` keys. The Tailscale `fleet` block stays for now — it's additive; the cluster block is the authoritative compute inventory going forward.)

- [ ] **Step 4: Run tests**

Run: `uv run pytest daemon/tests/ -v`
Expected: PASS

- [ ] **Step 5: Verify real setup output**

Run: `uv run python daemon/daemon.py manifest | python -c "import sys,json;print(json.load(sys.stdin)['cluster']['worker_free_mem_gb'])"`
Expected (after `kx setup`): a number (~6.7), confirming the probe records real k3s capacity.

- [ ] **Step 6: Commit**

```bash
git add daemon/probe.py daemon/tests/test_probe_k3s.py
git commit -m "feat: probe records k3s cluster capacity in the manifest"
```

---

### Task 10: MCP surface (`mcp_server.py`)

**Files:**
- Modify: `daemon/mcp_server.py` (expose `submit_job` + `gpu_lease_status`)

**Interfaces:**
- Consumes: `daemon.submit_job`, `lease.gpu_lease_status`, `jobspec.Job`.
- Produces: MCP tools `submit_job(script, task)` and `gpu_lease()`.

- [ ] **Step 1: Add the tools**

Append to `daemon/mcp_server.py` (before `if __name__`):

```python
@mcp.tool()
def submit_job(script: str, task: str = "") -> dict:
    """Broker a job script to the right machine: GPU->enigma (leased), CPU->idle workers.
    Reads the '# kniox: placement=' header for the fast path."""
    from jobspec import Job
    return registry.submit_job(Job.from_script(script, task or None))


@mcp.tool()
def gpu_lease() -> dict:
    """Who currently holds the single-GPU lease (or null if free)."""
    import lease
    return lease.gpu_lease_status() or {"holder": None}
```

- [ ] **Step 2: Verify it imports**

Run: `uv run python -c "import sys; sys.path.insert(0,'daemon'); import mcp_server; print('ok')"`
Expected: `ok` (no import error)

- [ ] **Step 3: Commit**

```bash
git add daemon/mcp_server.py
git commit -m "feat: expose submit_job + gpu_lease over MCP"
```

---

### Task 11: Bake the policy into the framework (docs)

**Files:**
- Modify: `alignment/PROJECT-ALIGNMENT-REQUIREMENT.md` (offload-first policy + placement-header convention)
- Modify: `CONTRIBUTING.md` (branch-per-change / PR-only / no-auto-push rule)
- Modify: `.claude/skills/project-alignment/SKILL.md` (note the repo contract is canonical; reconcile drift)

**Interfaces:** none (documentation).

- [ ] **Step 1: Add to `alignment/PROJECT-ALIGNMENT-REQUIREMENT.md`** a new section after "Compute & VRAM":

```markdown
## Offload-first routing (brokered by the daemon)
All jobs go through the daemon, which classifies each by resource profile:
- **GPU work → enigma only**, serialized behind a single-GPU lease (one heavy model at a time).
- **Needs enigma-local files / interactive / RAM over worker headroom → enigma.**
- **CPU-only, self-contained, modest-RAM, non-interactive → a k3s worker (default).**

There is no shared storage: offloaded jobs fetch inputs over the network and return via
stdout. Every job script MUST start, before its imports, with a placement header:
`# kniox: placement=<enigma-gpu|enigma-local|cluster|auto> [key=value ...]`
`auto` (or no header) lets the classifier decide.
```

- [ ] **Step 2: Add to `CONTRIBUTING.md`** a "Change workflow" section:

```markdown
## Change workflow (rule #1)
Every set of major edits gets its own branch and is raised as a Pull Request — never
pushed or merged automatically. Sequence: branch → implement → verify it works and breaks
nothing → open a PR. Nothing reaches `main` directly; no push/merge without explicit OK.
```

- [ ] **Step 3: Reconcile the alignment skill** — in `.claude/skills/project-alignment/SKILL.md`, change the "read the canonical doc" step to point at the repo contract (`alignment/PROJECT-ALIGNMENT-REQUIREMENT.md`) as canonical, noting the Desktop copy is a mirror.

- [ ] **Step 4: Commit**

```bash
git add alignment/PROJECT-ALIGNMENT-REQUIREMENT.md CONTRIBUTING.md .claude/skills/project-alignment/SKILL.md
git commit -m "docs: bake offload-first routing + PR-only workflow into alignment"
```

---

## Self-Review

**Spec coverage:** Job model (T3) ✓ · header pragma (T2) ✓ · classifier+safety rule (T4) ✓ · GPU lease (T5) ✓ · executors incl. fallback (T6,T7) ✓ · cluster-aware probe (T9) ✓ · honest degradation (T7) ✓ · MCP surface (T10) ✓ · alignment/PR-rule/skill reconcile (T11) ✓. Phase 2 items (kniox-runner image+registry, corn→CronJob, lint hook) intentionally deferred and noted in the spec.

**Placeholder scan:** none — every code step shows full code; every run step has an exact command + expected result.

**Type consistency:** `classify()` returns `{"placement","reason"}` used consistently in T7; `cluster_facts()` returns `worker_free_mem_gb` consumed by `classify` facts and `run_job`; `submit_cluster_job` return shape (`exit_code/stdout/node/error`) matches what `_run_cluster`/`run_job` propagate; the GPU lease is held in exactly one place (`daemon.dispatch`, T8) and the GPU path in T7 delegates to it — no double-acquire; `Job.source` (T3) is consumed by `_run_cluster` (T7) for self-contained code delivery.
