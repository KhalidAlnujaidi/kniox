#!/usr/bin/env python3
"""
Run an entire repository through DeepSeek V4 and collect code-review feedback.

Usage:
    python3 deepseek_review.py /path/to/repo
    python3 deepseek_review.py /path/to/repo --model deepseek-v4-flash
    python3 deepseek_review.py . --out review.md --focus "security and error handling"

Key resolution order: --key arg  ->  $DEEPSEEK_API_KEY  ->  ~/.config/free-claude-code/.env
No third-party deps (uses urllib), so it works even with a broken conda libcurl.
"""

import argparse, json, os, re, sys, time, urllib.request, urllib.error
from pathlib import Path

API_URL = "https://api.deepseek.com/chat/completions"

# Which files to review. Add/remove extensions as you like.
CODE_EXT = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java", ".kt", ".rb",
    ".php", ".c", ".h", ".cpp", ".hpp", ".cs", ".swift", ".scala", ".sh",
    ".sql", ".html", ".css", ".vue", ".svelte", ".lua", ".r", ".jl",
    ".toml", ".yaml", ".yml", ".json", ".md", ".dockerfile", "Dockerfile",
}
# Directories never worth sending.
SKIP_DIRS = {
    ".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build",
    ".next", ".nuxt", "target", "vendor", ".cache", ".mypy_cache", ".pytest_cache",
    "site-packages", ".idea", ".vscode", "coverage", ".gradle",
}
MAX_FILE_BYTES = 100_000      # skip huge generated/minified files
CHARS_PER_CHUNK = 120_000     # ~30k tokens; one API call per chunk


def resolve_key(cli_key):
    if cli_key:
        return cli_key
    if os.environ.get("DEEPSEEK_API_KEY"):
        return os.environ["DEEPSEEK_API_KEY"]
    env = Path.home() / ".config" / "free-claude-code" / ".env"
    if env.exists():
        m = re.search(r'DEEPSEEK_API_KEY\s*=\s*"?([^"\n]+)"?', env.read_text())
        if m:
            return m.group(1).strip()
    sys.exit("No API key. Set $DEEPSEEK_API_KEY or pass --key.")


def collect_files(root):
    root = Path(root).resolve()
    files = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.suffix.lower() not in CODE_EXT and p.name not in CODE_EXT:
            continue
        try:
            if p.stat().st_size > MAX_FILE_BYTES:
                continue
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary or unreadable
        files.append((str(p.relative_to(root)), text))
    return files


def chunk_files(files):
    """Pack files into chunks under CHARS_PER_CHUNK, keeping whole files together."""
    chunks, cur, size = [], [], 0
    for rel, text in files:
        block = f"\n\n===== FILE: {rel} =====\n{text}"
        if size + len(block) > CHARS_PER_CHUNK and cur:
            chunks.append("".join(cur))
            cur, size = [], 0
        cur.append(block)
        size += len(block)
    if cur:
        chunks.append("".join(cur))
    return chunks


def call_deepseek(key, model, system, user, temperature=0.3, retries=3):
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "stream": False,
    }).encode()
    req = urllib.request.Request(
        API_URL, data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                data = json.load(r)
            return data["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="replace")
            if e.code in (429, 500, 502, 503) and attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            return f"[API error {e.code}: {msg}]"
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            return f"[Request failed: {e}]"


REVIEW_SYSTEM = (
    "You are a meticulous senior software engineer doing a code review. "
    "Be concrete and specific: cite the file and the symbol/line context. "
    "Prioritize correctness bugs, security issues, and data-loss risks; then "
    "design/maintainability; then minor style. For each finding give: severity "
    "(Critical/High/Medium/Low), location, what's wrong, and a concrete fix. "
    "Skip praise and filler. If a chunk is clean, say so briefly."
)

SYNTH_SYSTEM = (
    "You are a staff engineer writing the final summary of a code review from "
    "several partial reviews. Deduplicate, group by theme, rank by severity, and "
    "produce a prioritized action list the author can work through top-to-bottom."
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repo", help="path to the repository to review")
    ap.add_argument("--model", default="deepseek-v4-pro",
                    help="deepseek-v4-pro (default, best) or deepseek-v4-flash (faster/cheaper)")
    ap.add_argument("--key", default=None)
    ap.add_argument("--out", default="deepseek_review.md")
    ap.add_argument("--focus", default="", help="optional: extra focus, e.g. 'security'")
    args = ap.parse_args()

    key = resolve_key(args.key)
    files = collect_files(args.repo)
    if not files:
        sys.exit("No reviewable source files found.")
    chunks = chunk_files(files)
    print(f"Reviewing {len(files)} files in {len(chunks)} chunk(s) with {args.model}...")

    focus = f"\n\nPay special attention to: {args.focus}." if args.focus else ""
    partials = []
    for i, chunk in enumerate(chunks, 1):
        print(f"  -> chunk {i}/{len(chunks)} ({len(chunk):,} chars)")
        user = (
            f"Review the following source files (chunk {i} of {len(chunks)}).{focus}\n{chunk}"
        )
        partials.append(call_deepseek(key, args.model, REVIEW_SYSTEM, user))

    if len(partials) == 1:
        final = partials[0]
    else:
        print("  -> synthesizing final summary...")
        joined = "\n\n".join(f"--- Partial review {i} ---\n{p}" for i, p in enumerate(partials, 1))
        final = call_deepseek(key, args.model, SYNTH_SYSTEM,
                              f"Combine these partial reviews into one prioritized report:\n\n{joined}")

    header = f"# DeepSeek code review ({args.model})\n\nRepo: `{Path(args.repo).resolve()}`  |  {len(files)} files\n\n---\n\n"
    Path(args.out).write_text(header + final, encoding="utf-8")
    print(f"\nDone. Wrote {args.out}\n")
    print(final[:2000] + ("\n... (truncated; see file)" if len(final) > 2000 else ""))


if __name__ == "__main__":
    main()
