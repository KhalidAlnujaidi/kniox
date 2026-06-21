#!/usr/bin/env python3
"""PreToolUse(Edit|Write): two jobs.
  1. Self-protection — the agent may not rewrite the rails that constrain it
     (hooks, settings, kx, the alignment contract, root CLAUDE.md, .mcp.json).
  2. Project-state gate — edits inside a project require that project's next.md.

Fails CLOSED on unparseable input. Override (in the launching shell, not the agent's
subshell):  export KNIOX_BYPASS_HOOKS=1   — this is also how YOU edit the rails via
the agent when you mean to.
"""
import json, sys, os

if os.environ.get("KNIOX_BYPASS_HOOKS") == "1":
    sys.exit(0)

def block(msg):
    sys.stderr.write("kniox: " + msg + "\n")
    sys.exit(2)

try:
    data = json.load(sys.stdin)
except Exception as e:
    block(f"guard-state could not parse the hook payload ({e}); blocking for safety. "
          f"Bypass a schema break with: export KNIOX_BYPASS_HOOKS=1")

# Non-dict payload (e.g. a list) would AttributeError on .get below — block cleanly
# instead of leaking a traceback, same fail-CLOSED direction as the parse error above.
if not isinstance(data, dict):
    block("guard-state received a non-dict hook payload; blocking for safety. "
          "Bypass a schema break with: export KNIOX_BYPASS_HOOKS=1")

fp = (data.get("tool_input") or {}).get("file_path") or ""
cwd = data.get("cwd") or os.getcwd()
kniox = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
kniox = os.path.abspath(kniox)
target = os.path.abspath(fp or cwd)

# (1) Self-protection. Editing code is the agent's job; editing the GOVERNANCE is not.
# daemon/ is deliberately NOT here — it's application code on the roadmap. Add it if
# you want the broker locked too.
rails_dirs  = [os.path.join(kniox, ".claude") + os.sep, os.path.join(kniox, "alignment") + os.sep]
rails_files = [os.path.join(kniox, "kx"), os.path.join(kniox, "CLAUDE.md"), os.path.join(kniox, ".mcp.json")]
if target in rails_files or any(target.startswith(d) for d in rails_dirs):
    block(f"blocked edit to a kniox rail ({os.path.relpath(target, kniox)}). These govern the agent; "
          f"edit them yourself, or set KNIOX_BYPASS_HOOKS=1 to allow it for this session.")

# (2) Project-state gate.
projects = os.path.join(kniox, "projects")
if not target.startswith(projects + os.sep):
    sys.exit(0)
name = os.path.relpath(target, projects).split(os.sep)[0]
if not os.path.exists(os.path.join(projects, name, "next.md")):
    block(f"blocked. Project '{name}' has no next.md. Use the new-project skill "
          f"or create {name}/next.md before editing.")
sys.exit(0)
