#!/usr/bin/env python3
"""Privacy guard — keep personal-project specifics OUT of the public kniox framework repo.

This repo is public. Personal projects (their names, ideas, domains) must NEVER appear in
tracked files, commit messages, or PR titles/bodies here. Project specifics live only in
the project's own gitignored repo under `projects/` plus the local daemon registry.

Two modes, one scan:
  * PreToolUse(Bash) hook  — reads the Claude Code JSON payload on stdin; inspects
    `git commit` / `git push` / `gh pr create|edit` commands and blocks (exit 2) when the
    staged content, commit message, or PR title/body names a registered personal project,
    or stages a path that encodes one (`projects/<x>`, `dashboard/<x>/...`).
  * `--staged` CLI         — the same scan over the index, for a git pre-commit hook
    (`git config core.hooksPath .githooks`) so manual commits are guarded too.

Forbidden names are read LIVE from the local daemon registry (and optional
KNIOX_PRIVACY_TOKENS), never written here — so this file itself names no project and is
safe to publish. Fails CLOSED on a malformed hook payload.

Bypass (set in the launching shell; inherited by the hook, not by the agent's subshell):
    export KNIOX_BYPASS_HOOKS=1
"""
import json
import os
import re
import shlex
import subprocess
import sys

PATH_RE = re.compile(r"^(projects/.+|dashboard/[^/]+/.+)$")
MIN_TOKEN_LEN = 4  # shorter names would false-positive on ordinary words


def _root():
    r = os.environ.get("CLAUDE_PROJECT_DIR")
    if r:
        return r
    out = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True).stdout.strip()
    return out or "."


def _candidate_homes(root):
    """Framework homes whose registries to consult, most-canonical first. The registry DB
    lives at <home>/daemon/state/kniox.db and is machine-local — so a transient git worktree
    has an EMPTY one. We therefore also read the canonical home ($KNIOX_HOME, else ~/kniox,
    matching the kx launcher's default) so enforcement holds no matter where work happens."""
    homes, seen = [], set()
    for h in (os.environ.get("KNIOX_HOME"), "~/kniox", root):
        if not h:
            continue
        h = os.path.abspath(os.path.expanduser(h))
        if h not in seen and os.path.isdir(h):
            seen.add(h)
            homes.append(h)
    return homes


def forbidden_tokens(root):
    """Registered project names + their directory basenames (lowercased), unioned across the
    canonical and repo-local daemon registries, plus any in KNIOX_PRIVACY_TOKENS (comma-sep)."""
    toks = set()
    homes = _candidate_homes(root)
    daemon_py = next((os.path.join(h, "daemon", "daemon.py") for h in homes
                      if os.path.exists(os.path.join(h, "daemon", "daemon.py"))), None)
    for h in homes:
        if not daemon_py:
            break
        env = dict(os.environ, KNIOX_STATE_DIR=os.path.join(h, "daemon", "state"))
        try:
            out = subprocess.run([sys.executable, daemon_py, "list"],
                                 capture_output=True, text=True, timeout=10, env=env)
            for p in json.loads(out.stdout or "[]"):
                n = (p.get("name") or "").strip().lower()
                if n:
                    toks.add(n)
                path = (p.get("path") or "").strip()
                if path:
                    toks.add(os.path.basename(path.rstrip("/")).lower())
        except Exception:
            pass
    for t in os.environ.get("KNIOX_PRIVACY_TOKENS", "").split(","):
        t = t.strip().lower()
        if t:
            toks.add(t)
    return {t for t in toks if len(t) >= MIN_TOKEN_LEN}


def _names_in(text, tokens):
    low = (text or "").lower()
    return sorted({t for t in tokens if t in low})


def _run(root, *args):
    return subprocess.run(["git", "-C", root, *args], capture_output=True, text=True).stdout


