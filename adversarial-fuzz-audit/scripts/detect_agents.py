#!/usr/bin/env python3
"""Detect which AI coding agents and model providers are reachable from this machine.

Prints a JSON document (or a table with --table) describing:
  * agent CLIs found on PATH with their version string and vendor family
  * provider API keys present in the environment (names only, never values)
  * the best guess for the model/vendor running the *current* session

Used by Phase 2 (adversary routing) of the adversarial-fuzz-audit skill. Standard library only.

Usage:
    detect_agents.py [--json] [--table] [--timeout SECONDS]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys

# name on PATH -> (vendor family, human name, version args)
AGENT_CLIS = {
    "claude": ("anthropic", "Claude Code", ["--version"]),
    "codex": ("openai", "Codex CLI", ["--version"]),
    "gemini": ("google", "Gemini CLI", ["--version"]),
    "opencode": ("multi", "OpenCode", ["--version"]),
    "aider": ("multi", "Aider", ["--version"]),
    "copilot": ("openai", "GitHub Copilot CLI", ["--version"]),
    "gh": ("openai", "GitHub CLI (copilot extension)", ["copilot", "--version"]),
    "cursor-agent": ("multi", "Cursor Agent", ["--version"]),
    "goose": ("multi", "Goose", ["--version"]),
    "amp": ("anthropic", "Amp", ["--version"]),
    "qwen": ("other", "Qwen Code", ["--version"]),
    "kimi": ("other", "Kimi CLI", ["--version"]),
    "ollama": ("other", "Ollama (local models)", ["--version"]),
}

API_KEYS = {
    "ANTHROPIC_API_KEY": "anthropic",
    "ANTHROPIC_AUTH_TOKEN": "anthropic",
    "OPENAI_API_KEY": "openai",
    "AZURE_OPENAI_API_KEY": "openai",
    "GEMINI_API_KEY": "google",
    "GOOGLE_API_KEY": "google",
    "GOOGLE_GENAI_API_KEY": "google",
    "OPENROUTER_API_KEY": "other",
    "MISTRAL_API_KEY": "other",
    "GROQ_API_KEY": "other",
    "DEEPSEEK_API_KEY": "other",
    "XAI_API_KEY": "other",
    "TOGETHER_API_KEY": "other",
    "FIREWORKS_API_KEY": "other",
    "COHERE_API_KEY": "other",
    "HF_TOKEN": "other",
}

# Environment markers that reveal which harness is running *this* process.
SESSION_MARKERS = [
    ("CLAUDECODE", "anthropic", "Claude Code harness"),
    ("CLAUDE_CODE_ENTRYPOINT", "anthropic", "Claude Code harness"),
    ("ANTHROPIC_MODEL", "anthropic", "ANTHROPIC_MODEL set"),
    ("CODEX_SANDBOX", "openai", "Codex sandbox"),
    ("CODEX_HOME", "openai", "Codex home"),
    ("GEMINI_CLI", "google", "Gemini CLI"),
    ("GEMINI_MODEL", "google", "GEMINI_MODEL set"),
    ("CURSOR_TRACE_ID", "multi", "Cursor"),
    ("AIDER_MODEL", "multi", "Aider"),
]


def run_version(exe: str, args: list[str], timeout: float) -> str | None:
    try:
        out = subprocess.run([exe, *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (out.stdout or out.stderr or "").strip().splitlines()
    return text[0][:120] if text else None


def detect_clis(timeout: float) -> list[dict]:
    found = []
    for name, (vendor, human, vargs) in AGENT_CLIS.items():
        path = shutil.which(name)
        if not path:
            continue
        version = run_version(path, vargs, timeout)
        if name == "gh" and (version is None or "not installed" in version.lower()
                             or "unknown command" in version.lower() or "copilot" not in version.lower()):
            continue  # gh without a working copilot extension is not an agent
        found.append({"name": name, "human": human, "vendor": vendor, "path": path, "version": version})
    return found


def detect_keys() -> list[dict]:
    return [{"name": k, "vendor": v} for k, v in API_KEYS.items() if os.environ.get(k)]


def detect_session() -> dict:
    hits = [(var, vendor, why) for var, vendor, why in SESSION_MARKERS if os.environ.get(var)]
    model = os.environ.get("ANTHROPIC_MODEL") or os.environ.get("GEMINI_MODEL") or os.environ.get("AIDER_MODEL")
    if hits:
        vendor = hits[0][1]
        return {
            "vendor_guess": vendor,
            "model_guess": model,
            "evidence": [f"{v}: {w}" for v, _, w in hits],
            "confidence": "medium" if len(hits) == 1 else "high",
            "note": "Prefer the harness's own session-info tool when available; env markers can be inherited.",
        }
    return {"vendor_guess": "unknown", "model_guess": model, "evidence": [], "confidence": "low",
            "note": "No harness markers. Ask the user which agent/model is running this session."}


def vendors_available(clis: list[dict], keys: list[dict]) -> dict:
    out: dict[str, list[str]] = {}
    for c in clis:
        out.setdefault(c["vendor"], []).append(f"cli:{c['name']}")
    for k in keys:
        out.setdefault(k["vendor"], []).append(f"key:{k['name']}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="JSON output (default)")
    ap.add_argument("--table", action="store_true", help="human-readable table instead of JSON")
    ap.add_argument("--timeout", type=float, default=8.0, help="seconds to wait for each --version call")
    args = ap.parse_args()

    clis = detect_clis(args.timeout)
    keys = detect_keys()
    session = detect_session()
    result = {
        "clis": clis,
        "api_keys": keys,
        "current_session": session,
        "vendors_available": vendors_available(clis, keys),
        "independent_adversary_candidates": {
            vendor: sources
            for vendor, sources in vendors_available(clis, keys).items()
            if vendor not in (session["vendor_guess"], "multi") or vendor == "multi"
        },
        "notes": [
            "'multi' vendor CLIs (opencode, aider, cursor-agent, goose) route to whichever provider is configured; "
            "check their configured model before counting them as independent.",
            "API key names are reported, values are never read beyond presence.",
        ],
    }

    if args.table and not args.json:
        print("Agent CLIs:")
        for c in clis or [{"name": "(none)", "vendor": "", "version": ""}]:
            print(f"  {c['name']:<14} {c.get('vendor',''):<10} {c.get('version') or ''}")
        print("API keys present:")
        for k in keys or [{"name": "(none)", "vendor": ""}]:
            print(f"  {k['name']:<26} {k['vendor']}")
        s = session
        print(f"Current session vendor guess: {s['vendor_guess']} ({s['confidence']}) model={s['model_guess']}")
        for e in s["evidence"]:
            print(f"  - {e}")
        return 0

    json.dump(result, sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
