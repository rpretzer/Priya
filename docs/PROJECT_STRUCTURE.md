# Project Structure — Hoopla Coach (Priya)

This document explains the directory layout and — critically — **where to plug in
new context** without touching coaching logic.

---

## Directory Map

```
Priya/
├── CLAUDE.md                    # AI assistant instructions (architectural invariants)
├── WORK_LOG.md                  # Running record of decisions and steps
├── agents.md                    # Agent topology for Phase 4 agentic layer
├── requirements.txt             # Python dependencies (boto3, anthropic)
├── scripts/
│   └── log_work.py              # Work logging hook (called by Claude Code PostToolUse)
│
├── docs/                        # Architecture and planning docs (you are here)
│   ├── PROJECT_STRUCTURE.md
│   ├── UPGRADE_V1_TO_V2.md
│   └── FINETUNE.md
│
├── pipeline/                    # All server-side Python code
│   ├── __init__.py
│   │
│   ├── backends/                # LLM provider adapters (swappable)
│   │   ├── base.py              # AgentBackend ABC + AgentResult
│   │   ├── llamacpp.py          # Phase 1 target (llama.cpp OpenAI-compatible API)
│   │   ├── ollama.py            # Current default (local Ollama)
│   │   ├── bedrock.py           # AWS Bedrock Converse API
│   │   ├── assisted.py          # Anthropic API direct (dev/testing)
│   │   └── __init__.py          # get_backend() factory
│   │
│   ├── coach/                   # Core coaching engine (sacred — do not modify casually)
│   │   ├── engine.py            # CoachEngine, ProgressTracker, SignalDetector,
│   │   │                        #   ContextAssembler, DomainContext, FieldStatus
│   │   ├── crystallizer.py      # Post-session learning extractor (heuristic, no LLM)
│   │   ├── memory.py            # CoachMemory (SQLite + FTS5 session store)
│   │   ├── server.py            # HTTP server: /api/coach streaming endpoint
│   │   ├── tools.py             # URLFetcher, FileProcessor, SlashCommandHandler
│   │   ├── __main__.py          # CLI entry: python3 -m pipeline.coach
│   │   └── test_hardening.py    # Behavioral contract tests (must always pass)
│   │
│   ├── intake/
│   │   └── domain-context/      # *** PRIMARY CONTEXT INJECTION POINT ***
│   │       └── hoopla-domain.md # Hoopla Digital domain knowledge
│   │
│   ├── methodology/
│   │   └── personas/            # *** PERSONA INJECTION POINT ***
│   │       └── coach-priya.md   # Priya Desai persona, push-back rules, artifact schemas
│   │
│   └── dashboard/               # Frontend config (auth, branding)
│       └── config-coach-auth.js
│
├── demo/
│   └── index.html               # Single-page streaming chat UI (development/testing)
│
├── knowledge/                   # Phase 2 RAG preparation
│   ├── hoopla-domain.md         # Source of truth for domain knowledge
│   └── topic-index.json         # Topic → file mapping for RAG indexing
│
└── roles/
    └── coach.md                 # Coach role spec (boundaries, handoff, escalation)
```

---

## Where to Plug In New Context

### 1. Domain Knowledge (most common)

**Location:** `pipeline/intake/domain-context/`

Add a new `.md` file. `DomainContext` in `engine.py` reads all `.md` files in
this directory at startup and injects them into the system prompt (Layer 2).

```
pipeline/intake/domain-context/
├── hoopla-domain.md        # Existing: business model, platforms, architecture
├── mwt-integration.md      # New: MWT library network specifics
└── publisher-contracts.md  # New: DRM constraints per publisher
```

