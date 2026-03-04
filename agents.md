# agents.md — Hoopla Coach Agent Topology

Covers Phase 1 (llama.cpp backend) and Phase 2 (RAG-augmented domain context). Priya's coaching core is documented here as a reference baseline. It does not change across phases.

---

## Agent Topology Diagram

```
                         Phase 1                              Phase 2
                     +--------------+                  +------------------+
                     | LlamaCpp     |                  | DocumentIndexer  |
                     | Backend      |                  | (ingestion)      |
                     +------+-------+                  +--------+---------+
                            |                                   |
                            | AgentBackend                      | writes
                            | interface                         v
                            |                          +------------------+
  User <---> CoachEngine ---+--- AgentBackend --->     | VectorStore      |
               |    |       |    (swappable)           +--------+---------+
               |    |       |                                   |
               |    |       +--- OllamaBackend (existing)       | reads
               |    |                                           v
               |    +--- ProgressTracker              +------------------+
               |    +--- SignalDetector               | ContextRetriever |
               |    +--- CoachMemory                  +--------+---------+
               |    +--- Crystallizer                          |
               |                                               | retrieved
               +--- ContextAssembler                           | context
                      |         |                              |
                      |         +--- DomainContext (files) <----+
                      |              (baseline, always active)
                      |
                      +--- RAG integration point (Phase 2)
```

```
Data flow per turn:

  User input
    |
    v
  CoachEngine
    |---> SignalDetector.analyze(input)        [heuristic, no LLM]
    |---> ProgressTracker.score(conversation)  [heuristic, no LLM]
    |---> ContextAssembler.build(overlays)
    |       |---> DomainContext.load()         [file-driven, always]
    |       +---> ContextRetriever.query()     [Phase 2 only, dynamic]
    |
    +---> AgentBackend.chat_stream(prompt)     [LlamaCppBackend in Phase 1]
            |
            v
          Response to user
            |
            +---> (late session) Artifact generation if ProgressTracker gates pass
            +---> (session end) Crystallizer.extract() --> CoachMemory.store()
```

---

## Stability Classification

| Agent              | Stability   | Rationale                                                      |
|--------------------|-------------|----------------------------------------------------------------|
| CoachEngine        | **Stable**  | Core conversation controller. Tested by `test_hardening.py`.   |
| ProgressTracker    | **Stable**  | Heuristic scoring, gates artifacts. Tested.                    |
| SignalDetector     | **Stable**  | Heuristic signal detection, tone adaptation. Tested.           |
| ContextAssembler   | **Stable**  | Layered prompt builder. Phase 2 adds an integration point but does not change existing layers. |
| CoachMemory        | **Stable**  | SQLite+FTS episodic memory. Interface is fixed.                |
| Crystallizer       | **Stable**  | Heuristic session-end extractor. No LLM dependency.            |
| DomainContext      | **Stable**  | File-driven loader. RAG augments, does not replace.            |
| AgentBackend       | **Stable**  | Interface is stable. Implementations are swappable.            |
| OllamaBackend      | Ephemeral   | Current default. Will be superseded by LlamaCppBackend.        |
| LlamaCppBackend    | Ephemeral   | Phase 1 target. Implements AgentBackend. Swappable.            |
| DocumentIndexer    | Ephemeral   | Phase 2. Ingestion pipeline. Replaceable with any indexer.     |
| VectorStore        | Ephemeral   | Phase 2. Storage layer. Swappable (FAISS, Chroma, etc.).       |
| ContextRetriever   | Ephemeral   | Phase 2. Retrieval layer. Swappable implementation.            |
| BackendValidator   | Ephemeral   | Phase 1. Test harness for backend swap. Disposable.            |

**Rule**: Stable agents must not be modified without running `test_hardening.py` and getting explicit approval. Ephemeral agents can be replaced, rewritten, or removed without affecting coaching correctness.

---

## Agents — Stable Core (Reference Baseline)

These agents exist today. They are documented here so Phase 1/2 agents know what they connect to and what they must not touch.

### CoachEngine

