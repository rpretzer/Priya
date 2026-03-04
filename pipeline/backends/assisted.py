"""AssistedBackend — direct Anthropic API backend (development and assisted testing).

"Assisted" means Claude API access without going through AWS infrastructure.
Useful for:
  - Local development without a running Ollama/llama.cpp instance
  - Running test_hardening.py --live against the actual Claude model
  - Benchmarking Priya's behavioral contract against the model she's tuned for

Configuration:
    ANTHROPIC_API_KEY  — API key (required)
    ANTHROPIC_MODEL    — Model ID (default: claude-sonnet-4-6)

Requires:
    pip install anthropic>=0.40.0
"""
from __future__ import annotations

import os
import time

from .base import AgentBackend, AgentResult


class AssistedBackend(AgentBackend):
    """Anthropic Claude API backend.

    Uses the anthropic Python SDK. Supports streaming and multimodal inputs
    (text + images) natively.

    The default model (claude-sonnet-4-6) matches the model Priya's behavioral
    contract is tested against. For architectural reasoning tasks, use Opus.
    """

    DEFAULT_MODEL = "claude-sonnet-4-6"

    def __init__(self, model: str | None = None):
        self._model = model or os.environ.get("ANTHROPIC_MODEL", self.DEFAULT_MODEL)
        self._client = None  # lazy-initialized

    @property
    def name(self) -> str:
        return f"assisted/{self._model}"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_client(self):
        if self._client is None:
            try:
                import anthropic
            except ImportError:
                raise RuntimeError(
                    "anthropic not installed. Run: pip install anthropic"
                )
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                raise RuntimeError(
                    "ANTHROPIC_API_KEY environment variable not set. "
                    "Get an API key at https://console.anthropic.com/"
                )
            self._client = anthropic.Anthropic(api_key=api_key)
        return self._client

    def _build_api_messages(self, messages: list[dict]) -> list[dict]:
        """Convert CoachEngine message format to Anthropic API format.

        Passes multimodal content blocks through unchanged (CoachEngine already
        formats images as {"type": "image", "source": {"type": "base64", ...}}).
        """
        api_messages: list[dict] = []
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, list):
                # Multimodal — pass through, convert text strings to blocks if needed
                blocks: list[dict] = []
                for block in content:
                    if isinstance(block, dict):
                        blocks.append(block)
                    else:
                        blocks.append({"type": "text", "text": str(block)})
                api_messages.append({"role": msg["role"], "content": blocks})
            else:
                api_messages.append({"role": msg["role"], "content": content})
        return api_messages

    # ------------------------------------------------------------------
    # Backend interface
    # ------------------------------------------------------------------

    def chat(
        self,
        messages: list[dict],
        system: str = "",
        config: dict | None = None,
    ) -> AgentResult:
        config = config or {}
        start = time.monotonic()
        try:
            client = self._get_client()
            api_messages = self._build_api_messages(messages)
            kwargs: dict = {
                "model": self._model,
                "max_tokens": config.get("max_tokens", 2048),
                "messages": api_messages,
            }
            if system:
                kwargs["system"] = system

            response = client.messages.create(**kwargs)
            duration_ms = int((time.monotonic() - start) * 1000)
            content = response.content[0].text
            usage = response.usage
            return AgentResult(
                output=content,
                success=True,
                duration_ms=duration_ms,
                model=self._model,
                token_usage={
                    "prompt_tokens": usage.input_tokens,
                    "completion_tokens": usage.output_tokens,
                },
            )
        except Exception as e:
            duration_ms = int((time.monotonic() - start) * 1000)
            return AgentResult(
                output="",
                success=False,
                error=str(e),
                duration_ms=duration_ms,
                model=self._model,
            )

    def chat_stream(
        self,
        messages: list[dict],
        system: str = "",
        config: dict | None = None,
    ) -> None:
        config = config or {}
        client = self._get_client()
        api_messages = self._build_api_messages(messages)
        kwargs: dict = {
            "model": self._model,
            "max_tokens": config.get("max_tokens", 2048),
            "messages": api_messages,
        }
        if system:
            kwargs["system"] = system

        with client.messages.stream(**kwargs) as stream:
            for text in stream.text_stream:
                yield text

    def invoke(
        self,
        prompt: str,
        context: str = "",
        config: dict | None = None,
    ) -> AgentResult:
        messages = [{"role": "user", "content": prompt}]
        return self.chat(messages, system=context, config=config)

    def health_check(self) -> bool:
        """Check that the API key is present and valid format."""
        try:
            client = self._get_client()
            return bool(client.api_key) and len(client.api_key) > 10
        except Exception:
            return False