**Rules:**
- Use clear section headers (`## Section Name`)
- Keep each file focused on one domain area (don't combine unrelated topics)
- Files are concatenated — avoid contradicting existing files
- No code, no JSON — plain markdown prose only
- After adding, verify it loads: start the server and check startup logs

**Do NOT:**
- Hardcode domain knowledge into `engine.py` or `coach-priya.md`
- Put domain knowledge in `requirements.txt` or config files

---

### 2. Persona and Behavioral Rules

**Location:** `pipeline/methodology/personas/coach-priya.md`

This is the most sensitive file. Changes here require running `test_hardening.py`.

**What to add safely:**
- New push-back patterns (add to the `## Push-Back Patterns` section)
- New artifact schemas (add to the `## Artifact Schemas` section)
- New tone adaptation rules (add to the `## Tone Adaptation` section)

**What requires approval + full hardening run:**
- Changing Priya's identity or purpose statement
- Weakening existing push-back patterns
- Adding compliments or encouragement language
- Modifying the anti-loop rule

---

### 3. A New LLM Backend

**Location:** `pipeline/backends/`

1. Create `pipeline/backends/yourbackend.py`
2. Implement the `AgentBackend` ABC from `pipeline/backends/base.py`:
   - `chat(messages, system, config) -> AgentResult`
   - `chat_stream(messages, system, config) -> Generator[str, None, None]`
   - `invoke(prompt, context, config) -> AgentResult`
   - `health_check() -> bool`
   - `name` property → `str`
3. Register in `pipeline/backends/__init__.py`:
   ```python
   from .yourbackend import YourBackend
   # in get_backend():
   "yourbackend": YourBackend,
   ```
4. Add to `--backend` choices in `pipeline/coach/__main__.py`
5. Run `test_hardening.py` with `--backend yourbackend` flag (when live tests exist)

**Do NOT:**
- Put provider-specific logic in `CoachEngine`, `ProgressTracker`, or `SignalDetector`
- Import boto3/anthropic/etc. outside of the backend module

---

### 4. Artifact Schemas

**Location:** `pipeline/methodology/personas/coach-priya.md` (in the Artifacts section)

Each artifact type has a schema defined in the persona file. The schema is what
`ContextAssembler` injects into the system prompt when artifact mode is active.

To add a new artifact type (e.g., `release-notes`):
1. Add the schema to `coach-priya.md` under `## Artifact Schemas`
2. Add the type to `valid_types` in `SlashCommandHandler._cmd_generate()` in `tools.py`
3. Add the type to `COMMANDS["/generate"]["usage"]` in `tools.py`
4. Add handling in `CoachEngine` if the new type needs a different generation path

---

### 5. RAG Topic Index (Phase 2 prep)

**Location:** `knowledge/topic-index.json`

This is a Phase 2 preparation file. It maps topics to source documents for
future RAG indexing. Format:

```json
{
  "topics": [
    {
      "id": "per-circulation-model",
      "title": "Per-Circulation Revenue Model",
      "keywords": ["borrow", "circulation", "cost per checkout"],
      "source_file": "knowledge/hoopla-domain.md",
      "section": "Business Model"
    }
  ]
}
```

When Phase 2 RAG is built, `pipeline/intake/rag/` will read this index to
build the embedding store. The static domain-context files remain the fallback.

---

## The "Plug In Context" Decision Tree

```
I want to add...
│
├─ New business/domain knowledge
│   └─→ pipeline/intake/domain-context/new-file.md
│
├─ A new type of product artifact
│   └─→ pipeline/methodology/personas/coach-priya.md (schema)
│       + pipeline/coach/tools.py (valid_types)
│
├─ A new LLM provider
│   └─→ pipeline/backends/newprovider.py
│       + pipeline/backends/__init__.py (register)
│       + pipeline/coach/__main__.py (CLI choice)
│
├─ New push-back or coaching behavior
│   └─→ pipeline/methodology/personas/coach-priya.md
│       (run test_hardening.py after any change)
│
├─ A new frontend (Slack, Teams, CLI)
│   └─→ New module calling /api/coach endpoint
│       (server.py contract does not change)
│
└─ New memory/session capabilities
    └─→ pipeline/coach/memory.py
        (CoachMemory.save_session / recall interface)
```

---

## Starting the Server

```bash
# Phase 1 (llama.cpp — preferred):
./llama-server -m priya-v1.gguf --port 8080
python3 -m pipeline.coach --backend llamacpp --port 3456

# Development (Anthropic API):
export ANTHROPIC_API_KEY=sk-ant-...
python3 -m pipeline.coach --backend assisted --port 3456

# Development (Ollama fallback):
python3 -m pipeline.coach --backend ollama --port 3456

# Open demo UI:
open http://localhost:3456/
```

## Running Tests

```bash
# From /home/user/Priya:
python3 -m pytest pipeline/coach/test_hardening.py -v
# 52 pass, 8 skipped (skipped = live backend tests requiring running instance)
```
