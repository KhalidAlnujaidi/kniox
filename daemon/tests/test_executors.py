import executors
from jobspec import Job

def test_cluster_job_runs_on_worker(monkeypatch):
    monkeypatch.setattr(executors.cluster, "cluster_facts",
                        lambda: {"present": True, "worker_free_mem_gb": 7.0})
    monkeypatch.setattr(executors.cluster, "submit_cluster_job",
                        lambda **k: {"exit_code": 0, "stdout": "hi", "node": "node2", "error": None})
    # Phase 1 cluster requires a source job; command-only jobs are Phase 2.
    r = executors.run_job(Job(task="t", source="print('hi')"))
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

def test_cluster_job_without_source_errors_honestly(monkeypatch):
    # Exercises both fixes: caller-supplied present is honored (no spurious fallback),
    # and a non-source cluster job degrades honestly instead of running in a python image.
    monkeypatch.setattr(executors.cluster, "kubectl_available", lambda: True)
    r = executors.run_job(Job(task="t", command=["echo", "hi"]),
                          facts={"worker_free_mem_gb": 7.0, "present": True})
    assert r["placement"] == "cluster"
    assert r["exit_code"] == 1
    assert "Phase 2" in (r["error"] or "")
