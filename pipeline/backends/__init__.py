"""pipeline.backends — provider-agnostic LLM backend interface.

All coaching logic (CoachEngine, ProgressTracker, SignalDetector) is backend-agnostic.
LLM calls go through AgentBackend.chat() and AgentBackend.chat_stream() only.

Available backends:
    ollama    — Local Ollama server (current default)
    llamacpp  — llama.cpp server, OpenAI-compatible API (Phase 1 target)
    bedrock   — AWS Bedrock Converse API (Claude models)
    assisted  — Anthropic API directly (development / hardening tests)
    agentcore — AWS Bedrock AgentCore (delegates to bedrock for now)

Usage:
    from pipeline.backends import get_backend, AgentBackend, AgentResult

    backend = get_backend("ollama", model="llama3.1:8b")
    result  = backend.chat(messages, system="...")

Adding a new backend:
    1. Implement AgentBackend in a new module under pipeline/backends/
    2. Register it in get_backend() below
    3. Add the CLI choice to pipeline/coach/__main__.py
    4. Run test_hardening.py against the new backend
    5. Do NOT modify CoachEngine, ProgressTracker, SignalDetector, or ContextAssembler
"""
from .base import AgentBackend, AgentResult, _extract_text
from .ollama import OllamaBackend
from .llamacpp import LlamaCppBackend
from .bedrock import BedrockBackend
from .assisted import AssistedBackend


def get_backend(name: str, **kwargs) -> AgentBackend:
    """Instantiate a backend by name.

    Args:
        name:    Backend identifier. One of: ollama, llamacpp, bedrock,
                 assisted, agentcore.
        **kwargs: Passed to the backend constructor. Common kwargs:
                  model (str), base_url (str for ollama/llamacpp),
                  region (str for bedrock).

    Returns:
        Configured AgentBackend instance.

    Raises:
        ValueError: Unknown backend name.
    """
    backends: dict[str, type] = {
        "ollama": OllamaBackend,
        "llamacpp": LlamaCppBackend,
        "bedrock": BedrockBackend,
        "assisted": AssistedBackend,
        # agentcore: AWS Bedrock Agents — delegates to BedrockBackend for now.
        # Phase 4 will introduce a proper AgentCore wrapper.
        "agentcore": BedrockBackend,
    }
    cls = backends.get(name)
    if cls is None:
        raise ValueError(
            f"Unknown backend: {name!r}. "
            f"Choose from: {', '.join(sorted(backends))}"
        )
    return cls(**kwargs)


__all__ = [
    # Core types — imported by CoachEngine, ProgressTracker, test_hardening
    "AgentBackend",
    "AgentResult",
    "_extract_text",
    # Backend classes — imported by test_hardening for OllamaBackend live tests
    "OllamaBackend",
    "LlamaCppBackend",
    "BedrockBackend",
    "AssistedBackend",
    # Factory — imported by server.py
    "get_backend",
]
