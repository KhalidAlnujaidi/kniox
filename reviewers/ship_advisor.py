#!/usr/bin/env python3
"""
Ship advisor — ask a commercial model how to PUBLISH this repo (not review it).

Same file-collection/chunking plumbing as the review scripts, but a completely
different prompt: this is release engineering, not code review. The model is told
the code already passed an adversarial dual-model review and is V1-READY; its job
is to get the repo published cleanly and make install trivial (ideally a one-liner).

Usage:
    python3 ship_advisor.py /path/to/repo --provider deepseek --key ... --out ds_ship.md
    python3 ship_advisor.py /path/to/repo --provider gemini  --key ... --out gm_ship.md

No third-party deps (urllib only).
"""

import argparse, json, sys, time, urllib.request, urllib.error
from pathlib import Path

CODE_EXT = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java", ".kt", ".rb",
    ".php", ".c", ".h", ".cpp", ".hpp", ".cs", ".swift", ".scala", ".sh",
    ".sql", ".html", ".css", ".vue", ".svelte", ".lua", ".r", ".jl",
    ".toml", ".yaml", ".yml", ".json", ".md", ".dockerfile", "Dockerfile",
}
SKIP_DIRS = {
    ".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build",
    ".next", ".nuxt", "target", "vendor", ".cache", ".mypy_cache", ".pytest_cache",
    "site-packages", ".idea", ".vscode", "coverage", ".gradle",
}
MAX_FILE_BYTES = 100_000
CHARS_PER_CHUNK = 700_000     # whole small repo in one shot for both providers

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

SHIP_SYSTEM = (
    "You are a pragmatic open-source release engineer and developer-experience lead. "
    "The repository you are given has ALREADY passed an adversarial dual-model code "
    "review and is certified V1-READY — do NOT re-review it for bugs or security "
    "findings. Your ONLY job is to help SHIP it to a public GitHub repository and make "
    "it delightful to adopt. Be concrete and specific to THIS repo's actual files and "
    "layout (cite real paths). Where you propose a file, give its full intended contents. "
    "Where you propose a command, give the exact command. Favor a single robust "
    "`curl ... | bash` one-liner installer if it can be made safe and idempotent for "
    "this project; if you have reservations about curl|bash, state them briefly and give "
    "the safer variant too. Keep it tight — no filler, no praise."
)

SHIP_TASK = """\
This repo is `kniox`, an LLM-native dev environment (Claude Code is the guest; kniox is the \
governed world). It is V1-READY and about to be published publicly for the first time. \
Today the install is a manual multi-step process anchored to `~/kniox`:

    cd ~/kniox
    uv venv && uv pip install -r daemon/requirements.txt   # mcp, psutil
    chmod +x kx .claude/hooks/* .claude/skills/new-project/scaffold.sh corn/*.sh daemon/*.py
    ln -s "$PWD/kx" ~/.local/bin/kx
    kx setup            # detect hardware + backend -> manifest/config  (kx setup --fleet optional)

Constraints / facts to respect:
- Python deps are uv-only (pip/conda/venv/poetry are blocked by the guard hooks). The installer \
itself runs OUTSIDE the governed world, so it may use uv directly but must not assume conda/pip.
- `uv` may or may not be installed; `claude` (Claude Code CLI) may or may not be installed; \
`tailscale` is optional. Detect, don't assume. Linux + macOS must both work.
- `kx setup` never installs backends — it only detects and suggests. Keep that property.
- The repo carries reviewer scripts in `reviewers/` that call commercial APIs with keys passed \
at runtime (`--key`) — NO secrets are committed. Confirm what must be scrubbed/gitignored anyway.
- KNIOX_HOME defaults to ~/kniox; the installer should honor an override.

Deliver, in this order, as clean Markdown:

1. PRE-PUBLISH CHECKLIST — exact steps to take this private folder to a clean public GitHub \
repo: secret-scrub audit, .gitignore additions, files to delete/keep, `git init` + first commit, \
recommended repo name/description/topics, and a LICENSE recommendation (name the license).
2. ONE-LINER INSTALLER — the full contents of an `install.sh` to host in the repo, invoked as \
`curl -fsSL https://raw.githubusercontent.com/<user>/kniox/main/install.sh | bash`. It must: \
detect/install uv if missing, clone or download kniox to $KNIOX_HOME (default ~/kniox), create \
the uv venv + install daemon deps, chmod the executables, symlink kx onto PATH (~/.local/bin), \
run `kx setup`, be idempotent (safe to re-run), fail loudly with clear messages, and print clear \
next-steps. Note any curl|bash caveats and give the inspect-first variant.
3. README QUICKSTART — the exact replacement for the current `## Setup` section so a newcomer \
goes from zero to a working `kx` in one paste, plus a short "Requirements" line.
4. ANNOUNCEMENT — a concise launch post (Show HN / README hero / social) that sells the core \
idea (agent-as-guest, fail-closed governance, detect-don't-assume) without hype.
5. NICE-TO-HAVES — optional, ranked: CI, a `kx doctor`-based smoke test, release tags, etc.

End with one line: `SHIP-PLAN: READY`.
"""


