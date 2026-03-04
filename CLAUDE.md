# CLAUDE.md — Hoopla Coach (codename: Priya)

## Project Identity

Hoopla Coach is an internal AI assistant for Hoopla Digital's product team (PMs, POs, BSAs). It is **not** a general-purpose chatbot. It is a **spec funnel**: a structured coaching system that guides product stakeholders through intake conversations and produces machine-readable artifacts for downstream engineering workflows.

The assistant persona is **Priya Desai** — a product development coach. Her persona, behavioral rules, and coaching logic are the most carefully designed part of the system. They are load-bearing and tested. Do not modify them without explicit approval.

## Architecture Overview

```
CLI entry point: python3 -m pipeline.coach [options]
Server: pipeline/coach/server.py → /api/coach (streaming, file upload, demo UI)

Core components (pipeline/coach/):
  CoachEngine        — Multi-turn conversation controller. Drives AgentBackend.chat/chat_stream,
                       injects layered system prompt, handles multimodal inputs and slash commands.
  ProgressTracker    — Scores business-case completeness across fields (problem, evidence, users,
                       impact, solution, metrics, risks, scope, platform). Gates artifact production.
  SignalDetector     — Detects weak signals (solution-before-problem, vague metrics, COPPA minors)
                       and strong signals (quantified problems, hypotheses, tradeoffs). Drives push-back.
  ContextAssembler   — Builds layered prompt: persona/protocol → domain context → artifact schemas
                       → interaction rules → dynamic overlays → memory context.
  DomainContext      — File-driven domain knowledge from pipeline/intake/domain-context/*.md
  CoachMemory        — SQLite+FTS episodic recall of prior sessions.
  Crystallizer       — Extracts constraints/decisions/assumptions/preferences at session end
                       without an LLM call.
  AgentBackend       — Provider-agnostic LLM interface. Current: Ollama. Target: llama.cpp.
```

### Prompt Assembly Order

ContextAssembler builds the system prompt in layers:
1. Persona and protocol definitions
2. Domain markdown context (file-driven)
3. Artifact schemas (business-case.md, epics.md, stories-draft.md)
4. Interaction rules and behavioral constraints
5. Dynamic overlays from ProgressTracker (turn-count-aware guidance)
6. Memory context from CoachMemory

### Data Flow

```
User input → CoachEngine → SignalDetector (analyze) → ProgressTracker (score)
           → ContextAssembler (build prompt with overlays)
           → AgentBackend.chat_stream (LLM call)
           → Response to user
           → (late session) Artifact generation gated by ProgressTracker completeness
           → (session end) Crystallizer extracts session learnings → CoachMemory
```

## Sacred Boundaries — Do Not Cross

These constraints are architectural invariants. Violating them breaks the system's design intent.

1. **Priya's persona is the stable core.** Her behavioral rules, push-back patterns, and tone adaptation logic are tested in `test_hardening.py`. Do not weaken, bypass, or "improve" them without running the full hardening suite and getting explicit approval.

2. **The spec funnel boundary is absolute.** Priya produces business artifacts only: `business-case.md`, `epics.md`, `stories-draft.md`. She NEVER generates code, SQL, API contracts, or system design diagrams. A downstream Spec Compiler handles translation to engineering artifacts.

3. **Backend is swappable; coaching logic is not.** The `AgentBackend` interface abstracts the LLM provider. All coaching logic must remain provider-agnostic. Never embed provider-specific behavior in CoachEngine, ProgressTracker, or SignalDetector.

4. **Domain context is file-driven.** Knowledge lives in markdown files under `pipeline/intake/domain-context/`. RAG will augment this later, but the file-based injection mechanism must keep working. Do not replace it; extend it.

5. **Artifact gating is intentional.** ProgressTracker gates artifact production until completeness gaps are addressed. Do not short-circuit this. The gating exists to ensure downstream consumers get well-formed specs.

## Priya's Behavioral Contract

These are hard constraints encoded in the persona and enforced by `test_hardening.py`. They are not style preferences.

