# agents.md — Hoopla Coach Agent Topology

Covers Phase 1 (llama.cpp backend) through Phase 4 (Slack + auth). Priya's coaching core is documented here as a reference baseline. It does not change across phases.

**POC vs. Enterprise:** Phases 1–2 run in this (POC) repository. Phases 3–4 require the enterprise fork. The coaching core is shared across both; everything else is fork-specific.

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
               |    |       +--- OllamaBackend (POC only)       | reads
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
                      |
                      +--- ContextSource registry (Phase 3+, additive)


                         Phase 3 (Enterprise Fork)

  User <---> CoachEngine (unchanged)
               |
               +--- ContextAssembler
               |       +--- ConfluenceConnector (ContextSource)
               |       +--- AnalyticsStub [PROVISIONAL] (ContextSource)
               |
               +--- AgentBackend (CloudLLMBackend: Bedrock / Claude API)
               |
               +--- JiraConnector (artifact push / issue read)
               +--- ConfluenceConnector (doc read / page push)
               +--- AnalyticsStub [PROVISIONAL]


                         Phase 4 (Enterprise Fork)

  Slack <---> SlackBot <---> CoachEngine (unchanged)
                               |
                               +--- AuthGateway (SSO/SAML, per-user identity)
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
    |       |---> ContextRetriever.query()     [Phase 2 only, dynamic]
    |       +---> ContextSource.get_context()  [Phase 3+, each registered source]
    |
    +---> AgentBackend.chat_stream(prompt)     [LlamaCppBackend in Phase 1;
            |                                   CloudLLMBackend in Phase 3+]
            v
          Response to user
            |
            +---> (late session) Artifact generation if ProgressTracker gates pass
            |       +---> JiraConnector.push(artifact)     [Phase 3+]
            |       +---> ConfluenceConnector.push(artifact) [Phase 3+]
            +---> (session end) Crystallizer.extract() --> CoachMemory.store()
