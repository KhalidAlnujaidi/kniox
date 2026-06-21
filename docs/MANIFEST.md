# Capability manifest & config — the single source of truth

kniox makes **zero hardware or backend assumptions**. Everything the broker needs is
*detected* and written to two generated files under `daemon/state/` (gitignored):

| File | Holds | Written by | Hand-editable |
|---|---|---|---|
| `manifest.json` | detected **facts** — hardware, accelerators, backends, tailnet fleet | `daemon/probe.py` (via `kx setup`) | regenerated, don't edit |
| `config.json`   | **decisions** — chosen backend, task→model map, VRAM budget | `kx setup` derives; you refine | yes |

Run `kx setup` to (re)generate both. `kx setup --fleet` also sweeps the tailnet.
Re-running preserves your `config.json` decisions and only refreshes the facts.

## The honesty rule

Every measured field is best-effort. **What can't be measured is `null` with a note —
never a fabricated zero.** This is the core fix over the original broker, which read
`0 GB used` on any non-NVIDIA box and "approved" every load. Now unmeasured → unknown →
the broker says so (`can_load.ok = null`), and dispatch proceeds only with a surfaced
caveat, while *over budget* (`ok = false`) remains the one hard stop.

## manifest.json

```jsonc
{
  "schema_version": 1,
  "generated_at": "2026-06-20T17:40:00",
  "generated_by": "kniox-probe",
  "host": {                       // the machine kniox is installed on (a "node")
    "hostname": "workstation",
    "is_self": true,
    "reachable": true,
    "access": "local",            // local | ssh | tailscale-info
    "os": "linux",                // linux | darwin | ...
    "arch": "x86_64",
    "cpu":    { "model": "...", "physical_cores": 16, "logical_cores": 32 },
    "memory": { "total_gb": 64.0, "available_gb": 51.2 },
    "accelerators": [             // [] if none; per-card vram null when unmeasurable
      { "vendor": "nvidia", "name": "RTX A4500",
        "vram_total_gb": 20.0, "vram_used_gb": 1.2, "util_percent": 3 }
    ],
    "vram_total_gb": 20.0,        // sum of measurable cards; null if none measurable
    "backends": [                 // every known backend, present:true only if reachable
      { "name": "ollama", "present": true, "version": "0.x",
        "endpoint": "http://localhost:11434", "binary": true,
        "models": [ { "name": "gemma3:27b", "size_gb": 17.4 } ] },
      { "name": "vllm",     "present": false, "endpoint": null, "binary": false, "models": [] },
      { "name": "llamacpp", "present": false, "endpoint": null, "binary": false, "models": [] }
    ],
    "notes": [ "..." ]            // why anything is null / what was skipped
  },
  "fleet": [ /* zero or more nodes, same shape as host, is_self:false */ ]
}
```

**Node shape is uniform.** A fleet peer is just another node. SSH-probed peers carry
full specs (`access: "ssh"`); peers we could only see via tailscale carry
`access: "tailscale-info"` and null specs — so the inventory never claims detail it
didn't measure.

## config.json

```jsonc
{
  "backend": "ollama",            // null until a backend exists; "none" => dispatch errors honestly
  "endpoint": "http://localhost:11434",
  "vram_budget_gb": 18.0,         // null = derive from manifest; env KNIOX_VRAM_BUDGET_GB overrides
  "vram_budget_fraction": 0.9,    // used when vram_budget_gb is null and VRAM was measured
  "task_models": {                // map your task names to models the backend actually has
    "text": "gemma3:27b",
    "vision": "qwen2.5vl"
  },
  "model_vram_gb": {}             // optional manual size hints for backends that don't report size
}
```

## Who reads what

- `daemon/daemon.py` → `vram_snapshot` (live accelerator read) + `can_load` + `dispatch`
  read `config.json` for decisions and re-probe live accelerators for current usage.
- `daemon/backends.py` → resolves `config.backend` to an implementation.
- MCP tools `get_manifest` / `refresh_manifest` / `vram_snapshot` / `can_load` /
  `dispatch` expose all of this to the agent.
