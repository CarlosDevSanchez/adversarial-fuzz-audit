#!/usr/bin/env python3
"""Build a responsibility matrix: who (human or which agent) wrote each code and test file.

Reads git history for the given paths and classifies every commit by trailers, author
identity and message markers that coding agents leave behind. Standard library only.

Usage:
    provenance.py <repo-root> [path ...] [--json OUT] [--since 2025-01-01] [--max-commits N]

Exit code 0 always (this is an advisory tool); errors are reported in the JSON `errors` list.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

# (regex on the whole commit text incl. author line, agent label, strength)
PATTERNS = [
    (r"co-authored-by:.*claude", "claude", 3),
    (r"noreply@anthropic\.com", "claude", 3),
    (r"claude-session:", "claude", 3),
    (r"generated with \[?claude code", "claude", 3),
    (r"\bclaude\b.*(wrote|generated|implemented)", "claude", 1),
    (r"co-authored-by:.*(codex|chatgpt|openai)", "codex", 3),
    (r"openai-codex\[bot\]|codex\[bot\]|noreply@openai\.com", "codex", 3),
    (r"generated (by|with) codex", "codex", 3),
    (r"co-authored-by:.*copilot|copilot-swe-agent\[bot\]|github copilot", "copilot", 3),
    (r"co-authored-by:.*gemini|gemini-cli|google-labs-jules\[bot\]|jules\[bot\]", "gemini", 3),
    (r"co-authored-by:.*aider|^aider:|\(aider\)", "aider", 3),
    (r"co-authored-by:.*cursor|cursoragent|made with cursor", "cursor", 3),
    (r"co-authored-by:.*devin|devin-ai-integration\[bot\]", "devin", 3),
    (r"co-authored-by:.*(opencode|amp|goose|qwen|kimi|windsurf|cline|roo code)", "other-agent", 2),
    (r"\[bot\]", "bot", 1),
]

TEST_PATH_HINTS = [
    r"(^|/)tests?/", r"(^|/)__tests__/", r"(^|/)spec/", r"(^|/)test_[^/]+\.py$", r"_test\.py$",
    r"_test\.go$", r"\.(test|spec)\.[cm]?[jt]sx?$", r"(^|/)src/test/", r"Tests?\.(java|kt|cs|swift)$",
    r"_spec\.rb$", r"(^|/)t/", r"\.feature$",
]
TEST_CONTENT_HINTS = [
    r"^\s*import pytest", r"^\s*from unittest", r"^\s*import unittest", r"\bdescribe\(", r"\bit\(",
    r"\btest\(", r"^\s*import \"testing\"", r"@Test\b", r"#\[test\]", r"#\[cfg\(test\)\]",
    r"\[Fact\]|\[Theory\]", r"RSpec\.describe",
]


def sh(args: list[str], cwd: str) -> tuple[int, str]:
    try:
        p = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=120)
        return p.returncode, p.stdout
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


def is_test_file(root: Path, rel: str) -> bool:
    if any(re.search(p, rel) for p in TEST_PATH_HINTS):
        return True
    try:
        head = (root / rel).read_text(errors="ignore")[:4000]
    except OSError:
        return False
    return any(re.search(p, head, re.M) for p in TEST_CONTENT_HINTS)


def classify_commit(text: str) -> tuple[str, int, str]:
    """Return (label, strength, evidence) for one commit's combined text."""
    low = text.lower()
    best = ("human", 0, "")
    for pat, label, strength in PATTERNS:
        m = re.search(pat, low, re.M)
        if m and strength > best[1]:
            line = next((ln.strip() for ln in text.splitlines() if m.group(0)[:12] in ln.lower()), m.group(0))
            best = (label, strength, line[:100])
    return best


def list_files(root: Path, paths: list[str]) -> list[str]:
    if not paths:
        rc, out = sh(["git", "ls-files"], str(root))
        return [l for l in out.splitlines() if l.strip()] if rc == 0 else []
    files: list[str] = []
    for p in paths:
        full = (root / p) if not os.path.isabs(p) else Path(p)
        if full.is_dir():
            rc, out = sh(["git", "ls-files", "--", str(full)], str(root))
            files += [l for l in out.splitlines() if l.strip()]
        elif full.exists():
            files.append(os.path.relpath(full, root))
    return sorted(set(files))


