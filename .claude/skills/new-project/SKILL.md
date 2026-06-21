---
name: new-project
description: Scaffold and register a new kniox project. Use when the user wants to start a new project, app, job, or repo inside kniox.
---
# new-project
1. Get a name (lowercase, hyphenated); ask if not given.
2. Run `"$CLAUDE_PROJECT_DIR/.claude/skills/new-project/scaffold.sh" <name>`
   (creates `projects/<name>/{src,docs,logs}`, a project `CLAUDE.md`, a `next.md`, git init).
3. Register via the kniox MCP tool `register_project` (name + absolute path).
4. Confirm the path; it inherits the root alignment automatically.

Until a project has `next.md`, the guard-state hook blocks edits inside it — scaffold first.
