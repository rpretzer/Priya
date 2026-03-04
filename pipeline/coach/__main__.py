# AI-GENERATED: 2026-03-03T16:57:33Z | pipeline/coach/__main__.py | Copilot
"""CLI entry point for Hoopla Coach.

Usage:
    python3 -m pipeline.coach [options]

Options:
    --port PORT         HTTP port for the coaching server (default: 3456)
    --backend BACKEND   LLM backend to use: ollama, llamacpp, bedrock, assisted, agentcore
    --model MODEL       Model name/path (backend-specific)
    --demo-dir DIR      Directory of demo fixture files for the demo UI
    --memory-path PATH  Path to SQLite memory database (default: ~/.hoopla/memory.db)
"""
from __future__ import annotations

import argparse
import sys


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m pipeline.coach",
        description="Hoopla Coach — Priya Desai spec-funnel coaching server",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=3456,
        help="HTTP port for the coaching server (default: 3456)",
    )
    parser.add_argument(
        "--backend",
        default="ollama",
        choices=["ollama", "llamacpp", "bedrock", "assisted", "agentcore"],
        help="LLM backend to use (default: ollama)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model name or path, backend-specific (e.g. llama3.1:8b for ollama)",
    )
    parser.add_argument(
        "--demo-dir",
        default=None,
        dest="demo_dir",
        help="Directory of demo fixture files for the demo UI",
    )
    parser.add_argument(
        "--memory-path",
        default=None,
        dest="memory_path",
        help="Path to SQLite memory database (default: ~/.hoopla/memory.db)",
    )
    return parser


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
            print(
                "ERROR: llamacpp backend not available. "
                "Install llama-cpp-python or check pipeline/backends/llamacpp.py.",
                file=sys.stderr,
            )
            sys.exit(1)
    elif backend_name == "bedrock":
        try:
            from pipeline.backends.bedrock import BedrockBackend
            return BedrockBackend(model=model)
        except ImportError:
            print(
                "ERROR: bedrock backend not available. Install boto3.",
                file=sys.stderr,
            )
            sys.exit(1)
    elif backend_name == "assisted":
        try:
            from pipeline.backends.assisted import AssistedBackend
            return AssistedBackend(model=model)
        except ImportError:
            print(
                "ERROR: assisted backend not available.",
                file=sys.stderr,
            )
            sys.exit(1)
    elif backend_name == "agentcore":
        try:
            from pipeline.backends.agentcore import AgentCoreBackend
            return AgentCoreBackend(model=model)
        except ImportError:
            print(
                "ERROR: agentcore backend not available.",
                file=sys.stderr,
            )
            sys.exit(1)
    else:
        print(f"ERROR: Unknown backend '{backend_name}'", file=sys.stderr)
        sys.exit(1)


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    backend = _build_backend(args.backend, args.model)

    from pipeline.coach.server import run_server
    run_server(
        backend=backend,
        port=args.port,
        demo_dir=args.demo_dir,
        memory_path=args.memory_path,
    )


if __name__ == "__main__":
    main()
