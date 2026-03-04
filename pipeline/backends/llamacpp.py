"""LlamaCppBackend — LLM backend using a llama.cpp server (Phase 1 target).

llama.cpp server exposes an OpenAI-compatible REST API. No special SDK needed —
all calls use stdlib urllib. This is the Phase 1 replacement for OllamaBackend.

Configuration (environment variables or constructor args):
    LLAMACPP_BASE_URL  — Server URL (default: http://localhost:8080)
    LLAMACPP_MODEL     — Model label for logging (default: "local", cosmetic only —
                         llama.cpp server loads one model at startup)

Start llama.cpp server:
    ./llama-server -m /path/to/model.gguf --port 8080 -c 4096 --host 0.0.0.0

With chat template (required for instruction-following models):
    ./llama-server -m /path/to/model.gguf --port 8080 -c 4096 \\
        --chat-template llama3 --host 0.0.0.0

Phase 1 target models (GGUF format):
    - Meta-Llama-3.1-8B-Instruct.Q5_K_M.gguf   (8B, runs on CPU+16GB RAM)
    - Meta-Llama-3.1-70B-Instruct.Q4_K_M.gguf  (70B, needs GPU)
    - Mistral-7B-Instruct-v0.3.Q5_K_M.gguf     (7B, fast on CPU)
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from .base import AgentBackend, AgentResult


class LlamaCppBackend(AgentBackend):
    """Backend for llama.cpp server (OpenAI-compatible /v1/chat/completions API).

    This is the Phase 1 target — replaces Ollama for production deployments.
    Uses only stdlib — no OpenAI SDK required.
    """

    DEFAULT_BASE_URL = "http://localhost:8080"
    DEFAULT_MODEL = "local"  # cosmetic; llama.cpp loads one model at startup

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
    ):
        # model is a label for logging only — llama.cpp ignores it
        self._model = model or os.environ.get("LLAMACPP_MODEL", self.DEFAULT_MODEL)
        self._base_url = (
            base_url or os.environ.get("LLAMACPP_BASE_URL", self.DEFAULT_BASE_URL)
        ).rstrip("/")

    @property
    def name(self) -> str:
        return f"llamacpp/{self._model}"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_messages(self, messages: list[dict], system: str) -> list[dict]:
        """Convert CoachEngine message format to OpenAI-compatible format.

        System prompt is injected as the first message with role "system".
        Multimodal content blocks are flattened to text (vision not in scope
        for Phase 1 llama.cpp deployment).
        """
        result: list[dict] = []
        if system:
            result.append({"role": "system", "content": system})
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, list):
                text = " ".join(
                    b.get("text", "")
                    for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                )
                result.append({"role": msg["role"], "content": text})
            else:
                result.append({"role": msg["role"], "content": content})
        return result

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
        oai_messages = self._build_messages(messages, system)
        body = {
            "model": self._model,
            "messages": oai_messages,
            "max_tokens": config.get("max_tokens", 2048),
            "temperature": config.get("temperature", 0.7),
            "stream": False,
        }
        start = time.monotonic()
        try:
            req = urllib.request.Request(
                f"{self._base_url}/v1/chat/completions",
                data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=300) as resp:
                data = json.loads(resp.read())
            duration_ms = int((time.monotonic() - start) * 1000)
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            return AgentResult(
                output=content,
                success=True,
                duration_ms=duration_ms,
                model=self._model,
                token_usage={
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
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
        """Stream via SSE (Server-Sent Events) as returned by llama.cpp server.

        Each line from the server looks like:
            data: {"choices":[{"delta":{"content":"Hello"}}],"done":false}
        Final line:
            data: [DONE]
        """
        config = config or {}
        oai_messages = self._build_messages(messages, system)
        body = {
            "model": self._model,
            "messages": oai_messages,
            "max_tokens": config.get("max_tokens", 2048),
            "temperature": config.get("temperature", 0.7),
            "stream": True,
        }
        req = urllib.request.Request(
            f"{self._base_url}/v1/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            for raw_line in resp:
                line = raw_line.strip()
                if not line:
                    continue
                # Strip SSE "data: " prefix
                if line.startswith(b"data: "):
                    line = line[6:]
                if line == b"[DONE]":
                    break
                try:
                    data = json.loads(line)
                    delta = data["choices"][0].get("delta", {})
                    chunk = delta.get("content", "")
                    if chunk:
                        yield chunk
                except (json.JSONDecodeError, KeyError, IndexError):
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
        """Check if the llama.cpp server is reachable.

        Tries /health first (newer llama.cpp versions), then /v1/models
        (OpenAI-compatible fallback).
        """
        for path in ("/health", "/v1/models"):
            try:
                req = urllib.request.Request(
                    f"{self._base_url}{path}", method="GET"
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    if resp.status == 200:
                        return True
            except Exception:
                continue
        return False
