"""k3s adapter — shells out to kubectl (no python kube client dependency).

Worker = any Ready node WITHOUT the control-plane role label (enigma is control-plane).
Cluster jobs get anti-affinity to the control-plane so they land on node1/2/3.
"""
from __future__ import annotations
import json, os, shutil, subprocess, time

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


def parse_deployments(kubectl_json: dict) -> list[dict]:
    out = []
    for item in kubectl_json.get("items", []):
        meta = item.get("metadata", {})
        spec, status = item.get("spec", {}), item.get("status", {})
        desired = spec.get("replicas", 0) or 0
        ready = status.get("readyReplicas", 0) or 0
        out.append({"name": meta.get("name"), "namespace": meta.get("namespace"),
                    "ready": ready, "desired": desired, "running": ready > 0})
    return out


def cluster_deployments() -> list[dict]:
    """Long-running k3s deployments = the '24/7 services' view. [] when no cluster."""
    if not kubectl_available():
        return []
    try:
        res = _kubectl("get", "deploy", "-A", "-o", "json", timeout=15)
        return parse_deployments(json.loads(res.stdout))
    except Exception:
        return []


def _await_job(name, timeout) -> str:
    """Poll the Job status until it succeeds or fails. Returns 'succeeded'|'failed'|'timeout'.
    Polling (not `kubectl wait --for=complete`) so a FAILED job is detected promptly instead
    of blocking until the deadline."""
    end = time.time() + timeout
    while time.time() < end:
        r = _kubectl("get", "job", name, "-o",
                     "jsonpath={.status.succeeded} {.status.failed}", timeout=10)
        raw = r.stdout  # space-separated: "{succeeded} {failed}" (fields may be absent/empty)
        succ, sep, failed = raw.partition(" ")
        if sep == "":
            # only one token — ambiguous; treat as neither terminal
            succ, failed = "", ""
        if succ.strip() == "1":
            return "succeeded"
        if failed.strip() and failed.strip() != "0":
            return "failed"
        time.sleep(2)
    return "timeout"


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
        outcome = _await_job(name, timeout)
        logs = _kubectl("logs", f"job/{name}", timeout=20)
        pod = _kubectl("get", "pods", "-l", f"job-name={name}",
                       "-o", "jsonpath={.items[0].spec.nodeName}", timeout=10)
        node = pod.stdout.strip() or None
        if outcome == "succeeded":
            return {"exit_code": 0, "stdout": logs.stdout, "node": node, "error": None}
        code = 124 if outcome == "timeout" else 1
        return {"exit_code": code, "stdout": logs.stdout, "node": node,
                "error": f"job {outcome}"}
    except subprocess.TimeoutExpired:
        return {"exit_code": 124, "stdout": "", "node": None, "error": "kubectl timed out"}
    finally:
        _kubectl("delete", "job", name, "--ignore-not-found", timeout=20)
