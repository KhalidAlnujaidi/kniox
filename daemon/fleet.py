#!/usr/bin/env python3
"""Optional tailnet fleet discovery.

If tailscale isn't installed, this is a no-op and kniox stays a clean single-machine
tool — the cluster is one user's situation, never a requirement. When tailscale IS
present, enumerate peers and best-effort profile each:

  1. SSH the probe over the tailnet and run it remotely -> real CPU/GPU/RAM specs.
  2. If SSH isn't available, fall back to whatever `tailscale status` itself reports
     (hostname / OS / online).

Per-node `access` records which path produced the data, so the inventory never claims
detail it didn't actually measure. Never required, never fatal.
"""
from __future__ import annotations
import json, os, shutil, subprocess


def _tailscale_status():
    if not shutil.which("tailscale"):
        return None
    try:
        out = subprocess.check_output(["tailscale", "status", "--json"], text=True, timeout=8)
        return json.loads(out)
    except Exception:
        return None


def _ssh_probe(host, probe_src):
    """Pipe probe.py to the remote python3 and run `probe host`. BatchMode means it
    fails fast (returns None) when keys/SSH aren't set up, rather than hanging."""
    try:
        out = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=6",
             "-o", "StrictHostKeyChecking=accept-new", host, "python3 - host"],
            input=probe_src, text=True, capture_output=True, timeout=25)
        if out.returncode != 0 or not out.stdout.strip():
            return None
        return json.loads(out.stdout)
    except Exception:
        return None


def probe_fleet(ssh=True):
    # No self_hostname needed: `tailscale status` reports this machine under "Self",
    # not "Peer", so iterating Peer already excludes us.
    status = _tailscale_status()
    if not status:
        return []
    probe_src = None
    src_path = os.path.join(os.path.dirname(__file__), "probe.py")
    try:
        with open(src_path) as f:
            probe_src = f.read()
    except Exception:
        ssh = False

    nodes = []
    for peer in (status.get("Peer") or {}).values():
        host = (peer.get("DNSName") or "").rstrip(".") or peer.get("HostName")
        online = bool(peer.get("Online"))
        if ssh and online and host and probe_src:
            remote = _ssh_probe(host, probe_src)
            if remote:
                remote.update({"is_self": False, "access": "ssh", "reachable": True,
                               "tailscale_ips": peer.get("TailscaleIPs", [])})
                nodes.append(remote)
                continue
        # fallback: only what tailscale itself can tell us
        nodes.append({
            "hostname": peer.get("HostName"), "dns": host, "is_self": False,
            "reachable": online, "online": online, "access": "tailscale-info",
            "os": peer.get("OS"), "arch": None, "cpu": None, "memory": None,
            "accelerators": [], "vram_total_gb": None, "backends": [],
            "tailscale_ips": peer.get("TailscaleIPs", []),
            "notes": ["ssh probe unavailable; tailscale-reported info only"],
        })
    return nodes


if __name__ == "__main__":
    print(json.dumps(probe_fleet(), indent=2))
