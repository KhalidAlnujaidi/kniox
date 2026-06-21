"""Tests for the privacy guard (.claude/hooks/guard-privacy.py).

Uses an injected fake token (KNIOX_PRIVACY_TOKENS) so the suite itself names no real
project and needs no running daemon. Exit 2 == blocked, 0 == allowed.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parents[2] / ".claude" / "hooks" / "guard-privacy.py"
FAKE = "acme-secret-project"


def _repo(tmp_path):
    subprocess.run(["git", "init", "-q", tmp_path], check=True)
    subprocess.run(["git", "-C", tmp_path, "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", tmp_path, "config", "user.name", "t"], check=True)
    return tmp_path


def _env(repo):
    e = dict(os.environ)
    e["CLAUDE_PROJECT_DIR"] = str(repo)
    e["KNIOX_PRIVACY_TOKENS"] = FAKE
    e.pop("KNIOX_BYPASS_HOOKS", None)
    return e


def _staged(repo):
    return subprocess.run([sys.executable, str(HOOK), "--staged"],
                          cwd=repo, env=_env(repo), capture_output=True, text=True)


def test_staged_content_naming_project_is_blocked(tmp_path):
    repo = _repo(tmp_path)
    (repo / "notes.md").write_text(f"see the {FAKE} pipeline", encoding="utf-8")
    subprocess.run(["git", "-C", repo, "add", "-A"], check=True)
    assert _staged(repo).returncode == 2


def test_staged_clean_content_is_allowed(tmp_path):
    repo = _repo(tmp_path)
    (repo / "notes.md").write_text("a generic framework note", encoding="utf-8")
    subprocess.run(["git", "-C", repo, "add", "-A"], check=True)
    assert _staged(repo).returncode == 0


def test_project_encoding_path_is_blocked_without_tokens(tmp_path):
    repo = _repo(tmp_path)
    slot = repo / "dashboard" / "someproj"
    slot.mkdir(parents=True)
    (slot / "README.md").write_text("generic text", encoding="utf-8")
    subprocess.run(["git", "-C", repo, "add", "-A"], check=True)
    r = subprocess.run([sys.executable, str(HOOK), "--staged"], cwd=repo,
                       env={**os.environ, "CLAUDE_PROJECT_DIR": str(repo), "KNIOX_PRIVACY_TOKENS": ""},
                       capture_output=True, text=True)
    assert r.returncode == 2


def test_hook_mode_blocks_pr_title_naming_project(tmp_path):
    repo = _repo(tmp_path)
    payload = {"tool_input": {"command": f'gh pr create --title "{FAKE} migration" --body x'}}
    r = subprocess.run([sys.executable, str(HOOK)], cwd=repo, env=_env(repo),
                       input=json.dumps(payload), capture_output=True, text=True)
    assert r.returncode == 2


def test_hook_mode_ignores_unrelated_commands(tmp_path):
    repo = _repo(tmp_path)
    payload = {"tool_input": {"command": "ls -la"}}
    r = subprocess.run([sys.executable, str(HOOK)], cwd=repo, env=_env(repo),
                       input=json.dumps(payload), capture_output=True, text=True)
    assert r.returncode == 0
