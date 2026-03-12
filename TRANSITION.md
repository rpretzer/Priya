# TRANSITION.md — Hoopla Coach Enterprise Fork Handoff

**This document is written for Amazon Kiro, Claude Code, or any AI agent that picks up
this work in a fresh context.** Read it fully before making any changes to the codebase
or designing the enterprise fork.

**Date**: 2026-03-12
**Handoff state**: POC complete through Phase B. Enterprise fork (Phase 3) is next.
**POC repo**: `github.com/rpretzer/Priya` branch `claude/init-015FfCqGH47w2ypz6P3jstSM`

---

## 1. What this system is

Hoopla Coach is a **spec funnel**: a structured AI coaching system for Hoopla Digital's product
team (PMs, POs, BSAs). Its job is to guide product stakeholders through intake conversations
and produce **machine-readable business artifacts** for downstream engineering workflows.

The AI assistant persona is **Priya Desai**. She is a product development coach, not a
general-purpose chatbot. She challenges vague thinking, enforces rigor, and produces structured
output gated on completeness. She does not generate code. She does not give compliments. She
corrects herself cleanly when wrong.

This system serves **Hoopla Digital / Midwest Tapes (MWT)** — a B2B2C digital content lending
platform for public libraries. Every design decision you make must be understood in that context.

---

## 2. POC state at handoff

| Phase | What was built | Tests |
|-------|---------------|-------|
| A | Six session modes (INTAKE, WORKING\_BACKWARDS, PREMORTEM, STEELMAN, PRIORITIZE, RETROSPECT); epistemic triage; patron privacy gate; error correction protocol | 114 heuristic tests |
| 2 | RAG: ContextRetriever, VectorStore (numpy), EmbeddingProvider (TFIDF + sentence-transformers + llamacpp), DocumentIndexer | 32 RAG tests |
| B | Active memory: feature index in CoachMemory, `recall_similar_feature`, `lookup_feature_outcome`, `extract_feature_name`, MemorySource ContextSource, `/recall` command, `close_session` | 46 heuristic tests (160 total) |

**Phase 1 (llama.cpp backend)** exists in the POC but is **not a prerequisite for the enterprise
fork**. The enterprise fork starts directly from cloud LLM backends (Bedrock / Claude API).

---

## 3. The core invariant: Sacred Boundaries

Before writing a single line of code, internalize these. Violating them breaks the system.

### 3.1 Priya's behavioral contract is load-bearing

`pipeline/methodology/personas/coach-priya.md` and the behavioral logic in `engine.py`
constitute Priya's identity. The following are **hard constraints enforced by `test_hardening.py`**:

- Push-back on: vague impact, solution-before-problem, unmeasurable metrics, scope creep,
  missing rollout strategy, patron data without privacy justification
- Anti-loop rule: never re-ask a question from a prior turn
- No compliments ("Great question!" is a test failure)
- No code generation (redirect to Spec Compiler)
- No fabrication (state `[ASSUMPTION: ...]` or `[UNKNOWN: ...]` explicitly)
- Error correction: acknowledge specifically, correct immediately, do not apologize repeatedly
- Epistemic tagging: `[DATA: source]`, `[INFERENCE: reasoning]`, `[ASSUMPTION: basis]`, `[UNKNOWN: what resolves this]`

**Do not soften, bypass, or "improve" any of these without running the full hardening suite
and getting explicit approval from the product owner.**

### 3.2 The spec funnel boundary is absolute

Priya produces only:
- `business-case.md` — problem, evidence, users, impact, solution, metrics, risks, scope, privacy impact
- `epics.md` — feature groupings with acceptance criteria
- `stories-draft.md` — user stories with sizing guidance
- Mode-specific artifacts: `working-backwards.md`, `pre-mortem.md`, `steelman.md`, `priority-stack.md`, `retrospect.md`

She **never** generates code, SQL, API contracts, system design diagrams, Confluence markup, or
Jira ticket bodies. A downstream Spec Compiler translates artifacts to engineering formats.

