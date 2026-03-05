"""DocumentIndexer — ingests markdown and text documents into the VectorStore.

Handles:
- Chunking by section headers (## / ###) and paragraph size
- Embedding generation via EmbeddingProvider
- Incremental ingestion (adding files does not require full reindex)
- Source metadata for deduplication and attribution

Chunking strategy:
- Split on H2/H3 markdown headers (## and ###)
- Within each section, split on double-newlines (paragraph breaks) if
  the section exceeds MAX_CHUNK_CHARS
- Each chunk carries its section header as context prefix
- Target: 200-400 tokens (~800-1600 chars) per chunk

Usage:
    from pipeline.coach.rag import DocumentIndexer, NumpyVectorStore, get_default_provider

    store = NumpyVectorStore()
    provider = get_default_provider()
    indexer = DocumentIndexer(vector_store=store, embedding_provider=provider)

    report = indexer.ingest_directory("pipeline/intake/domain-context")
    print(report)
    store.save("rag.index")
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from pipeline.coach.rag.embedding_provider import EmbeddingProvider
from pipeline.coach.rag.vector_store import Chunk, VectorStore

logger = logging.getLogger(__name__)

# Maximum chars per chunk before further splitting within a section
MAX_CHUNK_CHARS = 1500

# Minimum chars for a chunk to be worth indexing (skip trivial sections)
MIN_CHUNK_CHARS = 50


@dataclass
class IndexReport:
    """Result of an ingestion run."""
    files_processed: int = 0
    chunks_added: int = 0
    files_skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        lines = [
            f"DocumentIndexer: {self.files_processed} files, {self.chunks_added} chunks indexed",
        ]
        if self.files_skipped:
            lines.append(f"  Skipped: {', '.join(self.files_skipped)}")
        if self.errors:
            lines.append(f"  Errors: {len(self.errors)}")
            for e in self.errors[:5]:
                lines.append(f"    {e}")
        return "\n".join(lines)


class DocumentIndexer:
    """Ingests documents into the VectorStore.

    Implements the DocumentIndexer contract from agents.md Phase 2.

    Key properties:
    - Incremental: only indexes files that are not already present in the store
    - Preserves section structure in chunk metadata
    - Supports markdown (.md), plain text (.txt), and PDF (if pypdf installed)
    - Chunking preserves section header as context in each chunk
    """

    def __init__(
        self,
        vector_store: VectorStore,
        embedding_provider: EmbeddingProvider,
        max_chunk_chars: int = MAX_CHUNK_CHARS,
        min_chunk_chars: int = MIN_CHUNK_CHARS,
    ):
        self._store = vector_store
        self._provider = embedding_provider
        self._max_chunk_chars = max_chunk_chars
        self._min_chunk_chars = min_chunk_chars

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def ingest(self, file_paths: list[str]) -> IndexReport:
        """Ingest a list of files. Skips files already in the index."""
        report = IndexReport()
        already_indexed = set(self._store.sources()) if hasattr(self._store, "sources") else set()

        for path in file_paths:
            abs_path = os.path.abspath(path)
            if abs_path in already_indexed:
                logger.debug("DocumentIndexer: skipping already-indexed %s", abs_path)
                report.files_skipped.append(abs_path)
                continue
            try:
                self._ingest_file(abs_path, report)
            except Exception as exc:
                msg = f"{abs_path}: {exc}"
                logger.error("DocumentIndexer: error ingesting %s: %s", abs_path, exc)
                report.errors.append(msg)

        logger.info(str(report))
        return report

    def ingest_directory(self, dir_path: str, extensions: list[str] | None = None) -> IndexReport:
        """Ingest all supported files in a directory (non-recursive by default)."""
        if extensions is None:
            extensions = [".md", ".txt"]
        dir_path = os.path.abspath(dir_path)
        if not os.path.isdir(dir_path):
            raise NotADirectoryError(f"Not a directory: {dir_path}")

        file_paths = []
        for entry in sorted(os.listdir(dir_path)):
            if any(entry.endswith(ext) for ext in extensions):
                file_paths.append(os.path.join(dir_path, entry))

        logger.info(
            "DocumentIndexer: ingesting %d files from %s", len(file_paths), dir_path
        )
        return self.ingest(file_paths)

    def remove(self, source_path: str) -> int:
        """Remove all chunks from a given source file. Returns count removed."""
        abs_path = os.path.abspath(source_path)
        chunks_to_remove = [
            c.chunk_id
            for c in getattr(self._store, "_chunks", [])
            if c.source == abs_path
        ]
        if not chunks_to_remove:
            return 0
        removed = self._store.delete(chunks_to_remove)
        logger.info("DocumentIndexer: removed %d chunks for %s", removed, abs_path)
        return removed

    def status(self) -> dict:
        """Return current index status."""
        sources = getattr(self._store, "sources", lambda: [])()
        return {
            "total_chunks": self._store.count(),
            "indexed_sources": sources,
            "provider": self._provider.name,
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _ingest_file(self, abs_path: str, report: IndexReport) -> None:
        """Read, chunk, embed, and add a single file to the store."""
        ext = Path(abs_path).suffix.lower()
        if ext in (".md", ".txt"):
            text = self._read_text(abs_path)
        elif ext == ".pdf":
            text = self._read_pdf(abs_path)
        else:
            logger.debug("DocumentIndexer: unsupported extension %s, skipping", ext)
            report.files_skipped.append(abs_path)
            return

        chunks = self._chunk_markdown(text, source=abs_path)
        if not chunks:
            logger.debug("DocumentIndexer: no usable chunks from %s", abs_path)
            report.files_skipped.append(abs_path)
            return

        # Generate embeddings in batch
        texts = [c.content for c in chunks]
        embeddings = self._provider.embed_batch(texts)

        added_ids = self._store.add(chunks, embeddings)
        report.files_processed += 1
        report.chunks_added += len(added_ids)
        logger.info(
            "DocumentIndexer: indexed %s → %d chunks", abs_path, len(added_ids)
        )

    @staticmethod
    def _read_text(path: str) -> str:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()

    @staticmethod
    def _read_pdf(path: str) -> str:
        try:
            from pypdf import PdfReader
            reader = PdfReader(path)
            pages = [page.extract_text() or "" for page in reader.pages]
            return "\n\n".join(pages)
        except ImportError:
            raise RuntimeError(
                "pypdf not installed. Run: pip install pypdf  "
                "to enable PDF ingestion."
            )

    def _chunk_markdown(self, text: str, source: str) -> list[Chunk]:
        """Split markdown into chunks by section header and paragraph size.

        Each chunk:
        - Starts with its section header (for context in retrieval)
        - Is within MAX_CHUNK_CHARS (split on paragraph breaks if needed)
        - Is above MIN_CHUNK_CHARS (skip trivial chunks)
        """
        sections = self._split_by_headers(text)
        chunks: list[Chunk] = []
        global_chunk_idx = 0

        for header, body in sections:
            # Remove front-matter markers (YAML-style or --- dividers)
            body = re.sub(r"^---+\s*\n", "", body, flags=re.MULTILINE)
            body = body.strip()
            if not body:
                continue

            # Prefix body with header for context in each chunk
            if header:
                full_section = f"{header}\n\n{body}"
            else:
                full_section = body

            # Further split on paragraph boundaries if section is large
            sub_chunks = self._split_on_paragraphs(full_section)

            for sub in sub_chunks:
                sub = sub.strip()
                if len(sub) < self._min_chunk_chars:
                    continue
                chunk = Chunk(
                    content=sub,
                    source=source,
                    section_header=header or "",
                    chunk_index=global_chunk_idx,
                )
                chunks.append(chunk)
                global_chunk_idx += 1

        return chunks

    @staticmethod
    def _split_by_headers(text: str) -> list[tuple[str, str]]:
        """Split markdown text into (header, body) pairs.

        Splits on H1, H2, H3 headers. The document content before
        the first header is included as a header-less section.
        """
        # Match H1, H2, H3 headers (lines starting with 1-3 #s)
        pattern = re.compile(r"^(#{1,3} .+)$", re.MULTILINE)
        matches = list(pattern.finditer(text))

        sections = []
        prev_end = 0
        prev_header = ""

        for m in matches:
            # Body from previous header to this header
            body = text[prev_end:m.start()].strip()
            if body or prev_header:
                sections.append((prev_header, body))
            prev_header = m.group(1).strip()
            prev_end = m.end()

        # Trailing section
        body = text[prev_end:].strip()
        if body or prev_header:
            sections.append((prev_header, body))

        return sections

    def _split_on_paragraphs(self, text: str) -> list[str]:
        """Split text into sub-chunks if it exceeds MAX_CHUNK_CHARS.

        Splits on double-newlines (paragraph boundaries), accumulating
        paragraphs until the chunk reaches MAX_CHUNK_CHARS.
        """
        if len(text) <= self._max_chunk_chars:
            return [text]

        paragraphs = re.split(r"\n{2,}", text)
        chunks = []
        current = []
        current_len = 0

        for para in paragraphs:
            if current_len + len(para) + 2 > self._max_chunk_chars and current:
                chunks.append("\n\n".join(current))
                current = [para]
                current_len = len(para)
            else:
                current.append(para)
                current_len += len(para) + 2

        if current:
            chunks.append("\n\n".join(current))

        return chunks
