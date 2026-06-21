#!/usr/bin/env bash
# SubagentStart: inject a concise kniox digest into EVERY subagent, including
# plugin/third-party agents you cannot edit. Keep it short.
cat <<'DIGEST'
You are running inside the kniox framework. Its rules apply to you too:
- `uv` only — no pip / conda / venv / poetry.
- One specialized model per task; never exceed the VRAM budget. Dispatch heavy
  model work through the kniox daemon.
- Edits inside a project require that project's next.md to exist.
The PreToolUse hooks enforce these regardless, so comply rather than be blocked.
DIGEST
exit 0