### 3.3 Backend is swappable; coaching logic is not

`AgentBackend` in `pipeline/backends/base.py` is the only interface between coaching logic and
LLMs. All cloud LLM backends must implement this interface. Never embed provider-specific
behavior in `CoachEngine`, `ProgressTracker`, `SignalDetector`, or `ContextAssembler`.

### 3.4 Domain context is file-driven

Domain knowledge lives in `pipeline/intake/domain-context/*.md`. Add knowledge there,
not in prompt templates. RAG augments this but does not replace it.

### 3.5 Artifact gating is intentional

`ProgressTracker` gates artifact production. Features touching patron data also require
`privacy_impact` field coverage. Do not add overrides. The gating ensures downstream consumers
receive well-formed specs.

### 3.6 Patron privacy is non-negotiable

Library patron data (borrowing history, reading preferences, content interactions) is protected
by the **library social contract** (ALA principles) and Hoopla's legal exposure posture.

Rules that apply in all phases:
- No non-anonymized patron data in memory, logs, artifacts, analytics, or LLM prompts
- No patron data to law enforcement without proper legal process
- Kids Mode features must address COPPA and data minimization explicitly
- The `## Privacy Impact` section in `business-case.md` is mandatory for patron-data features

---

## 4. Architecture reference

```
pipeline/
  coach/
    __main__.py       ← CLI entry point: python3 -m pipeline.coach
    server.py         ← FastAPI/Starlette server, /api/coach (streaming)
    engine.py         ← CoachEngine, ProgressTracker, SignalDetector,
                        ContextAssembler, DomainContext, SessionMode,
                        MemorySource, FieldStatus, ContextChunk, ContextSource
    memory.py         ← CoachMemory (SQLite+FTS5): sessions, crystal_items,
                        artifacts, conversations, features (Phase B)
    crystallizer.py   ← Crystallizer (heuristic), extract_feature_name
    rag/              ← Phase 2: ContextRetriever, VectorStore, EmbeddingProvider,
                        DocumentIndexer, test_rag.py
    test_hardening.py ← Behavioral spec (160 heuristic + 13 live-LLM tests)
    tools.py          ← URLFetcher, FileProcessor, SlashCommandHandler
    model_server.py   ← llama.cpp process management (POC only)
    backend_validator.py ← Health checks for backend startup
  backends/
    base.py           ← AgentBackend ABC + AgentResult
    ollama.py         ← OllamaBackend (POC only)
    llamacpp.py       ← LlamaCppBackend (POC only)
    bedrock.py        ← BedrockBackend ← use this in enterprise fork
    assisted.py       ← AssistedBackend (Claude API) ← use this in enterprise fork
  intake/
    domain-context/   ← File-driven domain knowledge (loaded by DomainContext)
      hoopla-domain.md
      mwt-product-context.md
      patron-privacy.md
      platform-architecture.md
      exercises/      ← Exercise templates for non-intake session modes
        working-backwards.md
        premortem.md
        steelman.md
        prioritize.md
        retrospect.md
  methodology/
    personas/
      coach-priya.md  ← Priya's full behavioral specification (load-bearing)
agents.md             ← Agent topology and interface contracts
CLAUDE.md             ← Project instructions for Claude Code sessions
TRANSITION.md         ← This file
WORK_LOG.md           ← Session work log (append-only)
scripts/
  log_work.py         ← Work log helper
  build_rag_index.py  ← Build/update RAG index from domain context files
```

### Data flow

```
User input
  → CoachEngine.chat_stream()
      → SignalDetector.analyze()      [heuristic, no LLM]
      → ProgressTracker.update()      [heuristic, no LLM]
      → ContextAssembler.build()
          → DomainContext.load()      [file-driven]
          → DomainContext.load_exercise()  [non-intake modes]
          → MemorySource.get_context()    [Phase B analogues / prior specs]
          → ContextRetriever.get_context()  [Phase 2 RAG, if enabled]
          → ProgressTracker overlays   [turn-count-aware guidance]
          → CoachMemory.recall()      [crystal item context]
      → AgentBackend.chat_stream()    [LLM call — only LLM call in the hot path]
  → Response streamed to user
  → (session end) CoachEngine.close_session()
      → Crystallizer.extract()        [heuristic, no LLM]
      → CoachMemory.save_session()
      → extract_feature_name()        [heuristic, no LLM]
      → CoachMemory.save_feature()
```

