"""Shadow-Git gate — propose -> isolate -> verify -> apply.

An agent's edits should never hit the real working tree until they pass tests. This gate
runs the change in a throwaway `git worktree` on its own branch, runs the verify command
*there*, and only patches the result back into the real tree when verify is green. A red
verify discards the worktree; the real tree is never touched.

No models, no GPU, no daemon lease — pure git + CPU. It reinforces the alignment rather
than bending it: the apply target is the current feature branch, and `main`/`master` are
refused outright (PR-only; nothing lands on main without a pull request).
"""
from __future__ import annotations
import os
import subprocess
import tempfile
import time

PROTECTED = {"main", "master"}
_SHADOW_ROOT = ".kniox/shadow"


def _git(repo: str, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", repo, *args],
                          capture_output=True, text=True, check=check)


def current_branch(repo: str) -> str:
    return _git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()


def _sh(cmd: str, cwd: str) -> dict:
    """Run a shell command in `cwd`; capture everything, never raise."""
    p = subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True)
    return {"ok": p.returncode == 0, "exit_code": p.returncode,
            "stdout": p.stdout, "stderr": p.stderr}


def _has_changes(worktree: str) -> bool:
    return bool(_git(worktree, "status", "--porcelain").stdout.strip())


def _cleanup(repo: str, worktree: str, branch: str, drop_branch: bool) -> None:
    _git(repo, "worktree", "remove", "--force", worktree, check=False)
    if drop_branch:
        _git(repo, "branch", "-D", branch, check=False)


def shadow_run(repo: str, change_cmd: str, verify_cmd: str,
               apply: bool = True, keep: bool = False) -> dict:
    """Isolate `change_cmd`, verify it, and (on green) apply it back to the real tree.

    Returns a dict describing the outcome. `applied` is True only when verify passed AND
    the patch landed in the real working tree (left uncommitted for the normal PR step).
    `stage` names where the gate stopped: change | verify | apply | protected-branch | ok.
    """
    repo = os.path.abspath(repo)
    base = current_branch(repo)
    if apply and base in PROTECTED:
        return {"applied": False, "stage": "protected-branch", "branch": None,
                "reason": f"refusing to apply onto protected branch {base!r} (PR-only); "
                          "switch to a feature branch or pass apply=False"}

    sid = f"{int(time.time())}-{os.getpid()}"
    branch = f"shadow/{sid}"
    worktree = os.path.join(repo, _SHADOW_ROOT, sid)
    base_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
    _git(repo, "worktree", "add", "-q", "-b", branch, worktree, base_sha)

    # The shadow branch is disposable unless it becomes the only copy of a good change
    # (apply=False, an apply failure, or an explicit keep). Set as we learn the outcome.
    keep_branch = keep
    try:
        change = _sh(change_cmd, worktree)
        if not change["ok"]:
            return {"applied": False, "stage": "change", "branch": branch,
                    "change": change, "reason": "change command failed"}

        if not _has_changes(worktree):
            return {"applied": False, "stage": "change", "branch": branch,
                    "reason": "change command produced no edits"}

        _git(worktree, "add", "-A")
        _git(worktree, "commit", "-q", "-m", f"shadow: {sid}")

        verify = _sh(verify_cmd, worktree)
        if not verify["ok"]:
            return {"applied": False, "stage": "verify", "branch": branch, "verify": verify,
                    "reason": "verify failed; real tree untouched"}

        if not apply:
            keep_branch = True
            return {"applied": False, "stage": "ok", "branch": branch, "verify": verify,
                    "reason": "verify passed; change kept on shadow branch (apply=False)"}

        patch = _git(worktree, "diff", "--binary", f"{base_sha}..HEAD").stdout
        with tempfile.NamedTemporaryFile("w", suffix=".patch", delete=False) as f:
            f.write(patch)
            patch_path = f.name
        try:
            applied = _git(repo, "apply", "--3way", "--binary", patch_path, check=False)
        finally:
            os.unlink(patch_path)
        if applied.returncode != 0:
            keep_branch = True
            return {"applied": False, "stage": "apply", "branch": branch,
                    "verify": verify, "error": applied.stderr.strip(),
                    "reason": "verify passed but patch did not apply cleanly; "
                              f"changes preserved on branch {branch}"}

        return {"applied": True, "stage": "ok", "branch": branch, "verify": verify,
                "reason": "verify passed; change applied to working tree (uncommitted)"}
    finally:
        _cleanup(repo, worktree, branch, drop_branch=not keep_branch)
