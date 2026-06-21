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