**Key design principle**: Only one LLM call per turn. Everything else — signal detection,
completeness scoring, memory retrieval, context assembly — is heuristic and deterministic.
This keeps latency predictable and costs low.

---

## 5. Running the test suite

```bash
# Heuristic tests only (no LLM required) — run these after EVERY change
python3 -m pytest pipeline/coach/test_hardening.py pipeline/coach/rag/test_rag.py -q --tb=short -k "not live"

# Full suite including live LLM tests (requires configured backend)
python3 -m pytest pipeline/coach/test_hardening.py -v
```

**`test_hardening.py` is the behavioral contract.** If it fails, do not merge. The 13 skipped
tests require a live LLM (`@pytest.mark.skipif` on `OLLAMA_BASE_URL` / `ANTHROPIC_API_KEY`).
Configure the appropriate env vars to run them against the enterprise backend.

---

## 6. Phase 3: Enterprise Fork — what to build

### 6.1 Fork setup

```bash
# Create enterprise fork
git clone https://github.com/rpretzer/Priya hoopla-coach-enterprise
cd hoopla-coach-enterprise

# Remove POC-only backends
rm pipeline/backends/ollama.py pipeline/backends/llamacpp.py
rm pipeline/coach/model_server.py pipeline/coach/backend_validator.py

# Recommended: extract coaching core as installable package
# Structure: packages/hoopla-coach-core/ containing:
#   pipeline/coach/engine.py
#   pipeline/coach/memory.py
#   pipeline/coach/crystallizer.py
#   pipeline/coach/rag/
#   pipeline/methodology/personas/
#   pipeline/intake/domain-context/
# Then: pip install -e packages/hoopla-coach-core/ in both repos
```

### 6.2 Cloud LLM backend

The enterprise fork uses `BedrockBackend` (already implemented in `pipeline/backends/bedrock.py`)
or `AssistedBackend` (Claude API, `pipeline/backends/assisted.py`).

**Check `BedrockBackend`** by running:
```bash
--backend bedrock --model anthropic.claude-3-5-sonnet-20241022-v2:0
```

If using Claude API directly (`AssistedBackend`), set `ANTHROPIC_API_KEY`.

**Run `test_hardening.py` against the cloud backend before doing anything else.** The live
tests must pass. If they fail, debug the persona prompt injection, not the tests.

### 6.3 JiraConnector

**Interface contract** (from `agents.md`):

```python
class JiraConnector:
    """Ephemeral agent. CoachEngine must work if unavailable."""

    def get_issues(self, project_key: str, jql: str = "") -> list[dict]:
        """Return issues matching JQL. Each dict: {id, summary, description, status, labels}."""

    def push_artifact(self, issue_key: str, artifact_content: str, artifact_type: str) -> str:
        """Attach artifact to issue. Returns attachment URL."""

    def create_linked_spec(self, parent_key: str, summary: str, artifact_content: str) -> str:
        """Create a child issue with artifact as description. Returns new issue key."""
```

**Integration point in `ContextAssembler`**: add a `JiraContextSource` that implements the
`ContextSource` protocol. It should:
1. Receive `project_key` and/or `issue_key` from the conversation (extract heuristically)
2. Call `JiraConnector.get_issues()` to retrieve relevant context
3. Return `ContextChunk` objects — Priya receives these as domain context, not raw Jira data
4. Degrade gracefully (return `[]`) if Jira is unavailable

**Privacy constraint**: strip any patron-identifiable data before injecting Jira content into
the prompt. Jira issues may contain patron IDs in comments — the connector must filter them.

### 6.4 ConfluenceConnector

