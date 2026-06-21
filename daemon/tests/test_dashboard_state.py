import daemon

def test_gpu_util_max_or_none():
    assert daemon._gpu_util({"accelerators": [{"util_percent": 0}, {"util_percent": 7}]}) == 7
    assert daemon._gpu_util({"accelerators": [{"util_percent": None}]}) is None
    assert daemon._gpu_util({}) is None

def test_dashboard_state_shape_and_honest_unknowns(monkeypatch):
    monkeypatch.setattr(daemon, "system_resources", lambda: {
        "cpu_percent": 3.0, "memory_used_gb": 11.0, "memory_total_gb": 60.0,
        "memory_percent": 18.0,
        "vram": {"used_gb": None, "total_gb": None, "budget_gb": 18.0,
                 "accelerators": [], "notes": ["no accelerator measurable"]}})
    monkeypatch.setattr(daemon, "list_projects", lambda: [
        {"name": "p1", "path": "/tmp/p1", "status": "idle"}])
    monkeypatch.setattr(daemon, "_recent_runs", lambda n, limit=5: [])
    import cluster
    monkeypatch.setattr(cluster, "cluster_deployments", lambda: [
        {"name": "svc", "namespace": "default", "ready": 1, "desired": 1, "running": True}])
    monkeypatch.setattr(cluster, "cluster_facts",
                        lambda: {"present": True, "nodes": [], "worker_free_mem_gb": None})

    s = daemon.dashboard_state()
    assert set(s) == {"ts", "resources", "services", "projects", "cluster", "notes"}
    assert s["resources"]["gpu"]["used_gb"] is None        # honest unknown, not 0
    assert s["resources"]["gpu"]["budget_gb"] == 18.0
    assert s["services"][0] == {"name": "svc", "kind": "k3s-deploy",
                                "running": True, "draw": "1/1 replicas"}
    assert s["projects"][0]["name"] == "p1"
    assert "no accelerator measurable" in s["notes"]

def test_project_detail_unknown_is_none(monkeypatch):
    monkeypatch.setattr(daemon, "get_project", lambda n: None)
    assert daemon.project_detail("nope") is None
