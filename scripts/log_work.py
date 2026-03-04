#!/usr/bin/env python3
"""
log_work.py — Work log helper for Hoopla Coach development.

Usage modes:

  1. Called by Claude Code PostToolUse hook (reads JSON from stdin):
       python3 scripts/log_work.py --hook

  2. Called directly by agents to append a narrative entry:
       python3 scripts/log_work.py --entry "## [HH:MM UTC] Human Request\n..."

  3. Append a single tagged line (for quick inline logging):
       python3 scripts/log_work.py --line "DECISION: chose FAISS over ChromaDB for simplicity"

The log file is WORK_LOG.md at the repo root (sibling of this scripts/ dir).
"""

import json
import os
import sys
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_FILE = os.path.join(REPO_ROOT, "WORK_LOG.md")

# Tools to log automatically via the hook
TRACKED_TOOLS = {"Write", "Edit", "NotebookEdit"}


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def append(text: str):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(text)


def handle_hook():
    """Parse Claude Code PostToolUse JSON from stdin and append a log line."""
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        return

    tool = data.get("tool_name", "")
    if tool not in TRACKED_TOOLS:
        return

    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", tool_input.get("notebook_path", "unknown"))
    # Make path relative to repo root if possible
    try:
        rel = os.path.relpath(file_path, REPO_ROOT)
    except ValueError:
        rel = file_path

    append(f"\n> `[{now()}]` **{tool}** → `{rel}`")


def handle_entry(text: str):
    """Append a pre-formatted markdown block (newline-terminated)."""
    if not text.endswith("\n"):
        text += "\n"
    append(text)


def handle_line(text: str):
    """Append a single timestamped line."""
    append(f"\n> `[{now()}]` {text}")


if __name__ == "__main__":
    args = sys.argv[1:]

    if not args or args[0] == "--hook":
        handle_hook()

    elif args[0] == "--entry" and len(args) > 1:
        # Unescape \n in shell-passed strings
        handle_entry(args[1].replace("\\n", "\n"))

    elif args[0] == "--line" and len(args) > 1:
        handle_line(" ".join(args[1:]))

    else:
        print(__doc__)
        sys.exit(1)
