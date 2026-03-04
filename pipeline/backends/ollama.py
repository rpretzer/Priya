"""OllamaBackend — LLM backend using a local Ollama server.

Configuration (environment variables or constructor args):
    OLLAMA_BASE_URL  — Ollama server URL (default: http://localhost:11434)
    OLLAMA_MODEL     — Model to use (default: llama3.1:8b)

Start Ollama:
    ollama serve
    ollama pull llama3.1:8b
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from .base import AgentBackend, AgentResult


class OllamaBackend(AgentBackend):
    """Backend for a locally-running Ollama server.

    Uses the Ollama native /api/chat endpoint (not OpenAI-compatible).
    Streaming via NDJSON response.
    """

    DEFAULT_MODEL = "llama3.1:8b"
    DEFAULT_BASE_URL = "http://localhost:11434"

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
    ):
        self._model = model or os.environ.get("OLLAMA_MODEL", self.DEFAULT_MODEL)
        self._base_url = (
            base_url or os.environ.get("OLLAMA_BASE_URL", self.DEFAULT_BASE_URL)
        ).rstrip("/")

    @property
    def name(self) -> str:
        return f"ollama/{self._model}"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_messages(self, messages: list[dict], system: str) -> list[dict]:
        """Convert CoachEngine message format to Ollama format.

        Ollama accepts {"role": "system"|"user"|"assistant", "content": str}.
        Multimodal blocks are flattened to text-only (Ollama vision is handled
        separately via the 'images' field, not needed for the Coach use case).
        """
        result: list[dict] = []
        if system:
            result.append({"role": "system", "content": system})
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, list):
                # Flatten multimodal to text for Ollama
                text = " ".join(
                    b.get("text", "")
                    for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                )
                result.append({"role": msg["role"], "content": text})
            else:
                result.append({"role": msg["role"], "content": content})
        return result

    def _post(self, endpoint: str, body: dict, timeout: int = 300) -> urllib.request.Request:
        data = json.dumps(body).encode()
        return urllib.request.Request(
            f"{self._base_url}{endpoint}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

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
        ollama_msgs = self._build_messages(messages, system)
        body = {
            "model": self._model,
            "messages": ollama_msgs,
            "stream": False,
            "options": {
                "num_predict": config.get("max_tokens", 2048),
                "temperature": config.get("temperature", 0.7),
            },
        }
        start = time.monotonic()
        try:
            req = self._post("/api/chat", body)
            with urllib.request.urlopen(req, timeout=300) as resp:
                data = json.loads(resp.read())
            duration_ms = int((time.monotonic() - start) * 1000)
            content = data.get("message", {}).get("content", "")
            return AgentResult(
                output=content,
                success=True,
                duration_ms=duration_ms,
                model=self._model,
                token_usage={
                    "prompt_tokens": data.get("prompt_eval_count", 0),
                    "completion_tokens": data.get("eval_count", 0),
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
        ollama_msgs = self._build_messages(messages, system)
        body = {
            "model": self._model,
            "messages": ollama_msgs,
            "stream": True,
            "options": {
                "num_predict": config.get("max_tokens", 2048),
                "temperature": config.get("temperature", 0.7),
            },
        }
        req = self._post("/api/chat", body)
        with urllib.request.urlopen(req, timeout=300) as resp:
            for raw_line in resp:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    chunk = data.get("message", {}).get("content", "")
                    if chunk:
                        yield chunk
                    if data.get("done"):
                        break
                except json.JSONDecodeError:
                    continue

    def invoke(
        self,
        prompt: str,
        context: str = "",
        config: dict | None = None,
    ) -> AgentResult:
        messages = []
        if context:
            messages.append({"role": "system", "content": context})
        messages.append({"role": "user", "content": prompt})
        return self.chat(messages, config=config)

    def health_check(self) -> bool:
        try:
            req = urllib.request.Request(
                f"{self._base_url}/api/tags", method="GET"
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except Exception:
            return False
