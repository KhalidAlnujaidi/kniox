#!/usr/bin/env python3
"""PreToolUse(Bash): kniox-rtk-gate — encapsulated, policy-owned rtk integration.

kniox owns the policy; rtk is just a subprocess we call. The gate delegates to
`rtk rewrite "<cmd>"` ONLY for a narrow allow-list of high-output / low-density
commands (bulk install/build/sync logs) where a summary genuinely serves an agent.
Everything else — including decision-commands rtk *could* rewrite (git status,
grep, diff) — passes through RAW. That selectivity is the mitigation for rtk
issue #582 (indiscriminate compression inflates agent token use).

Properties (all deliberate):
  - Runs AFTER guard-uv. guard-uv's exit-2 short-circuits the chain, so a blocked
    command never reaches this gate. This hook NEVER exits 2 — it does not block.
  - INERT when rtk is absent: no `KNIOX_RTK_BIN` and no `rtk` on PATH -> passthrough.
    So the framework ships this safely whether or not rtk is installed.
  - Fail-OPEN on every error (bad payload, rtk non-zero, empty rewrite) -> passthrough.

Override the binary for testing with KNIOX_RTK_BIN=/path/to/rtk.
"""
import json, os, re, shutil, subprocess, sys

# kniox allow-list: high-output, low-information-density commands ONLY. Deliberately
# a SUBSET of what rtk can rewrite — git status / grep / diff are intentionally absent
# so the agent keeps their structured output.
ALLOW = [
    r"^npm (install|ci)\b", r"^npm run build\b",
    r"^pnpm install\b", r"^yarn install\b",
    r"^cargo build\b",
    r"^uv (sync|pip install)\b",
    r"^make\b",
]


def _passthrough():
    # Emit nothing; Claude Code then runs the original command unchanged.
    sys.exit(0)


def _rtk_bin():
    bin_ = os.environ.get("KNIOX_RTK_BIN") or shutil.which("rtk")
    return bin_ if bin_ and os.access(bin_, os.X_OK) else None


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        _passthrough()
    cmd = ((data or {}).get("tool_input") or {}).get("command", "") or ""
    if not cmd or not any(re.search(p, cmd) for p in ALLOW):
        _passthrough()                                  # off-list -> raw for the agent

    rtk = _rtk_bin()
    if not rtk:
        _passthrough()                                  # rtk not installed -> inert

    try:
        proc = subprocess.run([rtk, "rewrite", cmd], capture_output=True, text=True, timeout=10)
    except Exception:
        _passthrough()
    if proc.returncode != 0 or not proc.stdout.strip():
        _passthrough()                                  # no rtk equivalent -> raw

    json.dump({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow",
        "permissionDecisionReason": "kniox-rtk-gate: allow-listed high-output command",
        "updatedInput": {"command": proc.stdout.strip()},
    }}, sys.stdout)
    sys.exit(0)


if __name__ == "__main__":
    main()
