#!/usr/bin/env python3
"""kniox setup — detect, record, propose. Assume nothing.

Runs the probe, writes manifest.json, derives a config.json from what was ACTUALLY
found, and reports what's missing. It never installs anything and never assumes a
backend or a cluster: provisioning is only suggested, and the tailnet sweep is opt-in
via --fleet. Re-runnable; existing config decisions are preserved, not clobbered.

  python daemon/setup.py [--fleet] [--no-ssh]
"""
from __future__ import annotations
import argparse, datetime, json

from config import (load_config, save_config, save_manifest,
                    default_config_from_manifest)
import probe


# Suggestions only — printed, never executed. Provisioning stays a human/agent decision.
INSTALL_HINTS = {
    "ollama":   "curl -fsSL https://ollama.com/install.sh | sh   # then: ollama pull <model>",
    "vllm":     "uv add vllm   # then serve: vllm serve <model> (OpenAI API on :8000)",
    "llamacpp": "build llama.cpp and run its server (OpenAI API on :8080)",
}


def run(with_fleet=False, ssh=True):
    manifest = probe.build_manifest(
        datetime.datetime.now().isoformat(timespec="seconds"), with_fleet=with_fleet, ssh=ssh)
    save_manifest(manifest)

    # Merge derived defaults UNDER any existing decisions (don't clobber user choices)
    # — but only when a decision was ACTUALLY made. A stale `null` must never override a
    # freshly detected fact (e.g. a backend installed after the first `kx setup`), or the
    # framework stays permanently blind to it. To disable dispatch deliberately, set
    # backend to "none" (an explicit decision), not null.
    derived = default_config_from_manifest(manifest)
    existing = load_config()
    merged = dict(derived)
    for k, v in existing.items():
        if v is not None:
            merged[k] = v
    save_config(merged)
    return manifest, merged


def report(manifest, config):
    host = manifest["host"]
    print("kniox setup — detected:")
    print(probe._summary(host, indent="  host: "))
    for n in manifest["fleet"]:
        print(probe._summary(n, indent="  peer: "))
    for note in host["notes"]:
        print(f"  note: {note}")

    print("\nconfig:")
    print(f"  backend         = {config.get('backend')}")
    print(f"  vram_budget_gb  = {config.get('vram_budget_gb')}")
    print(f"  task_models     = {config.get('task_models') or '{} (map tasks -> models)'}")

    if not config.get("backend"):
        print("\nno inference backend detected. `dispatch` will report no-backend until you add one.")
        print("options (suggestions only — nothing was installed):")
        for name, hint in INSTALL_HINTS.items():
            print(f"  - {name:8s}: {hint}")
    elif not config.get("task_models"):
        be = config["backend"]
        print(f"\nbackend '{be}' is up but no task->model map is set. Edit daemon/state/config.json, e.g.:")
        print('  "task_models": { "text": "<a-model-you-have>", "vision": "<an-image-model>" }')


def main():
    ap = argparse.ArgumentParser(prog="kniox-setup")
    ap.add_argument("--fleet", action="store_true", help="also probe the tailnet (opt-in)")
    ap.add_argument("--no-ssh", action="store_true", help="fleet: tailscale info only, no SSH")
    a = ap.parse_args()
    manifest, config = run(with_fleet=a.fleet, ssh=not a.no_ssh)
    report(manifest, config)


if __name__ == "__main__":
    main()
