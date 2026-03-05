"""EmbeddingProvider — abstract interface for generating text embeddings.

Three implementations are provided in priority order:

1. SentenceTransformerProvider — best quality, requires sentence-transformers
   (pip install sentence-transformers). Downloads ~80MB model on first use.
   Model: all-MiniLM-L6-v2 (fast, 384-dim, good domain coverage).

2. LlamaCppEmbeddingProvider — uses the /v1/embeddings endpoint on a running
   llama.cpp server. No extra Python deps. Requires llama.cpp server to be up.

3. TFIDFProvider — pure Python fallback. No ML deps. Uses TF-IDF bag-of-words
   vectors. Lower semantic quality but always available. Useful for testing
   and environments where sentence-transformers cannot be installed.

The same EmbeddingProvider instance must be used for both indexing (DocumentIndexer)
and retrieval (ContextRetriever). Mixing providers breaks similarity search.

Usage:
    provider = get_default_provider()          # picks best available
    vec = provider.embed("library patron")
    batch = provider.embed_batch(["text1", "text2"])
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from collections import Counter
from typing import Optional

logger = logging.getLogger(__name__)


class EmbeddingProvider(ABC):
    """Abstract interface for embedding generation."""

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """Embed a single string. Returns a float vector."""

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of strings. Returns a list of float vectors."""

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Embedding vector dimensionality."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable provider identifier."""


# ---------------------------------------------------------------------------
# SentenceTransformerProvider
# ---------------------------------------------------------------------------

