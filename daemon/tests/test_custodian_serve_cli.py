import daemon as registry

def test_cli_serve_once(monkeypatch):
    import custodian_service
    monkeypatch.setattr(custodian_service, "serve", lambda once=False: {"once": once})
    assert registry.cli_custodian_serve(once=True) == {"once": True}
