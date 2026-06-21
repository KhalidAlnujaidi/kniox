#!/usr/bin/env python3
"""kniox shared paths + generated-artifact I/O.

Two generated files live under daemon/state/ (gitignored):
  manifest.json — detected FACTS (hardware, backends, fleet). Written by the probe.
  config.json   — DECISIONS (chosen backend, task->model map, VRAM budget). Written by
                  setup; hand-editable.

Nothing here assumes any hardware or any backend. Missing files yield empty/derived
defaults, so a fresh checkout works before setup has ever run.
"""
from __future__ import annotations
import json, os
from pathlib import Path

KNIOX_HOME    = Path(__file__).resolve().parent.parent
STATE_DIR     = Path(os.environ.get("KNIOX_STATE_DIR", KNIOX_HOME / "daemon" / "state"))
MANIFEST_PATH = STATE_DIR / "manifest.json"
CONFIG_PATH   = STATE_DIR / "config.json"
DB_PATH       = STATE_DIR / "kniox.db"


def _read_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write_json(path, data):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(path) + ".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)            # atomic; never leaves a half-written manifest
    return path


def load_manifest():        return _read_json(MANIFEST_PATH)
def save_manifest(m):       return _write_json(MANIFEST_PATH, m)
def load_config():          return _read_json(CONFIG_PATH) or {}
def save_config(c):         return _write_json(CONFIG_PATH, c)


# ---- derived defaults (no hardcoded hardware) -------------------------------
def default_config_from_manifest(manifest):
    """Propose a config from detected facts. Never invents capacity it can't see:
    no backend present -> backend stays None; no VRAM measured -> budget stays None."""
    host = (manifest or {}).get("host") or {}
    vram = host.get("vram_total_gb")
    present = [b for b in host.get("backends", []) if b.get("present")]
    return {
        "backend": present[0]["name"] if present else None,
        "endpoint": present[0].get("endpoint") if present else None,
        "vram_budget_gb": (round(vram * 0.9, 1) if vram else None),
        "vram_budget_fraction": 0.9,
        "task_models": {},          # empty = derive from backend / pass explicit model
        "model_vram_gb": {},        # optional manual overrides for unmeasurable backends
    }


def vram_budget(config, manifest):
    """Budget precedence: env override -> explicit config -> fraction of detected VRAM
    -> None (honest unknown). Returning None is correct: it makes can_load report
    'unknown' instead of fabricating headroom."""
    env = os.environ.get("KNIOX_VRAM_BUDGET_GB")
    if env:
        try:
            return float(env)
        except ValueError:
            pass
    if config.get("vram_budget_gb") is not None:
        return config["vram_budget_gb"]
    host = (manifest or {}).get("host") or {}
    vram = host.get("vram_total_gb")
    frac = config.get("vram_budget_fraction", 0.9)
    return round(vram * frac, 1) if vram else None