### Push-Back Patterns (must challenge)
- Vague impact claims without quantification
- Solution-before-problem (jumping to "build X" without stating the problem)
- No alternatives considered
- Unmeasurable or undefined metrics
- Scope creep during a session
- Missing rollout strategy

### Anti-Loop Rule
Never re-ask a question already asked in a prior turn. Interpret indirect answers charitably and move the conversation forward.

### Response Length Limits
- Clarifying questions: 2-4 sentences max
- Push-back: 2 sentences
- Artifacts: structured output only, no narrative introduction

### Prohibited Behaviors
- **No compliments**: Never say "Great question!", "I love that idea", etc. Acknowledge substance, not people.
- **No code generation**: Coach never writes code. Redirect to Spec Compiler.
- **No fabrication**: If Priya lacks a number, she says so. Label assumptions explicitly with markers.
- **No emotional labor**: Coach, not companion. Professional boundaries. Clean endings.

### Tone Adaptation
SignalDetector identifies user emotional signals (sarcasm, frustration, disengagement, overwhelm, enthusiasm) and Priya adapts:
- Frustrated users get shorter, more direct responses
- Overwhelmed users get the scope narrowed
- Disengaged users get re-anchored to their original problem
- Sarcastic users get substance-focused responses without mirroring

### Conversation Arc
- **Early turns**: Exploratory, open questions, understand the problem space
- **Mid turns**: Structured, fill gaps identified by ProgressTracker
- **Late turns**: Artifact mode, generate structured output
- **Fast-track**: When input is already strong, skip exploratory phase

## Code Conventions and Patterns

- Python 3 module structure under `pipeline/coach/`
- Entry point: `python3 -m pipeline.coach`
- CLI flags: `--port` (default 3456), `--backend` (ollama|bedrock|assisted|agentcore), `--model`, `--demo-dir`, `--memory-path`
- Streaming responses via `/api/coach` endpoint
- Heuristic-first design: ProgressTracker and SignalDetector use regex/rule-based scoring, not LLM calls, to keep them fast and deterministic
- Crystallizer is also heuristic (no LLM) — this is intentional for speed and cost
- Slash commands in conversation: `/help`, `/status`, `/generate`, `/reset`
- Multimodal input support: URLs, file uploads, images are passed through CoachEngine

## Testing Philosophy

### test_hardening.py Is the Contract

`test_hardening.py` contains behavioral tests that define Priya's correctness. These are not unit tests in the traditional sense — they are behavioral specifications:

- Signal detection accuracy (weak and strong signals)
- Artifact gating (refuses to generate when completeness is low)
- COPPA compliance checks (flags minors-related features)
- Role boundary enforcement (refuses code generation)
- Non-fabrication (does not invent numbers)
- Brevity enforcement (response length limits)
- Attachment handling (multimodal inputs)

**These tests include live Ollama runs.** They require a running Ollama instance with the configured model.

### When You Must Run Tests
- Any change to CoachEngine, ProgressTracker, SignalDetector, or ContextAssembler
- Any change to persona or protocol prompt text
- Any change to artifact schemas
- Any change to the push-back or tone-adaptation logic

### When Tests Are Not Required
- Changes to server.py routing or transport
- Changes to CLI argument parsing
- Adding new domain context files (but verify they load)

## Domain Knowledge Management

### Current Mechanism
Domain context files live in `pipeline/intake/domain-context/` as markdown. ContextAssembler reads and injects them into the system prompt at assembly time.

### Hoopla Digital Domain Essentials
- Digital content lending for public libraries (ebooks, audiobooks, comics, movies, TV, music, BingePass)
- **Per-circulation revenue model** — every borrow costs the library money. This is a critical constraint that Priya must understand for impact analysis.
- **B2B2C model**: library admins control budget, patrons are end users. Features must consider both audiences.
- 7+ client platforms: iOS, Android, Web, Kindle, Roku, Apple TV, Fire TV
- WCAG AA accessibility required contractually
- DRM complexity varies per publisher contract
- Android undergoing KMP migration; iOS modernizing UIKit to SwiftUI
- Shared business logic via KMP is a major architectural goal

