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
    # Phase 1 cluster delivery is self-contained Python source (no shared storage):
    # embed the script as `python -c <source>` in a stock python image. Non-source jobs
    # need the custom runner image (Phase 2), so fail honestly rather than mis-run them.
    if job.source is None:
        return {"exit_code": 1, "stdout": "", "node": None,
                "error": "cluster execution needs a Python source job in Phase 1; "
                         "non-source jobs await the runner image (Phase 2)"}
    return cluster.submit_cluster_job(
        name=_safe_name(job.task), image="python:3.12-slim",
        command=["python", "-c", job.source], env=job.env,
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
        # Honor a caller-supplied present flag; otherwise let the fallback check probe live.
        cf = {"present": facts["present"]} if "present" in facts else {}

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
