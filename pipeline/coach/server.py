# AI-GENERATED: 2026-03-03T16:57:33Z | pipeline/coach/server.py | Copilot
"""Hoopla Coach HTTP server.

Endpoints:
    POST /api/coach          — streaming coaching chat (SSE / chunked)
    POST /api/coach/upload   — file upload for multimodal input
    GET  /api/coach/status   — completeness status for current session
    POST /api/coach/reset    — reset session state
    GET  /demo               — demo UI (if --demo-dir is set)
    GET  /health             — backend health check

Server is intentionally minimal (stdlib http.server + threading). No framework
dependency. Transport and routing changes do not require running test_hardening.py.
"""
from __future__ import annotations

import io
import json
import mimetypes
import os
import threading
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import TYPE_CHECKING

from pipeline.coach.engine import CoachEngine
from pipeline.coach.memory import CoachMemory, generate_session_id
from pipeline.coach.crystallizer import Crystallizer

if TYPE_CHECKING:
    from pipeline.backends.base import AgentBackend


# ---------------------------------------------------------------------------
# Session store — one CoachEngine per session (keyed by session_id cookie)
# ---------------------------------------------------------------------------

_sessions: dict[str, CoachEngine] = {}
_sessions_lock = threading.Lock()


def _get_or_create_engine(
    session_id: str,
    backend: "AgentBackend",
    memory: CoachMemory,
) -> CoachEngine:
    with _sessions_lock:
        if session_id not in _sessions:
            memory_context = memory.recall(query="", top_k=5)
            _sessions[session_id] = CoachEngine(
                backend=backend,
                memory_context=memory_context,
            )
        return _sessions[session_id]


def _remove_session(session_id: str) -> CoachEngine | None:
    with _sessions_lock:
        return _sessions.pop(session_id, None)


# ---------------------------------------------------------------------------
# Request handler
# ---------------------------------------------------------------------------

class CoachHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the Coach server."""

    # Injected by run_server before starting HTTPServer
    backend: "AgentBackend"
    memory: CoachMemory
    demo_dir: str | None

    def log_message(self, format_str, *args):
        # Suppress default access log to keep output clean; errors still print
        pass

    def _session_id(self) -> str:
        """Extract or create a session_id from the Cookie header."""
        cookie_header = self.headers.get("Cookie", "")
        for part in cookie_header.split(";"):
            part = part.strip()
            if part.startswith("session_id="):
                return part[len("session_id="):]
        return generate_session_id()

    def _send_json(self, status: int, data: dict) -> None:
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_ndjson(self, data: dict) -> None:
        """Write one NDJSON line."""
        self.wfile.write((json.dumps(data) + "\n").encode())
        self.wfile.flush()

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length) if length > 0 else b""

    # ------------------------------------------------------------------
    # Route dispatch
    # ------------------------------------------------------------------

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Cookie")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path == "/health":
            self._handle_health()
        elif path == "/api/coach/status":
            self._handle_status()
        elif path == "/api/coach/commands":
            self._handle_commands()
        elif path.startswith("/demo") and self.demo_dir:
            self._handle_demo(path)
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path == "/api/coach":
            self._handle_chat()
        elif path == "/api/coach/upload":
            self._handle_upload()
        elif path == "/api/coach/reset":
            self._handle_reset()
        else:
            self._send_json(404, {"error": "not found"})

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _handle_health(self) -> None:
        ok = self.backend.health_check()
        self._send_json(200 if ok else 503, {
            "status": "ok" if ok else "degraded",
            "backend": self.backend.name,
        })

    def _handle_commands(self) -> None:
        from pipeline.coach.tools import COMMANDS
        commands = [
            {
                "command": cmd,
                "description": info.get("description", ""),
                "usage": info.get("usage", cmd),
            }
            for cmd, info in COMMANDS.items()
        ]
        self._send_json(200, {"commands": commands})

    def _handle_status(self) -> None:
        session_id = self._session_id()
        with _sessions_lock:
            engine = _sessions.get(session_id)
        if engine is None:
            self._send_json(200, {
                "session_id": session_id,
                "completeness": 0.0,
                "ready_for_artifacts": False,
                "fields": {},
                "missing": [],
            })
            return
        tracker = engine.tracker
        self._send_json(200, {
            "session_id": session_id,
            "completeness": tracker.completeness(),
            "ready_for_artifacts": tracker.is_ready_for_artifacts(),
            "fields": tracker.status_report(),
            "missing": tracker.missing_fields(),
        })

    def _handle_chat(self) -> None:
        body = self._read_body()
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid JSON"})
            return

        message = data.get("message", "").strip()
        if not message:
            self._send_json(400, {"error": "message is required"})
            return

        attachments = data.get("attachments")
        session_id = data.get("session_id") or self._session_id()

        engine = _get_or_create_engine(session_id, self.backend, self.memory)

        # Stream NDJSON response — one JSON object per line
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("X-Session-Id", session_id)
        self.end_headers()

        try:
            for chunk in engine.chat_stream(message, attachments=attachments):
                self._send_ndjson({"type": "token", "text": chunk})
            self._send_ndjson({"type": "done"})
        except Exception:
            err = traceback.format_exc()
            self._send_ndjson({"type": "error", "text": err})

    def _handle_upload(self) -> None:
        """Accept a file upload and return its text content for use as an attachment."""
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            self._send_json(400, {"error": "expected multipart/form-data"})
            return

        body = self._read_body()
        # Parse multipart boundary
        boundary = None
        for part in content_type.split(";"):
            part = part.strip()
            if part.startswith("boundary="):
                boundary = part[len("boundary="):].strip()
                break

        if not boundary:
            self._send_json(400, {"error": "missing boundary in Content-Type"})
            return

        # Simple multipart parser — extracts first file part
        filename, file_content = _parse_multipart(body, boundary)
        if file_content is None:
            self._send_json(400, {"error": "no file found in upload"})
            return

        # Attempt to decode as text
        try:
            text_content = file_content.decode("utf-8", errors="replace")
        except Exception:
            text_content = "[Binary file — cannot display as text]"

        self._send_json(200, {
            "filename": filename,
            "content": text_content[:50_000],  # cap at 50k chars
            "attachment": {
                "type": "file",
                "filename": filename,
                "content": text_content[:50_000],
            },
        })

    def _handle_reset(self) -> None:
        body = self._read_body()
        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            data = {}

        session_id = data.get("session_id") or self._session_id()
        engine = _remove_session(session_id)

        # Save any learnings from the session before discarding it
        if engine and engine.messages:
            crystallizer = Crystallizer()
            result = crystallizer.extract(engine.messages)
            if result.items:
                self.memory.save_session(session_id, result)

        self._send_json(200, {"status": "reset", "session_id": session_id})

    def _handle_demo(self, path: str) -> None:
        """Serve static files from demo_dir."""
        if path == "/demo" or path == "/demo/":
            rel = "index.html"
        else:
            rel = path[len("/demo/"):]

        file_path = os.path.join(self.demo_dir, rel)
        if not os.path.isfile(file_path):
            self._send_json(404, {"error": f"demo file not found: {rel}"})
            return

        mime_type, _ = mimetypes.guess_type(file_path)
        mime_type = mime_type or "application/octet-stream"

        with open(file_path, "rb") as f:
            content = f.read()

        self.send_response(200)
        self.send_header("Content-Type", mime_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


# ---------------------------------------------------------------------------
# Multipart parser (stdlib only)
# ---------------------------------------------------------------------------

def _parse_multipart(body: bytes, boundary: str) -> tuple[str, bytes | None]:
    """Extract the first file part from a multipart body.

    Returns (filename, content_bytes). filename is "" if not found.
    content_bytes is None if parsing failed.
    """
    boundary_bytes = ("--" + boundary).encode()
    parts = body.split(boundary_bytes)
    for part in parts[1:]:  # skip preamble
        if part.startswith(b"--"):
            break  # epilogue
        # Split headers from body
        if b"\r\n\r\n" in part:
            headers_raw, content = part.split(b"\r\n\r\n", 1)
        elif b"\n\n" in part:
            headers_raw, content = part.split(b"\n\n", 1)
        else:
            continue
        # Strip trailing boundary marker
        content = content.rstrip(b"\r\n")

        headers_str = headers_raw.decode("utf-8", errors="replace")
        filename = ""
        for line in headers_str.splitlines():
            if "Content-Disposition" in line and "filename=" in line:
                for token in line.split(";"):
                    token = token.strip()
                    if token.startswith("filename="):
                        filename = token[len("filename="):].strip().strip('"')
                        break

        return filename, content

    return "", None


# ---------------------------------------------------------------------------
# Server entry point
# ---------------------------------------------------------------------------

def run_server(
    backend: "AgentBackend",
    port: int = 3456,
    demo_dir: str | None = None,
    memory_path: str | None = None,
) -> None:
    """Start the Coach HTTP server. Blocks until interrupted."""
    memory = CoachMemory(db_path=memory_path)

    # Inject backend, memory, and demo_dir into the handler class
    # (HTTPServer passes no constructor args to handlers)
    CoachHandler.backend = backend
    CoachHandler.memory = memory
    CoachHandler.demo_dir = demo_dir

    server = HTTPServer(("", port), CoachHandler)
    print(f"Hoopla Coach server running on http://localhost:{port}")
    print(f"Backend: {backend.name}")
    if demo_dir:
        print(f"Demo UI: http://localhost:{port}/demo")
    print("Press Ctrl+C to stop.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        server.server_close()
