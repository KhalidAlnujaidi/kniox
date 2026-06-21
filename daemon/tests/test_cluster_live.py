import os, pytest, cluster
pytestmark = pytest.mark.skipif(not cluster.kubectl_available(), reason="no k3s")

def test_echo_job_lands_on_worker():
    r = cluster.submit_cluster_job(name="kniox-itest", image="busybox:1.36",
                                   command=["sh", "-c", "echo hello-from-$(hostname)"], timeout=120)
    assert r["exit_code"] == 0
    assert "hello-from-" in r["stdout"]
    assert r["node"] in ("node1", "node2", "node3")   # never enigma
