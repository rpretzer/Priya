# V1 → V2 Upgrade & Integration Plan

This document describes what "V1" and "V2" mean for Hoopla Coach (Priya),
what changes between them, and how to migrate without breaking the coaching core.

---

## What is V1?

V1 is the current state as of March 2026:

| Component | V1 State |
|-----------|----------|
| LLM backend | Ollama (local, generic model) |
| Model | Any llama-family model served by Ollama |
| Frontend | Single-page HTML demo (`demo/index.html`) |
| Memory | SQLite + FTS5 (`CoachMemory`) |
| Domain context | Static markdown files in `pipeline/intake/domain-context/` |
| Artifact output | Markdown text returned in chat stream |
| Auth | None (development only) |
| Deployment | `python3 -m pipeline.coach` on a local machine |

V1 is functional end-to-end: Priya coaches, tracks progress, generates artifacts,
and remembers sessions across conversations. The behavioral contract is stable and
tested via `test_hardening.py`.

---

## What is V2?

V2 is the target state after Phase 1–3 of the 5-phase plan:

| Component | V2 State |
|-----------|----------|
| LLM backend | llama.cpp serving a **purpose-built fine-tuned model** |
| Model | Fine-tuned LLaMA variant (Priya behavioral contract baked in) |
| Frontend | Slack bot (meets users where they work) |
| Memory | SQLite + FTS5 (unchanged — already solid) |
| Domain context | Static files + RAG augmentation (Phase 2) |
| Artifact output | Structured handoff to Confluence/Jira/Figma (Phase 3) |
| Auth | Slack OAuth (team-level) |
| Deployment | Containerized service (Docker/ECS or EC2) |

---

## Migration Steps: V1 → V2

### Step 1: Swap Ollama for llama.cpp (Phase 1 — Active)

No coaching logic changes. Only the backend layer changes.

**What to do:**
1. Build or download the fine-tuned GGUF model file
2. Start llama.cpp server: `./llama-server -m priya-v1.gguf --port 8080`
3. Launch coach with: `python3 -m pipeline.coach --backend llamacpp --model priya-v1`
4. Run `test_hardening.py` — all tests must pass

**What does NOT change:**
- `CoachEngine`, `ProgressTracker`, `SignalDetector`, `ContextAssembler`
- Persona prompt, push-back patterns, artifact schemas
- `CoachMemory` and `Crystallizer`
- Domain context files

**Risk:** Low. `LlamaCppBackend` uses the OpenAI-compatible REST API — no SDK,
pure stdlib. If the model follows the chat format, it works.

**Rollback:** `--backend ollama` restores V1 behavior instantly.

---

### Step 2: Add Slack Frontend (parallel with Phase 1)

The server (`pipeline/coach/server.py`) exposes `/api/coach` as an HTTP streaming
endpoint. A Slack bot is a new client that calls this same endpoint.

**What to do:**
1. Create `pipeline/slack/bot.py` using `slack_bolt` SDK
2. On `app_mention` or DM: forward message to `/api/coach`, stream response back
3. Handle file uploads via Slack's file API → pass as multipart to `/api/coach`
4. Session ID = Slack channel + user ID (stable across conversations)

**What does NOT change:**
- Server routing or `/api/coach` contract
- Any coaching logic

**Risk:** Low. The server API is stable. Slack bot is a thin adapter.

**Note:** The HTML demo (`demo/index.html`) can remain for internal testing.
It does not need to be removed — just not the primary interface.

---

### Step 3: Add RAG Augmentation (Phase 2)

Domain context grows beyond what fits in a system prompt. RAG adds dynamic
retrieval without replacing the static file mechanism.

**What to do:**
1. Add `pipeline/intake/rag/` with an embedding store (sqlite-vec or Chroma)
2. Add `RAGRetriever` class with `.retrieve(query, top_k=5) -> list[str]`
3. Extend `ContextAssembler.build()` to call `RAGRetriever` and inject results
   into Layer 2 (domain context layer) alongside the static files
4. Index new domain knowledge documents into the RAG store

**What does NOT change:**
- Existing static domain context files (they remain the baseline)
- ContextAssembler's 7-layer structure (Layer 2 gets augmented, not replaced)
- Any other coaching component

**Risk:** Medium. RAG retrieval quality affects response quality. Use
`test_hardening.py` to verify behavioral contract still holds after integration.

---

### Step 4: Structured Artifact Handoff (Phase 3)

Artifacts currently return as markdown text in the chat stream. V2 delivers
them directly to Confluence, Jira, and Figma.

**What to do:**
1. Define handoff schemas for each artifact type (JSON, not markdown)
2. Add `pipeline/handoff/` with connectors: `confluence.py`, `jira.py`, `figma.py`
3. When `ProgressTracker` gates artifact generation and the user confirms,
   `CoachEngine` calls the appropriate handoff connector
4. Return a confirmation link in the chat response

**What does NOT change:**
- Artifact gating logic in `ProgressTracker`
- Artifact content schemas (the information captured stays the same)
- Priya's coaching behavior

**Risk:** Medium. Connector auth (Confluence/Jira API keys) needs secure storage.
Use environment variables; do not hardcode.

---

## What Must NOT Change Between V1 and V2

These are the invariants. Any migration that touches them requires full
hardening suite re-run and explicit approval:

1. **Priya's behavioral contract** — push-back patterns, anti-loop rule,
   response length limits, prohibited behaviors. These are encoded in
   `ContextAssembler` and `pipeline/methodology/personas/coach-priya.md`.
2. **Artifact gating** — `ProgressTracker` completeness thresholds.
3. **The spec funnel boundary** — Priya never generates code, SQL, or
   system design. This holds in V2.
4. **`AgentBackend` interface** — `chat()`, `chat_stream()`, `invoke()`,
   `health_check()`. New backends implement this; nothing else changes.
5. **Domain context file structure** — `pipeline/intake/domain-context/*.md`
   files must remain loadable by `DomainContext`. RAG augments; does not replace.

---

## Version Compatibility Matrix

| Feature | V1 (Ollama) | V1.5 (llama.cpp) | V2 (Full) |
|---------|------------|-----------------|-----------|
| Coaching conversation | ✅ | ✅ | ✅ |
| Artifact generation | ✅ | ✅ | ✅ (+ handoff) |
| Memory across sessions | ✅ | ✅ | ✅ |
| HTML demo UI | ✅ | ✅ | Optional |
| Slack bot | ❌ | Parallel | ✅ |
| RAG domain context | ❌ | ❌ | ✅ |
| Structured handoff | ❌ | ❌ | ✅ |
| Fine-tuned model | ❌ | ✅ | ✅ |

---

## Running the Hardening Suite at Each Phase Boundary

```bash
# Before any phase transition, run from /home/user/Priya:
cd /home/user/Priya
python3 -m pytest pipeline/coach/test_hardening.py -v

# For live backend tests (requires running llama.cpp or Ollama):
python3 -m pytest pipeline/coach/test_hardening.py -v -m live
```

All non-live tests must pass (currently 52/52). Live tests require a running
backend instance — run these manually before declaring a phase complete.