- **Role**: Multi-turn conversation controller. Drives all LLM calls via AgentBackend, injects the assembled system prompt, handles multimodal inputs and slash commands (`/help`, `/status`, `/generate`, `/reset`).
- **Inputs**: User text, file uploads, URLs, images, conversation history.
- **Outputs**: Streamed response text. Artifact markdown when gating passes.
- **Interface**: `CoachEngine.handle_turn(user_input) -> AsyncIterator[str]`
- **Dependencies**: AgentBackend, ProgressTracker, SignalDetector, ContextAssembler, CoachMemory, Crystallizer.
- **Constraints**: Provider-agnostic. No LLM-specific logic. Persona/protocol prompt text is load-bearing.

### ProgressTracker

- **Role**: Scores business-case completeness across 9 fields: problem, evidence, users, impact, solution, metrics, risks, scope, platform. Gates artifact production.
- **Inputs**: Conversation history.
- **Outputs**: Completeness scores per field, overall readiness boolean, gap list.
- **Interface**: `ProgressTracker.score(conversation) -> CompletenessReport`
- **Dependencies**: None (heuristic, no LLM).
- **Constraints**: Must remain heuristic/regex-based. No LLM calls. Gating logic must not be bypassed or overridden.

### SignalDetector

- **Role**: Detects weak signals (solution-before-problem, vague metrics, COPPA minors) and strong signals (quantified problems, hypotheses, tradeoffs). Feeds push-back and tone adaptation logic.
- **Inputs**: User input text, conversation history.
- **Outputs**: Signal list (type, strength, category), emotional tone classification.
- **Interface**: `SignalDetector.analyze(user_input, history) -> SignalReport`
- **Dependencies**: None (heuristic, no LLM).
- **Constraints**: Must remain heuristic/regex-based. No LLM calls.

### ContextAssembler

- **Role**: Builds the layered system prompt. Assembly order: persona/protocol, domain context, artifact schemas, interaction rules, dynamic overlays, memory context.
- **Inputs**: DomainContext files, ProgressTracker overlays, CoachMemory context, conversation state.
- **Outputs**: Assembled system prompt string.
- **Interface**: `ContextAssembler.build(tracker_overlays, memory_context) -> str`
- **Dependencies**: DomainContext, ProgressTracker (for overlays), CoachMemory (for recall).
- **Constraints**: Domain context injection must remain file-driven as the baseline. Phase 2 adds a RAG integration point as an additional context source — it does not replace any existing layer.

### DomainContext

- **Role**: Loads domain knowledge from markdown files in `pipeline/intake/domain-context/`.
- **Inputs**: File system path.
- **Outputs**: List of domain context strings.
- **Interface**: `DomainContext.load() -> list[str]`
- **Dependencies**: File system.
- **Constraints**: Files are the source of truth. RAG augments; it does not replace this mechanism. New domain knowledge goes into markdown files first.

### CoachMemory

- **Role**: SQLite+FTS episodic recall of prior sessions. Stores crystallized session learnings.
- **Inputs**: Session crystallization output (constraints, decisions, assumptions, preferences).
- **Outputs**: Relevant prior context for current session.
- **Interface**: `CoachMemory.store(session_data)`, `CoachMemory.recall(query) -> list[MemoryEntry]`
- **Dependencies**: SQLite.
- **Constraints**: Interface is fixed. Storage backend can change but the contract must hold.

### Crystallizer

- **Role**: Extracts constraints, decisions, assumptions, and preferences at session end. No LLM call — purely heuristic.
- **Inputs**: Full conversation history.
- **Outputs**: Structured extraction (constraints, decisions, assumptions, preferences).
- **Interface**: `Crystallizer.extract(conversation) -> SessionCrystallization`
- **Dependencies**: None.
- **Constraints**: Must remain heuristic. No LLM dependency. Speed and cost are the reasons.

### AgentBackend (Interface)

- **Role**: Provider-agnostic LLM interface. All LLM calls from CoachEngine go through this.
- **Inputs**: System prompt, message history, generation parameters.
- **Outputs**: Response text (sync) or async token stream.
- **Interface**:
  ```
  AgentBackend.chat(messages, **kwargs) -> str
  AgentBackend.chat_stream(messages, **kwargs) -> AsyncIterator[str]
  ```
