"""AgentBackend — abstract base class and shared types for all LLM backends.

All coaching logic (CoachEngine, ProgressTracker, SignalDetector) is provider-agnostic
and communicates with LLMs only through this interface. Never embed provider-specific
behavior in coaching components — put it here.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Generator


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class AgentResult:
    """Unified result from any backend chat/invoke call."""
    output: str
    success: bool
    error: str = ""
    duration_ms: int = 0
    model: str = ""
    token_usage: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Abstract backend
# ---------------------------------------------------------------------------

class AgentBackend(ABC):
    """Provider-agnostic LLM interface.

    Implement this for each backend (Ollama, llama.cpp, Bedrock, Anthropic API).
    CoachEngine only calls chat() and chat_stream(). invoke() is a simpler
    single-turn variant kept for compatibility and testing.
    """

    @abstractmethod
    def invoke(
        self,
        prompt: str,
        context: str = "",
        config: dict | None = None,
    ) -> AgentResult:
        """Single-turn prompt → response (no message history)."""
        ...

    @abstractmethod
    def chat(
        self,
        messages: list[dict],
        system: str = "",
        config: dict | None = None,
    ) -> AgentResult:
        """Multi-turn chat with optional system prompt. Blocking."""
        ...

    @abstractmethod
    def chat_stream(
        self,
        messages: list[dict],
        system: str = "",
        config: dict | None = None,
    ) -> Generator[str, None, None]:
        """Multi-turn chat, yields text chunks as they arrive."""
        ...

    @abstractmethod
    def health_check(self) -> bool:
        """Return True if the backend is reachable and ready."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable backend/model identifier for logging and UI."""
        ...


# ---------------------------------------------------------------------------
# Shared utility
# ---------------------------------------------------------------------------

def _extract_text(msg: dict) -> str:
    """Extract plain text from a message dict.

    Handles both simple string content and multimodal content lists
    (as produced by CoachEngine when attachments or images are present).

    Args:
        msg: A message dict with at least {"role": ..., "content": ...}

    Returns:
        Concatenated text from all text blocks, or "" if no text found.
    """
    content = msg.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""
