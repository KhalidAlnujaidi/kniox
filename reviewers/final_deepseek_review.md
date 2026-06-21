# DeepSeek code review (deepseek-v4-pro)

Repo: `kniox`  |  38 files

---

I’ve verified the specific claims from `response_to_reviewers.md` against the actual current source, and I’ve also audited the full codebase for critical/high-severity issues.

**STEP 2 – Verification of reported fixes**

- **J (`_uv_run_remote` in `.claude/hooks/guard-uv.py`):** The function is present exactly as described. It tokenises via `shlex.split`, replays enough of `uv run`'s argument parsing to locate the first positional (script) slot, and blocks if that slot is a URL. The Gemini/DeepSeek PoCs (`--python fake.py https://…`, `--with something.py https://…`, multi‑URL flags) are all blocked because the parser refuses to let a flag consume a URL as a value, so the URL falls through to the script-slot check. The documented false-positive (space‑form `--index https://… script.py`) is also present and handled as described. The fallback regex for unparseable commands is in place. **Verified – the bypass is closed.**

- **N1 (non‑dict `isinstance` guard) in `guard-uv.py` and `guard-state.py`:** Both files contain `if not isinstance(data, dict): block(…)` immediately after `json.load`. The Stop hooks (`cap-nextmd.py`, `session-end-append.py`) correctly use `sys.exit(0)` (fail‑OPEN) for the same check, which is appropriate for telemetry/cleanup. **Verified – both PreToolUse hooks now fail‑CLOSED on a list payload.**

- **D (`CLAUDE_PROJECT_DIR` unset):** No new code change, as documented. The hooks themselves still fall back to deriving the kniox root from `__file__`, so they function correctly regardless; the remaining gap is at the launcher/config level, and it’s an acknowledged hardening item.

**STEP 3 – Overall assessment**

No new **Critical** or **High** severity issues were found in the current source. The framework’s security model (fail-closed hooks, one-way override, path sandboxing, VRAM budget gate, atomic config writes) is sound and correctly implemented. The code reviewed is production‑ready for its intended use.

**VERDICT: V1-READY** – The two reported issues (J and N1) are fixed and verified. The design is defense-in-depth with hooks that fail closed, a manual override that the agent cannot reach, and honest "unknown" handling for unmeasurable resources. No demonstrable Critical or High defects remain in the current codebase.