def collect_files(root):
    root = Path(root).resolve()
    files = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.suffix.lower() not in CODE_EXT and p.name not in CODE_EXT:
            continue
        try:
            if p.stat().st_size > MAX_FILE_BYTES:
                continue
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        files.append((str(p.relative_to(root)), text))
    return files


def chunk_files(files):
    chunks, cur, size = [], [], 0
    for rel, text in files:
        block = f"\n\n===== FILE: {rel} =====\n{text}"
        if size + len(block) > CHARS_PER_CHUNK and cur:
            chunks.append("".join(cur)); cur, size = [], 0
        cur.append(block); size += len(block)
    if cur:
        chunks.append("".join(cur))
    return chunks


def call_deepseek(key, model, system, user, retries=3):
    body = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": 0.4, "stream": False,
    }).encode()
    req = urllib.request.Request(DEEPSEEK_URL, data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.load(r)["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="replace")
            if e.code in (429, 500, 502, 503) and attempt < retries - 1:
                time.sleep(2 ** attempt); continue
            return f"[API error {e.code}: {msg}]"
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt); continue
            return f"[Request failed: {e}]"


def call_gemini(key, model, system, user, retries=3):
    url = f"{GEMINI_BASE}/{model}:generateContent?key={key}"
    body = json.dumps({
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 65536},
    }).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                data = json.load(r)
            cand = data["candidates"][0]
            return "".join(p.get("text", "") for p in cand["content"]["parts"])
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="replace")
            if e.code in (429, 500, 502, 503) and attempt < retries - 1:
                time.sleep(2 ** attempt); continue
            return f"[API error {e.code}: {msg}]"
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt); continue
            return f"[Request failed: {e}]"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("--provider", required=True, choices=["deepseek", "gemini"])
    ap.add_argument("--model", default=None)
    ap.add_argument("--key", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    model = args.model or (
        "deepseek-v4-pro" if args.provider == "deepseek" else "gemini-3.1-pro-preview")
    files = collect_files(args.repo)
    if not files:
        sys.exit("No files found.")
    chunks = chunk_files(files)
    print(f"[{args.provider}] {len(files)} files, {len(chunks)} chunk(s), model={model}")

    repo_blob = "".join(f"\n\n===== FILE: {rel} =====\n{text}" for rel, text in files)
    user = SHIP_TASK + "\n\n--- FULL REPOSITORY BELOW ---\n" + repo_blob
    call = call_deepseek if args.provider == "deepseek" else call_gemini
    out = call(args.key, model, SHIP_SYSTEM, user)

    header = f"# kniox ship plan — {args.provider} ({model})\n\n---\n\n"
    Path(args.out).write_text(header + out, encoding="utf-8")
    print(f"[{args.provider}] wrote {args.out} ({len(out):,} chars)")


if __name__ == "__main__":
    main()
