import daemon as registry
import lease

class _FakeBackend:
    name = "ollama"
    def present(self): return True
    def generate(self, model, prompt): return "GENERATED"

def _setup(monkeypatch, acquire_result):
    monkeypatch.setattr(registry, "load_config",
                        lambda: {"backend": "ollama", "task_models": {"text": "m"}})
    monkeypatch.setattr(registry, "get_backend", lambda cfg: _FakeBackend())
    monkeypatch.setattr(registry, "can_load", lambda model: {"ok": True})
    monkeypatch.setattr(lease, "acquire_gpu", lambda *a, **k: acquire_result)
    released = {}
    monkeypatch.setattr(lease, "release_gpu", lambda holder: released.__setitem__("held", holder))
    return released

def test_dispatch_gpu_busy_returns_honest_error(monkeypatch):
    _setup(monkeypatch, acquire_result=False)
    out = registry.dispatch("text", "hi")
    assert "busy" in (out.get("error") or "").lower()
    assert "response" not in out   # generate was NOT called

def test_dispatch_acquires_and_releases_on_success(monkeypatch):
    released = _setup(monkeypatch, acquire_result=True)
    out = registry.dispatch("text", "hi")
    assert out.get("response") == "GENERATED"
    assert released.get("held") == "dispatch:text"   # lease released