class SentenceTransformerProvider(EmbeddingProvider):
    """Local embedding via sentence-transformers.

    Requires: pip install sentence-transformers

    Model defaults to 'all-MiniLM-L6-v2':
    - 384-dimensional embeddings
    - ~80MB download on first use
    - ~14ms/sentence on CPU
    - Strong semantic similarity for English text
    """

    DEFAULT_MODEL = "all-MiniLM-L6-v2"

    def __init__(self, model_name: str = DEFAULT_MODEL):
        self._model_name = model_name
        self._model = None  # lazy load

    def _get_model(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                logger.info("EmbeddingProvider: loading sentence-transformers model '%s'", self._model_name)
                self._model = SentenceTransformer(self._model_name)
                logger.info("EmbeddingProvider: model loaded, dim=%d", self.dimension)
            except ImportError:
                raise ImportError(
                    "sentence-transformers not installed. "
                    "Run: pip install sentence-transformers"
                )
        return self._model

    def embed(self, text: str) -> list[float]:
        model = self._get_model()
        vec = model.encode(text, normalize_embeddings=True)
        return vec.tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        model = self._get_model()
        vecs = model.encode(texts, normalize_embeddings=True, batch_size=32)
        return [v.tolist() for v in vecs]

    @property
    def dimension(self) -> int:
        return self._get_model().get_sentence_embedding_dimension()

    @property
    def name(self) -> str:
        return f"sentence-transformers/{self._model_name}"


# ---------------------------------------------------------------------------
# LlamaCppEmbeddingProvider
# ---------------------------------------------------------------------------

class LlamaCppEmbeddingProvider(EmbeddingProvider):
    """Embedding via the /v1/embeddings endpoint on a running llama.cpp server.

    Requires a llama.cpp server started with --embedding flag:
        llama-server --model model.gguf --embedding --port 8080

    No extra Python dependencies needed.
    """

    def __init__(self, base_url: str = "http://localhost:8080", dim: int = 0):
        self._base_url = base_url.rstrip("/")
        self._dim: Optional[int] = dim if dim > 0 else None

    def _call(self, texts: list[str]) -> list[list[float]]:
        payload = json.dumps({"input": texts}).encode()
        req = urllib.request.Request(
            f"{self._base_url}/v1/embeddings",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read())
                # OpenAI-compatible response: {"data": [{"embedding": [...]}]}
                embeddings = [item["embedding"] for item in body["data"]]
                if self._dim is None and embeddings:
                    self._dim = len(embeddings[0])
                return embeddings
        except (urllib.error.URLError, KeyError, json.JSONDecodeError) as e:
            raise RuntimeError(f"LlamaCppEmbeddingProvider: request failed: {e}") from e

    def embed(self, text: str) -> list[float]:
        return self._call([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        # llama.cpp embedding endpoint may have a batch size limit — chunk at 32
        results = []
        for i in range(0, len(texts), 32):
            results.extend(self._call(texts[i:i+32]))
        return results

    @property
    def dimension(self) -> int:
        if self._dim is None:
            # Probe with a dummy call
            self.embed("probe")
        return self._dim or 0

    @property
    def name(self) -> str:
        return f"llamacpp-embedding@{self._base_url}"


# ---------------------------------------------------------------------------
# TFIDFProvider — pure Python fallback
# ---------------------------------------------------------------------------

_STOPWORDS = frozenset([
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "have", "has", "had", "do", "does", "did", "not", "this", "that",
    "it", "its", "as", "if", "so", "we", "our", "they", "their", "you",
    "your", "he", "she", "his", "her", "which", "who", "what", "when",
    "where", "will", "can", "may", "should", "would", "could", "also",
])


class TFIDFProvider(EmbeddingProvider):
    """Pure-Python TF-IDF bag-of-words embedding fallback.

    No external dependencies. Lower semantic quality than sentence-transformers
    but always available. Suitable for testing and resource-constrained
    environments.

    The vocabulary is built lazily from documents. The first call to
    embed() or embed_batch() sets the vocabulary. Subsequent calls use the
    same vocabulary — do NOT mix vocabularies between indexing and retrieval
    (they are the same provider instance, so this is automatic).

    Dimension = vocabulary size (capped at MAX_VOCAB).
    """

    MAX_VOCAB = 4096

    def __init__(self):
        self._vocab: dict[str, int] = {}    # token → index
        self._idf: dict[str, float] = {}    # token → IDF weight
        self._doc_corpus: list[list[str]] = []  # for IDF calculation

    def _tokenize(self, text: str) -> list[str]:
        tokens = re.findall(r"[a-z][a-z']{1,}", text.lower())
        return [t for t in tokens if t not in _STOPWORDS and len(t) > 2]

    def _build_vocab(self, docs: list[list[str]]) -> None:
        """Build or extend vocabulary and IDF from a batch of documents."""
        # Count document frequency for new tokens
        all_tokens = set()
        for doc in docs:
            all_tokens.update(doc)

        new_tokens = all_tokens - set(self._vocab.keys())
        for tok in sorted(new_tokens):
            if len(self._vocab) >= self.MAX_VOCAB:
                break
            self._vocab[tok] = len(self._vocab)

        # Store docs for IDF computation
        self._doc_corpus.extend(docs)
        n = len(self._doc_corpus)
        for tok in self._vocab:
            df = sum(1 for d in self._doc_corpus if tok in d)
            self._idf[tok] = math.log((n + 1) / (df + 1)) + 1.0

    def _vectorize(self, tokens: list[str]) -> list[float]:
        if not self._vocab:
            return [0.0] * self.MAX_VOCAB
        dim = len(self._vocab)
        vec = [0.0] * dim
        tf = Counter(tokens)
        total = max(len(tokens), 1)
        for tok, count in tf.items():
            idx = self._vocab.get(tok)
            if idx is not None:
                tf_weight = count / total
                idf_weight = self._idf.get(tok, 1.0)
                vec[idx] = tf_weight * idf_weight
        # L2 normalize
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    def embed(self, text: str) -> list[float]:
        tokens = self._tokenize(text)
        if not self._vocab:
            self._build_vocab([tokens])
        return self._vectorize(tokens)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        tokenized = [self._tokenize(t) for t in texts]
        self._build_vocab(tokenized)
        return [self._vectorize(toks) for toks in tokenized]

    @property
    def dimension(self) -> int:
        return len(self._vocab) or self.MAX_VOCAB

    @property
    def name(self) -> str:
        return f"tfidf(vocab={len(self._vocab)})"


# ---------------------------------------------------------------------------
# Default provider selection
# ---------------------------------------------------------------------------

def get_default_provider(
    llamacpp_url: Optional[str] = None,
    sentence_transformer_model: str = SentenceTransformerProvider.DEFAULT_MODEL,
) -> EmbeddingProvider:
    """Return the best available EmbeddingProvider.

    Priority:
    1. sentence-transformers (if installed)
    2. llama.cpp embedding endpoint (if llamacpp_url provided and reachable)
    3. TF-IDF pure Python fallback

    Args:
        llamacpp_url: Optional llama.cpp server URL for embedding endpoint.
        sentence_transformer_model: sentence-transformers model name to use.
    """
    # Try sentence-transformers first
    try:
        import sentence_transformers  # noqa: F401
        logger.info("EmbeddingProvider: using sentence-transformers")
        return SentenceTransformerProvider(sentence_transformer_model)
    except ImportError:
        pass

    # Try llama.cpp embedding endpoint
    if llamacpp_url:
        try:
            provider = LlamaCppEmbeddingProvider(base_url=llamacpp_url)
            # Quick health probe
            provider.embed("test")
            logger.info("EmbeddingProvider: using llama.cpp embedding @ %s", llamacpp_url)
            return provider
        except Exception as e:
            logger.debug("EmbeddingProvider: llama.cpp embedding probe failed: %s", e)

    # Fall back to TF-IDF
    logger.info(
        "EmbeddingProvider: using TF-IDF fallback (no sentence-transformers available). "
        "Install sentence-transformers for better retrieval quality."
    )
    return TFIDFProvider()
