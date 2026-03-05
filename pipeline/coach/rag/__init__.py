"""pipeline.coach.rag — Phase 2 RAG package.

Provides DocumentIndexer, VectorStore, ContextRetriever, and EmbeddingProvider.
These are ephemeral agents (per agents.md) — they can be replaced or upgraded
without touching the stable coaching core.

All coaching correctness is in CoachEngine, ProgressTracker, SignalDetector,
and ContextAssembler. This package is pure infrastructure.

Quick-start:
    from pipeline.coach.rag import build_retriever
    retriever = build_retriever(
        domain_context_dir="pipeline/intake/domain-context",
        index_path="/var/hoopla/rag.index",
    )
    # Then pass to ContextAssembler:
    assembler = ContextAssembler(context_sources=[retriever])
"""
from pipeline.coach.rag.embedding_provider import (
    EmbeddingProvider,
    SentenceTransformerProvider,
    LlamaCppEmbeddingProvider,
    TFIDFProvider,
    get_default_provider,
)
from pipeline.coach.rag.vector_store import (
    Chunk,
    SearchResult,
    VectorStore,
    NumpyVectorStore,
)
from pipeline.coach.rag.document_indexer import (
    DocumentIndexer,
    IndexReport,
)
from pipeline.coach.rag.context_retriever import (
    ContextRetriever,
)


def build_retriever(
    domain_context_dir: str | None = None,
    index_path: str = "rag.index",
    embedding_provider: EmbeddingProvider | None = None,
    top_k: int = 5,
    threshold: float = 0.3,
    max_tokens: int = 2000,
) -> "ContextRetriever":
    """Convenience factory: build and return a ready-to-use ContextRetriever.

    Loads or builds the index from `domain_context_dir` (if provided).
    Persists the index at `index_path`.

    Args:
        domain_context_dir: Path to directory containing domain markdown files.
            If provided and index_path doesn't exist, the index will be built.
        index_path: Where to store/load the numpy index.
        embedding_provider: EmbeddingProvider to use. Defaults to best available.
        top_k: Number of chunks to retrieve per query.
        threshold: Minimum similarity score for a chunk to be included.
        max_tokens: Maximum token budget for retrieved context.

    Returns:
        A configured ContextRetriever ready to be registered with ContextAssembler.
    """
    import os
    provider = embedding_provider or get_default_provider()
    store = NumpyVectorStore()

    if os.path.exists(index_path):
        store = NumpyVectorStore.load(index_path)
    elif domain_context_dir and os.path.isdir(domain_context_dir):
        indexer = DocumentIndexer(vector_store=store, embedding_provider=provider)
        indexer.ingest_directory(domain_context_dir)
        store.save(index_path)

    return ContextRetriever(
        vector_store=store,
        embedding_provider=provider,
        top_k=top_k,
        threshold=threshold,
        max_tokens=max_tokens,
    )


__all__ = [
    "EmbeddingProvider",
    "SentenceTransformerProvider",
    "LlamaCppEmbeddingProvider",
    "TFIDFProvider",
    "get_default_provider",
    "Chunk",
    "SearchResult",
    "VectorStore",
    "NumpyVectorStore",
    "DocumentIndexer",
    "IndexReport",
    "ContextRetriever",
    "build_retriever",
]
