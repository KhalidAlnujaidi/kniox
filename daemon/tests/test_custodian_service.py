import custodian_service as cs
import custodian_report as report

def _common(monkeypatch, tmp_path, fp_state):
    monkeypatch.setenv("KNIOX_CUSTODIAN_DIR", str(tmp_path / "custodian"))
    monkeypatch.setattr(cs.lease, "gpu_is_idle", lambda: True)
    monkeypatch.setattr(cs.custodian_survey, "survey", lambda: {"x": 1})
    monkeypatch.setattr(cs.custodian_survey, "material_fingerprint", lambda s: "fp")
    monkeypatch.setattr(cs.report, "_load_state", lambda: fp_state)
    monkeypatch.setattr(cs.custodian_model, "select_model", lambda: ("m", "r"))

def test_skips_when_busy(monkeypatch):
    monkeypatch.setattr(cs.lease, "gpu_is_idle", lambda: False)
    out = cs.run_once()
    assert out["skipped"] and "busy" in out["reason"]

def test_skips_when_unchanged(monkeypatch, tmp_path):
    _common(monkeypatch, tmp_path, {"fingerprint": "fp"})
    out = cs.run_once()
    assert out["skipped"] and out["reason"] == "no change"

def test_happy_path_writes_and_releases(monkeypatch, tmp_path):
    _common(monkeypatch, tmp_path, {})
    monkeypatch.setattr(cs.lease, "acquire_gpu", lambda *a, **k: True)
    monkeypatch.setattr(cs.lease, "is_revoked", lambda h: False)
    monkeypatch.setattr(cs, "_generate", lambda model, survey: "REPORT")
    rel = {}
    monkeypatch.setattr(cs.lease, "release_gpu", lambda h: rel.__setitem__("h", h))
    out = cs.run_once()
    assert out["written"] and out["model"] == "m"
    assert rel["h"] == "custodian"
    assert (report._reports_dir() / "latest.md").read_text() == "REPORT"

def test_preempted_discards_and_releases(monkeypatch, tmp_path):
    _common(monkeypatch, tmp_path, {})
    monkeypatch.setattr(cs.lease, "acquire_gpu", lambda *a, **k: True)
    monkeypatch.setattr(cs.lease, "is_revoked", lambda h: True)     # revoked immediately
    rel = {}
    monkeypatch.setattr(cs.lease, "release_gpu", lambda h: rel.__setitem__("h", h))
    out = cs.run_once()
    assert out["skipped"] and out["reason"] == "preempted" and rel["h"] == "custodian"

def test_serve_once_returns_run_once(monkeypatch):
    monkeypatch.setattr(cs, "run_once", lambda: {"skipped": True, "reason": "z"})
    assert cs.serve(once=True)["reason"] == "z"
