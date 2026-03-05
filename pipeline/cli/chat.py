"""Hoopla Coach — Terminal CLI frontend.

A readline-enabled terminal chat that connects to the Coach HTTP server.
Streams responses token-by-token to stdout. Supports all slash commands.
Optionally renders markdown with `rich` if installed; falls back to plain text.

Session model: one session per terminal process. Session ID stored in
~/.priya/session_id and reused across invocations (persists until /reset).

Usage:
    python3 -m pipeline.cli.chat [--server http://localhost:3456] [--new]

Options:
    --server URL    Coach server URL (default: http://localhost:3456)
    --new           Start a new session (discards previous session ID)
    --no-color      Disable color/markdown rendering

Environment:
    COACH_SERVER_URL   Override server URL
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import readline  # noqa: F401 — side effect: enables readline in input()
import shutil
import sys
import time
import urllib.request
import urllib.error
import uuid
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_SERVER = os.environ.get("COACH_SERVER_URL", "http://localhost:3456")
SESSION_FILE = Path.home() / ".priya" / "session_id"

# ANSI escape codes
_RESET   = "\033[0m"
_BOLD    = "\033[1m"
_DIM     = "\033[2m"
_CYAN    = "\033[36m"
_GREEN   = "\033[32m"
_YELLOW  = "\033[33m"
_RED     = "\033[31m"
_MAGENTA = "\033[35m"
_BLUE    = "\033[34m"


# ---------------------------------------------------------------------------
# Session persistence
# ---------------------------------------------------------------------------

def _load_session_id() -> str | None:
    try:
        return SESSION_FILE.read_text().strip() or None
    except FileNotFoundError:
        return None


def _save_session_id(session_id: str) -> None:
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    SESSION_FILE.write_text(session_id)


def _clear_session_id() -> None:
    try:
        SESSION_FILE.unlink()
    except FileNotFoundError:
        pass


def _new_session_id() -> str:
    return "cli-" + uuid.uuid4().hex[:16]


# ---------------------------------------------------------------------------
# Coach server calls (stdlib urllib — no requests dependency)
# ---------------------------------------------------------------------------

def _post_stream(server: str, session_id: str, message: str) -> None:
    """Stream tokens from /api/coach to stdout."""
    url = f"{server}/api/coach"
    payload = {"message": message, "session_id": session_id}
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                kind = event.get("type")
                if kind == "token":
                    sys.stdout.write(event.get("text", ""))
                    sys.stdout.flush()
                elif kind == "done":
                    break
                elif kind == "error":
                    _print_error(event.get("text", "Unknown error"))
                    break
    except urllib.error.URLError as e:
        _print_error(f"Cannot reach server at {server}: {e}")
        sys.exit(1)


def _post_reset(server: str, session_id: str) -> None:
    url = f"{server}/api/coach/reset"
    body = json.dumps({"session_id": session_id}).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=10)
    except urllib.error.URLError:
        pass


def _get_status(server: str, session_id: str) -> dict:
    url = f"{server}/api/coach/status?session_id={session_id}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, json.JSONDecodeError):
        return {}


def _get_commands(server: str) -> list[dict]:
    url = f"{server}/api/coach/commands"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read())
            return data.get("commands", [])
    except (urllib.error.URLError, json.JSONDecodeError):
        return []


def _health_check(server: str) -> bool:
    try:
        with urllib.request.urlopen(f"{server}/health", timeout=5) as resp:
            return resp.status == 200
    except urllib.error.URLError:
        return False


# ---------------------------------------------------------------------------
# Terminal helpers
# ---------------------------------------------------------------------------

_USE_COLOR = sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    return f"{code}{text}{_RESET}" if _USE_COLOR else text


def _print_error(msg: str) -> None:
    print(f"\n{_c(_RED, '⚠ Error:')} {msg}", file=sys.stderr)


def _print_header(server: str, session_id: str) -> None:
    term_width = shutil.get_terminal_size((80, 24)).columns
    print(_c(_BOLD, "━" * term_width))
    print(_c(_BOLD + _MAGENTA, "  Priya — Product Development Coach") +
          _c(_DIM, "  (Hoopla Digital)"))
    print(_c(_DIM, f"  Server: {server}   Session: {session_id[:12]}…"))
    print(_c(_BOLD, "━" * term_width))
    print(_c(_DIM, "  Type your product idea or question. /help for commands. Ctrl-D to quit.\n"))


def _render_markdown_plain(text: str) -> str:
    """Minimal markdown → plain text for non-rich mode."""
    import re
    # Strip bold/italic markers
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'`(.+?)`', r'\1', text)
    # Headings → uppercase
    text = re.sub(r'^#{1,4} (.+)$', lambda m: m.group(1).upper(), text, flags=re.M)
    return text


def _render_response(text: str, use_rich: bool) -> None:
    """Re-render the accumulated response text (after streaming is done)."""
    if not use_rich:
        return  # already printed token-by-token
    # rich import (optional)
    try:
        from rich.console import Console
        from rich.markdown import Markdown
        console = Console()
        console.print(Markdown(text))
    except ImportError:
        pass  # already streamed plain


def _print_status(status: dict) -> None:
    if not status:
        print(_c(_DIM, "  No active session."))
        return
    pct = int(status.get("completeness", 0) * 100)
    missing = status.get("missing", [])
    ready = status.get("ready_for_artifacts", False)
    bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
    print(f"\n  {_c(_BOLD, 'Completeness:')} {_c(_CYAN, bar)} {pct}%")
    if ready:
        print(f"  {_c(_GREEN, '✓')} Ready to generate artifacts. Type /generate")
    elif missing:
        chips = "  ".join(_c(_YELLOW, f) for f in missing)
        print(f"  {_c(_DIM, 'Missing:')} {chips}")
    print()


# ---------------------------------------------------------------------------
# Tab completion for slash commands
# ---------------------------------------------------------------------------

class _CommandCompleter:
    def __init__(self, commands: list[dict]) -> None:
        self._usages = [c.get("usage", c["command"]) for c in commands]

    def complete(self, text: str, state: int) -> str | None:
        if text.startswith("/"):
            matches = [u for u in self._usages if u.startswith(text)]
        else:
            matches = []
        return matches[state] if state < len(matches) else None


# ---------------------------------------------------------------------------
# Main REPL
# ---------------------------------------------------------------------------

def run(server: str, new_session: bool, no_color: bool) -> None:
    global _USE_COLOR
    if no_color:
        _USE_COLOR = False

    # Session management
    if new_session:
        _clear_session_id()
    session_id = _load_session_id()
    if not session_id:
        session_id = _new_session_id()
        _save_session_id(session_id)

    # Health check
    if not _health_check(server):
        print(_c(_RED, f"✗ Coach server not reachable at {server}"))
        print(_c(_DIM, "  Start it with: python3 -m pipeline.coach --port 3456"))
        sys.exit(1)

    # Tab completion
    commands = _get_commands(server)
    completer = _CommandCompleter(commands)
    readline.set_completer(completer.complete)
    readline.parse_and_bind("tab: complete")
    readline.set_completer_delims(" \t\n")

    _print_header(server, session_id)

    # Check if rich is available (for post-stream markdown rendering)
    use_rich = False
    try:
        import rich  # noqa: F401
        use_rich = _USE_COLOR
    except ImportError:
        pass

    while True:
        # User prompt
        try:
            prompt = _c(_BOLD + _BLUE, "You › ") if _USE_COLOR else "You › "
            user_input = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_input:
            continue

        # Local slash command handling
        if user_input == "/reset":
            _post_reset(server, session_id)
            _clear_session_id()
            session_id = _new_session_id()
            _save_session_id(session_id)
            print(_c(_DIM, "  Session reset. New session started.\n"))
            continue

        if user_input == "/status":
            status = _get_status(server, session_id)
            _print_status(status)
            continue

        if user_input in ("/quit", "/exit", "exit", "quit"):
            break

        # Print Priya label
        print(_c(_BOLD + _MAGENTA, "\nPriya › "), end="", flush=True)

        # Stream the response
        accumulated: list[str] = []
        url = f"{server}/api/coach"
        payload = {"message": user_input, "session_id": session_id}
        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    kind = event.get("type")
                    if kind == "token":
                        token = event.get("text", "")
                        accumulated.append(token)
                        if not use_rich:
                            sys.stdout.write(token)
                            sys.stdout.flush()
                    elif kind == "done":
                        break
                    elif kind == "error":
                        _print_error(event.get("text", "Unknown error"))
                        break

        except urllib.error.URLError as e:
            _print_error(f"Server error: {e}")
            continue

        full_response = "".join(accumulated)

        if use_rich:
            # Clear the "Priya › " prefix line and re-render with rich
            print()  # newline after the label
            _render_response(full_response, use_rich=True)
        else:
            print("\n")  # blank line after streamed response

        # Show completeness hint every 3 turns
        if hasattr(run, "_turn_count"):
            run._turn_count += 1
        else:
            run._turn_count = 1

        if run._turn_count % 3 == 0:
            status = _get_status(server, session_id)
            pct = int(status.get("completeness", 0) * 100)
            if pct > 0 and not status.get("ready_for_artifacts"):
                missing = status.get("missing", [])
                hint = f"  [{pct}% complete"
                if missing:
                    hint += f" — still need: {', '.join(missing)}"
                hint += "]"
                print(_c(_DIM, hint + "\n"))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Priya — Hoopla Coach terminal frontend",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--server",
        default=DEFAULT_SERVER,
        metavar="URL",
        help=f"Coach server URL (default: {DEFAULT_SERVER})",
    )
    parser.add_argument(
        "--new",
        action="store_true",
        help="Start a fresh session (discards saved session ID)",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable color output",
    )
    args = parser.parse_args()
    run(server=args.server, new_session=args.new, no_color=args.no_color)


if __name__ == "__main__":
    main()
