#!/usr/bin/env python3
"""Build (or rebuild) the RAG index from domain context files.

Usage:
    python3 scripts/build_rag_index.py [options]

Options:
    --domain-dir DIR        Directory of markdown files to index
                            (default: pipeline/intake/domain-context/)
    --output PATH           Where to write the index
                            (default: ~/.hoopla/rag.index)
    --embedding auto|sentence-transformers|llamacpp|tfidf
                            Embedding provider (default: auto)
    --llamacpp-url URL      llama.cpp server URL for embedding endpoint
                            (default: http://localhost:8080)
    --force                 Rebuild even if index already exists
    --status                Print current index status without rebuilding

This script is idempotent: if the index already exists and --force is not
set, it only indexes new files (incremental update).

After building, start the coach with:
    python3 -m pipeline.coach --rag-index ~/.hoopla/rag.index
"""
import argparse
import os
import sys

# Ensure repo root is on the path
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)


def main():
    parser = argparse.ArgumentParser(
        prog="build_rag_index.py",
        description="Build the RAG index from domain context files",
    )
    parser.add_argument(
        "--domain-dir", default=None, dest="domain_dir",
        help="Directory of markdown files (default: pipeline/intake/domain-context/)",
    )
    parser.add_argument(
        "--output", default=None,
        help="Index output path (default: ~/.hoopla/rag.index)",
    )
    parser.add_argument(
        "--embedding", default="auto",
        choices=["auto", "sentence-transformers", "llamacpp", "tfidf"],
        help="Embedding provider (default: auto)",
    )
    parser.add_argument(
        "--llamacpp-url", default="http://localhost:8080", dest="llamacpp_url",
        help="llama.cpp server URL for embedding endpoint",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Rebuild the full index even if it already exists",
    )
    parser.add_argument(
        "--status", action="store_true",
        help="Print current index status and exit",
    )
    args = parser.parse_args()

    # Defaults
    domain_dir = args.domain_dir or os.path.join(
        _REPO_ROOT, "pipeline", "intake", "domain-context"
    )
    output = args.output or os.path.expanduser("~/.hoopla/rag.index")

    # Ensure output directory exists
    os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)

    from pipeline.coach.rag.embedding_provider import (
        get_default_provider,
        SentenceTransformerProvider,
        LlamaCppEmbeddingProvider,
        TFIDFProvider,
    )
    from pipeline.coach.rag.vector_store import NumpyVectorStore
    from pipeline.coach.rag.document_indexer import DocumentIndexer

    # Select embedding provider
    if args.embedding == "sentence-transformers":
        provider = SentenceTransformerProvider()
    elif args.embedding == "llamacpp":
        provider = LlamaCppEmbeddingProvider(base_url=args.llamacpp_url)
    elif args.embedding == "tfidf":
        provider = TFIDFProvider()
    else:
        provider = get_default_provider(llamacpp_url=args.llamacpp_url)

    print(f"Embedding provider: {provider.name}")
    print(f"Domain directory:   {domain_dir}")
    print(f"Index output:       {output}")
    print()

    # Load or create store
    if args.status:
        if os.path.exists(output + ".meta"):
            store = NumpyVectorStore.load(output)
            indexer = DocumentIndexer(vector_store=store, embedding_provider=provider)
            status = indexer.status()
            print(f"Index status:")
            print(f"  Total chunks: {status['total_chunks']}")
            print(f"  Indexed sources ({len(status['indexed_sources'])}):")
            for src in sorted(status["indexed_sources"]):
                print(f"    {src}")
        else:
            print("No index found at:", output)
        return

    if args.force and os.path.exists(output + ".meta"):
        print("--force: removing existing index files")
        for ext in [".meta", ".npz", ".npz.json"]:
            path = output + ext
            if os.path.exists(path):
                os.remove(path)
        store = NumpyVectorStore()
    elif os.path.exists(output + ".meta"):
        print("Loading existing index (incremental update)...")
        store = NumpyVectorStore.load(output)
        print(f"  Loaded {store.count()} existing chunks")
    else:
        print("Creating new index...")
        store = NumpyVectorStore()

    # Run indexer
    indexer = DocumentIndexer(vector_store=store, embedding_provider=provider)

    if not os.path.isdir(domain_dir):
        print(f"ERROR: domain directory not found: {domain_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Indexing {domain_dir}...")
    report = indexer.ingest_directory(domain_dir)
    print(report)

    # Save
    store.save(output)
    print(f"\nIndex saved to: {output}")
    print(f"Total chunks in index: {store.count()}")
    print()
    print("Start coach with RAG:")
    print(f"  python3 -m pipeline.coach --rag-index {output}")


if __name__ == "__main__":
    main()
