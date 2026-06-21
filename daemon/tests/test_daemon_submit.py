import daemon as registry
from jobspec import Job

def test_submit_job_routes_via_executors(monkeypatch):
    import executors
    monkeypatch.setattr(executors, "run_job", lambda job, **k: {"placement": "cluster", "ok": True})
    assert registry.submit_job(Job(task="t", command=["echo", "x"]))["placement"] == "cluster"
