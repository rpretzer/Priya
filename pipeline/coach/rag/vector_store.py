"""VectorStore — stores and retrieves document chunk embeddings.

Implementation: NumpyVectorStore
- Pure numpy cosine similarity search (no FAISS dependency for Phase 2)
- Persists to disk via numpy .npz + JSON metadata
- Thread-safe reads; file-level locking for writes
- Suitable for Phase 2 scale (~100-1000 chunks)

For Phase 3+ at larger scale, swap in FAISSVectorStore or ChromaDB
by implementing the VectorStore abstract interface.

Interface (from agents.md Contract 2):
    VectorStore.add(chunks) -> list[str]    # chunk IDs
    VectorStore.search(query_embedding, top_k) -> list[SearchResult]
    VectorStore.delete(chunk_ids)
    VectorStore.count() -> int
    VectorStore.save(path)
    VectorStore.load(path)  -> NumpyVectorStore [classmethod]
"""
from __future__ import annotations

import json
import logging
import math
import os
import threading
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Chunk:
    """A document chunk ready for indexing or retrieval."""
    content: str
    source: str          # file path of origin document
    section_header: str  # section heading this chunk falls under
    chunk_index: int     # position within the source document
    chunk_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    metadata: dict = field(default_factory=dict)


@dataclass
class SearchResult:
    """A chunk returned by a similarity search."""
    chunk: Chunk
    score: float         # cosine similarity [0.0, 1.0]; higher is more similar


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------

class VectorStore(ABC):
    """Abstract vector store. Implementations are swappable."""

    @abstractmethod
    def add(self, chunks: list[Chunk], embeddings: list[list[float]]) -> list[str]:
        """Add chunks with their precomputed embeddings.

        Returns the list of chunk_ids assigned.
        """

    @abstractmethod
    def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        threshold: float = 0.0,
        source_filter: Optional[list[str]] = None,
    ) -> list[SearchResult]:
        """Return top_k most similar chunks above threshold.

        Args:
            query_embedding: Query vector (must match index dimension).
            top_k: Maximum number of results.
            threshold: Minimum cosine similarity score to include.
            source_filter: If given, only return chunks from these source paths.
        """

    @abstractmethod
    def delete(self, chunk_ids: list[str]) -> int:
        """Delete chunks by ID. Returns number of chunks deleted."""

    @abstractmethod
    def count(self) -> int:
        """Return number of chunks in the store."""


# ---------------------------------------------------------------------------
# NumpyVectorStore — Phase 2 default implementation
# ---------------------------------------------------------------------------

