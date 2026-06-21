import daemon as registry


def test_cli_custodian_run_dispatches(monkeypatch, capsys):
    import custodian_report
    monkeypatch.setattr(custodian_report, "run", lambda force=False: {"skipped": True, "reason": "no model"})
    rc = registry.cli_custodian(force=True)   # thin helper the CLI handler calls
    assert rc["skipped"] is True