```

---

## Stability Classification

| Agent                | Stability   | Rationale                                                                      |
|----------------------|-------------|--------------------------------------------------------------------------------|
| CoachEngine          | **Stable**  | Core conversation controller. Tested by `test_hardening.py`. Shared across all phases. |
| ProgressTracker      | **Stable**  | Heuristic scoring, gates artifacts. Tested. Shared across all phases.           |
| SignalDetector       | **Stable**  | Heuristic signal detection, tone adaptation, privacy flagging. Tested.          |
| ContextAssembler     | **Stable**  | Layered prompt builder. New phases add integration points; existing layers unchanged. |
| CoachMemory          | **Stable**  | SQLite+FTS episodic memory. Interface is fixed; storage backend may change.     |
| Crystallizer         | **Stable**  | Heuristic session-end extractor. No LLM dependency.                             |
| DomainContext        | **Stable**  | File-driven loader. RAG augments; it does not replace.                          |
| AgentBackend         | **Stable**  | Interface is stable. Implementations are swappable.                             |
| OllamaBackend        | Ephemeral   | POC only. Will not be carried to enterprise fork.                               |
| LlamaCppBackend      | Ephemeral   | Phase 1 POC target. Implements AgentBackend. Not carried to enterprise fork.    |
| DocumentIndexer      | Ephemeral   | Phase 2. Ingestion pipeline. Replaceable with any indexer.                      |
| VectorStore          | Ephemeral   | Phase 2. Storage layer. Swappable (FAISS, Chroma, etc.).                        |
| ContextRetriever     | Ephemeral   | Phase 2. Retrieval layer. Swappable implementation.                             |
| EmbeddingProvider    | Ephemeral   | Phase 2. Embedding abstraction. Swappable.                                      |
| BackendValidator     | Ephemeral   | Phase 1. Test harness for backend swap. Disposable.                             |
| CloudLLMBackend      | Ephemeral   | Phase 3. AgentBackend impl for Bedrock / Claude API. Enterprise fork only.      |
| JiraConnector        | Ephemeral   | Phase 3. Artifact push + issue read. Enterprise fork only.                      |
| ConfluenceConnector  | Ephemeral   | Phase 3. Doc read + page push. Enterprise fork only.                            |
| AnalyticsStub        | Ephemeral   | Phase 3. Provisional stub. Subject to replacement. See privacy constraints.     |
| SlackBot             | Ephemeral   | Phase 4. Slack surface for CoachEngine. Enterprise fork only.                   |
| AuthGateway          | Ephemeral   | Phase 4. SSO/SAML identity. Enterprise fork only.                               |

**Rule**: Stable agents must not be modified without running `test_hardening.py` and getting explicit approval. Ephemeral agents can be replaced, rewritten, or removed without affecting coaching correctness.

---

## Agents — Stable Core (Reference Baseline)

These agents exist today and carry forward into all phases. They are documented here so Phase 1–4 agents know what they connect to and what they must not touch.

### CoachEngine

- **Role**: Multi-turn conversation controller. Drives all LLM calls via AgentBackend, injects the assembled system prompt, handles multimodal inputs and slash commands (`/help`, `/status`, `/generate`, `/reset`).
- **Inputs**: User text, file uploads, URLs, images, conversation history.
- **Outputs**: Streamed response text. Artifact markdown when gating passes.
- **Interface**: `CoachEngine.handle_turn(user_input) -> AsyncIterator[str]`
- **Dependencies**: AgentBackend, ProgressTracker, SignalDetector, ContextAssembler, CoachMemory, Crystallizer.
- **Constraints**: Provider-agnostic. No LLM-specific logic. Persona/protocol prompt text is load-bearing. No patron data in conversation history storage.

### ProgressTracker

- **Role**: Scores business-case completeness across fields: problem, evidence, users, impact, solution, metrics, risks, scope, platform. Gates artifact production. In Phase 3+, also gates on `privacy_impact` for features touching patron data.
- **Inputs**: Conversation history.
- **Outputs**: Completeness scores per field, overall readiness boolean, gap list.
- **Interface**: `ProgressTracker.score(conversation) -> CompletenessReport`
- **Dependencies**: None (heuristic, no LLM).
- **Constraints**: Must remain heuristic/regex-based. No LLM calls. Gating logic must not be bypassed or overridden.

### SignalDetector

- **Role**: Detects weak signals (solution-before-problem, vague metrics, COPPA minors, patron data exposure) and strong signals (quantified problems, hypotheses, tradeoffs). Feeds push-back and tone adaptation logic.
- **Inputs**: User input text, conversation history.
- **Outputs**: Signal list (type, strength, category), emotional tone classification.
- **Interface**: `SignalDetector.analyze(user_input, history) -> SignalReport`
- **Dependencies**: None (heuristic, no LLM).
- **Constraints**: Must remain heuristic/regex-based. No LLM calls. Must detect patron data exposure signals and Kids Mode / COPPA signals.

### ContextAssembler

- **Role**: Builds the layered system prompt. Assembly order: persona/protocol, domain context, artifact schemas, interaction rules, dynamic overlays, memory context.
- **Inputs**: DomainContext files, ProgressTracker overlays, CoachMemory context, conversation state. Phase 2+: ContextRetriever results. Phase 3+: registered ContextSource results.
- **Outputs**: Assembled system prompt string.
- **Interface**: `ContextAssembler.build(tracker_overlays, memory_context) -> str`
- **Dependencies**: DomainContext, ProgressTracker (for overlays), CoachMemory (for recall).
- **Constraints**: Domain context injection must remain file-driven as the baseline. Phase 2 RAG and Phase 3 ContextSources are additive — they do not replace any existing layer. If any ContextSource is unavailable, prompt assembly falls back gracefully.

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
- **Constraints**: Interface is fixed. Storage backend can change but the contract must hold. Must not store patron-identifiable data.

### Crystallizer

- **Role**: Extracts constraints, decisions, assumptions, and preferences at session end. No LLM call — purely heuristic.
- **Inputs**: Full conversation history.
- **Outputs**: Structured extraction (constraints, decisions, assumptions, preferences).
- **Interface**: `Crystallizer.extract(conversation) -> SessionCrystallization`
- **Dependencies**: None.
- **Constraints**: Must remain heuristic. No LLM dependency. Speed and cost are the reasons. Must not include patron data in crystallization output.

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

## Agents — Phase 1 (llama.cpp Backend, POC Only)

These agents are POC-specific. They will not be carried to the enterprise fork.

### LlamaCppBackend

- **Name**: `llama-cpp-backend`
- **Phase**: 1 (POC)
- **Role**: AgentBackend implementation that serves LLaMA-family models via llama.cpp. Replaces OllamaBackend as the default local backend.
- **Inputs**: System prompt, message history, generation parameters.
- **Outputs**: Response text (sync) or async token stream.
- **Interface**: Implements `AgentBackend`.
- **Dependencies**: llama.cpp server process or llama-cpp-python bindings; GGUF model file.
- **Constraints**:
  - Must satisfy the full `AgentBackend` interface.
  - Must support streaming.
  - Must pass `test_hardening.py` with a LLaMA-family GGUF model.
  - Register as `--backend llama-cpp` in CLI.
  - **Not carried to enterprise fork.** Enterprise uses CloudLLMBackend.

### BackendValidator

- **Name**: `backend-validator`
- **Phase**: 1 (POC)
- **Role**: Test harness that validates a new AgentBackend implementation against the behavioral contract.
- **Outputs**: Pass/fail per test case, latency metrics, token throughput, failure diagnostics.
- **Constraints**: Must run full `test_hardening.py`, not a subset. Disposable after validation is complete.

### ModelServer

- **Name**: `model-server`
- **Phase**: 1 (POC)
- **Role**: Manages llama.cpp server process lifecycle.
- **Interface**: `ModelServer.start()`, `ModelServer.health()`, `ModelServer.stop()`
- **Constraints**: Must expose a health check endpoint. Must handle crashes with auto-restart. Must not interfere with any coaching component.

---

## Agents — Phase 2 (RAG-Augmented Domain Context, POC)

### DocumentIndexer

- **Name**: `document-indexer`
- **Phase**: 2 (POC)
- **Role**: Ingests domain context files into a vector store. Handles chunking, embedding generation, and incremental index updates.
- **Interface**:
  ```
  DocumentIndexer.ingest(file_paths: list[str]) -> IndexReport
  DocumentIndexer.ingest_directory(dir_path: str) -> IndexReport
  DocumentIndexer.remove(doc_id: str)
  DocumentIndexer.status() -> IndexStatus
  ```
- **Constraints**: Handles existing `pipeline/intake/domain-context/*.md` as first-class inputs. Supports incremental updates. Chunking preserves document structure.

### VectorStore

- **Name**: `vector-store`
- **Phase**: 2 (POC)
- **Role**: Stores and retrieves document chunk embeddings. Provides similarity search.
- **Interface**:
  ```
  VectorStore.add(chunks: list[Chunk]) -> list[str]
  VectorStore.search(query_embedding: list[float], top_k: int) -> list[SearchResult]
  VectorStore.delete(chunk_ids: list[str])
  VectorStore.count() -> int
  ```
- **Constraints**: Must persist to disk. Must handle concurrent reads and writes safely. Implementation is swappable (FAISS, ChromaDB, SQLite-VSS).

### ContextRetriever

- **Name**: `context-retriever`
- **Phase**: 2 (POC)
- **Role**: Retrieves relevant domain context chunks from VectorStore. Called by ContextAssembler as an additional source alongside static DomainContext.
- **Interface**:
  ```
  ContextRetriever.query(text: str, top_k: int = 5, threshold: float = 0.7) -> list[ContextChunk]
  ```
  Where `ContextChunk` contains: `content: str`, `source: str`, `score: float`, `metadata: dict`.
- **Constraints**:
  - Target retrieval latency: <200ms.
  - Must deduplicate against static DomainContext content.
  - Must respect a total context budget (token count).
  - Must include source attribution.
  - Implements `ContextSource` interface (same interface used by Phase 3 connectors).

### EmbeddingProvider

- **Name**: `embedding-provider`
- **Phase**: 2 (POC)
- **Role**: Generates embedding vectors for document chunks and query text. Abstracts the embedding model.
- **Interface**:
  ```
  EmbeddingProvider.embed(text: str) -> list[float]
  EmbeddingProvider.embed_batch(texts: list[str]) -> list[list[float]]
  ```
- **Constraints**: Same model for indexing and retrieval. For Phase 2, prefer a local embedding model. Configured independently of the chat model.

---

## Agents — Phase 3 (Enterprise Fork: Integrations)

**All Phase 3 agents live in the enterprise fork, not this repo.**

### CloudLLMBackend

- **Name**: `cloud-llm-backend`
- **Phase**: 3 (Enterprise fork)
- **Role**: AgentBackend implementation for hosted cloud LLMs (Amazon Bedrock, Anthropic Claude API). Replaces local backends in the enterprise build.
- **Interface**: Implements `AgentBackend`.
- **Constraints**:
  - Must satisfy the full `AgentBackend` interface.
  - Must support streaming.
  - Must handle rate limits and retry with backoff.
  - Must never log prompt content at the INFO level or below — prompts may contain sensitive product information.
  - Must pass `test_hardening.py` against the configured cloud model.
  - Register as `--backend cloud` in CLI.

### JiraConnector

- **Name**: `jira-connector`
- **Phase**: 3 (Enterprise fork)
- **Role**: Reads Jira issues for context enrichment and pushes completed artifacts as linked Jira documents or attachments.
- **Inputs**: Jira project key, issue ID, artifact markdown.
- **Outputs**: Retrieved issue content as ContextSource results; push confirmation.
- **Interface**:
  ```
  JiraConnector.get_context(conversation_state: dict) -> list[ContextChunk]  # ContextSource
  JiraConnector.push_artifact(issue_id: str, artifact: str, artifact_type: str) -> str  # returns Jira link
  JiraConnector.read_issue(issue_id: str) -> JiraIssue
  ```
- **Dependencies**: Jira REST API, credentials from environment/secrets manager.
- **Constraints**:
  - Implements `ContextSource` interface for ContextAssembler registration.
  - CoachEngine must function if JiraConnector is unavailable. It is always optional.
  - Must not pass patron data to Jira. Artifacts must be scrubbed of any patron-identifiable content before push.
  - Credentials must come from a secrets manager, never from code or environment files checked in.
  - Jira-sourced context must be tagged in the prompt as `[JIRA-CONTEXT]` for traceability.

### ConfluenceConnector

- **Name**: `confluence-connector`
- **Phase**: 3 (Enterprise fork)
- **Role**: Reads existing Confluence documents for session context and pushes completed business cases as Confluence pages.
- **Interface**:
  ```
  ConfluenceConnector.get_context(conversation_state: dict) -> list[ContextChunk]  # ContextSource
  ConfluenceConnector.push_page(space_key: str, title: str, artifact: str) -> str  # returns Confluence URL
  ConfluenceConnector.read_page(page_id: str) -> ConfluencePage
  ```
- **Dependencies**: Confluence REST API, credentials from environment/secrets manager.
- **Constraints**:
  - Implements `ContextSource` interface.
  - CoachEngine must function if unavailable.
  - Pre-existing Jira/Confluence templates (stored as markdown in `pipeline/intake/`) govern output page structure.
  - Must not push patron data to Confluence.
  - Confluence-sourced context tagged as `[CONFLUENCE-CONTEXT]` in the prompt.

### AnalyticsStub

- **Name**: `analytics-stub`
- **Phase**: 3 (Enterprise fork) — **PROVISIONAL**
- **Role**: Placeholder interface for Hoopla's in-house analytics system. Returns stub data only. Intended for replacement when the Hoopla analytics system redesign is complete.
- **Interface**:
  ```
  AnalyticsStub.get_context(conversation_state: dict) -> list[ContextChunk]  # ContextSource
  AnalyticsStub.query(metric: str, filters: dict) -> AnalyticsResult
  ```
- **Dependencies**: None (stub returns placeholder data).
- **Constraints**:
  - **This agent is explicitly provisional.** Do not build logic that depends on its output being accurate.
  - Must return stub `ContextChunk` objects with a clear `[ANALYTICS-PENDING]` tag so ContextAssembler and Priya can surface the gap to the user.
  - Must implement the `ContextSource` interface so it can be swapped for a real implementation without changes to ContextAssembler.
  - Any real implementation that replaces this stub must enforce data anonymization: no patron-level records may be returned through this interface.
  - The stub must never generate plausible-looking fake numbers. It returns explicit stubs, not estimates.

---

## Agents — Phase 4 (Enterprise Fork: User Surface)

**All Phase 4 agents live in the enterprise fork.**

### SlackBot

- **Name**: `slack-bot`
- **Phase**: 4 (Enterprise fork)
- **Role**: Surfaces Priya via Slack. Handles multi-user sessions in DMs and channels. Routes Slack messages to CoachEngine and streams responses back.
- **Inputs**: Slack events (messages, file uploads, slash commands from Slack).
- **Outputs**: Streamed Slack messages, threaded replies, artifact attachments.
- **Interface**:
  ```
  SlackBot.handle_event(slack_event: dict) -> None  # dispatches to CoachEngine
  SlackBot.send_response(channel_id: str, thread_ts: str, text: str) -> None
  SlackBot.send_artifact(channel_id: str, thread_ts: str, artifact: str, filename: str) -> None
  ```
- **Dependencies**: Slack Bolt SDK, CoachEngine, AuthGateway.
- **Constraints**:
  - Each Slack user gets an isolated CoachEngine session. Sessions must not bleed across users.
  - SlackBot is a transport layer only. No coaching logic lives here.
  - Slash commands from Slack (`/priya`, or however the bot is invoked) map to CoachEngine slash commands (`/help`, `/status`, `/generate`, `/reset`).
  - Artifacts delivered via Slack must be posted as file attachments (markdown files), not inline text, to preserve structure.
  - Session context (CoachMemory) is scoped to the Slack user identity resolved by AuthGateway.
  - Must not log Slack message content at INFO level or below.

### AuthGateway

- **Name**: `auth-gateway`
- **Phase**: 4 (Enterprise fork)
- **Role**: Resolves user identity via SSO/SAML. Ties user identity to CoachMemory sessions and per-user session isolation.
- **Inputs**: Slack user ID or session token.
- **Outputs**: Resolved user identity (internal user ID, role, team).
- **Interface**:
  ```
  AuthGateway.resolve_identity(slack_user_id: str) -> UserIdentity
  AuthGateway.authorize(user_identity: UserIdentity, action: str) -> bool
  ```
- **Dependencies**: SSO/SAML provider (Okta, Azure AD, or similar), enterprise identity store.
- **Constraints**:
  - User identity must be resolved before any CoachEngine session is opened.
  - Role-based authorization is supported but minimal in Phase 4: all authenticated PM/PO/BSA users have full access to Priya.
  - User identity is used only for session scoping and CoachMemory recall — not for any behavioral differentiation in Priya's responses.
  - Must not store credentials. Resolves identity per request against the SSO provider.

---

## Interface Contracts

These are the boundaries between the stable coaching core and the Phase 1–4 agents. All new agents connect through these contracts. No new agent may reach past these interfaces into coaching internals.

### Contract 1: AgentBackend (All phases)

```python
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

**Generation parameters** (via kwargs):
- `temperature: float` (default: 0.7)
- `max_tokens: int` (default: model-dependent)
- `top_p: float` (default: 0.9)
- `stop: list[str]` (optional stop sequences)

**Invariant**: CoachEngine calls only `chat()` and `chat_stream()`. It never references provider-specific concepts (GGUF, quantization, GPU layers, API keys, region). Those belong in the backend implementation and its configuration.

### Contract 2: ContextSource (Phase 2+ for RAG; Phase 3+ for connectors)

```python
class ContextSource:
    def get_context(self, conversation_state: dict) -> list[ContextChunk]:
        """Returns relevant context chunks for the current conversation state.
        Must return an empty list (not raise) if the source is unavailable."""
        ...
```

**Integration approach**: ContextAssembler maintains an optional list of `ContextSource` providers. During prompt assembly, after loading static DomainContext (layer 2), it calls each registered ContextSource and appends retrieved chunks as a sub-layer.

**Invariant**: Static file-driven DomainContext always loads first and is never skipped. All ContextSource results are additive. If no ContextSource is registered or all sources fail, prompt assembly works exactly as today.

**Context budget**: ContextAssembler enforces a total token budget for the domain context layer (static + retrieved). Truncation is by relevance score, never by dropping static content.

**Privacy constraint**: ContextSources must never return patron-identifiable data. Any ContextSource that reads from a system with patron data must anonymize or aggregate before returning context chunks.

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

**Privacy Impact field**: For any feature that touches patron data (detected by SignalDetector), `business-case.md` must include a `## Privacy Impact` section. ProgressTracker gates artifact generation until this field is present. The field includes:
- Data types accessed or created
- Retention policy
- Anonymization/aggregation approach
- COPPA applicability (Kids Mode)
- Legal exposure assessment

This contract does not change across phases. Downstream consumers (Spec Compiler, JiraConnector, ConfluenceConnector) depend on this format.

---

## Privacy Constraints (Cross-Cutting)

These constraints apply to all agents at all phases. They are not phase-specific.

1. **No patron-level records through any interface.** Patron borrowing history, reading habits, and content interactions are private. No agent may request, store, log, or pass through non-anonymized patron data.

2. **Analytics data must be aggregated.** Any integration with Hoopla's analytics system (stub or real) must return only aggregated or anonymized metrics. Row-level patron data is never acceptable through this channel.

3. **Kids Mode features require explicit COPPA treatment.** Any feature proposal involving Kids Mode must include a `## Privacy Impact` section in its business case and must pass ProgressTracker's `privacy_impact` gate.

4. **Logging must not capture conversation content at INFO or below.** LLM prompt content may contain sensitive product strategy. Log levels at INFO and below must not capture message text. ERROR-level logs may capture error context without conversation content.

5. **Credentials through secrets manager only.** API keys, OAuth tokens, and SSO credentials for Jira, Confluence, analytics, and Slack must come from a secrets manager. Never from code, .env files checked in, or environment-variable fallbacks that are not injected at runtime.

---

## Phase Boundary Checklists

### Phase 1 Complete When (POC)

- [ ] `LlamaCppBackend` implements `AgentBackend.chat()` and `AgentBackend.chat_stream()`
- [ ] `ModelServer` manages llama.cpp server lifecycle with health checks
- [ ] `--backend llama-cpp` registered in CLI and selectable
- [ ] `test_hardening.py` passes fully against LlamaCppBackend with a LLaMA-family GGUF model
- [ ] Streaming works end-to-end through `/api/coach`
- [ ] No changes to CoachEngine, ProgressTracker, SignalDetector, ContextAssembler, or persona/protocol prompts
- [ ] BackendValidator produces a clean validation report
- [ ] Performance baseline documented (latency, token throughput)

### Phase 2 Complete When (POC)

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
- [ ] Patron privacy and Kids Mode domain context files added to `pipeline/intake/domain-context/`

### Phase 3 Complete When (Enterprise Fork)

- [ ] Enterprise fork created from POC
- [ ] Coaching core extracted as installable package (or cleanly vendored)
- [ ] `CloudLLMBackend` implements `AgentBackend` for Bedrock or Claude API
- [ ] `test_hardening.py` passes fully against cloud backend
- [ ] `JiraConnector` reads issues and pushes artifacts; CoachEngine degrades gracefully when unavailable
- [ ] `ConfluenceConnector` reads pages and pushes business cases; CoachEngine degrades gracefully when unavailable
- [ ] `AnalyticsStub` implements `ContextSource`; returns `[ANALYTICS-PENDING]` tagged stubs
- [ ] ProgressTracker gates `privacy_impact` field for patron-data features
- [ ] `business-case.md` schema updated to include `## Privacy Impact` section
- [ ] No patron data passes through any connector or stub
- [ ] Credentials served from secrets manager (not .env files)
- [ ] Logging does not capture conversation content at INFO or below

### Phase 4 Complete When (Enterprise Fork)

- [ ] `SlackBot` routes Slack messages to CoachEngine with user session isolation
- [ ] `AuthGateway` resolves Slack user identity via SSO/SAML
- [ ] CoachMemory is scoped to authenticated user identity
- [ ] Artifacts delivered via Slack as file attachments (structured markdown preserved)
- [ ] Multi-user sessions do not bleed across users
- [ ] No coaching logic in SlackBot (transport only)
- [ ] `test_hardening.py` passes (coaching behavior unchanged)
- [ ] All Phase 3 constraints hold

### Phase 5 Complete When (Enterprise Fork)

- [ ] Beta deployed to real PM/PO/BSA users at MWT
- [ ] Session-to-artifact completion rate tracked
- [ ] Engineering team artifact adoption rate tracked
- [ ] Spec quality feedback loop established (did the artifact actually produce a good spec?)
- [ ] AnalyticsStub replacement plan confirmed based on status of Hoopla analytics redesign
- [ ] No patron-privacy incidents in beta period
