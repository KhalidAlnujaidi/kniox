import os, json
import custodian_report as cr
import custodian_survey, custodian_model
import daemon as registry

FAKE_SURVEY = {"operational": {"projects": ["p"]}, "repo": {"git_status": ["M x"]}}

def _patch(monkeypatch, tmp_path, dispatch_result, fp="fp1"):
    monkeypatch.setenv("KNIOX_CUSTODIAN_DIR", str(tmp_path / "custodian"))
    monkeypatch.setattr(cr.custodian_survey, "survey", lambda: FAKE_SURVEY)
    monkeypatch.setattr(cr.custodian_survey, "material_fingerprint", lambda s: fp)
    monkeypatch.setattr(cr.custodian_model, "select_model", lambda: ("m", "largest"))
    monkeypatch.setattr(cr.registry, "dispatch", lambda *a, **k: dispatch_result)

def test_build_prompt_has_instruction_and_alignment():
    p = cr.build_prompt(FAKE_SURVEY, "ALIGNMENT-CONTRACT-TEXT")
    assert "ALIGNMENT-CONTRACT-TEXT" in p
    assert "propose" in p.lower() and "do not apply" in p.lower()
    assert "git_status" in p   # survey digest present

def test_run_writes_report_and_latest_and_state(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path, {"response": "ALL GOOD"})
    out = cr.run(force=True)
    assert out["written"] is True
    assert os.path.exists(out["path"])
    assert (cr._reports_dir() / "latest.md").read_text() == "ALL GOOD"
    assert json.loads(cr._state_path().read_text())["fingerprint"] == "fp1"

def test_run_skips_when_fingerprint_unchanged(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path, {"response": "X"})
    cr._state_path().parent.mkdir(parents=True, exist_ok=True)
    cr._state_path().write_text(json.dumps({"fingerprint": "fp1"}))
    def _boom(*a, **k): raise AssertionError("dispatch must not be called")
    monkeypatch.setattr(cr.registry, "dispatch", _boom)
    out = cr.run(force=False)
    assert out["skipped"] is True and "change" in out["reason"].lower()

def test_run_skips_on_gpu_busy(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path, {"error": "GPU busy: another job holds the lease"})
    out = cr.run(force=True)
    assert out["skipped"] is True and "busy" in out["reason"].lower()

def test_run_writes_only_under_custodian_dir(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path, {"response": "R"})
    out = cr.run(force=True)
    assert str(cr._custodian_dir()) in out["path"]   # report lives under the custodian dir
