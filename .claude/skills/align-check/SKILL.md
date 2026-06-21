---
name: align-check
description: Validate a project against the kniox alignment requirement. Use for "check alignment", "is X compliant", "audit drift".
---
# align-check
On-demand audit (the hard gates are the hooks; this is the human-invoked check).
For the named project (or all under `projects/`), verify: registered + has `next.md`;
uses `uv` (pyproject.toml + uv.lock, no requirements.txt/conda); models match the
catalog; no heavy model exceeds the VRAM budget in its slot. Report per project:
compliant, or issues + one-line fixes.