Same isolation pattern as Jira:

```python
class ConfluenceConnector:
    """Ephemeral agent. CoachEngine must work if unavailable."""

    def search_pages(self, query: str, space_key: str = "") -> list[dict]:
        """Return pages matching CQL query. Each dict: {id, title, body_excerpt, url}."""

    def push_business_case(self, space_key: str, parent_id: str,
                           title: str, artifact_content: str) -> str:
        """Create/update a Confluence page with artifact content. Returns page URL."""
```

`ConfluenceContextSource` follows the same ContextSource protocol. Inject retrieved page
excerpts as domain context chunks, not raw Confluence markup.

### 6.5 AnalyticsStub

The Hoopla analytics system is being redesigned. Build a stub that satisfies the interface
but returns `[ANALYTICS-PENDING: ...]` markers for all data requests:

```python
class AnalyticsStub:
    """Provisional stub. Do not build logic that depends on this being accurate."""

    def get_circulation_trend(self, content_type: str, days: int = 90) -> dict:
        """Returns {'status': 'pending', 'note': 'Analytics system unavailable'}."""

    def get_platform_engagement(self, platform: str, days: int = 90) -> dict:
        """Returns {'status': 'pending', 'note': 'Analytics system unavailable'}."""
```

When Priya would use analytics data to strengthen a business case, she should output:
`[ANALYTICS-PENDING: this claim requires data from the Hoopla analytics system, which is
currently unavailable due to infrastructure redesign]`

Do not build production analytics logic. The stub interface is designed for replacement.

### 6.6 AuthGateway (Phase 4 but design now)

The enterprise fork needs user identity tied to session and memory. Design the interface
while building Phase 3 so the memory layer is ready for it:

```python
class AuthGateway:
    def verify_token(self, token: str) -> dict:
        """Returns {'user_id': str, 'email': str, 'role': str} or raises AuthError."""

    def get_user_permissions(self, user_id: str) -> list[str]:
        """Returns list of permission strings: ['intake', 'premortem', 'admin', ...]."""
```

In `CoachMemory`, add `user_id` to the `sessions` table. In `close_session()`, pass `user_id`
so session learnings are scoped to the user. This enables per-user memory recall in Phase B.

### 6.7 Updated ProgressTracker for privacy gate

The privacy gate is already implemented as a heuristic pattern match. In Phase 3, make the
`privacy_impact` field an explicit scored field in `ProgressTracker` for INTAKE mode:

```python
# Add to _SCORED_FIELDS in engine.py
_SCORED_FIELDS = [
    "problem", "evidence", "users", "impact", "solution",
    "metrics", "risks", "scope", "platform",
    "privacy_impact",   # ← gated: only required when patron data detected
]
```

The gate logic already exists (`_privacy_gate_required`, `_privacy_impact_met`). This just
makes it visible in `/status` output and ProgressTracker completeness scoring.

---

## 7. Phase 4: Slack + Auth

### SlackBot

```python
class SlackBot:
    """Routes Slack messages to CoachEngine sessions."""

    def handle_message(self, event: dict) -> str:
        """
        event: {user_id, channel_id, text, files}
        Returns response text to post back to Slack.
        Uses user_id to look up or create a session in CoachMemory.
        """
```

**Important**: Slack messages are multi-user. Each `user_id` gets an independent `CoachEngine`
session. Do not mix sessions. Do not surface one user's memory to another.

The Slack integration is a transport layer. `CoachEngine` does not change. `SlackBot` wraps it.

### AuthGateway wiring

1. Middleware in `server.py` that calls `AuthGateway.verify_token()` on every request
2. User identity propagated to `CoachEngine` via session metadata
3. `CoachMemory` sessions scoped by `user_id` — users recall only their own past sessions
4. Admin users can view aggregate session statistics (no patron data, no individual user details)

---

## 8. Phase 5: Beta deployment and measurement

### What to measure

The goal of beta deployment is to answer: **does Priya improve spec quality in the engineering
pipeline?** Proxy metrics:

