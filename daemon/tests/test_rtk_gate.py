# kniox: placement=cluster
"""Framework contract for the encapsulated rtk gate (.claude/hooks/rtk-gate.py).

kniox owns the policy: the gate delegates to `rtk rewrite` ONLY for a narrow
high-output allow-list, passes everything else through RAW (the #582 mitigation),
is INERT when rtk is not installed, and NEVER blocks (exit-2 is guard-uv's job).
"""
import json, os, subprocess, sys, stat
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GATE = REPO / ".claude" / "hooks" / "rtk-gate.py"
GUARD = REPO / ".claude" / "hooks" / "guard-uv.py"


def _payload(command):
    return json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})


def _run(script, command, env_extra=None):
    env = {**os.environ}
    if env_extra:
        env.update(env_extra)
    return subprocess.run([sys.executable, str(script)],
                          input=_payload(command), capture_output=True, text=True, env=env)


def _fake_rtk(tmp_path):
    """A stand-in `rtk` binary implementing `rtk rewrite "<cmd>"`."""
    p = tmp_path / "rtk"
    p.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "KNOWN={'git','ls','grep','npm','cargo','uv','pnpm','yarn','pip','pytest'}\n"
        "if len(sys.argv)>=3 and sys.argv[1]=='rewrite':\n"
        "    cmd=sys.argv[2]; base=cmd.split()[0] if cmd.split() else ''\n"
        "    if base in KNOWN: sys.stdout.write('rtk '+cmd); sys.exit(0)\n"
        "    sys.exit(1)\n"
        "sys.exit(1)\n"
    )
    p.chmod(p.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return str(p)


def _rewritten(stdout):
    if not stdout.strip():
        return None
    out = json.loads(stdout)
    return (out.get("hookSpecificOutput") or {}).get("updatedInput", {}).get("command")


# --- #582 mitigation: rtk-rewritable but OFF the list → stays raw -----------
def test_off_list_passes_through_raw_even_with_rtk(tmp_path):
    r = _run(GATE, "git status", {"KNIOX_RTK_BIN": _fake_rtk(tmp_path)})
    assert r.returncode == 0
    assert _rewritten(r.stdout) is None  # gate left the decision-command raw


# --- on the allow-list + rtk present → rewritten via updatedInput ----------
def test_on_list_rewritten_when_rtk_present(tmp_path):
    r = _run(GATE, "npm install", {"KNIOX_RTK_BIN": _fake_rtk(tmp_path)})
    assert r.returncode == 0
    assert _rewritten(r.stdout) == "rtk npm install"


# --- inert when rtk is not installed → passthrough -------------------------
def test_inert_when_rtk_absent():
    r = _run(GATE, "npm install", {"KNIOX_RTK_BIN": "/nonexistent/rtk", "PATH": "/nonexistent"})
    assert r.returncode == 0
    assert _rewritten(r.stdout) is None


# --- the gate must NEVER block (that is guard-uv's exclusive job) ----------
def test_gate_never_blocks_on_dangerous_or_garbage(tmp_path):
    fake = _fake_rtk(tmp_path)
    for cmd in ["rm -rf /", "git push --force"]:
        assert _run(GATE, cmd, {"KNIOX_RTK_BIN": fake}).returncode == 0
    # malformed payload → still must not block
    bad = subprocess.run([sys.executable, str(GATE)], input="not json",
                         capture_output=True, text=True)
    assert bad.returncode == 0


# --- guard-uv stays authoritative: it blocks before the gate is reached ----
def test_guard_blocks_dangerous_command():
    assert _run(GUARD, "rm -rf /").returncode == 2
    assert _run(GUARD, "git push --force origin main").returncode == 2
