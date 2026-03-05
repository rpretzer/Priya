"""BedrockBackend — Claude models via AWS Bedrock Converse API.

Uses the newer Converse API (not InvokeModel) which provides a consistent
interface across model providers and native streaming support.

Configuration (environment variables or constructor args):
    AWS_REGION       — AWS region (default: us-east-1)
    AWS_PROFILE      — AWS profile name (optional, for local dev)
    BEDROCK_MODEL    — Model ID (default: anthropic.claude-3-5-haiku-20241022-v1:0)

Available models (from config-coach-auth.js):
    anthropic.claude-3-5-haiku-20241022-v1:0    — Fast, cost-effective (recommended)
    anthropic.claude-3-5-sonnet-20241022-v2:0   — Balanced
    anthropic.claude-opus-4-1-20250805-v1:0     — Most capable (architectural reasoning)

Requires:
    pip install boto3>=1.34.0
    AWS credentials configured (IAM role, ~/.aws/credentials, or env vars)
"""
from __future__ import annotations

import os
import time

from .base import AgentBackend, AgentResult


def _retry(fn, *, max_attempts: int = 3, base_delay: float = 1.0):
    """Call fn(), retrying on throttling and transient errors with exponential backoff."""
    _RETRYABLE_CODES = {"ThrottlingException", "ServiceUnavailableException", "RequestTimeout"}
    last_exc: Exception | None = None
    delay = base_delay
    for attempt in range(max_attempts):
        try:
            return fn()
        except Exception as exc:
            # Retry on boto3 throttling / transient errors; re-raise everything else
            code = getattr(getattr(exc, "response", None), "Error", {}).get("Code", "") \
                if hasattr(exc, "response") else ""
            if not code:
                try:
                    code = exc.response["Error"]["Code"]  # type: ignore[index]
                except Exception:
                    code = ""
            if code in _RETRYABLE_CODES or isinstance(exc, (ConnectionError, TimeoutError)):
                last_exc = exc
                if attempt < max_attempts - 1:
                    time.sleep(delay)
                    delay *= 2
            else:
                raise
    raise last_exc  # type: ignore[misc]


class BedrockBackend(AgentBackend):
    """AWS Bedrock backend using the Converse API.

    Supports streaming via converse_stream(). Handles multimodal inputs
    (text + images) using Bedrock's native content block format.
    """

    DEFAULT_MODEL = "anthropic.claude-3-5-haiku-20241022-v1:0"

    def __init__(
        self,
        model: str | None = None,
        region: str | None = None,
    ):
        self._model = model or os.environ.get("BEDROCK_MODEL", self.DEFAULT_MODEL)
        self._region = region or os.environ.get("AWS_REGION", "us-east-1")
        self._client = None  # lazy-initialized

    @property
    def name(self) -> str:
        return f"bedrock/{self._model}"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_client(self):
        if self._client is None:
            try:
                import boto3
            except ImportError:
                raise RuntimeError(
                    "boto3 not installed. Run: pip install boto3"
                )
            session_kwargs: dict = {}
            if profile := os.environ.get("AWS_PROFILE"):
                session_kwargs["profile_name"] = profile
            session = boto3.Session(**session_kwargs)
            self._client = session.client(
                "bedrock-runtime", region_name=self._region
            )
        return self._client

    def _build_converse_messages(
        self, messages: list[dict], system: str, config: dict
    ) -> tuple[list[dict], list[dict] | None]:
        """Build (converse_messages, system_blocks) for Bedrock Converse API.

        Returns a tuple of (messages_list, system_list_or_None).
        """
        converse_messages: list[dict] = []
        for msg in messages:
            role = msg["role"]
            content = msg.get("content", "")
            if isinstance(content, list):
                # Multimodal content
                blocks: list[dict] = []
                for block in content:
                    if block.get("type") == "text":
                        blocks.append({"text": block["text"]})
                    elif block.get("type") == "image":
                        src = block.get("source", {})
                        media_type = src.get("media_type", "image/png")
                        img_format = media_type.split("/")[-1]
                        blocks.append({
                            "image": {
                                "format": img_format,
                                "source": {
                                    "bytes": src.get("data", "").encode()
                                    if isinstance(src.get("data"), str)
                                    else src.get("data", b""),
                                },
                            }
                        })
                converse_messages.append({"role": role, "content": blocks})
            else:
                converse_messages.append(
                    {"role": role, "content": [{"text": content}]}
                )

        system_blocks = [{"text": system}] if system else None
        return converse_messages, system_blocks

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
            converse_msgs, system_blocks = self._build_converse_messages(
                messages, system, config
            )
            kwargs: dict = {
                "modelId": self._model,
                "messages": converse_msgs,
                "inferenceConfig": {
                    "maxTokens": config.get("max_tokens", 2048),
                    "temperature": config.get("temperature", 0.7),
                },
            }
            if system_blocks:
                kwargs["system"] = system_blocks

            response = _retry(lambda: client.converse(**kwargs))
            duration_ms = int((time.monotonic() - start) * 1000)
            content = response["output"]["message"]["content"][0]["text"]
            usage = response.get("usage", {})
            return AgentResult(
                output=content,
                success=True,
                duration_ms=duration_ms,
                model=self._model,
                token_usage={
                    "prompt_tokens": usage.get("inputTokens", 0),
                    "completion_tokens": usage.get("outputTokens", 0),
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
        converse_msgs, system_blocks = self._build_converse_messages(
            messages, system, config
        )
        kwargs: dict = {
            "modelId": self._model,
            "messages": converse_msgs,
            "inferenceConfig": {
                "maxTokens": config.get("max_tokens", 2048),
                "temperature": config.get("temperature", 0.7),
            },
        }
        if system_blocks:
            kwargs["system"] = system_blocks

        response = client.converse_stream(**kwargs)
        event_stream = response.get("stream")
        if not event_stream:
            return
        for event in event_stream:
            if "contentBlockDelta" in event:
                delta = event["contentBlockDelta"].get("delta", {})
                text = delta.get("text", "")
                if text:
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
        """Check AWS credentials and Bedrock reachability."""
        try:
            import boto3
            session = boto3.Session()
            bedrock = session.client("bedrock", region_name=self._region)
            # list_foundation_models is a cheap read-only call
            bedrock.list_foundation_models(byOutputModality="TEXT")
            return True
        except Exception:
            return False