1. **Artifact completeness rate**: % of sessions that reach artifact generation (vs abandon)
2. **Field coverage**: average ProgressTracker completeness score at artifact generation
3. **Spec-to-story latency**: time from Priya artifact to first engineering story in Jira
4. **Rework rate**: % of Priya-originated specs that require major revision after engineering review
5. **Privacy gate trigger rate**: % of sessions where patron data is mentioned (measures awareness)

**Do not use patron-level data to compute any of these metrics.** All metrics are session-level
aggregates, anonymized before analysis.

### ProgressTracker weight iteration

After beta data is collected, field weights in `_COMPLETENESS_WEIGHTS` can be tuned based on
which fields correlate with high-quality downstream engineering outcomes. This is data-driven
iteration on a heuristic — it does not touch Priya's persona or behavioral contract.

---

## 9. What not to do (re-stated for fresh context)

This list exists because the mistakes are tempting. They break things.

1. **Do not change `coach-priya.md` or persona prompt text** without running `test_hardening.py`
2. **Do not add code generation to Priya** — not even "just one SQL query"
3. **Do not bypass `ProgressTracker` artifact gating** — not even for demos
4. **Do not put provider-specific logic in `CoachEngine`** — it belongs in a backend
5. **Do not hardcode domain knowledge** — put it in `pipeline/intake/domain-context/`
6. **Do not add compliments to Priya** — "Great question!" fails a test
7. **Do not re-ask questions** — the anti-loop rule is tested and enforced
8. **Do not let Jira/Confluence connectors be required** — Priya must work without them
9. **Do not retain non-anonymized patron data** — in any layer, at any point
10. **Do not make the analytics stub load-bearing** — it returns pending markers; that is correct
11. **Do not mix users' sessions or memory** — isolation is required for the enterprise context
12. **Do not amend Phase A/B/2 behavior** — it is tested and complete; extend, do not change

---

## 10. Before your first commit in the enterprise fork

Run this checklist:

- [ ] `python3 -m pytest pipeline/coach/test_hardening.py -k "not live" -q` → **160 passed, 0 failed**
- [ ] `python3 -m pytest pipeline/coach/rag/test_rag.py -q` → **32 passed**
- [ ] Cloud backend configured and reachable
- [ ] Live tests pass: `python3 -m pytest pipeline/coach/test_hardening.py -k "live" -v`
- [ ] `git log --oneline -5` shows a clean history from this handoff commit
- [ ] `WORK_LOG.md` has an entry for your session (see Work Logging Protocol in `CLAUDE.md`)

---

## 11. Key files to read before making changes

In priority order:

1. `pipeline/methodology/personas/coach-priya.md` — Priya's full behavioral spec
2. `pipeline/coach/engine.py` — CoachEngine, all core classes
3. `pipeline/coach/test_hardening.py` — the behavioral contract (read the test names)
4. `agents.md` — agent topology and interface contracts for Phase 3+
5. `pipeline/coach/memory.py` — CoachMemory schema (especially the `features` table, Phase B)
6. `pipeline/intake/domain-context/patron-privacy.md` — privacy posture
7. `pipeline/backends/bedrock.py` or `assisted.py` — the backends you'll actually use

---

## 12. Work logging protocol

Every session must append to `WORK_LOG.md` via `scripts/log_work.py`:

```bash
# At session start
python3 scripts/log_work.py --entry "## Session — YYYY-MM-DD\n\n### Human Request\n> [what was asked]\n"

# At session end
python3 scripts/log_work.py --entry "### Chain of Thought\n[decisions]\n\n### Steps\n[what was done]\n\n### Outputs\n[what was produced]\n"
```

A `PostToolUse` hook fires automatically on `Write`/`Edit` to log file changes. The manual
entries capture the *why* behind those changes.

---

*This document was written at the POC completion boundary (Phase B complete) to enable a clean
handoff to the enterprise fork phase. The POC repository remains the source of truth for the
coaching core until a shared package is extracted in Phase 3.*
