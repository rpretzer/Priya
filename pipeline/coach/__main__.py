"""CLI entry point for Hoopla Coach.

Usage:
    python3 -m pipeline.coach [options]

Options:
    --port PORT         HTTP port for the coaching server (default: 3456)
    --backend BACKEND   LLM backend to use: ollama, llamacpp, bedrock, assisted, agentcore
    --model MODEL       Model name/path (backend-specific)
    --demo-dir DIR      Directory of demo fixture files for the demo UI
    --memory-path PATH  Path to SQLite memory database (default: ~/.hoopla/memory.db)
    --workers N         Number of uvicorn worker processes (default: 1)
"""
from __future__ import annotations

import argparse
import os
import sys


# ---------------------------------------------------------------------------
# Startup env validation — fail fast with clear messages
# ---------------------------------------------------------------------------

_REQUIRED_BY_BACKEND: dict[str, list[tuple[str, str]]] = {
    "assisted": [
        ("ANTHROPIC_API_KEY", "Anthropic API key — get one at console.anthropic.com"),
    ],
    "bedrock": [],   # boto3 handles its own credential validation
    "ollama": [],
    "llamacpp": [],
    "agentcore": [],
}


def _validate_env(backend_name: str) -> None:
    """Check required env vars for the chosen backend. Exit with a clear message if missing."""
    missing = [
        (var, desc)
        for var, desc in _REQUIRED_BY_BACKEND.get(backend_name, [])
        if not os.environ.get(var)
    ]
    if missing:
        lines = [f"ERROR: Missing required environment variables for --backend={backend_name}:"]
        for var, desc in missing:
            lines.append(f"  {var}  ({desc})")
        print("\n".join(lines), file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m pipeline.coach",
        description="Hoopla Coach — Priya Desai spec-funnel coaching server",
    )
    parser.add_argument("--port", type=int, default=3456,
                        help="HTTP port (default: 3456)")
    parser.add_argument("--backend", default="ollama",
                        choices=["ollama", "llamacpp", "bedrock", "assisted", "agentcore"],
                        help="LLM backend (default: ollama)")
    parser.add_argument("--model", default=None,
                        help="Model name/path, backend-specific")
    parser.add_argument("--demo-dir", default=None, dest="demo_dir",
                        help="Directory of demo fixture files for the demo UI")
    parser.add_argument("--memory-path", default=None, dest="memory_path",
                        help="Path to SQLite memory database (default: ~/.hoopla/memory.db)")
    parser.add_argument("--workers", type=int, default=1,
                        help="Number of uvicorn worker processes (default: 1)")
    return parser


# ---------------------------------------------------------------------------
# Backend factory
# ---------------------------------------------------------------------------

def _build_backend(backend_name: str, model: str | None):
    """Instantiate the requested AgentBackend."""
    if backend_name == "ollama":
        from pipeline.backends.ollama import OllamaBackend
        return OllamaBackend(model=model)
    elif backend_name == "llamacpp":
        try:
            from pipeline.backends.llamacpp import LlamaCppBackend
            return LlamaCppBackend(model_path=model)
        except ImportError:
            print("ERROR: llamacpp backend not available. Check pipeline/backends/llamacpp.py.",
                  file=sys.stderr)
            sys.exit(1)
    elif backend_name == "bedrock":
        try:
            from pipeline.backends.bedrock import BedrockBackend
            return BedrockBackend(model=model)
        except ImportError:
            print("ERROR: bedrock backend not available. Run: pip install boto3",
                  file=sys.stderr)
            sys.exit(1)
    elif backend_name == "assisted":
        try:
            from pipeline.backends.assisted import AssistedBackend
            return AssistedBackend(model=model)
        except ImportError:
            print("ERROR: assisted backend not available. Run: pip install anthropic",
                  file=sys.stderr)
            sys.exit(1)
    elif backend_name == "agentcore":
        try:
            from pipeline.backends.agentcore import AgentCoreBackend
            return AgentCoreBackend(model=model)
        except ImportError:
            print("ERROR: agentcore backend not available.", file=sys.stderr)
            sys.exit(1)
    else:
        print(f"ERROR: Unknown backend '{backend_name}'", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    _validate_env(args.backend)
    backend = _build_backend(args.backend, args.model)

    from pipeline.coach.server import create_app
    import uvicorn

    app = create_app(backend, demo_dir=args.demo_dir, memory_path=args.memory_path)
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=args.port,
        workers=args.workers,
        log_config=None,  # we handle our own JSON logging
    )


if __name__ == "__main__":
    main()
