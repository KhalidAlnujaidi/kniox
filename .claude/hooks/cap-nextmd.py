#!/usr/bin/env python3
"""Stop: hard-cap the current project's next.md.

next.md is injected verbatim into every session via --append-system-prompt-file, so a
file that grows unbounded silently bloats the context window of every future launch.
Overwrite discipline used to be a REQUEST (template comment + CLAUDE.md saying "trim");
this makes it a MECHANISM. The header is preserved; the body is trimmed to the last
MAX_LINES lines and MAX_BYTES bytes.

Fails OPEN (a trimming hiccup must never block ending a session). Honors the same
manual override as the guards: KNIOX_BYPASS_HOOKS=1.
"""
import json, os, sys

MAX_LINES = int(os.environ.get("KNIOX_NEXTMD_MAX_LINES", "60"))
MAX_BYTES = int(os.environ.get("KNIOX_NEXTMD_MAX_BYTES", "6000"))

if os.environ.get("KNIOX_BYPASS_HOOKS") == "1":
    sys.exit(0)
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
if not isinstance(data, dict):
    sys.exit(0)   # fail OPEN — an unexpected payload shape must never block session end

cwd = os.path.abspath(data.get("cwd") or os.getcwd())
kniox = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", ".."))
projects = os.path.abspath(os.path.join(kniox, "projects"))
if not cwd.startswith(projects + os.sep):
    sys.exit(0)

name = os.path.relpath(cwd, projects).split(os.sep)[0]
path = os.path.join(projects, name, "next.md")
try:
    with open(path) as f:
        text = f.read()
except Exception:
    sys.exit(0)

if len(text.encode("utf-8")) <= MAX_BYTES and text.count("\n") < MAX_LINES:
    sys.exit(0)   # already small — nothing to do

lines = text.splitlines()
# Keep the header: the title plus everything up to the first blank line after it.
head = []
for ln in lines:
    head.append(ln)
    if len(head) > 1 and ln.strip() == "":
        break
# If no blank line separates title from body, the loop above swallows the whole file
# and trimming would be a no-op — keep only the title line in that case.
if not any(ln.strip() == "" for ln in head[1:]):
    head = lines[:1]
body = lines[len(head):]
kept = body[-MAX_LINES:]
marker = f"<!-- kniox: next.md auto-capped to last {MAX_LINES} lines to protect context -->"
head_block = head + [marker, ""]
out = "\n".join(head_block + kept).rstrip() + "\n"
if len(out.encode("utf-8")) > MAX_BYTES:
    # Last-resort byte cap that PRESERVES the header: trim bytes from the body only,
    # never blindly from the front (which would drop the structural title).
    head_str = "\n".join(head_block)
    allowed = MAX_BYTES - len(head_str.encode("utf-8")) - 2   # joining "\n" + trailing "\n"
    if allowed > 0:
        body_tail = "\n".join(kept).encode("utf-8")[-allowed:].decode("utf-8", "ignore").lstrip("\n")
        out = (head_str + "\n" + body_tail).rstrip() + "\n"
    else:
        out = head_str.rstrip() + "\n"

try:
    with open(path, "w") as f:
        f.write(out)
except Exception:
    pass
sys.exit(0)