### Adding Domain Context
1. Add a markdown file to `pipeline/intake/domain-context/`
2. Follow the structure of existing files
3. Verify it loads by checking ContextAssembler output or running a session
4. Do not hardcode domain knowledge into CoachEngine or prompt templates — it belongs in the context files

## The Spec Funnel

### Inputs
- Multi-turn conversation with a product stakeholder
- Optional: file attachments, URLs, images for context
- Optional: prior session memory via CoachMemory

### Outputs (Artifacts)
- **business-case.md** — Problem, evidence, users, impact, solution, metrics, risks, scope
- **epics.md** — High-level feature groupings with acceptance criteria
- **stories-draft.md** — User stories with sizing guidance

### Gating
ProgressTracker must reach sufficient completeness before artifact generation is permitted. The fields scored are: problem, evidence, users, impact, solution, metrics, risks, scope, platform.

### Handoff Contract
Artifacts are the interface between Priya (coaching) and downstream systems (Spec Compiler, code agents). The artifact schemas are defined in the system prompt and must produce consistent, machine-readable output. Do not add narrative prose, commentary, or caveats inside artifact output.

## Backend Abstraction

### AgentBackend Interface
All LLM calls go through `AgentBackend.chat()` and `AgentBackend.chat_stream()`. To add a new provider:

1. Implement the AgentBackend interface for the new provider
2. Register it as a backend option in the CLI (`--backend` flag)
3. Do not modify CoachEngine, ProgressTracker, SignalDetector, or ContextAssembler
4. Ensure streaming support works (the server relies on it)
5. Run `test_hardening.py` against the new backend

### Current State
- **Ollama**: Current default backend
- **llama.cpp**: Target backend (Phase 1 of the 5-phase plan)
- **Bedrock, assisted, agentcore**: Additional backend options in CLI

## What NOT to Do

1. **Do not make Priya "nicer."** The push-back behavior is intentional and tested. Softening it degrades spec quality.
2. **Do not add code generation capabilities to Priya.** This is a spec funnel, not a coding assistant. The boundary is sacred.
3. **Do not bypass artifact gating.** If ProgressTracker says the spec is incomplete, the user needs to provide more information. Do not add overrides.
4. **Do not embed provider-specific logic in coaching components.** Use AgentBackend.
5. **Do not hardcode domain knowledge into prompt templates.** Put it in `pipeline/intake/domain-context/` files.
6. **Do not add compliments, encouragement, or emotional responses to Priya.** This is tested and will fail hardening.
7. **Do not re-ask questions.** The anti-loop rule exists because users find it infuriating. Interpret and move forward.
8. **Do not add narrative introductions to artifacts.** Structured output only.
9. **Do not modify persona/protocol prompt text without running the full hardening suite.** These are load-bearing strings.
10. **Do not treat agents.md agents as stable.** Priya is stable. Everything else in the agent topology is ephemeral and swappable.

## Phase Awareness

### 5-Phase Plan

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Stabilize Priya on LLaMA-family backend via llama.cpp | **Active** |
| 2 | Extend domain context with Hoopla/MWT product knowledge + RAG | Upcoming |
| 3 | Formalize structured spec output schemas (Confluence, Jira, Figma) as handoff contracts | Planned |
| 4 | Wrap in agentic layer (agents.md) without disturbing coaching core | Planned |
| 5 | Deploy to beta users at MWT and measure spec-to-code pipeline success | Planned |

### Phase 1 Priorities
- Replace or extend Ollama backend with llama.cpp serving LLaMA-family models
- Maintain all existing behavioral tests passing
- Do not change coaching logic — only the backend layer

### Phase 2 Implications
- RAG will augment (not replace) the file-driven domain context
- ContextAssembler will need a RAG integration point
- Domain context files remain the baseline; RAG adds dynamic retrieval

### Guard Rails for All Phases
- Priya's behavioral contract does not change across phases
- `test_hardening.py` must pass at every phase boundary
- The spec funnel boundary holds regardless of what agents are added downstream
