#!/usr/bin/env python3
"""kniox capability probe — detect, never assume.

Pure stdlib so it runs on a bare box before any `uv sync`, and so it can be piped over
SSH to profile a remote node. Every measurement is best-effort: what can't be measured
is recorded as null with a note in `notes`, NEVER as a fabricated zero. That honesty is
the whole point — the old broker read 0 used VRAM on any non-NVIDIA box and "approved"
every load. Here, unmeasured means unknown means the broker says so.

  probe.py host              # print THIS machine's node JSON (used for remote SSH probing)
  probe.py write [--fleet]   # write manifest.json (host + optional tailnet fleet)
"""
from __future__ import annotations
import argparse, json, os, platform, shutil, subprocess, sys, urllib.request
import cluster

SCHEMA_VERSION = 1


def _run(cmd, timeout=6):
    try:
        return subprocess.check_output(cmd, text=True, timeout=timeout,
                                       stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None


def _read(path):
    try:
        with open(path) as f:
            return f.read()
    except Exception:
        return None


def _http_json(url, timeout=3):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:
        return None


# ---- CPU / memory -----------------------------------------------------------
def probe_cpu(notes):
    system = platform.system()
    model, phys, logical = None, None, os.cpu_count()
    if system == "Linux":
        ls = _run(["lscpu"])
        if ls:
            d = {k.strip(): v.strip() for k, v in
                 (l.split(":", 1) for l in ls.splitlines() if ":" in l)}
            model = d.get("Model name")
            try:
                sockets = int(d.get("Socket(s)", "1"))
                per = int(d.get("Core(s) per socket", "0"))
                phys = sockets * per or None
            except ValueError:
                pass
        if model is None:
            for line in (_read("/proc/cpuinfo") or "").splitlines():
                if line.lower().startswith("model name"):
                    model = line.split(":", 1)[1].strip()
                    break
    elif system == "Darwin":
        model = _run(["sysctl", "-n", "machdep.cpu.brand_string"])
        p = _run(["sysctl", "-n", "hw.physicalcpu"])
        phys = int(p) if p and p.isdigit() else None
    if model is None:
        notes.append("cpu model unmeasured")
    return {"model": model, "physical_cores": phys, "logical_cores": logical}


def probe_memory(notes):
    system = platform.system()
    total = avail = None
    if system == "Linux":
        kv = {}
        for line in (_read("/proc/meminfo") or "").splitlines():
            parts = line.split(":")
            if len(parts) == 2:
                kv[parts[0].strip()] = parts[1].strip()

        def gb(key):
            v = kv.get(key)
            try:
                return round(int(v.split()[0]) / 1024 / 1024, 1) if v else None  # kB -> GB
            except (ValueError, IndexError):
                return None
        total, avail = gb("MemTotal"), gb("MemAvailable")
    elif system == "Darwin":
        t = _run(["sysctl", "-n", "hw.memsize"])
        total = round(int(t) / 1e9, 1) if t and t.isdigit() else None
    if total is None:
        notes.append("memory total unmeasured")
    return {"total_gb": total, "available_gb": avail}


# ---- accelerators (the honest one) ------------------------------------------
def probe_accelerators(notes):
    """Try NVIDIA, then AMD ROCm, then Apple Silicon. Anything unmeasured is null."""
    accels = []
    if shutil.which("nvidia-smi"):
        out = _run(["nvidia-smi",
                    "--query-gpu=name,memory.total,memory.used,utilization.gpu",
                    "--format=csv,noheader,nounits"])
        if out:
            def _gb(v):   # MiB -> GB; null (not dropped) when a field is unparseable
                try:
                    return round(int(v) / 1024, 1)
                except (ValueError, TypeError):
                    return None

            def _int(v):
                try:
                    return int(v)
                except (ValueError, TypeError):
                    return None
            for line in out.splitlines():
                parts = [x.strip() for x in line.split(",")]
                if len(parts) != 4:
                    continue
                name, mt, mu, util = parts
                # Parse each field independently: a driver that reports "[Not Supported]"
                # for utilization (MIG / WSL / some drivers) must NOT make the whole GPU
                # vanish — that would be a fabricated absence, the exact lie we forbid.
                accels.append({"vendor": "nvidia", "name": name,
                               "vram_total_gb": _gb(mt), "vram_used_gb": _gb(mu),
                               "util_percent": _int(util)})
            if not any(a["vendor"] == "nvidia" for a in accels):
                notes.append("nvidia-smi present but no GPU rows parsed")
        else:
            notes.append("nvidia-smi present but returned no data")
    elif shutil.which("rocm-smi"):
        # rocm-smi JSON shape is version-dependent; capture what we can, stay honest.
        raw = _run(["rocm-smi", "--showmeminfo", "vram", "--json"])
        parsed = False
        if raw:
            try:
                data = json.loads(raw)
                for card, vals in data.items():
                    tot = next((v for k, v in vals.items() if "total" in k.lower()), None)
                    use = next((v for k, v in vals.items() if "used" in k.lower()), None)
                    accels.append({"vendor": "amd", "name": card,
                                   "vram_total_gb": round(int(tot) / 1e9, 1) if tot else None,
                                   "vram_used_gb": round(int(use) / 1e9, 1) if use else None,
                                   "util_percent": None})
                    parsed = True
            except (ValueError, AttributeError):
                pass
        if not parsed:
            accels.append({"vendor": "amd", "name": "ROCm device", "vram_total_gb": None,
                           "vram_used_gb": None, "util_percent": None})
            notes.append("rocm-smi present but VRAM not parseable on this version")
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        chip = _run(["sysctl", "-n", "machdep.cpu.brand_string"]) or "Apple Silicon"
        accels.append({"vendor": "apple", "name": chip, "vram_total_gb": None,
                       "vram_used_gb": None, "util_percent": None,
                       "note": "unified memory; VRAM shares system RAM (no dedicated total)"})
    if not accels:
        notes.append("no GPU accelerator detected (nvidia-smi / rocm-smi absent)")
    return accels


# ---- inference backends -----------------------------------------------------
def _probe_ollama():
    endpoint = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    ver = _http_json(f"{endpoint}/api/version")
    tags = _http_json(f"{endpoint}/api/tags")
    present = ver is not None or tags is not None
    models = [{"name": m.get("name"),
               "size_gb": round(m.get("size", 0) / 1e9, 2) if m.get("size") else None}
              for m in (tags or {}).get("models", [])]
    return {"name": "ollama", "present": present,
            "version": (ver or {}).get("version"),
            "endpoint": endpoint if present else None,
            "binary": shutil.which("ollama") is not None,
            "models": models}


def _probe_openai_compatible(name, endpoint):
    data = _http_json(f"{endpoint}/v1/models")
    present = data is not None
    models = [{"name": m.get("id")} for m in (data or {}).get("data", [])]
    return {"name": name, "present": present,
            "endpoint": endpoint if present else None,
            "binary": shutil.which(name) is not None,
            "models": models}


def probe_backends(notes):
    backends = [
        _probe_ollama(),
        _probe_openai_compatible("vllm", os.environ.get("VLLM_ENDPOINT", "http://localhost:8000")),
        _probe_openai_compatible("llamacpp", os.environ.get("LLAMACPP_ENDPOINT", "http://localhost:8080")),
        _probe_openai_compatible("lmstudio", os.environ.get("LMSTUDIO_ENDPOINT", "http://localhost:1234")),
    ]
    if not any(b["present"] for b in backends):
        notes.append("no inference backend reachable (ollama / vllm / llamacpp / lmstudio)")
    return backends


# ---- assembly ---------------------------------------------------------------
def probe_host(is_self=True):
    notes = []
    accels = probe_accelerators(notes)
    measured = [a["vram_total_gb"] for a in accels if a.get("vram_total_gb")]
    return {
        "hostname": platform.node() or None,
        "is_self": is_self,
        "reachable": True,
        "access": "local",
        "os": platform.system().lower(),
        "arch": platform.machine(),
        "cpu": probe_cpu(notes),
        "memory": probe_memory(notes),
        "accelerators": accels,
        "vram_total_gb": round(sum(measured), 1) if measured else None,
        "backends": probe_backends(notes),
        "notes": notes,
    }


def build_manifest(generated_at, with_fleet=False, ssh=True):
    host = probe_host(is_self=True)
    fleet = []
    if with_fleet:
        try:
            import fleet as fleet_mod
            fleet = fleet_mod.probe_fleet(ssh=ssh)
        except Exception as e:
            host["notes"].append(f"fleet probe skipped: {e}")
    manifest = {"schema_version": SCHEMA_VERSION, "generated_at": generated_at,
                "generated_by": "kniox-probe", "host": host, "fleet": fleet}
    manifest["cluster"] = cluster.cluster_facts()
    return manifest


def _summary(node, indent="  "):
    a = node.get("accelerators") or []
    gpu = ", ".join(f"{x.get('name')} ({x.get('vram_total_gb') or '?'}GB)" for x in a) or "none"
    be = ", ".join(b["name"] for b in node.get("backends", []) if b.get("present")) or "none"
    mem = (node.get("memory") or {}).get("total_gb")
    return (f"{indent}{node.get('hostname')} [{node.get('os')}/{node.get('arch')}] "
            f"cpu={ (node.get('cpu') or {}).get('physical_cores') }c mem={mem}GB "
            f"gpu={gpu} backends={be} access={node.get('access')}")


def main():
    import datetime
    ap = argparse.ArgumentParser(prog="kniox-probe")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("host")
    w = sub.add_parser("write")
    w.add_argument("--fleet", action="store_true")
    a = ap.parse_args()

    if a.cmd == "host":
        print(json.dumps(probe_host(), indent=2))
        return
    # write
    from config import save_manifest, default_config_from_manifest
    m = build_manifest(datetime.datetime.now().isoformat(timespec="seconds"), with_fleet=a.fleet)
    path = save_manifest(m)
    print(f"wrote {path}")
    print(_summary(m["host"], indent="  host: "))
    for n in m["fleet"]:
        print(_summary(n, indent="  peer: "))
    for note in m["host"]["notes"]:
        print(f"  note: {note}")


if __name__ == "__main__":
    main()
