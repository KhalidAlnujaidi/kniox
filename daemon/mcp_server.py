#!/usr/bin/env python3
"""kniox MCP server — registry + capability manifest + VRAM broker + dispatch, exposed
to Claude Code. Run:  python daemon/mcp_server.py     (deps: uv add mcp psutil)
"""
from __future__ import annotations
from mcp.server.fastmcp import FastMCP
import daemon as registry

registry.init_db()
mcp = FastMCP("kniox")


@mcp.tool()
def list_projects() -> list:
    """All registered kniox projects with status + last activity."""
    return registry.list_projects()


@mcp.tool()
def project_status(name: str) -> dict:
    """Status of one project by name."""
    return registry.get_project(name) or {"error": f"no project named {name!r}"}


@mcp.tool()
def register_project(name: str, path: str) -> dict:
    """Register/update a project in the registry."""
    return registry.register_project(name, path)


@mcp.tool()
def register_run(project: str, task: str, state: str = "queued") -> dict:
    """Record a run for a project (queued|running|done|failed)."""
    return registry.record_run(project, task, state)


@mcp.tool()
def get_manifest() -> dict:
    """Detected hardware + backends + tailnet fleet (the capability manifest)."""
    return registry.load_manifest() or {"error": "no manifest yet; run `kx setup`"}


@mcp.tool()
def refresh_manifest(with_fleet: bool = False) -> dict:
    """Re-run the probe and persist the manifest. Set with_fleet to sweep the tailnet."""
    return registry.refresh_manifest(with_fleet=with_fleet)


@mcp.tool()
def vram_snapshot() -> dict:
    """Live accelerator usage, budget, current slot, configured backend, loaded models.
    Unmeasurable values are null (honest), never zero."""
    return registry.vram_snapshot()


@mcp.tool()
def can_load(model: str) -> dict:
    """Whether `model` fits the VRAM budget. ok is true/false/null (null = can't verify)."""
    return registry.can_load(model)


@mcp.tool()
def dispatch(task: str, prompt: str, model: str = "") -> dict:
    """Run the configured backend's model for a task, VRAM-brokered. Degrades honestly
    when no backend or no task->model mapping exists."""
    return registry.dispatch(task, prompt, model or None)


@mcp.tool()
def submit_job(script: str, task: str = "") -> dict:
    """Broker a job script to the right machine: GPU->enigma (leased), CPU->idle workers.
    Reads the '# kniox: placement=' header for the fast path."""
    from jobspec import Job
    return registry.submit_job(Job.from_script(script, task or None))


@mcp.tool()
def shadow_run(change_cmd: str, verify_cmd: str, repo: str = ".",
               apply: bool = True, keep: bool = False) -> dict:
    """Run edits behind the Shadow-Git gate: execute `change_cmd` in an isolated worktree,
    run `verify_cmd` there, and apply to the real tree only if verify passes. A red verify
    never touches the real tree. Refuses to apply onto main/master (PR-only). No GPU lease."""
    return registry.shadow_run(repo, change_cmd, verify_cmd, apply=apply, keep=keep)


@mcp.tool()
def gpu_lease() -> dict:
    """Who currently holds the single-GPU lease (or null if free)."""
    import lease
    return lease.gpu_lease_status() or {"holder": None}


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


if __name__ == "__main__":
    mcp.run()