def file_history(root: Path, rel: str, since: str | None, max_commits: int) -> list[dict]:
    fmt = "%H%x1f%an <%ae>%x1f%ad%x1f%B%x1e"
    args = ["git", "log", f"--max-count={max_commits}", "--date=short", f"--format={fmt}", "--follow"]
    if since:
        args.append(f"--since={since}")
    args += ["--", rel]
    rc, out = sh(args, str(root))
    if rc != 0:
        return []
    commits = []
    for rec in out.split("\x1e"):
        rec = rec.strip("\n")
        if not rec.strip():
            continue
        parts = rec.split("\x1f")
        if len(parts) < 4:
            continue
        sha, author, date, body = parts[0].strip(), parts[1], parts[2], parts[3]
        label, strength, ev = classify_commit(author + "\n" + body)
        commits.append({"sha": sha[:10], "author": author, "date": date, "label": label, "strength": strength, "evidence": ev})
    return commits


def summarize(commits: list[dict]) -> tuple[str, str, str]:
    if not commits:
        return "unknown", "none", "no git history"
    weights: Counter = Counter()
    for c in commits:
        weights[c["label"]] += max(1, c["strength"])
    label, w = weights.most_common(1)[0]
    total = sum(weights.values())
    share = w / total
    agent_commits = [c for c in commits if c["label"] == label]
    confidence = "high" if share >= 0.75 and (label == "human" or any(c["strength"] >= 3 for c in agent_commits)) else "medium" if share >= 0.5 else "low"
    ev = agent_commits[0]["evidence"] if label != "human" else f"author:{agent_commits[0]['author']}"
    return label, confidence, f"{ev} ({len(agent_commits)}/{len(commits)} commits)"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("repo")
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--json", dest="json_out", help="write full result to this file")
    ap.add_argument("--since", help="only consider commits after this date (YYYY-MM-DD)")
    ap.add_argument("--max-commits", type=int, default=200)
    args = ap.parse_args()

    root = Path(args.repo).resolve()
    errors: list[str] = []
    rc, _ = sh(["git", "rev-parse", "--is-inside-work-tree"], str(root))
    if rc != 0:
        errors.append("not a git repository; ask the user who wrote the code and the tests")
        files = []
    else:
        files = list_files(root, args.paths)

    rows = []
    kinds: dict[str, Counter] = {"code": Counter(), "test": Counter()}
    for rel in files:
        if any(seg in rel.split("/") for seg in ("node_modules", ".git", "vendor", "dist", "build", "__pycache__")):
            continue
        kind = "test" if is_test_file(root, rel) else "code"
        hist = file_history(root, rel, args.since, args.max_commits)
        label, conf, ev = summarize(hist)
        kinds[kind][label] += 1
        rows.append({"path": rel, "kind": kind, "author": label, "confidence": conf, "evidence": ev,
                     "commits": hist[:5]})

    def top(counter: Counter) -> list[str]:
        return [k for k, _ in counter.most_common() if k != "unknown"] or ["unknown"]

    result = {
        "repo": str(root),
        "code_authors": top(kinds["code"]),
        "test_authors": top(kinds["test"]),
        "source": "git-trailers" if files else "none",
        "confidence": "high" if rows and all(r["confidence"] == "high" for r in rows) else "medium" if rows else "low",
        "files": rows,
        "errors": errors,
        "notes": "Labels: human, claude, codex, copilot, gemini, aider, cursor, devin, other-agent, bot, unknown. "
                 "Confirm with the user when confidence is not high; routing to the author by mistake defeats the audit.",
    }

    print(f"{'file':<48} {'kind':<5} {'author':<12} {'conf':<7} evidence")
    for r in rows:
        print(f"{r['path'][:47]:<48} {r['kind']:<5} {r['author']:<12} {r['confidence']:<7} {r['evidence'][:70]}")
    print(f"\ncode authors: {result['code_authors']}   test authors: {result['test_authors']}")
    for e in errors:
        print("warning:", e, file=sys.stderr)

    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
