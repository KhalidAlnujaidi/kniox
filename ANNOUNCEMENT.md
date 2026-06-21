# kniox — your AI coding agent is the guest, not the host

**Show HN / launch post**

Most AI dev tooling puts the agent in charge of your environment and hopes for the best.
**kniox flips that.** Claude Code is the *guest*; kniox is the governed world it runs in — a
self-describing operating environment with laws, a census of its own hardware, and a
quartermaster that rations GPU memory.

Four independent layers, each enforcing even if the one above it is bypassed:

1. **`kx` launcher** — injects the constitution + the project's working memory before every
   session, and only grants full autonomy *inside* the kniox tree.
2. **`CLAUDE.md`** — the always-on floor; loads no matter how the agent starts.
3. **Fail-closed hooks** — Python/shell guards that fire *even under
   `--dangerously-skip-permissions`*. They block `pip`/`conda`/remote-exec, protect the
   framework's own rules from agent edits, and hard-cap context. The agent **cannot disable its
   own guards** — the override is structurally unreachable from its subshell.
4. **Daemon broker** — a VRAM gate plus a `dispatch` MCP tool that routes specialized jobs
   (vision, image, batch) to local models. "One model per task" is enforced, not hoped.

**Detect, never assume.** Zero baked-in GPU sizes or model rosters. A probe writes a manifest of
your actual machine; everything downstream reads facts, not guesses. Unmeasurable resources are
recorded as `null` with a note — never a convenient zero. (The bug that birthed the project: an
old broker read "0 GB used" on any non-NVIDIA box and approved every load.)

**Opt-in tailnet fleet.** If you run Tailscale, `kx setup --fleet` enumerates peers and
SSH-probes their real specs, turning a personal cluster into a brokered resource pool. No
cluster? kniox stays a clean single-machine tool.

It's defense-in-depth for autonomous agents: real freedom inside hard, self-protecting laws.

- **License:** MIT
- **Status:** v1.0.0 — certified V1-READY by an adversarial dual-model review (DeepSeek + Gemini),
  whose scripts and reconciled findings ship in [`reviewers/`](reviewers/).
- **Install (Linux/macOS):**
  ```bash
  curl -fsSL https://raw.githubusercontent.com/KhalidAlnujaidi/kniox/main/install.sh | bash
  ```
- **Repo:** https://github.com/KhalidAlnujaidi/kniox