def check(root, *, message="", extra_text="", diff=None, paths=None, tokens=None):
    """Return a list of human-readable violations ([] == clean)."""
    if tokens is None:
        tokens = forbidden_tokens(root)
    if paths is None:
        paths = [l for l in _run(root, "diff", "--cached", "--name-only").splitlines() if l.strip()]
    if diff is None:
        diff = _run(root, "diff", "--cached")
    out = []
    for p in paths:
        if PATH_RE.match(p):
            out.append(f"staged path '{p}' encodes a project — keep it in projects/ (gitignored)")
    if tokens:
        for where, text in (("staged content", diff),
                            ("commit message", message),
                            ("PR title/body", extra_text)):
            hits = _names_in(text, tokens)
            if hits:
                out.append(f"{where} names personal project(s): {', '.join(hits)}")
    return out


def _deny(violations):
    sys.stderr.write(
        "kniox privacy guard blocked this — kniox is a PUBLIC framework repo and personal "
        "projects must never appear in it:\n  - " + "\n  - ".join(violations) +
        "\nKeep project specifics in the project's own gitignored repo under projects/. "
        "Override (only if you are certain it is generic): export KNIOX_BYPASS_HOOKS=1\n")
    sys.exit(2)


def _opt_values(tokens, *flags):
    """Collect values that follow any of `flags` in a tokenized command line."""
    vals, i = [], 0
    flagset = set(flags)
    while i < len(tokens):
        t = tokens[i]
        for f in flagset:
            if t == f and i + 1 < len(tokens):
                vals.append(tokens[i + 1])
            elif t.startswith(f + "="):
                vals.append(t.split("=", 1)[1])
        i += 1
    return " ".join(vals)


def _hook_mode():
    if os.environ.get("KNIOX_BYPASS_HOOKS") == "1":
        sys.exit(0)
    try:
        data = json.load(sys.stdin)
        assert isinstance(data, dict)
    except Exception:
        sys.stderr.write("kniox privacy guard: unparseable hook payload; blocking for safety. "
                         "Bypass a schema break with: export KNIOX_BYPASS_HOOKS=1\n")
        sys.exit(2)
    cmd = (data.get("tool_input") or {}).get("command", "") or ""
    norm = re.sub(r"\s+", " ", cmd)
    is_commit = bool(re.search(r"\bgit\b.*\bcommit\b", norm))
    is_push = bool(re.search(r"\bgit\b.*\bpush\b", norm))
    is_pr = bool(re.search(r"\bgh\b.*\bpr\b.*\b(create|edit)\b", norm))
    if not (is_commit or is_push or is_pr):
        sys.exit(0)
    root = _root()
    try:
        toks = shlex.split(cmd)
    except ValueError:
        toks = cmd.split()
    violations = []
    if is_commit:
        msg = _opt_values(toks, "-m", "--message")
        violations = check(root, message=msg)
    elif is_pr:
        body = _opt_values(toks, "--title", "-t", "--body", "-b", "--body-file", "-F")
        # PR body/title carry no staged index; scan only the provided text.
        violations = check(root, extra_text=body, diff="", paths=[],
                          tokens=forbidden_tokens(root))
    elif is_push:
        base = "origin/main"
        rng = f"{base}..HEAD"
        diff = _run(root, "diff", base + "...HEAD")
        msgs = _run(root, "log", "--format=%B", rng)
        outpaths = [l for l in _run(root, "diff", "--name-only", base + "...HEAD").splitlines() if l.strip()]
        violations = check(root, message=msgs, diff=diff, paths=outpaths)
    if violations:
        _deny(violations)
    sys.exit(0)


def _staged_mode():
    root = _root()
    msg = ""
    p = os.path.join(root, ".git", "COMMIT_EDITMSG")
    if os.path.exists(p):
        try:
            msg = open(p, encoding="utf-8").read()
        except OSError:
            pass
    violations = check(root, message=msg)
    if violations:
        _deny(violations)
    sys.exit(0)


if __name__ == "__main__":
    if "--staged" in sys.argv[1:]:
        _staged_mode()
    else:
        _hook_mode()
