"""Shadow-Git gate: run edits in an isolated worktree, verify there, apply on green only.

These tests build throwaway git repos so the gate is exercised end to end without touching
the kniox working tree. The contract: a failing verify NEVER mutates the real tree, a
passing verify lands the change, and `main`/`master` are refused as apply targets (PR-only).
"""
import subprocess
import pytest
import shadow


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, check=True)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "work")
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "t")
    (r / "seed.txt").write_text("seed\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "seed")
    return r


def test_green_applies_change_to_real_tree(repo):
    res = shadow.shadow_run(str(repo),
                            change_cmd="printf 'hello\\n' > new.txt",
                            verify_cmd="test -f new.txt")
    assert res["applied"] is True
    assert res["verify"]["ok"] is True
    assert (repo / "new.txt").read_text() == "hello\n"
    # gate cleaned up after itself — no shadow worktree or branch left behind
    branches = _git(repo, "branch", "--list", "shadow/*").stdout
    assert branches.strip() == ""


def test_red_leaves_real_tree_untouched(repo):
    res = shadow.shadow_run(str(repo),
                            change_cmd="printf 'oops\\n' > broken.txt",
                            verify_cmd="exit 1")
    assert res["applied"] is False
    assert res["verify"]["ok"] is False
    assert res["stage"] == "verify"
    assert not (repo / "broken.txt").exists()


def test_change_cmd_failure_is_reported_and_does_not_apply(repo):
    res = shadow.shadow_run(str(repo),
                            change_cmd="exit 7",
                            verify_cmd="true")
    assert res["applied"] is False
    assert res["stage"] == "change"
    assert not (repo / "new.txt").exists()


def test_refuses_to_apply_onto_protected_branch(tmp_path):
    r = tmp_path / "mainrepo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "t")
    (r / "seed.txt").write_text("seed\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "seed")
    res = shadow.shadow_run(str(r), change_cmd="echo x > x.txt", verify_cmd="true")
    assert res["applied"] is False
    assert res["stage"] == "protected-branch"
    assert not (r / "x.txt").exists()


def test_no_apply_keeps_change_on_shadow_branch_only(repo):
    res = shadow.shadow_run(str(repo),
                            change_cmd="printf 'hi\\n' > kept.txt",
                            verify_cmd="true", apply=False)
    assert res["verify"]["ok"] is True
    assert res["applied"] is False
    assert not (repo / "kept.txt").exists()          # real tree untouched
    branch = res["branch"]
    show = _git(repo, "show", f"{branch}:kept.txt").stdout
    assert show == "hi\n"                              # but preserved on the shadow branch
