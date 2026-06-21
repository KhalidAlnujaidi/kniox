# kniox Universal Job Broker — Design

_Date: 2026-06-20 · Status: approved design, pending spec review_

## Problem

enigma runs a 4-node k3s cluster (enigma control-plane + node1/2/3 workers). enigma
holds the **only** GPU (RTX A4500 20 GB) and is already at ~71% memory while the three
CPU-only workers (36 vCPU / ~22 GiB combined) sit at ~0%. Today nothing exploits them:
the daemon's `dispatch()` only calls localhost ollama, cron lives separately in `corn/`,
and there is **no cross-session GPU lock** (multiple `kx` sessions can oversubscribe the
A4500). We want the daemon to be the single broker that routes every job by its resource
profile — GPU work serialized on enigma, CPU-eligible work offloaded to idle workers.

See `docs/cluster-status.md` for the recorded cluster snapshot and constraints.

## Goals

- One front door: all jobs flow through the daemon, which decides placement.
- Offload CPU-eligible, self-contained, non-interactive jobs (cron, scripts) to workers
  by default.
- Serialize GPU jobs on enigma behind a real lease/lock (one heavy model at a time).
- Make the routing decision cheap via a declared placement header on each job.
- Degrade honestly: if k3s is unreachable, fall back to local execution with a surfaced note.

## Non-goals

- Multi-GPU scheduling (there is one GPU; revisit only if GPU nodes are added).
- Shared/RWX storage. v1 offloaded jobs are self-contained (network-fetched inputs,
  stdout/exit-code outputs). Jobs needing enigma-local files are pinned to enigma.
- Replacing ollama or the backend abstraction.

## Constraints (from the live cluster)

- **Only `local-path` storage** — no shared filesystem. Offloaded jobs cannot read
  enigma-local paths.
- **~7.4 GiB RAM per worker** — caps per-job memory for offloaded work.
- **All nodes untainted** — without worker-preferring affinity, k8s could place a job on
  enigma; the ClusterExecutor must add anti-affinity to enigma.

## Placement model

Three placements; the classifier resolves every job to exactly one:

| Placement | Where | When |
|---|---|---|
| `enigma-gpu` | enigma, behind GPU lease | needs the A4500 |
| `enigma-local` | enigma, `uv run` subprocess | needs local files / interactive / RAM > worker free |
| `cluster` | k8s Job on a worker | CPU-only, self-contained, modest RAM, non-interactive |

## Component 1 — Placement header pragma (the fast path)

Every Python job/script in the framework starts, **before the imports**, with a single
machine-readable comment declaring its placement. The scheduler parses this from the
first ~20 lines and treats it as authoritative — no inference needed.

```python
# kniox: placement=cluster          # offloadable CPU background work
# kniox: placement=enigma-gpu       # requires the A4500
# kniox: placement=enigma-local     # CPU but needs local files / interactive
# kniox: placement=auto             # let the classifier decide
```

- Optional inline hints: `# kniox: placement=cluster mem=2G task=scrape`.
- Grammar: `# kniox: placement=<enigma-gpu|enigma-local|cluster|auto> [key=value ...]`.
- `auto` (or a missing header) → fall through to Component 2's inference.
- **Safety rule:** if a header says `placement=cluster` but the job also declares
  `local_paths` (or the classifier detects enigma-local deps), the daemon **refuses to
  offload** and surfaces a warning rather than silently running it where it will fail.
- Parser lives in one small module (`placement.py`) so it is unit-testable in isolation
  and shared by the daemon, an optional lint hook, and `kx`.

## Component 2 — Classifier / router (pure function)

`classify(job, cluster_facts) -> Placement`. Precedence:

1. Valid header pragma (non-`auto`) → use it, subject to the safety rule.
2. `needs_gpu` → `enigma-gpu`.
3. `local_paths` non-empty OR `interactive` OR `est_mem_gb` > worker free RAM → `enigma-local`.
4. Else → `cluster`.

Pure and side-effect-free → table-driven unit tests cover every branch.

