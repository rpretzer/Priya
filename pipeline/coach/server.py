"""Hoopla Coach HTTP server — Starlette + uvicorn.

Endpoints (v1):
    POST /api/v1/coach                              — streaming chat (NDJSON)
    POST /api/v1/coach/upload                       — file upload for multimodal input
    GET  /api/v1/coach/status                       — completeness status
    POST /api/v1/coach/reset                        — reset session + crystallize
    GET  /api/v1/coach/commands                     — available slash commands
    GET  /api/v1/coach/sessions/{sid}/artifacts     — list persisted artifacts
    GET  /health                                    — backend health check
    GET  /demo/*                                    — static demo UI (if --demo-dir set)

Legacy aliases at /api/coach/... are kept for backward compat with existing clients.

Session security:
    Sessions are HMAC-signed tokens: "{uuid}.{hmac_hex}".
    Set SESSION_SECRET env var (a strong random string).
    If unset, a random secret is generated per-process with a startup warning —
    this means sessions are invalidated on restart. Set it explicitly for production.

CORS:
    Set CORS_ORIGINS env var to a comma-separated list of allowed origins.
    Defaults to "*" (open) — restrict this for production.

Rate limiting:
    60 req/min per IP on /chat, 10/min on /upload (all endpoints share a 120/min global).

Logging:
    Structured JSON to stdout. Set LOG_LEVEL env var (default: INFO).
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
import traceback
import uuid
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.applications import Starlette
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from pipeline.coach.crystallizer import Crystallizer
from pipeline.coach.engine import CoachEngine
from pipeline.coach.memory import CoachMemory, generate_session_id

if TYPE_CHECKING:
    from pipeline.backends.base import AgentBackend


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

_LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data: dict = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        # Merge any extra fields passed via `extra=` kwarg
        for key, val in record.__dict__.items():
            if key not in (
                "name", "msg", "args", "levelname", "levelno", "pathname",
                "filename", "module", "exc_info", "exc_text", "stack_info",
                "lineno", "funcName", "created", "msecs", "relativeCreated",
                "thread", "threadName", "processName", "process", "message",
                "taskName",
            ):
                data[key] = val
        return json.dumps(data)


def _setup_logging() -> logging.Logger:
    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())
    logger = logging.getLogger("coach")
    logger.setLevel(_LOG_LEVEL)
    logger.addHandler(handler)
    logger.propagate = False
    return logger


log = _setup_logging()


# ---------------------------------------------------------------------------
# Session signing (HMAC)
# ---------------------------------------------------------------------------

_SESSION_SECRET: bytes = (
    os.environ.get("SESSION_SECRET", "").encode()
    or (lambda: (
        log.warning(
            "SESSION_SECRET not set — generating ephemeral secret. "
            "Sessions will be invalidated on restart. Set SESSION_SECRET for production."
        ),
        secrets.token_hex(32).encode(),
    )[-1])()
)


def _sign_session(session_id: str) -> str:
    """Return a signed session token: '{session_id}.{hmac_hex}'."""
    sig = hmac.new(_SESSION_SECRET, session_id.encode(), hashlib.sha256).hexdigest()[:24]
    return f"{session_id}.{sig}"


def _verify_session(token: str) -> str | None:
    """Verify and return the session_id from a signed token, or None if invalid."""
    if not token or "." not in token:
        return None
    # Split on last dot to handle UUIDs (which also contain hyphens but not dots)
    idx = token.rfind(".")
    session_id, sig = token[:idx], token[idx + 1:]
    expected = hmac.new(_SESSION_SECRET, session_id.encode(), hashlib.sha256).hexdigest()[:24]
    if hmac.compare_digest(expected, sig):
        return session_id
    return None


def _get_or_mint_session(token: str | None) -> tuple[str, str]:
    """Return (session_id, signed_token). Mints a new one if token is absent/invalid."""
    if token:
        session_id = _verify_session(token)
        if session_id:
            return session_id, token
    session_id = generate_session_id()
    return session_id, _sign_session(session_id)


# ---------------------------------------------------------------------------
# Session store — one CoachEngine per session (keyed by session_id)
# ---------------------------------------------------------------------------

_sessions: dict[str, CoachEngine] = {}
_sessions_lock = asyncio.Lock()

# Injected by create_app() before the server starts
_backend: "AgentBackend"
_memory: CoachMemory
_context_sources: list = []


async def _get_or_create_engine(session_id: str) -> CoachEngine:
    async with _sessions_lock:
        if session_id not in _sessions:
            memory_context = await run_in_threadpool(
                _memory.recall, query="", top_k=5
            )
            _sessions[session_id] = CoachEngine(
                backend=_backend,
                memory_context=memory_context,
                context_sources=_context_sources or None,
            )
        return _sessions[session_id]


async def _remove_session(session_id: str) -> CoachEngine | None:
    async with _sessions_lock:
        return _sessions.pop(session_id, None)


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------

limiter = Limiter(key_func=get_remote_address, default_limits=["120/minute"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class _AttachmentModel(BaseModel):
    type: str = "file"
    filename: str = ""
    content: str = ""


class _ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=32_000)
    session_token: str | None = None
    attachments: list[_AttachmentModel] | None = None


class _ResetRequest(BaseModel):
    session_token: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _json(status: int, data: dict, headers: dict | None = None) -> JSONResponse:
    return JSONResponse(data, status_code=status, headers=headers or {})


def _artifact_type_from_response(text: str) -> str | None:
    """Detect if the response contains a known artifact and return its type."""
    markers = {
        "business-case": ("# business-case.md", "## business-case.md"),
        "epics": ("# epics.md", "## epics.md"),
        "stories-draft": ("# stories-draft.md", "## stories-draft.md"),
    }
    lower = text.lower()
    for artifact_type, needles in markers.items():
        if any(n.lower() in lower for n in needles):
            return artifact_type
    return None


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------

async def health(request: Request) -> JSONResponse:
    ok = await run_in_threadpool(_backend.health_check)
    return _json(200 if ok else 503, {
        "status": "ok" if ok else "degraded",
        "backend": _backend.name,
    })


async def commands(request: Request) -> JSONResponse:
    from pipeline.coach.tools import COMMANDS
    return _json(200, {
        "commands": [
            {"command": cmd, "description": info.get("description", ""), "usage": info.get("usage", cmd)}
            for cmd, info in COMMANDS.items()
        ]
    })


async def status(request: Request) -> JSONResponse:
    token = request.query_params.get("session_token")
    session_id, signed = _get_or_mint_session(token)

    async with _sessions_lock:
        engine = _sessions.get(session_id)

    if engine is None:
        return _json(200, {
            "session_token": signed,
            "completeness": 0.0,
            "ready_for_artifacts": False,
            "fields": {},
            "missing": [],
        })

    tracker = engine.tracker
    return _json(200, {
        "session_token": signed,
        "completeness": tracker.completeness(),
        "ready_for_artifacts": tracker.is_ready_for_artifacts(),
        "fields": tracker.status_report(),
        "missing": tracker.missing_fields(),
    })


@limiter.limit("60/minute")
async def chat(request: Request) -> Response:
    try:
        body = await request.json()
        req = _ChatRequest.model_validate(body)
    except Exception:
        return _json(400, {"error": "invalid request body"})

    session_id, signed_token = _get_or_mint_session(req.session_token)
    engine = await _get_or_create_engine(session_id)

    attachments = [a.model_dump() for a in req.attachments] if req.attachments else None
    message = req.message
    turn_index = engine.turn_count

    t_start = time.monotonic()

    async def generate():
        accumulated: list[str] = []
        error_occurred = False
        try:
            async for chunk in iterate_in_threadpool(
                engine.chat_stream(message, attachments=attachments)
            ):
                accumulated.append(chunk)
                yield (json.dumps({"type": "token", "text": chunk}) + "\n").encode()

            full_response = "".join(accumulated)

            # Persist conversation turns
            await run_in_threadpool(_memory.save_turn, session_id, "user", message, turn_index)
            await run_in_threadpool(_memory.save_turn, session_id, "assistant", full_response, turn_index)

            # Persist artifact if detected
            artifact_type = _artifact_type_from_response(full_response)
            if artifact_type:
                await run_in_threadpool(_memory.save_artifact, session_id, artifact_type, full_response)

            duration_ms = int((time.monotonic() - t_start) * 1000)
            completeness = engine.tracker.completeness()

            log.info("chat", extra={
                "session_id": session_id,
                "turn": turn_index,
                "backend": _backend.name,
                "duration_ms": duration_ms,
                "completeness": round(completeness, 2),
                "prompt_tokens": len(message) // 4,  # rough estimate
            })

            yield (json.dumps({"type": "done"}) + "\n").encode()

        except Exception:
            error_occurred = True
            error_id = uuid.uuid4().hex[:8]
            log.error("chat_error", extra={
                "session_id": session_id,
                "error_id": error_id,
                "traceback": traceback.format_exc(),
            })
            yield (json.dumps({"type": "error", "error_id": error_id}) + "\n").encode()

    headers = {
        "X-Session-Token": signed_token,
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",  # disable nginx buffering for streaming
    }
    return StreamingResponse(generate(), media_type="application/x-ndjson", headers=headers)


@limiter.limit("10/minute")
async def upload(request: Request) -> JSONResponse:
    try:
        form = await request.form()
        file = form.get("file")
        if file is None:
            return _json(400, {"error": "no file field in form"})

        filename = getattr(file, "filename", "") or "upload"
        raw: bytes = await file.read()
    except Exception:
        return _json(400, {"error": "could not read upload"})

    try:
        text_content = raw.decode("utf-8", errors="replace")
    except Exception:
        text_content = "[Binary file — cannot display as text]"

    text_content = text_content[:50_000]
    return _json(200, {
        "filename": filename,
        "content": text_content,
        "attachment": {"type": "file", "filename": filename, "content": text_content},
    })


async def reset(request: Request) -> JSONResponse:
    try:
        body = await request.json()
        req = _ResetRequest.model_validate(body)
    except Exception:
        req = _ResetRequest()

    session_id, _ = _get_or_mint_session(req.session_token)
    engine = await _remove_session(session_id)

    if engine and engine.messages:
        crystallizer = Crystallizer()
        result = crystallizer.extract(engine.messages)
        if result.items:
            await run_in_threadpool(_memory.save_session, session_id, result)

    new_id = generate_session_id()
    new_token = _sign_session(new_id)
    return _json(200, {"status": "reset", "session_token": new_token})


async def get_artifacts(request: Request) -> JSONResponse:
    token = request.query_params.get("session_token")
    session_id, _ = _get_or_mint_session(token)
    artifacts = await run_in_threadpool(_memory.get_artifacts, session_id)
    return _json(200, {"session_id": session_id, "artifacts": artifacts})


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app(
    backend: "AgentBackend",
    demo_dir: str | None = None,
    memory_path: str | None = None,
    context_sources: list | None = None,
) -> Starlette:
    """Build and return the Starlette application.

    Separated from run_server() so tests can instantiate the app without
    starting a live server.

    Args:
        context_sources: Optional list of ContextSource instances for Phase 2 RAG.
            If provided, they are registered with each CoachEngine session.
    """
    global _backend, _memory, _context_sources
    _backend = backend
    _memory = CoachMemory(db_path=memory_path)
    _context_sources = context_sources or []

    v1_routes = [
        Route("/coach",            chat,         methods=["POST"]),
        Route("/coach/upload",     upload,       methods=["POST"]),
        Route("/coach/status",     status,       methods=["GET"]),
        Route("/coach/reset",      reset,        methods=["POST"]),
        Route("/coach/commands",   commands,     methods=["GET"]),
        Route("/coach/sessions/{session_id:str}/artifacts", get_artifacts, methods=["GET"]),
    ]

    routes = [
        Route("/health", health, methods=["GET"]),
        Mount("/api/v1", routes=v1_routes),
        # Legacy aliases — keep until all clients migrate to /api/v1/
        Route("/api/coach",          chat,     methods=["POST"]),
        Route("/api/coach/upload",   upload,   methods=["POST"]),
        Route("/api/coach/status",   status,   methods=["GET"]),
        Route("/api/coach/reset",    reset,    methods=["POST"]),
        Route("/api/coach/commands", commands, methods=["GET"]),
    ]

    if demo_dir and os.path.isdir(demo_dir):
        routes.append(Mount("/demo", app=StaticFiles(directory=demo_dir, html=True)))

    app = Starlette(routes=routes)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    cors_origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",")]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-Session-Token"],
        expose_headers=["X-Session-Token"],
    )

    return app


def run_server(
    backend: "AgentBackend",
    port: int = 3456,
    demo_dir: str | None = None,
    memory_path: str | None = None,
) -> None:
    """Start the Coach HTTP server. Blocks until interrupted."""
    import uvicorn
    app = create_app(backend, demo_dir=demo_dir, memory_path=memory_path)
    log.info("server_start", extra={"port": port, "backend": backend.name, "demo_dir": demo_dir})
    uvicorn.run(app, host="0.0.0.0", port=port, log_config=None)
