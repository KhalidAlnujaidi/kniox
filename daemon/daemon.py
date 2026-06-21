#!/usr/bin/env python3
"""kniox daemon — registry + VRAM broker + specialized-model dispatch.

Hardware-agnostic: there are NO baked-in GPU sizes, model rosters, or backend
assumptions anymore. The broker reads detected FACTS from manifest.json (written by the
probe) and DECISIONS from config.json (written by setup). Anything that can't be
measured is reported as unknown, never as a convenient zero.

CLI:
    python daemon/daemon.py init
    python daemon/daemon.py register <name> <path>
    python daemon/daemon.py list
    python daemon/daemon.py vram | resources | manifest
    python daemon/daemon.py can-load <model>          # exit 0 ok/unknown, exit 3 over budget
    python daemon/daemon.py dispatch <task> <prompt>  # via the configured backend
"""
from __future__ import annotations
import argparse, contextlib, datetime, json, os, sqlite3, time

from config import (DB_PATH, load_config, save_config, load_manifest, save_manifest,
                    default_config_from_manifest, vram_budget as cfg_vram_budget)
from backends import get_backend

SLOTS = {"daytime": "interactive; one model, fast unload",
         "render":  "video pipelines, sequential queue",
         "nightly": "batch jobs"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects(name TEXT PRIMARY KEY, path TEXT NOT NULL,
  created_at REAL NOT NULL, updated_at REAL NOT NULL, status TEXT NOT NULL DEFAULT 'idle');
CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY AUTOINCREMENT, project TEXT NOT NULL,
  task TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'queued', started_at REAL NOT NULL);
