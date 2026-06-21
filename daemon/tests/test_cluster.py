import cluster

SAMPLE = {"items": [
  {"metadata": {"name": "enigma", "labels": {"node-role.kubernetes.io/control-plane": "true"}},
   "status": {"capacity": {"cpu": "16", "memory": "63375384Ki"},
              "allocatable": {"memory": "60000000Ki"},
              "conditions": [{"type": "Ready", "status": "True"}]}},
  {"metadata": {"name": "node1", "labels": {}},
   "status": {"capacity": {"cpu": "12", "memory": "7795408Ki"},
              "allocatable": {"memory": "7000000Ki"},
              "conditions": [{"type": "Ready", "status": "True"}]}},
]}

def test_parse_nodes_marks_roles_and_workers():
    nodes = cluster.parse_nodes(SAMPLE)
    by = {n["name"]: n for n in nodes}
    assert by["enigma"]["control_plane"] is True
    assert by["node1"]["control_plane"] is False
    assert by["node1"]["ready"] is True
    assert round(by["node1"]["alloc_mem_gb"], 1) == 6.7  # 7000000Ki -> GiB


class _R:
    def __init__(self, rc=0, out=""):
        self.returncode, self.stdout, self.stderr = rc, out, ""

def _mock_cluster(monkeypatch, job_status):
    monkeypatch.setattr(cluster.subprocess, "run", lambda *a, **k: _R(0, ""))
    monkeypatch.setattr(cluster.time, "sleep", lambda s: None)
    def fake_kubectl(*args, **k):
        if args[:2] == ("get", "job"):
            return _R(0, job_status)            # "{succeeded} {failed}"
        if args[0] == "logs":
            return _R(0, "out")
        if args[:2] == ("get", "pods"):
            return _R(0, "node2")
        return _R(0, "")
    monkeypatch.setattr(cluster, "_kubectl", fake_kubectl)

def test_submit_reports_success(monkeypatch):
    _mock_cluster(monkeypatch, "1 ")
    r = cluster.submit_cluster_job(name="kniox-x", image="busybox", command=["true"], timeout=5)
    assert r["exit_code"] == 0 and r["node"] == "node2" and r["error"] is None

def test_submit_reports_failure(monkeypatch):
    _mock_cluster(monkeypatch, " 1")
    r = cluster.submit_cluster_job(name="kniox-x", image="busybox", command=["false"], timeout=5)
    assert r["exit_code"] == 1 and "fail" in (r["error"] or "")


SAMPLE_DEPLOY = {"items": [
    {"metadata": {"name": "render-worker", "namespace": "default"},
     "spec": {"replicas": 1}, "status": {"readyReplicas": 1}},
    {"metadata": {"name": "idle-svc", "namespace": "default"},
     "spec": {"replicas": 2}, "status": {}},
]}

def test_parse_deployments_running_and_stopped():
    d = cluster.parse_deployments(SAMPLE_DEPLOY)
    assert d[0] == {"name": "render-worker", "namespace": "default",
                    "ready": 1, "desired": 1, "running": True}
    assert d[1]["ready"] == 0 and d[1]["desired"] == 2 and d[1]["running"] is False