- **Dependencies**: Underlying LLM provider.
- **Constraints**: Interface is stable. Implementations are swappable. No coaching logic in implementations. CoachEngine must never call provider-specific methods directly.

---

## Agents — Phase 1 (llama.cpp Backend)

### LlamaCppBackend

- **Name**: `llama-cpp-backend`
- **Phase**: 1
- **Role**: AgentBackend implementation that serves LLaMA-family models via llama.cpp. Replaces OllamaBackend as the default backend for local inference.
- **Inputs**: System prompt, message history, generation parameters (temperature, top_p, top_k, max_tokens, stop sequences).
- **Outputs**: Response text (sync) or async token stream.
- **Interface**: Implements `AgentBackend`:
  ```
  LlamaCppBackend.chat(messages, **kwargs) -> str
  LlamaCppBackend.chat_stream(messages, **kwargs) -> AsyncIterator[str]
  ```
- **Dependencies**:
  - llama.cpp server process (HTTP API) or llama-cpp-python bindings
  - GGUF model file on disk
  - Model configuration: context window size, quantization level, GPU layers
- **Constraints**:
  - Must satisfy the full `AgentBackend` interface. No partial implementations.
  - Must support streaming. The server (`/api/coach`) relies on `chat_stream()`.
  - Must handle context window limits gracefully (truncation strategy for long conversations).
  - Must map generation parameters to llama.cpp equivalents without leaking abstractions.
  - Must not contain any coaching logic, signal detection, or prompt assembly.
  - Must pass `test_hardening.py` with all behavioral tests green.
  - Register as `--backend llama-cpp` in CLI argument parser.
- **Configuration**:
  - `--model` flag specifies GGUF model path or name
  - Context window size (default: model-dependent, typically 4096-8192)
  - GPU offload layers (0 for CPU-only)
  - Server mode: connect to running llama.cpp server vs. spawn embedded

### BackendValidator

- **Name**: `backend-validator`
- **Phase**: 1
- **Role**: Test harness that validates a new AgentBackend implementation against the behavioral contract. Runs `test_hardening.py` against the specified backend and produces a pass/fail report with diagnostics.
- **Inputs**: Backend identifier (e.g., `llama-cpp`), model configuration, test suite path.
- **Outputs**: Test results: pass/fail per test case, latency metrics, token throughput, failure diagnostics.
- **Interface**:
  ```
  BackendValidator.validate(backend_name, model_config) -> ValidationReport
  ```
- **Dependencies**: `test_hardening.py`, running LLM instance for the target backend.
- **Constraints**:
  - Must run the full `test_hardening.py` suite, not a subset.
  - Must report per-test pass/fail, not just aggregate.
  - Must capture response latency and streaming token rate for performance baseline.
  - Disposable after Phase 1 validation is complete, but useful to retain for future backend swaps.

### ModelServer

- **Name**: `model-server`
- **Phase**: 1
- **Role**: Manages the llama.cpp server process lifecycle. Starts, monitors, and restarts the server. Handles model loading and health checks.
- **Inputs**: GGUF model path, server configuration (port, context size, GPU layers, threads).
- **Outputs**: Server status, health check results, process handle.
- **Interface**:
  ```
  ModelServer.start(model_path, config) -> ServerHandle
  ModelServer.health() -> bool
  ModelServer.stop()
  ```
- **Dependencies**: llama.cpp binary (`llama-server` or equivalent).
- **Constraints**:
  - Must expose a health check endpoint that LlamaCppBackend can poll before sending requests.
  - Must handle process crashes with automatic restart.
  - Must log model loading time and memory usage for operational visibility.
  - Must not interfere with CoachEngine or any coaching component.

---

## Agents — Phase 2 (RAG-Augmented Domain Context)

### DocumentIndexer

- **Name**: `document-indexer`
- **Phase**: 2
- **Role**: Ingests domain context files (existing markdown + new Hoopla/MWT documents) into a vector store. Handles chunking, embedding generation, and index updates. Supports incremental ingestion without full reindex.
- **Inputs**: Document file paths (markdown, PDF, plain text), chunking configuration, embedding model reference.
- **Outputs**: Indexed document chunks in VectorStore.
- **Interface**:
  ```
  DocumentIndexer.ingest(file_paths: list[str]) -> IndexReport
  DocumentIndexer.ingest_directory(dir_path: str) -> IndexReport
  DocumentIndexer.remove(doc_id: str)
  DocumentIndexer.status() -> IndexStatus
  ```
