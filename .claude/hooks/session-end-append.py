#!/usr/bin/env python3
"""Stop: append a timestamped line to the project's logs/sessions.log.

This is TELEMETRY, kept OUT of the prompt-injected context. next.md is injected
verbatim every session via --append-system-prompt-file, so it must stay small and
agent-curated; dumping per-session timestamps into it rots the context window. The
agent writes its own one-line summary into next.md before finishing; this hook just
records that a session ended, where it costs nothing.

Fails OPEN (a logging hiccup must never block ending a session).
"""
import json, sys, os, datetime

if os.environ.get("KNIOX_BYPASS_HOOKS") == "1":
    sys.exit(0)
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)   # fail OPEN — telemetry, not a guard
if not isinstance(data, dict):
    sys.exit(0)   # fail OPEN — an unexpected payload shape must never block session end

cwd = os.path.abspath(data.get("cwd") or os.getcwd())
kniox = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
projects = os.path.abspath(os.path.join(kniox, "projects"))
if not cwd.startswith(projects + os.sep):
    sys.exit(0)
name = os.path.relpath(cwd, projects).split(os.sep)[0]
logdir = os.path.join(projects, name, "logs")
try:
    os.makedirs(logdir, exist_ok=True)
    with open(os.path.join(logdir, "sessions.log"), "a") as f:
        f.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M} session ended\n")
except Exception:
    pass
sys.exit(0)