class NumpyVectorStore(VectorStore):
    """In-memory cosine similarity search using numpy.

    Persists to disk as:
      <path>.npz     — numpy array of embeddings [N × D]
      <path>.meta    — JSON list of chunk metadata

    Thread-safe reads (GIL + read-only numpy ops).
    Write operations hold a threading.Lock.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._chunks: list[Chunk] = []
        self._embeddings: list[list[float]] = []  # parallel to _chunks
        self._id_to_idx: dict[str, int] = {}       # chunk_id → index

    # ------------------------------------------------------------------
    # VectorStore interface
    # ------------------------------------------------------------------

    def add(self, chunks: list[Chunk], embeddings: list[list[float]]) -> list[str]:
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings must have the same length")
        ids = []
        with self._lock:
            for chunk, emb in zip(chunks, embeddings):
                idx = len(self._chunks)
                self._chunks.append(chunk)
                self._embeddings.append(emb)
                self._id_to_idx[chunk.chunk_id] = idx
                ids.append(chunk.chunk_id)
        logger.debug("VectorStore: added %d chunks (total=%d)", len(chunks), len(self._chunks))
        return ids

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        threshold: float = 0.0,
        source_filter: Optional[list[str]] = None,
    ) -> list[SearchResult]:
        if not self._embeddings:
            return []

        try:
            import numpy as np
        except ImportError:
            return self._search_pure_python(query_embedding, top_k, threshold, source_filter)

        q = np.array(query_embedding, dtype=np.float32)
        q_norm = np.linalg.norm(q)
        if q_norm == 0:
            return []
        q = q / q_norm

        # Compute cosine similarity for all embeddings
        matrix = np.array(self._embeddings, dtype=np.float32)  # [N × D]
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        normed = matrix / norms
        scores = normed @ q  # [N]

        # Apply source filter
        indices = np.arange(len(self._chunks))
        if source_filter:
            filter_set = set(source_filter)
            mask = np.array([c.source in filter_set for c in self._chunks])
            indices = indices[mask]
            scores_filtered = scores[indices]
        else:
            scores_filtered = scores[indices]

        # Apply threshold and sort
        above_threshold = scores_filtered >= threshold
        valid_indices = indices[above_threshold]
        valid_scores = scores_filtered[above_threshold]

        if len(valid_scores) == 0:
            return []

        order = np.argsort(valid_scores)[::-1][:top_k]
        results = [
            SearchResult(chunk=self._chunks[valid_indices[i]], score=float(valid_scores[i]))
            for i in order
        ]
        return results

    def _search_pure_python(
        self,
        query_embedding: list[float],
        top_k: int,
        threshold: float,
        source_filter: Optional[list[str]],
    ) -> list[SearchResult]:
        """Fallback cosine similarity without numpy."""
        def dot(a: list[float], b: list[float]) -> float:
            return sum(x * y for x, y in zip(a, b))

        def norm(v: list[float]) -> float:
            return math.sqrt(sum(x * x for x in v))

        q_norm = norm(query_embedding)
        if q_norm == 0:
            return []

        results = []
        filter_set = set(source_filter) if source_filter else None
        for chunk, emb in zip(self._chunks, self._embeddings):
            if filter_set and chunk.source not in filter_set:
                continue
            e_norm = norm(emb)
            if e_norm == 0:
                continue
            score = dot(query_embedding, emb) / (q_norm * e_norm)
            if score >= threshold:
                results.append(SearchResult(chunk=chunk, score=score))

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]

    def delete(self, chunk_ids: list[str]) -> int:
        id_set = set(chunk_ids)
        deleted = 0
        with self._lock:
            new_chunks = []
            new_embeddings = []
            new_id_to_idx: dict[str, int] = {}
            for chunk, emb in zip(self._chunks, self._embeddings):
                if chunk.chunk_id in id_set:
                    deleted += 1
                else:
                    new_id_to_idx[chunk.chunk_id] = len(new_chunks)
                    new_chunks.append(chunk)
                    new_embeddings.append(emb)
            self._chunks = new_chunks
            self._embeddings = new_embeddings
            self._id_to_idx = new_id_to_idx
        return deleted

    def count(self) -> int:
        return len(self._chunks)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: str) -> None:
        """Persist index to disk. Creates <path>.npz and <path>.meta."""
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        meta_path = path + ".meta"
        npz_path = path + ".npz"

        with self._lock:
            # Metadata
            meta = []
            for chunk in self._chunks:
                meta.append({
                    "chunk_id": chunk.chunk_id,
                    "content": chunk.content,
                    "source": chunk.source,
                    "section_header": chunk.section_header,
                    "chunk_index": chunk.chunk_index,
                    "metadata": chunk.metadata,
                })
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f)

            # Embeddings
            if self._embeddings:
                try:
                    import numpy as np
                    np.savez_compressed(npz_path, embeddings=np.array(self._embeddings, dtype=np.float32))
                except ImportError:
                    # Fallback: save as JSON
                    with open(npz_path + ".json", "w") as f:
                        json.dump(self._embeddings, f)
            else:
                # Empty store — create empty npz placeholder
                with open(npz_path + ".json", "w") as f:
                    json.dump([], f)

        logger.info("VectorStore: saved %d chunks to %s", len(self._chunks), path)

    @classmethod
    def load(cls, path: str) -> "NumpyVectorStore":
        """Load a previously saved index from disk."""
        meta_path = path + ".meta"
        npz_path = path + ".npz"
        npz_json_path = path + ".npz.json"

        store = cls()
        if not os.path.exists(meta_path):
            logger.warning("VectorStore: no index found at %s, returning empty store", path)
            return store

        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

        chunks = [
            Chunk(
                chunk_id=m["chunk_id"],
                content=m["content"],
                source=m["source"],
                section_header=m["section_header"],
                chunk_index=m["chunk_index"],
                metadata=m.get("metadata", {}),
            )
            for m in meta
        ]

        embeddings: list[list[float]] = []
        if os.path.exists(npz_path):
            try:
                import numpy as np
                data = np.load(npz_path)
                embeddings = data["embeddings"].tolist()
            except ImportError:
                logger.warning("VectorStore: numpy not available, cannot load .npz — trying JSON fallback")
        if not embeddings and os.path.exists(npz_json_path):
            with open(npz_json_path) as f:
                embeddings = json.load(f)

        if len(chunks) != len(embeddings):
            logger.error(
                "VectorStore: metadata has %d chunks but embeddings has %d — index is corrupt",
                len(chunks), len(embeddings),
            )
            return cls()

        with store._lock:
            store._chunks = chunks
            store._embeddings = embeddings
            store._id_to_idx = {c.chunk_id: i for i, c in enumerate(chunks)}

        logger.info("VectorStore: loaded %d chunks from %s", len(chunks), path)
        return store

    def sources(self) -> list[str]:
        """Return unique source file paths indexed."""
        return list({c.source for c in self._chunks})
