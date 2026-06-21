import probe

def test_manifest_includes_cluster(monkeypatch):
    monkeypatch.setattr(probe.cluster, "cluster_facts",
                        lambda: {"present": True, "nodes": [{"name": "node1"}], "worker_free_mem_gb": 6.7})
    m = probe.build_manifest("2026-06-20T00:00:00", with_fleet=False)
    assert m["cluster"]["present"] is True
    assert m["cluster"]["worker_free_mem_gb"] == 6.7