"""


# ---- registry ---------------------------------------------------------------
def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


# `with conn` manages the TRANSACTION (commit/rollback) but never CLOSES the connection;
# in the long-running mcp_server.py that leaks a file descriptor per call until the OS
# open-file limit is hit. closing() guarantees the close; the inner `c` keeps the txn.
def init_db():
    with contextlib.closing(_conn()) as c, c:
        c.executescript(SCHEMA)


def register_project(name, path):
    now = time.time()
    with contextlib.closing(_conn()) as c, c:
        c.execute("INSERT INTO projects(name,path,created_at,updated_at) VALUES(?,?,?,?) "
                  "ON CONFLICT(name) DO UPDATE SET path=excluded.path, updated_at=?",
                  (name, path, now, now, now))
    return get_project(name)


def list_projects():
    with contextlib.closing(_conn()) as c:
        return [dict(r) for r in c.execute("SELECT * FROM projects ORDER BY updated_at DESC")]


def get_project(name):
    with contextlib.closing(_conn()) as c:
        r = c.execute("SELECT * FROM projects WHERE name=?", (name,)).fetchone()
    return dict(r) if r else None


def record_run(project, task, state="queued"):
    now = time.time()
    with contextlib.closing(_conn()) as c, c:
        cur = c.execute("INSERT INTO runs(project,task,state,started_at) VALUES(?,?,?,?)",
                        (project, task, state, now))
        c.execute("UPDATE projects SET status=?, updated_at=? WHERE name=?", (state, now, project))
        rid = cur.lastrowid
    return {"id": rid, "project": project, "task": task, "state": state}


def list_runs(limit=20):
    with contextlib.closing(_conn()) as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,))]


# ---- manifest / resources ---------------------------------------------------
def current_slot():
    h = datetime.datetime.now().hour
    return "nightly" if (h >= 23 or h < 6) else "render" if h >= 18 else "daytime"


def refresh_manifest(with_fleet=False):
    """Re-run the probe and persist the manifest. Used by setup and the MCP tool."""
    import probe
    m = probe.build_manifest(datetime.datetime.now().isoformat(timespec="seconds"),
                             with_fleet=with_fleet)
    save_manifest(m)
    return m


def vram_snapshot():
    """LIVE accelerator read (OS-aware via the probe) + budget from config/manifest.
    used_gb / total_gb are None when no accelerator is measurable — honest, not zero."""
    import probe
    config, manifest = load_config(), load_manifest()
    notes = []
    accels = probe.probe_accelerators(notes)
    used_vals = [a["vram_used_gb"] for a in accels if a.get("vram_used_gb") is not None]
    tot_vals = [a["vram_total_gb"] for a in accels if a.get("vram_total_gb")]
    backend = get_backend(config)
    return {"accelerators": accels,
            "used_gb": round(sum(used_vals), 2) if used_vals else None,
            "total_gb": round(sum(tot_vals), 2) if tot_vals else None,
            "budget_gb": cfg_vram_budget(config, manifest),
            "slot": current_slot(),
            "backend": backend.name,
            "loaded": backend.loaded() if backend.present() else [],
            "notes": notes, "slots": SLOTS}


def _estimate_model_gb(model, config, backend):
    override = (config.get("model_vram_gb") or {}).get(model)
    if override is not None:
        return override, "config override"
    for m in backend.models():
        if m.get("name") == model and m.get("size_gb"):
            return m["size_gb"], "backend model size"
    return None, "unknown"


def can_load(model):
    """ok is True (fits), False (over budget), or None (can't verify — honest unknown).
    None is NOT a green light dressed as one; callers must treat it as 'proceed with a
    caveat', and the CLI exits non-blocking (0) only because over-budget (False) is the
    sole hard stop."""
    config = load_config()
    backend = get_backend(config)
    snap = vram_snapshot()
    budget, used = snap["budget_gb"], snap["used_gb"]
    est, basis = _estimate_model_gb(model, config, backend)
    if budget is None or used is None or est is None:
        return {"model": model, "est_gb": est, "used_gb": used, "budget_gb": budget,
                "headroom_gb": None, "ok": None, "basis": basis,
                "reason": "insufficient data to verify VRAM fit (honest unknown)"}
    headroom = round(budget - used, 2)
    ok = est <= headroom
    return {"model": model, "est_gb": est, "used_gb": used, "budget_gb": budget,
            "headroom_gb": headroom, "ok": ok, "basis": basis,
            "reason": "fits" if ok else "would exceed VRAM budget"}


def submit_job(job):
    """Single broker entry point: classify + execute a Job."""
    import executors
    return executors.run_job(job)


def shadow_run(repo, change_cmd, verify_cmd, apply=True, keep=False):
    """Run edits in an isolated worktree, verify there, apply to the real tree only on green.
    Refuses to apply onto main/master (PR-only). Pure git + CPU — no GPU lease."""
    import shadow
    return shadow.shadow_run(repo, change_cmd, verify_cmd, apply=apply, keep=keep)


def cli_custodian(force=False):
    import custodian_report
    return custodian_report.run(force=force)


def cli_custodian_serve(once=False):
    import custodian_service
    return custodian_service.serve(once=once)


def dispatch(task, prompt, model=None):
    """Run the configured backend's best model for a task, brokered against VRAM.
    Degrades honestly: no backend / no model mapping returns an actionable error
    instead of pretending to succeed."""
    config = load_config()
    backend = get_backend(config)
    if backend.name == "none":
        return {"error": "no inference backend configured", "backend": "none",
                "hint": "run `kx setup` to detect or install one (ollama / vllm / llama.cpp)"}
    if not backend.present():
        return {"error": f"backend '{backend.name}' configured but not reachable",
                "backend": backend.name, "hint": "is it running? check the endpoint in config.json"}
    model = model or (config.get("task_models") or {}).get(task)
    if not model:
        return {"error": f"no model mapped for task '{task}'",
                "task_models": config.get("task_models", {}),
                "hint": "set task_models in daemon/state/config.json or pass an explicit model"}
    gate = can_load(model)
    if gate.get("ok") is False:
        return {"error": "VRAM budget", **gate}
    import lease
    holder = f"dispatch:{task}"
    if not lease.acquire_gpu(holder, task, ttl=1800, timeout=600):
        return {"error": "GPU busy: another job holds the single-GPU lease",
                "backend": backend.name, "model": model,
                "gpu_lease": lease.gpu_lease_status(),
                "hint": "retry shortly; the lease frees on completion or its TTL"}
    try:
        text = backend.generate(model, prompt)
    except Exception as e:
        return {"error": f"generation failed: {e}", "backend": backend.name, "model": model}
    finally:
        lease.release_gpu(holder)
    out = {"backend": backend.name, "model": model, "task": task, "response": text}
    if gate.get("ok") is None:
        out["vram_note"] = gate["reason"]      # surfaced, not hidden
    return out


def system_resources():
    try:
        import psutil
    except ImportError:
        return {"error": "psutil missing (uv add psutil)", "vram": vram_snapshot()}
    vm = psutil.virtual_memory()
    return {"cpu_percent": psutil.cpu_percent(interval=0.2), "memory_percent": vm.percent,
            "memory_used_gb": round(vm.used / 1e9, 2), "memory_total_gb": round(vm.total / 1e9, 2),
            "vram": vram_snapshot()}


def _recent_runs(name, limit=5):
    with contextlib.closing(_conn()) as c:
        rows = c.execute("SELECT task,state,started_at FROM runs WHERE project=? "
                         "ORDER BY started_at DESC LIMIT ?", (name, limit)).fetchall()
    return [{"task": r[0], "state": r[1], "started_at": r[2]} for r in rows]


def _gpu_util(vram):
    accs = (vram or {}).get("accelerators") or []
    utils = [a.get("util_percent") for a in accs if a.get("util_percent") is not None]
    return max(utils) if utils else None


def dashboard_state():
    """Single read-only aggregate for the dashboard. Composes existing readers;
    unmeasurable values stay null (never faked as 0)."""
    import cluster
    res = system_resources()
    vram = res.get("vram", {}) if isinstance(res, dict) else {}
    try:
        import lease
        holder = lease.gpu_lease_status() or {}
    except Exception:
        holder = {}
    projects = [{"name": p["name"], "status": p.get("status"), "path": p.get("path"),
                 "last_run": (_recent_runs(p["name"], 1) or [None])[0],
                 "slot": current_slot()} for p in list_projects()]
    services = [{"name": d["name"], "kind": "k3s-deploy", "running": d["running"],
                 "draw": f'{d["ready"]}/{d["desired"]} replicas'}
                for d in cluster.cluster_deployments()]
    return {
        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        "resources": {
            "gpu": {"used_gb": vram.get("used_gb"), "total_gb": vram.get("total_gb"),
                    "budget_gb": vram.get("budget_gb"), "util_pct": _gpu_util(vram),
                    "lease_holder": holder.get("holder")},
            "cpu_pct": res.get("cpu_percent"),
            "ram": {"used_gb": res.get("memory_used_gb"),
                    "total_gb": res.get("memory_total_gb"), "pct": res.get("memory_percent")},
            "slot": current_slot()},
        "services": services,
        "projects": projects,
        "cluster": cluster.cluster_facts().get("nodes", []),
        "notes": list(vram.get("notes") or []),
    }


def project_detail(name):
    p = get_project(name)
    if not p:
        return None
    doc, path = None, p.get("path")
    if path:
        for fn in ("next.md", "PROGRESS.md"):
            try:
                with open(os.path.join(os.path.expanduser(path), fn)) as f:
                    doc = f.read()
                    break
            except OSError:
                continue
    return {"name": name, "path": path, "status": p.get("status"),
            "doc": doc, "runs": _recent_runs(name, 5)}


def _cli():
    p = argparse.ArgumentParser(prog="kniox-daemon")
    s = p.add_subparsers(dest="cmd", required=True)
    for c in ("init", "list", "vram", "resources", "manifest"):
        s.add_parser(c)
    r = s.add_parser("register"); r.add_argument("name"); r.add_argument("path")
    cl = s.add_parser("can-load"); cl.add_argument("model")
    d = s.add_parser("dispatch"); d.add_argument("task"); d.add_argument("prompt")
    sj = s.add_parser("submit"); sj.add_argument("script"); sj.add_argument("--task", default=None)
    cu = s.add_parser("custodian"); cu.add_argument("action", choices=["run", "serve"])
    cu.add_argument("--force", action="store_true"); cu.add_argument("--once", action="store_true")
    sh = s.add_parser("shadow"); sh.add_argument("change_cmd"); sh.add_argument("verify_cmd")
    sh.add_argument("--repo", default="."); sh.add_argument("--no-apply", action="store_true")
    sh.add_argument("--keep", action="store_true")
    a = p.parse_args()
    init_db()
    if a.cmd == "init":
        print("initialized", DB_PATH)
    elif a.cmd == "register":
        print(json.dumps(register_project(a.name, a.path), indent=2))
    elif a.cmd == "list":
        print(json.dumps(list_projects(), indent=2))
    elif a.cmd == "vram":
        print(json.dumps(vram_snapshot(), indent=2))
    elif a.cmd == "resources":
        print(json.dumps(system_resources(), indent=2))
    elif a.cmd == "manifest":
        print(json.dumps(load_manifest() or {"error": "no manifest; run `kx setup`"}, indent=2))
    elif a.cmd == "dispatch":
        print(json.dumps(dispatch(a.task, a.prompt), indent=2))
    elif a.cmd == "can-load":
        res = can_load(a.model)
        print(json.dumps(res, indent=2))
        raise SystemExit(3 if res["ok"] is False else 0)   # only over-budget blocks
    elif a.cmd == "submit":
        from jobspec import Job
        print(json.dumps(submit_job(Job.from_script(a.script, a.task)), indent=2))
    elif a.cmd == "shadow":
        res = shadow_run(a.repo, a.change_cmd, a.verify_cmd,
                         apply=not a.no_apply, keep=a.keep)
        print(json.dumps(res, indent=2))
        raise SystemExit(0 if res.get("applied") or res.get("stage") == "ok" else 1)
    elif a.cmd == "custodian":
        if a.action == "serve":
            res = cli_custodian_serve(once=a.once)
            if a.once:
                print(json.dumps(res, indent=2))
        else:
            print(json.dumps(cli_custodian(force=a.force), indent=2))


if __name__ == "__main__":
    _cli()
