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
