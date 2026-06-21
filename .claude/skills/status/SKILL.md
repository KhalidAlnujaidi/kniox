---
name: status
description: Report kniox status — projects, VRAM/compute, resource pressure. Use for "what's running", "status of X", "show VRAM".
---
# status
Read the daemon, don't inspect processes by hand.
1. Call `list_projects` and `vram_snapshot` (and `project_status <name>` if named).
2. Summarize: active projects, loaded models, VRAM headroom vs budget, slot conflicts. Keep it short.
3. If the MCP server is unreachable, say so (start: `python daemon/mcp_server.py`).
