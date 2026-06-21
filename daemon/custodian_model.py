"""Pick the report model at runtime — the largest backend model that fits the VRAM budget.
No hardcoded model names (alignment rule). Honest: returns (None, reason) when nothing fits."""
from __future__ import annotations
import config
import backends


def select_model(config_arg: dict | None = None):
    import daemon as registry
    cfg = config_arg if config_arg is not None else config.load_config()
    backend = backends.get_backend(cfg)
    if backend.name == "none" or not backend.present():
        return None, "no inference backend available"
    sized = [m for m in backend.models() if m.get("size_gb")]
    if not sized:
        return None, "backend reports no models with known sizes"
    unknown = []
    for m in sorted(sized, key=lambda x: x["size_gb"], reverse=True):
        ok = registry.can_load(m["name"]).get("ok")
        if ok is True:
            return m["name"], f"largest model fitting the VRAM budget ({m['size_gb']} GB)"
        if ok is None:
            unknown.append(m)
    if unknown:
        m = unknown[0]
        return m["name"], f"largest model; VRAM fit unverified ({m['size_gb']} GB)"
    return None, "no model fits the VRAM budget"
