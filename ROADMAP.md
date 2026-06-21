# kniox roadmap

Post-v1 design proposals. These are **open for collaborators** — each is a direction with a
sketch, not a finished spec. Comment on the linked issues with approaches, objections, or PRs.

Both items extend kniox's existing thesis rather than fight it: governance lives in hooks and the
daemon, hardware is **detected never assumed**, and failures are **honest**.

---

## 1. Conversation corpus — capture every session as training/eval data

**Goal.** Every Claude Code session that runs inside kniox — start to end, every turn — is recorded
into an append-only corpus on the framework, so the whole body of work becomes a reusable dataset
for fine-tuning, evals, or distillation into the local model (see item 2).

**Why it fits kniox.** The Stop-hook lane already exists: `session-end-append.py` writes a
timestamp to each project's `logs/sessions.log`. Claude Code hands every Stop hook a payload that
includes `transcript_path` — the full session JSONL. We already log *that* a session happened; this
captures *what* happened.

**Sketch.**
- New Stop / SubagentStop hook `.claude/hooks/corpus-capture.py`:
  - Reads `transcript_path` from the hook payload, normalizes the transcript into one structured
    record (project, model, timestamps, turn count, token usage, tool calls, final state).
  - Appends to an append-only store — e.g. `corpus/sessions.jsonl` (one record per session) plus
    raw transcripts under `corpus/raw/`.
- **Fail honest.** Record what's measurable; mark the rest `null` with a note. Never fabricate a
  field to make a record look complete.
- **Secret hygiene is mandatory.** This data may be used for training, so the capture step must
  scrub credentials before write (reuse the secret patterns the `guard-uv.py` hook already knows).
- **Consent + control.** Default behavior and an off-switch (`KNIOX_NO_CORPUS=1` in the launching
  shell, same one-way model as `KNIOX_BYPASS_HOOKS`). The corpus is **gitignored** — it is private,
  large, and per-machine; it never gets committed.
- Optional: a `kx corpus` verb (count, size, export, redact-audit) and a daemon endpoint so the
  fine-tuning loop in item 2 can consume it.

**Open questions for collaborators.**
- Record granularity: per-session vs per-turn vs both?
- Redaction strength — how aggressive before the data loses training value?
- Schema: what makes a session row useful as SFT / preference / eval data?

→ tracked in **issue #1**.

---

## 2. Mandatory local-LLM offload for "manual labor" coding

**Goal.** If a local LLM is available, then **mechanical coding labor is forced onto the local
model** — not the cloud agent. Claude stays the architect/reviewer; the hardware does the grunt
work it's capable of.

**Why it fits kniox.** The daemon already detects backends and models into
`daemon/state/manifest.json`, brokers VRAM, and exposes the `dispatch` MCP tool. Today `dispatch`
routes *specialized* jobs (vision, image, batch) to local models while the agent's brain stays
Claude (`docs/OVERVIEW.md`). This item adds **a policy layer on top of that same machinery**: when a
capable coding model is detected, certain task classes *must* go through dispatch to it.

**Sketch.**
- **Capability gate (detect, don't assume).** The daemon flags `local_coding_capable: true` in the
  manifest when a usable local LLM is actually present (a backend is up and a coding-capable model
  is available) — no hardcoded parameter count. No local LLM detected → the policy is silently
  inert; kniox stays cloud-only.
- **Policy enforcement, fail-closed.** When the gate is on, a hook + a `CLAUDE.md` non-negotiable
  steer "labor-class" work to the local model via dispatch — and block the cloud agent from doing
  it by hand. Same escape hatch as the rest of the rails (`KNIOX_BYPASS_HOOKS=1`, set only in the
  launching shell — the agent can't lift its own restriction).
- **Respect the broker.** Offloaded jobs go through the existing VRAM gate and "one specialized
  model per task" rule. No co-loading past budget.

**Open questions for collaborators (the hard part).**
- **Defining "manual labor."** Where's the line between mechanical labor (boilerplate, scaffolding,
  formatting, test stubs, repetitive refactors) and reasoning that should stay with Claude? This
  classification is the crux and the most valuable thing to get right.
- Should *any* available local LLM trigger offload, or only some? If gated, what signal decides
  "good enough" — without hardcoding a parameter count?
- Enforcement strength: hard block vs strong nudge vs advisory, and how local results flow back
  into the session cleanly.

→ tracked in **issue #2**.

---

## 3. Terse by default — execution over explanation

**Goal.** Inside a kx environment, agents spend tokens on *doing*, not narrating. What reaches the
end user is concise, plain, and minimal: the result and the next step, not a lecture.

**The principle.**
- Prioritize execution over explanation. Fewer output tokens, more done.
- User-facing text is short, descriptive, minimalistic — plain language over technical jargon.
- Recommending a tool or library is welcome: **name it, skip the essay.** No detail on frameworks
  or languages unless the user asks.
- Verbosity is opt-in — the user can always ask for more.

**Why it fits kniox.** This is a behavioral floor, so it belongs where the other always-on rules
live: state it as a non-negotiable in `CLAUDE.md` / the alignment contract (loads no matter how the
agent starts), optionally reinforced by a lightweight reminder in the `kx` pre-context.

---

## Contributing

These are deliberately under-specified — the design is the work. Pick an open question, open a PR or
comment on the issue, and keep changes inside kniox's grain: enforce in hooks/daemon, detect never
assume, fail honest and fail closed. See [`CONTRIBUTING.md`](CONTRIBUTING.md).