## Component 3 — Job model

The single descriptor every caller (MCP `dispatch`, future `kx job`, `corn/` cron) submits:

```
Job(task, command, args, env,
    needs_gpu=False, est_mem_gb=None, est_vram_gb=None,
    local_paths=[], interactive=False, schedule=None,
    placement=None)   # parsed from header when the job is a script
```

Defaults are safe: an unknown/under-specified job resolves to `enigma-local`, never
wrongly flung at a worker.

## Component 4 — Executors (one interface, three impls)

- **GPULocalExecutor** — acquire GPU lease → run via existing backend (ollama) → release.
  Wraps today's `dispatch()`; this is where the cross-session VRAM lock finally lives.
- **LocalExecutor** — `uv run` subprocess on enigma; captures stdout/exit.
- **ClusterExecutor** — render a k8s Job: worker-preferring nodeAffinity + anti-affinity
  to enigma, resource requests from hints, command. Submit, wait, capture stdout + exit
  code, then delete the Job. v1 uses a stock `python:3.x-slim` image for trivial
  self-contained jobs (no registry needed).

## Component 5 — GPU lease

A `gpu_lease` row in the existing SQLite DB: `(holder, task, acquired_at, ttl)`.
Acquire = transactional check-and-set (grant only if no active, non-expired lease);
concurrent `kx` sessions poll/block until free. **TTL** prevents a dead holder from
deadlocking the GPU. Converts "one heavy model at a time" from discipline to enforcement.

## Component 6 — Cluster-aware probe

Extend `probe.py` so `kx setup` records k3s node capacity (`kubectl get nodes`: CPU,
memory, GPU, Ready) into `manifest.json` as the worker-pool facts, replacing the broken
Tailscale-SSH fleet section. Makes "detect, never assume" actually true for the cluster.

## Data flow

```
caller → daemon.submit(Job)
       → placement.parse_header (if script)  [fast path]
       → classify(job, facts)
       → executor[placement].run(job)
       → {stdout, exit_code, placement, node, vram_note?}
```

## Error handling (honest degradation)

- k3s unreachable / no kubeconfig → `cluster` jobs fall back to `enigma-local` + surfaced note.
- image-pull / job failure → return error with captured logs.
- worker `OOMKilled` → detect, surface, suggest enigma-pin / higher mem hint.
- GPU lease busy → wait with a caveat; lease TTL bounds worst case.

## Testing

- `placement.py`: parser unit tests (valid, malformed, hints, missing).
- `classify`: table-driven tests for every precedence branch incl. the safety rule.
- GPU lease: parallel-acquire concurrency test (only one holder; expiry releases).
- ClusterExecutor: real-cluster integration test — submit an `echo` Job, assert it lands
  on a worker (not enigma), capture stdout.
- Fallback test: kubeconfig absent → `cluster` resolves to `enigma-local`.

## Phasing

- **Phase 1 (shippable):** `placement.py` + classifier + Job model + Local/Cluster/GPU
  executors (stock image, trivial jobs) + GPU lease + k3s-aware manifest + alignment-doc
  update (offload-first policy + the placement-header convention).
- **Phase 2:** `kniox-runner` image (uv + git + ffmpeg) + local registry; `corn/` cron →
  k8s `CronJob`; MCP/`kx` surface polish; optional lint hook that flags
  framework Python files missing a `# kniox: placement=` header.

## Alignment changes

`alignment/PROJECT-ALIGNMENT-REQUIREMENT.md` gains an **Offload-first routing** section:
the daemon is the single broker; CPU-eligible/self-contained jobs prefer workers; GPU and
enigma-local jobs stay home; **every job/script must carry a `# kniox: placement=` header.**
Also reconcile the `project-alignment` skill (still pointing at the stale Desktop doc) so
it and the repo contract agree.

## Open items folded into the plan, not blocking

- Registry choice for the custom runner image (Phase 2): k3s local registry vs ghcr.
- Whether the placement-header lint is advisory (warn) or enforced (block) — start advisory.
