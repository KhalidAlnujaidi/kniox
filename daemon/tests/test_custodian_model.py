import custodian_model as cm
import daemon as registry
import backends, config

class _FakeBackend:
    name = "ollama"
    def __init__(self, models): self._m = models
    def present(self): return True
    def models(self): return self._m

def _setup(monkeypatch, models, ok_by_name):
    monkeypatch.setattr(config, "load_config", lambda: {"backend": "ollama"})
    monkeypatch.setattr(backends, "get_backend", lambda cfg: _FakeBackend(models))
    monkeypatch.setattr(registry, "can_load", lambda name: {"ok": ok_by_name.get(name)})

def test_picks_largest_that_fits(monkeypatch):
    models = [{"name": "big", "size_gb": 19}, {"name": "mid", "size_gb": 9}, {"name": "sm", "size_gb": 2}]
    _setup(monkeypatch, models, {"big": False, "mid": True, "sm": True})
    name, reason = cm.select_model()
    assert name == "mid"            # big doesn't fit; mid is the largest that does

def test_none_fits_returns_none(monkeypatch):
    models = [{"name": "big", "size_gb": 19}]
    _setup(monkeypatch, models, {"big": False})
    name, reason = cm.select_model()
    assert name is None and "fit" in reason.lower()

def test_no_backend_returns_none(monkeypatch):
    monkeypatch.setattr(config, "load_config", lambda: {})
    class _None:
        name = "none"
        def present(self): return True
        def models(self): return []
    monkeypatch.setattr(backends, "get_backend", lambda cfg: _None())
    name, reason = cm.select_model()
    assert name is None