- **Dependencies**: VectorStore, embedding model (local or API-based).
- **Constraints**:
  - Must handle the existing `pipeline/intake/domain-context/*.md` files as first-class inputs.
  - Must support incremental updates: adding a new file does not require reindexing everything.
  - Must support adding new documents without restarting the coach server.
  - Chunking strategy must preserve document structure (headers, sections) for retrieval quality.
  - Must store source file path and chunk location as metadata for traceability.
  - Embedding model is a configuration parameter, not hardcoded.

### VectorStore

- **Name**: `vector-store`
- **Phase**: 2
- **Role**: Stores and retrieves document chunk embeddings. Provides similarity search for the ContextRetriever.
- **Inputs**: Embedding vectors with metadata (source file, chunk index, section header).
- **Outputs**: Ranked list of relevant chunks with similarity scores.
- **Interface**:
  ```
  VectorStore.add(chunks: list[Chunk]) -> list[str]  # returns chunk IDs
  VectorStore.search(query_embedding: list[float], top_k: int) -> list[SearchResult]
  VectorStore.delete(chunk_ids: list[str])
  VectorStore.count() -> int
  ```
- **Dependencies**: Storage backend (FAISS, ChromaDB, SQLite-VSS, or similar).
- **Constraints**:
  - Implementation is swappable. The interface is what matters.
  - Must support metadata filtering (e.g., filter by source document).
  - Must persist to disk. In-memory-only is not acceptable for production use.
  - Must handle concurrent reads (retrieval) and writes (ingestion) safely.
  - Start with the simplest viable implementation (e.g., FAISS + pickle, or ChromaDB). Do not over-engineer.

### ContextRetriever

- **Name**: `context-retriever`
- **Phase**: 2
- **Role**: Retrieves relevant domain context chunks from the VectorStore based on the current conversation. Called by ContextAssembler during prompt assembly as an additional context source alongside the static file-driven baseline.
- **Inputs**: Query text (derived from current conversation turn and/or topic summary), retrieval parameters (top_k, similarity threshold).
- **Outputs**: List of relevant context chunks with source attribution.
- **Interface**:
  ```
  ContextRetriever.query(text: str, top_k: int = 5, threshold: float = 0.7) -> list[ContextChunk]
  ```
  Where `ContextChunk` contains: `content: str`, `source: str`, `score: float`, `metadata: dict`.
- **Dependencies**: VectorStore, embedding model (same as DocumentIndexer).
- **Constraints**:
  - Must return results fast enough to not degrade turn latency perceptibly. Target: <200ms for retrieval.
  - Must deduplicate against static DomainContext content. If a chunk comes from a file already loaded by DomainContext, skip it to avoid prompt bloat.
  - Must respect a total retrieved context budget (token count) to avoid blowing the context window.
  - Must include source attribution so ContextAssembler can mark retrieved context distinctly from static context in the prompt.
  - Must not modify any other ContextAssembler layers. It is an additive source only.

### EmbeddingProvider

- **Name**: `embedding-provider`
- **Phase**: 2
- **Role**: Generates embedding vectors for document chunks (indexing) and query text (retrieval). Abstracts the embedding model so DocumentIndexer and ContextRetriever are not coupled to a specific model.
- **Inputs**: Text string or batch of text strings.
- **Outputs**: Embedding vector(s).
- **Interface**:
  ```
  EmbeddingProvider.embed(text: str) -> list[float]
  EmbeddingProvider.embed_batch(texts: list[str]) -> list[list[float]]
  ```
- **Dependencies**: Embedding model (local via llama.cpp/sentence-transformers, or API-based).
- **Constraints**:
  - Must use the same model for indexing and retrieval. Mismatched embeddings break similarity search.
  - Interface is stable. Implementation is swappable (local model, API, etc.).
  - For Phase 2, prefer a local embedding model to avoid external API dependencies. Sentence-transformers or llama.cpp embedding mode are good candidates.
  - Must be configured independently of the chat model used by AgentBackend.

