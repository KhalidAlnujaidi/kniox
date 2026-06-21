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
