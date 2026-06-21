# kniox compute cluster — status snapshot

_Recorded 2026-06-20. Source: `KUBECONFIG=/etc/rancher/k3s/k3s.yaml kubectl` on enigma._
_This is a hand-recorded snapshot; the probe (`kx setup`) is not yet k3s-aware (see ROADMAP / framework work)._

## Cluster
- **Orchestrator:** k3s v1.35.5+k3s1 (single control-plane, embedded).
- **Network:** LAN `192.168.0.0/24`; pod CIDR `10.42.0.0/16`; nodes also on Tailscale.
- **Storage:** `local-path` (default, `rancher.io/local-path`) ONLY — node-local, `WaitForFirstConsumer`. **No shared/RWX storage.** A pod's data does not follow it across nodes.
- **Scheduling:** no taints on any node — all schedulable (so without nodeSelector/affinity, k8s may place work on enigma; real offload needs a worker-preferring affinity).

## Nodes
| Node | Role | CPU | RAM | GPU | Kernel | Live load |
|---|---|---|---|---|---|---|
| **enigma** | control-plane | 16 | ~60 GiB | **RTX A4500 20 GB** | 6.17 | 10% CPU / 71% mem (~44 GiB used) |
| node1 | worker | 12 | ~7.4 GiB | none | 6.8 | ~0% CPU / 6% mem (idle) |
| node2 | worker | 12 | ~7.4 GiB | none | 6.8 | ~0% CPU / 6% mem (idle) |
| node3 | worker | 12 | ~7.4 GiB | none | 6.8 | ~0% CPU / 6% mem (idle) |

## What this means
- **One GPU in the whole cluster** (enigma's A4500). Heavy model inference has exactly one home; the cluster is not a GPU pool.
- **Idle CPU pool:** node1–3 = **36 vCPU / ~22 GiB RAM combined, sitting at ~0%.** Ideal for CPU-only batch, cron, scripts.
- **Hard constraints on offload:** (1) ~7.4 GiB RAM/worker caps per-job memory; (2) no shared storage — offloaded jobs must be self-contained (bundle data, or reach it over the network), not assume enigma-local files.