---

## Interface Contracts

These are the boundaries between the stable coaching core and the Phase 1/2 agents. All new agents connect through these contracts. No new agent may reach past these interfaces into coaching internals.

### Contract 1: AgentBackend (Phase 1 boundary)

```
class AgentBackend:
    def chat(self, messages: list[dict], **kwargs) -> str:
        """Synchronous completion. Returns full response text."""
        ...

    async def chat_stream(self, messages: list[dict], **kwargs) -> AsyncIterator[str]:
        """Streaming completion. Yields response tokens."""
        ...
```

**Message format**:
```python
{"role": "system" | "user" | "assistant", "content": str}
```

**Generation parameters** (passed via kwargs):
- `temperature: float` (default: 0.7)
- `max_tokens: int` (default: model-dependent)
- `top_p: float` (default: 0.9)
- `stop: list[str]` (optional stop sequences)

**Invariant**: CoachEngine calls only `chat()` and `chat_stream()`. It never references provider-specific concepts (GGUF, quantization, GPU layers, API keys). Those belong in the backend implementation and its configuration.

### Contract 2: ContextAssembler RAG Integration Point (Phase 2 boundary)

```
class ContextSource:
    def get_context(self, conversation_state: dict) -> list[ContextChunk]:
        """Returns relevant context chunks for the current conversation state."""
        ...
```

**Integration approach**: ContextAssembler gains an optional list of `ContextSource` providers. During prompt assembly, after loading static DomainContext (layer 2), it calls each registered ContextSource and appends retrieved chunks as a new sub-layer within the domain context layer.

**Invariant**: Static file-driven DomainContext always loads first and is never skipped. RAG results are additive. If no ContextSource is registered (Phase 1, or RAG is down), prompt assembly works exactly as it does today.

**Context budget**: ContextAssembler enforces a total token budget for the domain context layer (static + retrieved). If retrieved context would exceed the budget, it is truncated by relevance score, not by dropping static context.

### Contract 3: Artifact Handoff (Stable, cross-phase)

```
Artifacts produced by CoachEngine (gated by ProgressTracker):
  - business-case.md
  - epics.md
  - stories-draft.md

Format: Structured markdown, machine-readable.
No narrative prose, commentary, or caveats inside artifact output.
Schema defined in system prompt and enforced by ContextAssembler.
```

This contract does not change in Phase 1 or Phase 2. Downstream consumers (Spec Compiler, future Phase 3/4 agents) depend on this format.

---

## Phase Boundary Checklist

### Phase 1 Complete When

- [ ] `LlamaCppBackend` implements `AgentBackend.chat()` and `AgentBackend.chat_stream()`
- [ ] `ModelServer` manages llama.cpp server lifecycle with health checks
- [ ] `--backend llama-cpp` registered in CLI and selectable
- [ ] `test_hardening.py` passes fully against LlamaCppBackend with a LLaMA-family GGUF model
- [ ] Streaming works end-to-end through `/api/coach`
- [ ] No changes to CoachEngine, ProgressTracker, SignalDetector, ContextAssembler, or persona/protocol prompts
- [ ] BackendValidator produces a clean validation report
- [ ] Performance baseline documented (latency, token throughput)

### Phase 2 Complete When

- [ ] `DocumentIndexer` ingests all existing `pipeline/intake/domain-context/*.md` files + new Hoopla/MWT documents
- [ ] `VectorStore` persists to disk and supports concurrent read/write
- [ ] `EmbeddingProvider` uses a local embedding model
- [ ] `ContextRetriever` returns relevant chunks in <200ms
- [ ] `ContextAssembler` integrates retrieved context via `ContextSource` interface without modifying existing layers
- [ ] Static DomainContext continues to load and work as baseline (RAG down = graceful degradation)
- [ ] New documents can be added without server restart
- [ ] Deduplication between static and retrieved context is working
- [ ] Context budget enforcement prevents context window overflow
- [ ] `test_hardening.py` passes fully (coaching behavior unchanged)
- [ ] No changes to CoachEngine, ProgressTracker, SignalDetector, Crystallizer, or persona/protocol prompts
