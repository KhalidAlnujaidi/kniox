import custodian_survey as cs
import daemon as registry
import lease, cluster

def _patch_ops(monkeypatch):
    monkeypatch.setattr(registry, "list_projects", lambda: [{"name": "p", "status": "idle"}])
    monkeypatch.setattr(registry, "list_runs", lambda n=20: [{"state": "done", "task": "t"}])
    monkeypatch.setattr(registry, "current_slot", lambda: "nightly")
    monkeypatch.setattr(registry, "vram_snapshot", lambda: {"used_gb": 1.0})
    monkeypatch.setattr(registry, "system_resources", lambda: {"cpu_percent": 5})
    monkeypatch.setattr(lease, "gpu_lease_status", lambda: None)
    monkeypatch.setattr(cluster, "cluster_facts", lambda: {"present": True})

def test_collect_operational_uses_registry(monkeypatch):
    _patch_ops(monkeypatch)
    op = cs.collect_operational()
    assert op["projects"] == [{"name": "p", "status": "idle"}]
    assert op["slot"] == "nightly" and op["cluster"] == {"present": True}

def test_collector_failure_is_isolated(monkeypatch):
    _patch_ops(monkeypatch)
    def boom(): raise RuntimeError("db down")
    monkeypatch.setattr(registry, "list_projects", boom)
    op = cs.collect_operational()
    assert "error" in op["projects"]          # isolated, not a crash
    assert op["slot"] == "nightly"            # other sections still collected

def test_fingerprint_ignores_live_noise():
    s1 = {"operational": {"resources": {"cpu": 1}, "projects": ["a"], "vram": {"u": 1}},
          "repo": {"git_status": ["x"]}}
    s2 = {"operational": {"resources": {"cpu": 99}, "projects": ["a"], "vram": {"u": 9}},
          "repo": {"git_status": ["x"]}}
    assert cs.material_fingerprint(s1) == cs.material_fingerprint(s2)

def test_fingerprint_changes_on_material():
    s1 = {"operational": {"projects": ["a"]}, "repo": {"git_status": ["x"]}}
    s2 = {"operational": {"projects": ["a"]}, "repo": {"git_status": ["y"]}}
    assert cs.material_fingerprint(s1) != cs.material_fingerprint(s2)

def test_list_runs_reads_recent(tmp_path, monkeypatch):
    registry.init_db()
    registry.record_run("proj", "task", "done")
    runs = registry.list_runs(5)
    assert runs and runs[0]["project"] == "proj" and runs[0]["state"] == "done"
