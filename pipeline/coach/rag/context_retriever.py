"""ContextRetriever — retrieves relevant domain context chunks for prompt assembly.

Implements the ContextSource interface (agents.md Contract 2) so it can be
registered with ContextAssembler as an additive context source alongside the
static file-driven DomainContext baseline.

Key behaviors:
- Queries VectorStore using the current conversation as the query
- Deduplicates against static domain context (skips chunks whose content
  is substantially present in the static context string)
- Enforces a token budget to prevent context window overflow
- Returns chunks with source attribution (filename + section header)
- Degrades gracefully: if retrieval fails, returns empty list (no crash)
- Target retrieval latency: <200ms (requirement from agents.md)

Usage:
    retriever = ContextRetriever(
        vector_store=store,
        embedding_provider=provider,
        top_k=5,
        threshold=0.3,
        max_tokens=2000,
    )
    # Register with ContextAssembler:
    assembler = ContextAssembler(context_sources=[retriever])

    # Direct usage (for testing):
    chunks = retriever.query("patron borrow flow Android KMP")
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from pipeline.coach.rag.embedding_provider import EmbeddingProvider
from pipeline.coach.rag.vector_store import VectorStore

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Approximate chars-per-token ratio for token budget estimation
_CHARS_PER_TOKEN = 4


class ContextRetriever:
    """Retrieves relevant domain context chunks from the VectorStore.

    Implements the ContextSource protocol:
        get_context(conversation_state: dict) -> list[ContextChunk]

    where conversation_state is:
        {
            "messages": list[dict],   # recent conversation messages
            "missing_fields": list[str],  # from ProgressTracker
            "turn_count": int,
        }

    The query is built from the last N user messages in conversation_state.
    If conversation_state is missing or empty, a generic domain query is used.
    """

    # Number of recent user messages to include in the retrieval query
    QUERY_WINDOW = 3
    # Target retrieval latency warning threshold
    LATENCY_WARNING_MS = 200

    def __init__(
        self,
        vector_store: VectorStore,
        embedding_provider: EmbeddingProvider,
        top_k: int = 5,
        threshold: float = 0.3,
        max_tokens: int = 2000,
    ):
        self._store = vector_store
        self._provider = embedding_provider
        self._top_k = top_k
        self._threshold = threshold
        self._max_tokens = max_tokens
        self._max_chars = max_tokens * _CHARS_PER_TOKEN

    # ------------------------------------------------------------------
    # ContextSource protocol (called by ContextAssembler)
    # ------------------------------------------------------------------

    def get_context(self, conversation_state: dict) -> list["ContextChunk"]:
        """Return relevant context chunks for the current conversation.

        Called by ContextAssembler during prompt assembly (Layer 2b).
        Returns ContextChunk objects as defined in engine.py.

        Graceful degradation: returns [] on any error.
        """
        # Import here to avoid circular deps (engine imports this module)
        from pipeline.coach.engine import ContextChunk

        t_start = time.monotonic()
        try:
            query = self._build_query(conversation_state)
            if not query.strip():
                return []

            raw_results = self.query(query)

            # Convert SearchResult → ContextChunk
            chunks = [
                ContextChunk(
                    content=r.chunk.content,
                    source=r.chunk.source,
                    score=r.score,
                    metadata={
                        "section_header": r.chunk.section_header,
                        "chunk_index": r.chunk.chunk_index,
                        **r.chunk.metadata,
                    },
                )
                for r in raw_results
            ]

            elapsed_ms = (time.monotonic() - t_start) * 1000
            if elapsed_ms > self.LATENCY_WARNING_MS:
                logger.warning(
                    "ContextRetriever: retrieval took %.0fms (target <200ms)", elapsed_ms
                )
            else:
                logger.debug(
                    "ContextRetriever: retrieved %d chunks in %.0fms", len(chunks), elapsed_ms
                )

            return chunks

        except Exception as exc:
            logger.warning("ContextRetriever: retrieval failed, returning empty: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Direct query interface (for testing and build_rag_index.py)
    # ------------------------------------------------------------------

    def query(
        self,
        text: str,
        top_k: int | None = None,
        threshold: float | None = None,
        static_context: str = "",
    ) -> list:
        """Query the vector store with a text string.

        Args:
            text: Query text.
            top_k: Override instance top_k.
            threshold: Override instance threshold.
            static_context: Static domain context string for deduplication.
                Chunks whose content is substantially present in this string
                will be excluded.

        Returns:
            List of SearchResult objects sorted by score desc, within
            the token budget, deduplicated against static_context.
        """
        k = top_k if top_k is not None else self._top_k
        thresh = threshold if threshold is not None else self._threshold

        if self._store.count() == 0:
            return []

        try:
            embedding = self._provider.embed(text)
        except Exception as exc:
            logger.warning("ContextRetriever: embedding failed: %s", exc)
            return []

        results = self._store.search(embedding, top_k=k * 2, threshold=thresh)

        # Deduplicate against static context
        if static_context:
            results = self._deduplicate(results, static_context)

        # Apply token budget
        results = self._apply_budget(results, k)

        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_query(self, conversation_state: dict) -> str:
        """Build a retrieval query string from conversation state."""
        messages = conversation_state.get("messages", [])
        missing = conversation_state.get("missing_fields", [])

        # Extract last N user messages
        user_texts = [
            m["content"] if isinstance(m["content"], str) else ""
            for m in messages
            if m.get("role") == "user"
        ][-self.QUERY_WINDOW:]

        parts = []
        if user_texts:
            parts.extend(user_texts)
        if missing:
            # Hint the retriever toward missing fields
            parts.append(f"Topics needed: {', '.join(missing)}")

        return " ".join(parts).strip()

    def _deduplicate(self, results: list, static_context: str) -> list:
        """Remove chunks whose content is substantially present in static_context.

        Uses a simple substring check: if >60% of the chunk's sentences
        appear verbatim in static_context, skip the chunk.
        """
        filtered = []
        sc_lower = static_context.lower()
        for result in results:
            content = result.chunk.content
            # Check if a substantial portion of the chunk appears in static context
            sentences = [s.strip() for s in content.split(".") if len(s.strip()) > 20]
            if not sentences:
                filtered.append(result)
                continue
            found = sum(1 for s in sentences if s.lower()[:80] in sc_lower)
            overlap_ratio = found / len(sentences)
            if overlap_ratio < 0.6:
                filtered.append(result)
            else:
                logger.debug(
                    "ContextRetriever: deduplicated chunk from %s (%.0f%% overlap)",
                    result.chunk.source, overlap_ratio * 100,
                )
        return filtered

    def _apply_budget(self, results: list, max_results: int) -> list:
        """Return results that fit within the token budget, up to max_results."""
        budget_remaining = self._max_chars
        kept = []
        for result in results:
            if len(kept) >= max_results:
                break
            chunk_len = len(result.chunk.content)
            if chunk_len <= budget_remaining:
                kept.append(result)
                budget_remaining -= chunk_len
            # If first chunk already exceeds budget, include it truncated
            elif not kept:
                kept.append(result)
                break
        return kept

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @property
    def index_size(self) -> int:
        return self._store.count()

    def is_ready(self) -> bool:
        """True if the store has at least one chunk indexed."""
        return self._store.count() > 0
