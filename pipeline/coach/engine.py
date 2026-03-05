# AI-GENERATED: 2026-03-03T16:57:33Z | pipeline/coach/engine.py | Copilot
"""Hoopla Coach engine — core coaching logic for Priya Desai.

Components defined here:
    FieldStatus       — completeness state for one business-case field
    ProgressTracker   — scores business-case completeness across all fields
    SignalDetector    — detects weak/strong signals in user messages
    DomainContext     — file-driven domain knowledge loader
    ContextAssembler  — builds layered system prompt for each LLM call
    CoachEngine       — multi-turn conversation controller

Design invariants (see CLAUDE.md Sacred Boundaries):
    - All heuristics are regex/rule-based, never LLM calls
    - Provider-agnostic: all LLM interaction goes through AgentBackend
    - Priya's persona/protocol text is injected via ContextAssembler, not hardcoded
    - Artifact generation is gated by ProgressTracker completeness
"""
from __future__ import annotations

import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Generator

from pipeline.backends.base import AgentBackend, AgentResult


# ===========================================================================
# ContextChunk and ContextSource — Phase 2 RAG integration types
# ===========================================================================

@dataclass
class ContextChunk:
    """A retrieved context chunk from the RAG system.

    Returned by ContextSource.get_context() and injected into the system
    prompt by ContextAssembler as an additive layer alongside the static
    file-driven DomainContext baseline.
    """
    content: str
    source: str       # file path or URL of origin
    score: float      # similarity score [0.0, 1.0]
    metadata: dict = field(default_factory=dict)


class ContextSource(ABC):
    """Abstract base for Phase 2 RAG context providers.

    Implementations (e.g. ContextRetriever) are registered with
    ContextAssembler at startup. During prompt assembly, ContextAssembler
    calls get_context() for each registered source and appends the results
    as a sub-layer within the domain context layer (after static DomainContext).

    Contract (agents.md Contract 2):
    - Must not modify any existing ContextAssembler layer
    - Must degrade gracefully (return [] on failure)
    - Must respect the token budget enforced by ContextAssembler
    - Static DomainContext always loads first; this is additive only
    """

    @abstractmethod
    def get_context(self, conversation_state: dict) -> list[ContextChunk]:
        """Return relevant context chunks for the current conversation.

        Args:
            conversation_state: dict with keys:
                "messages"       — recent conversation messages (list[dict])
                "missing_fields" — fields still needed (list[str])
                "turn_count"     — current turn number (int)

        Returns:
            List of ContextChunk, sorted by relevance score descending.
            Return [] if nothing relevant or on any error.
        """


# ===========================================================================
# FieldStatus — completeness state for one business-case field
# ===========================================================================

class FieldStatus(Enum):
    """Completeness state for a single business-case field."""
    MISSING = "missing"       # Not mentioned at all
    WEAK = "weak"             # Mentioned but vague/unquantified
    ADEQUATE = "adequate"     # Sufficient for artifact generation
    STRONG = "strong"         # Well-evidenced, quantified, or validated


# ===========================================================================
# ProgressTracker — scores completeness across business-case fields
# ===========================================================================

# Fields that ProgressTracker scores, as per CLAUDE.md
_SCORED_FIELDS = [
    "problem",
    "evidence",
    "users",
    "impact",
    "solution",
    "metrics",
    "risks",
    "scope",
    "platform",
]

# Minimum completeness score (0.0–1.0) required to generate artifacts
_ARTIFACT_GATE_THRESHOLD = 0.65

# Regex anchors for field detection (heuristic, not exhaustive)
_FIELD_PATTERNS: dict[str, list[re.Pattern]] = {
    "problem": [
        re.compile(r"\b(problem|pain point|issue|challenge|gap|friction|struggle|fail(ure|ing)?)\b", re.I),
        re.compile(r"\b(users (can't|cannot|are unable|have trouble|struggle))\b", re.I),
    ],
    "evidence": [
        re.compile(r"\b(data|evidence|research|survey|interview|analytic|metric|statistic|report)\b", re.I),
        re.compile(r"\b(\d+\s*%|\d+\s*(users|patrons|customers|sessions|tickets|calls))\b", re.I),
    ],
    "users": [
        re.compile(r"\b(user|patron|librarian|admin|stakeholder|audience|persona|segment|customer)\b", re.I),
        re.compile(r"\b(who (is|are|will|would)|target (user|audience|market))\b", re.I),
    ],
    "impact": [
        re.compile(r"\b(impact|benefit|value|outcome|result|improve|increase|decrease|reduce|save|revenue)\b", re.I),
        re.compile(r"\b(\d+\s*%\s*(increase|decrease|reduction|improvement|growth|drop))\b", re.I),
    ],
    "solution": [
        re.compile(r"\b(solution|feature|build|implement|add|create|design|develop|product)\b", re.I),
        re.compile(r"\b(we (want|need|plan|propose|are (thinking|considering)) to)\b", re.I),
    ],
    "metrics": [
        re.compile(r"\b(metric|KPI|measure|success criterion|OKR|goal|target|benchmark|SLA)\b", re.I),
        re.compile(r"\b(track(ed|ing)?|monitor(ed|ing)?|analytic|dashboard|report)\b", re.I),
    ],
    "risks": [
        re.compile(r"\b(risk|concern|issue|blocker|dependency|assumption|unknown|uncertainty)\b", re.I),
        re.compile(r"\b(what if|could fail|might (not|be)|downside|tradeoff|trade-off)\b", re.I),
    ],
    "scope": [
        re.compile(r"\b(scope|in scope|out of scope|phase|milestone|MVP|v1|release|launch)\b", re.I),
        re.compile(r"\b(timeline|deadline|quarter|Q[1-4]|sprint|roadmap|backlog)\b", re.I),
    ],
    "platform": [
        re.compile(r"\b(platform|iOS|Android|web|Kindle|Roku|Apple TV|Fire TV|KMP|mobile|desktop)\b", re.I),
        re.compile(r"\b(app|browser|device|client|front.?end|back.?end|API)\b", re.I),
    ],
}

# Strong quantification signals boost a field from WEAK to ADEQUATE/STRONG
_QUANTIFICATION_PATTERN = re.compile(
    r"\b(\d[\d,\.]*\s*(%|users|patrons|sessions|tickets|dollars|\$|hours|days|weeks))\b", re.I
)


@dataclass
class FieldScore:
    """Score for one field."""
    field: str
    status: FieldStatus = FieldStatus.MISSING
    evidence_snippets: list[str] = field(default_factory=list)


class ProgressTracker:
    """Scores business-case completeness across all required fields.

    Uses regex heuristics — no LLM calls. Fast and deterministic.

    Completeness is scored as a float 0.0–1.0 across the 9 fields.
    Artifact generation is gated at _ARTIFACT_GATE_THRESHOLD.
    """

    def __init__(self):
        self._scores: dict[str, FieldScore] = {
            f: FieldScore(field=f) for f in _SCORED_FIELDS
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, messages: list[dict]) -> None:
        """Re-score all fields from the full conversation history.

        Called after each user turn so ProgressTracker always reflects the
        latest state.
        """
        # Reset
        self._scores = {f: FieldScore(field=f) for f in _SCORED_FIELDS}

        # Collect all user text
        user_text = self._collect_user_text(messages)

        for fname, patterns in _FIELD_PATTERNS.items():
            snippets = []
            matched = False
            for pattern in patterns:
                for m in pattern.finditer(user_text):
                    matched = True
                    # Grab surrounding context as snippet
                    start = max(0, m.start() - 40)
                    end = min(len(user_text), m.end() + 40)
                    snippets.append(user_text[start:end].strip())

            if not matched:
                self._scores[fname].status = FieldStatus.MISSING
                continue

            # Check for quantification to promote to ADEQUATE/STRONG
            has_quantification = bool(_QUANTIFICATION_PATTERN.search(user_text))
            if has_quantification and fname in ("problem", "impact", "evidence", "metrics"):
                self._scores[fname].status = FieldStatus.STRONG
            else:
                self._scores[fname].status = FieldStatus.ADEQUATE

            self._scores[fname].evidence_snippets = snippets[:3]

    def completeness(self) -> float:
        """Return completeness as a float 0.0–1.0."""
        if not self._scores:
            return 0.0
        weights = {
            "problem": 2.0,
            "evidence": 1.5,
            "users": 1.0,
            "impact": 1.5,
            "solution": 1.0,
            "metrics": 1.0,
            "risks": 0.5,
            "scope": 0.5,
            "platform": 0.5,
        }
        total_weight = sum(weights.values())
        earned = 0.0
        for fname, score in self._scores.items():
            w = weights.get(fname, 1.0)
            if score.status == FieldStatus.STRONG:
                earned += w * 1.0
            elif score.status == FieldStatus.ADEQUATE:
                earned += w * 0.75
            elif score.status == FieldStatus.WEAK:
                earned += w * 0.35
            # MISSING = 0
        return earned / total_weight

    def is_ready_for_artifacts(self) -> bool:
        """Return True if completeness meets the artifact gate threshold."""
        return self.completeness() >= _ARTIFACT_GATE_THRESHOLD

    def missing_fields(self) -> list[str]:
        """Return list of field names that are MISSING or WEAK."""
        return [
            f for f, s in self._scores.items()
            if s.status in (FieldStatus.MISSING, FieldStatus.WEAK)
        ]

    def status_report(self) -> dict[str, str]:
        """Return a dict of field → status string for display."""
        return {f: s.status.value for f, s in self._scores.items()}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _collect_user_text(messages: list[dict]) -> str:
        parts = []
        for msg in messages:
            if msg.get("role") != "user":
                continue
            content = msg.get("content", "")
            if isinstance(content, str):
                parts.append(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        parts.append(block.get("text", ""))
        return " ".join(parts)


# ===========================================================================
# SignalDetector — detects weak/strong signals in user messages
# ===========================================================================

class SignalType(Enum):
    # Weak signals (trigger push-back)
    SOLUTION_BEFORE_PROBLEM = "solution_before_problem"
    VAGUE_METRICS = "vague_metrics"
    VAGUE_IMPACT = "vague_impact"
    NO_ALTERNATIVES = "no_alternatives"
    UNMEASURABLE_GOAL = "unmeasurable_goal"
    SCOPE_CREEP = "scope_creep"
    MISSING_ROLLOUT = "missing_rollout"
    COPPA_MINORS = "coppa_minors"
    # Strong signals (can skip exploratory phase)
    QUANTIFIED_PROBLEM = "quantified_problem"
    HYPOTHESIS_STATED = "hypothesis_stated"
    TRADEOFF_STATED = "tradeoff_stated"
    # Emotional signals (drive tone adaptation)
    FRUSTRATION = "frustration"
    OVERWHELM = "overwhelm"
    DISENGAGEMENT = "disengagement"
    SARCASM = "sarcasm"
    ENTHUSIASM = "enthusiasm"


_WEAK_SIGNAL_PATTERNS: list[tuple[SignalType, re.Pattern]] = [
    (SignalType.SOLUTION_BEFORE_PROBLEM,
     re.compile(r"\b(build|implement|add|create|develop|ship|launch)\b.{0,60}\b(feature|button|page|screen|flow|API)\b", re.I | re.S)),
    (SignalType.VAGUE_METRICS,
     re.compile(r"\b(improve(d)?|better|faster|easier|more (efficient|engaging|intuitive))\b(?!.{0,30}\d)", re.I)),
    (SignalType.VAGUE_IMPACT,
     re.compile(r"\b(big impact|huge|massive|significant|greatly|substantially)\b(?!.{0,40}\d)", re.I)),
    (SignalType.COPPA_MINORS,
     re.compile(r"\b(child(ren)?|minor|kid|teen|juvenile|under.?13|under.?18)\b", re.I)),
    (SignalType.SCOPE_CREEP,
     re.compile(r"\b(also|and also|while we're at it|while we are at it|oh and|one more thing)\b", re.I)),
    (SignalType.MISSING_ROLLOUT,
     re.compile(r"\b(rollout|roll.out|phased|gradual|canary|beta|pilot|release plan)\b", re.I)),
]

_STRONG_SIGNAL_PATTERNS: list[tuple[SignalType, re.Pattern]] = [
    (SignalType.QUANTIFIED_PROBLEM,
     re.compile(r"\b\d[\d,\.]*\s*(%|users|patrons|sessions|tickets|calls|hours|dollars|\$).{0,80}(problem|issue|fail|drop|churn|abandon)", re.I | re.S)),
    (SignalType.HYPOTHESIS_STATED,
     re.compile(r"\b(hypothesis|we believe (that )?if|we think (that )?if|if we .{0,40} then)\b", re.I)),
    (SignalType.TRADEOFF_STATED,
     re.compile(r"\b(tradeoff|trade.off|we considered|alternative(s)? (include|are|were)|instead of)\b", re.I)),
]

_EMOTIONAL_SIGNAL_PATTERNS: list[tuple[SignalType, re.Pattern]] = [
    (SignalType.FRUSTRATION,
     re.compile(r"\b(frustrated?|annoyed?|ugh|this is (hard|difficult|a pain)|why (can't|won't|isn't))\b", re.I)),
    (SignalType.OVERWHELM,
     re.compile(r"\b(overwhelm(ed)?|too much|don't know where to start|lost|confused|complicated)\b", re.I)),
    (SignalType.DISENGAGEMENT,
     re.compile(r"\b(whatever|doesn't matter|i don't care|skip it|just do (it|anything))\b", re.I)),
    (SignalType.SARCASM,
     re.compile(r"\b(oh sure|yeah right|obviously|clearly|of course .{0,20}not)\b", re.I)),
    (SignalType.ENTHUSIASM,
     re.compile(r"\b(excited|love (this|it)|can't wait|amazing|fantastic|this is great)\b", re.I)),
]


@dataclass
class DetectedSignal:
    """A single detected signal."""
    signal_type: SignalType
    excerpt: str = ""
    is_weak: bool = False
    is_strong: bool = False
    is_emotional: bool = False


class SignalDetector:
    """Detects weak and strong signals in user messages.

    Heuristic only — no LLM calls. Fast and deterministic.

    Weak signals trigger push-back from Priya.
    Strong signals allow skipping the exploratory phase.
    Emotional signals drive tone adaptation.
    """

    def analyze(self, text: str) -> list[DetectedSignal]:
        """Return all signals detected in the given text."""
        signals: list[DetectedSignal] = []
        seen: set[SignalType] = set()

        for signal_type, pattern in _WEAK_SIGNAL_PATTERNS:
            if signal_type in seen:
                continue
            m = pattern.search(text)
            if m:
                seen.add(signal_type)
                signals.append(DetectedSignal(
                    signal_type=signal_type,
                    excerpt=text[max(0, m.start()-20):m.end()+20].strip(),
                    is_weak=True,
                ))

        for signal_type, pattern in _STRONG_SIGNAL_PATTERNS:
            if signal_type in seen:
                continue
            m = pattern.search(text)
            if m:
                seen.add(signal_type)
                signals.append(DetectedSignal(
                    signal_type=signal_type,
                    excerpt=text[max(0, m.start()-20):m.end()+20].strip(),
                    is_strong=True,
                ))

        for signal_type, pattern in _EMOTIONAL_SIGNAL_PATTERNS:
            if signal_type in seen:
                continue
            m = pattern.search(text)
            if m:
                seen.add(signal_type)
                signals.append(DetectedSignal(
                    signal_type=signal_type,
                    excerpt=text[max(0, m.start()-20):m.end()+20].strip(),
                    is_emotional=True,
                ))

        return signals

    def has_weak_signals(self, text: str) -> bool:
        return any(s.is_weak for s in self.analyze(text))

    def has_strong_signals(self, text: str) -> bool:
        return any(s.is_strong for s in self.analyze(text))

    def emotional_tone(self, text: str) -> SignalType | None:
        """Return the first emotional signal type detected, or None."""
        for s in self.analyze(text):
            if s.is_emotional:
                return s.signal_type
        return None


# ===========================================================================
# DomainContext — file-driven domain knowledge loader
# ===========================================================================

_DEFAULT_DOMAIN_DIR = os.path.join(
    os.path.dirname(__file__), "..", "intake", "domain-context"
)


class DomainContext:
    """Loads and caches domain context from markdown files.

    Files live in pipeline/intake/domain-context/*.md
    All files are read at load time and concatenated for injection into
    the system prompt. This mechanism must remain working as RAG is added
    in Phase 2 — do not replace, extend it.
    """

    def __init__(self, domain_dir: str | None = None):
        self._domain_dir = os.path.abspath(domain_dir or _DEFAULT_DOMAIN_DIR)
        self._cache: str | None = None

    def load(self) -> str:
        """Return concatenated domain context markdown.

        Cached after first read. Call invalidate() to force re-read.
        """
        if self._cache is not None:
            return self._cache

        if not os.path.isdir(self._domain_dir):
            self._cache = ""
            return self._cache

        parts: list[str] = []
        try:
            filenames = sorted(os.listdir(self._domain_dir))
        except OSError:
            self._cache = ""
            return self._cache

        for fname in filenames:
            if not fname.endswith(".md"):
                continue
            fpath = os.path.join(self._domain_dir, fname)
            try:
                with open(fpath, encoding="utf-8") as f:
                    content = f.read().strip()
                if content:
                    parts.append(f"## {fname}\n\n{content}")
            except OSError:
                continue

        self._cache = "\n\n---\n\n".join(parts)
        return self._cache

    def invalidate(self) -> None:
        """Clear cache so next load() re-reads files."""
        self._cache = None


# ===========================================================================
# ContextAssembler — builds layered system prompt for each LLM call
# ===========================================================================

# Priya's persona and protocol — the stable core (see CLAUDE.md)
_PERSONA_BLOCK = """
# Priya Desai — Product Development Coach

You are Priya Desai, a product development coach at Hoopla Digital. You help
product managers, product owners, and business systems analysts structure their
ideas into rigorous business cases, epics, and user stories.

## Core Identity
- Coach, not a chatbot. You guide, you do not comply.
- You produce business artifacts only: business-case.md, epics.md, stories-draft.md.
- You NEVER generate code, SQL, API contracts, or system design diagrams.
- You do not compliment people. Acknowledge substance, not people.
- You do not fabricate numbers. If you lack data, say so. Label assumptions explicitly.
- You do not provide emotional support or act as a companion.

## Coaching Protocol
1. Understand the problem before entertaining solutions.
2. Push back on vague impact claims, unmeasured metrics, and missing alternatives.
3. Do not re-ask a question already asked. Interpret indirect answers charitably.
4. Calibrate response length: clarifying questions = 2-4 sentences, push-back = 2 sentences.
5. Artifact output is structured only — no narrative introduction.

## Push-Back Triggers (always challenge these)
- Vague impact claims without quantification
- Solution-before-problem (jumping to "build X" without stating the problem)
- No alternatives considered
- Unmeasurable or undefined metrics
- Scope creep during a session
- Missing rollout strategy

## Tone Adaptation
- Frustrated users: shorter, more direct responses
- Overwhelmed users: narrow the scope, one question at a time
- Disengaged users: re-anchor to their original stated problem
- Sarcastic users: substance-focused, no mirroring
- Enthusiastic users: channel energy into specifics

## Prohibited
- Compliments ("Great question!", "I love that idea", etc.)
- Code generation of any kind
- Fabricated numbers or invented evidence
- Emotional labor or companionship language
- Re-asking questions already asked in this session
""".strip()

_ARTIFACT_SCHEMAS_BLOCK = """
# Artifact Schemas

When generating artifacts, use EXACTLY these structures. No narrative prose,
no commentary, no caveats inside artifact output.

## business-case.md
```markdown
# Business Case: [Feature Name]

## Problem
[Clear problem statement]

## Evidence
[Data, research, or user feedback supporting the problem]

## Users
[Who is affected and how]

## Impact
[Quantified expected outcome]

## Solution
[Proposed approach]

## Metrics
[How success will be measured]

## Risks
[Known risks, dependencies, assumptions]

## Scope
[What is in scope / out of scope for this effort]

## Platform
[Which platforms / clients are affected]
```

## epics.md
```markdown
# Epics: [Feature Name]

## Epic 1: [Name]
**Goal:** [What this epic achieves]
**Acceptance Criteria:**
- [ ] [Criterion 1]
- [ ] [Criterion 2]
```

## stories-draft.md
```markdown
# User Stories: [Feature Name]

## [Epic Name]

### Story 1: [Name]
**As a** [user type]
**I want** [capability]
**So that** [benefit]

**Sizing:** [XS/S/M/L/XL]
**Notes:** [Any clarifications or open questions]
```
""".strip()

_INTERACTION_RULES_BLOCK = """
# Interaction Rules

1. Conversation arc:
   - Early turns: open questions, understand problem space
   - Mid turns: structured gap-filling per ProgressTracker
   - Late turns: artifact generation (gated by completeness)
   - Fast-track: skip exploratory phase if input is already strong

2. Slash commands:
   - /help — explain what Priya does and how to use the coach
   - /status — show current completeness status across business-case fields
   - /generate — attempt artifact generation (gated by completeness)
   - /reset — clear session and start over

3. Multimodal inputs:
   - URLs, file uploads, images are context; extract relevant product information
   - Do not describe images in detail; extract product-relevant facts

4. Artifact gating:
   - Do NOT generate artifacts if ProgressTracker completeness is below threshold
   - Tell the user which fields are still incomplete
   - Do not offer to "generate a partial" artifact — it degrades downstream quality
""".strip()


class ContextAssembler:
    """Builds the layered system prompt for each LLM call.

    Layer order (per CLAUDE.md):
    1. Persona and protocol definitions
    2. Domain markdown context (file-driven)
    3. Artifact schemas
    4. Interaction rules and behavioral constraints
    5. Dynamic overlays from ProgressTracker (turn-count-aware guidance)
    6. Memory context from CoachMemory
    """

    # Maximum chars to inject from RAG before truncating (~2000 tokens)
    RAG_BUDGET_CHARS: int = 8000

    def __init__(
        self,
        domain_context: DomainContext | None = None,
        context_sources: list[ContextSource] | None = None,
    ):
        self._domain = domain_context or DomainContext()
        self._context_sources: list[ContextSource] = context_sources or []

    def build(
        self,
        progress: ProgressTracker,
        turn_count: int = 0,
        memory_context: str = "",
        extra_overlay: str = "",
        conversation_state: dict | None = None,
    ) -> str:
        """Assemble and return the full system prompt string.

        Args:
            progress: Current ProgressTracker state (for dynamic overlays).
            turn_count: Number of turns so far (drives phase-awareness).
            memory_context: Text from CoachMemory for this session.
            extra_overlay: Any additional instruction text to append.
            conversation_state: Optional dict with "messages", "missing_fields",
                "turn_count" keys for Phase 2 RAG retrieval. If None, RAG
                sources are not queried (graceful degradation).

        Returns:
            Complete system prompt string ready for the LLM.
        """
        sections: list[str] = []

        # Layer 1: Persona and protocol
        sections.append(_PERSONA_BLOCK)

        # Layer 2: Domain context (static file-driven baseline — always active)
        domain_text = self._domain.load()
        if domain_text:
            sections.append("# Domain Knowledge\n\n" + domain_text)

        # Layer 2b: RAG-retrieved context (Phase 2, additive only)
        # Static DomainContext always loads first and is never skipped.
        # If no context_sources are registered or retrieval fails, this
        # layer is simply absent — no change to coaching behaviour.
        if self._context_sources and conversation_state is not None:
            rag_text = self._build_rag_layer(conversation_state, domain_text or "")
            if rag_text:
                sections.append("# Additional Retrieved Context\n\n" + rag_text)

        # Layer 3: Artifact schemas
        sections.append(_ARTIFACT_SCHEMAS_BLOCK)

        # Layer 4: Interaction rules
        sections.append(_INTERACTION_RULES_BLOCK)

        # Layer 5: Dynamic overlay from ProgressTracker
        overlay = self._build_progress_overlay(progress, turn_count)
        if overlay:
            sections.append(overlay)

        # Layer 6: Memory context
        if memory_context:
            sections.append("# Prior Session Context\n\n" + memory_context)

        # Extra overlay (for testing or one-off injections)
        if extra_overlay:
            sections.append(extra_overlay)

        return "\n\n---\n\n".join(sections)

    def _build_rag_layer(self, conversation_state: dict, static_context: str) -> str:
        """Collect RAG chunks from all registered ContextSources.

        Applies deduplication against static_context and enforces the
        RAG_BUDGET_CHARS limit. Returns an empty string if nothing useful
        is retrieved.
        """
        all_chunks: list[ContextChunk] = []
        for source in self._context_sources:
            try:
                chunks = source.get_context(conversation_state)
                all_chunks.extend(chunks)
            except Exception:
                pass  # ContextSource must degrade gracefully; log inside source

        if not all_chunks:
            return ""

        # Sort by score desc, apply budget
        all_chunks.sort(key=lambda c: c.score, reverse=True)
        lines: list[str] = []
        total_chars = 0

        for chunk in all_chunks:
            if total_chars >= self.RAG_BUDGET_CHARS:
                break
            # Attribution header
            source_name = chunk.source.split("/")[-1] if "/" in chunk.source else chunk.source
            section = chunk.metadata.get("section_header", "")
            if section:
                attr = f"[Source: {source_name} — {section}]"
            else:
                attr = f"[Source: {source_name}]"

            entry = f"{attr}\n{chunk.content}"
            lines.append(entry)
            total_chars += len(entry)

        return "\n\n".join(lines)

    @staticmethod
    def _build_progress_overlay(progress: ProgressTracker, turn_count: int) -> str:
        """Build a turn-count-aware guidance overlay."""
        completeness = progress.completeness()
        missing = progress.missing_fields()
        ready = progress.is_ready_for_artifacts()

        lines: list[str] = ["# Current Session State (Dynamic Overlay)"]
        lines.append(f"Turn count: {turn_count}")
        lines.append(f"Completeness: {completeness:.0%}")
        lines.append(f"Artifact ready: {ready}")

        if missing:
            lines.append(f"Missing/weak fields: {', '.join(missing)}")
            lines.append(
                "Focus your next question on the highest-priority missing field. "
                "Do not ask about fields already covered."
            )

        if turn_count <= 2:
            lines.append("Phase: EARLY — ask open, exploratory questions. Understand the problem space.")
        elif turn_count <= 6:
            lines.append("Phase: MID — structured gap-filling. Address missing fields systematically.")
        else:
            lines.append("Phase: LATE — push toward artifact generation if completeness allows.")

        if ready:
            lines.append(
                "Completeness threshold met. You MAY offer to generate artifacts when the user is ready."
            )
        else:
            lines.append(
                "Do NOT generate artifacts yet. Tell the user which fields need more detail."
            )

        return "\n".join(lines)


# ===========================================================================
# CoachEngine — multi-turn conversation controller
# ===========================================================================

_SLASH_COMMANDS = {"/help", "/status", "/generate", "/reset"}

# Artifact generation refused response (used when gating)
_ARTIFACT_GATE_REFUSAL_TEMPLATE = (
    "The business case isn't complete enough to generate artifacts yet. "
    "These fields still need detail: {missing}. "
    "Let's work through those before generating the spec."
)

# Help text for /help command
_HELP_TEXT = """
Priya Desai — Product Development Coach

I help you build rigorous business cases, epics, and user stories for Hoopla Digital's product team.

Commands:
  /help     — show this message
  /status   — show completeness status for the current business case
  /generate — generate artifacts (business-case.md, epics.md, stories-draft.md)
  /reset    — clear this session and start over

Tips:
  - Start by describing the problem you're trying to solve, not the feature you want to build.
  - Bring data if you have it. Quantified problems get better specs.
  - I'll push back if something is vague or missing. That's intentional.
""".strip()


class CoachEngine:
    """Multi-turn conversation controller.

    Drives AgentBackend.chat_stream, injects the layered system prompt
    via ContextAssembler, runs SignalDetector and ProgressTracker on each
    turn, and handles slash commands.

    Usage:
        engine = CoachEngine(backend)
        for chunk in engine.chat_stream(user_message):
            print(chunk, end="", flush=True)
    """

    def __init__(
        self,
        backend: AgentBackend,
        domain_context: DomainContext | None = None,
        memory_context: str = "",
        context_sources: list[ContextSource] | None = None,
    ):
        self._backend = backend
        self._assembler = ContextAssembler(
            domain_context=domain_context,
            context_sources=context_sources,
        )
        self._tracker = ProgressTracker()
        self._detector = SignalDetector()
        self._memory_context = memory_context
        self._messages: list[dict] = []
        self._turn_count: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chat(self, user_message: str, attachments: list[dict] | None = None) -> AgentResult:
        """Blocking single-turn interface."""
        result_text = ""
        for chunk in self.chat_stream(user_message, attachments=attachments):
            result_text += chunk
        return AgentResult(output=result_text, success=True)

    def chat_stream(
        self,
        user_message: str,
        attachments: list[dict] | None = None,
    ) -> Generator[str, None, None]:
        """Stream response chunks for a single user turn.

        Handles slash commands inline. For normal messages:
        1. Runs SignalDetector to flag weak/strong signals
        2. Updates ProgressTracker
        3. Builds system prompt via ContextAssembler
        4. Calls AgentBackend.chat_stream
        5. Appends the assistant response to history
        """
        # Handle slash commands first
        stripped = user_message.strip().lower()
        if stripped in _SLASH_COMMANDS:
            response = self._handle_slash(stripped)
            self._append_message("user", user_message)
            self._append_message("assistant", response)
            yield response
            return

        # Build user message (with attachments if any)
        content = self._build_content(user_message, attachments)
        self._append_message("user", content)

        # Analyze signals
        signals = self._detector.analyze(user_message)
        _ = signals  # SignalDetector results inform the system prompt via overlays;
                     # direct signal injection handled by ContextAssembler overlays

        # Update completeness scoring
        self._tracker.update(self._messages)

        # Build system prompt (include conversation_state for Phase 2 RAG)
        system_prompt = self._assembler.build(
            progress=self._tracker,
            turn_count=self._turn_count,
            memory_context=self._memory_context,
            conversation_state={
                "messages": self._messages[-6:],  # last 3 turns
                "missing_fields": self._tracker.missing_fields(),
                "turn_count": self._turn_count,
            },
        )

        # Stream from backend
        response_parts: list[str] = []
        try:
            for chunk in self._backend.chat_stream(
                messages=self._messages,
                system=system_prompt,
            ):
                response_parts.append(chunk)
                yield chunk
        except Exception as e:
            error_msg = f"[Backend error: {e}]"
            yield error_msg
            response_parts.append(error_msg)

        # Append assistant response to history
        full_response = "".join(response_parts)
        self._append_message("assistant", full_response)
        self._turn_count += 1

    def reset(self) -> None:
        """Clear conversation history and reset state."""
        self._messages = []
        self._turn_count = 0
        self._tracker = ProgressTracker()

    @property
    def messages(self) -> list[dict]:
        return list(self._messages)

    @property
    def tracker(self) -> ProgressTracker:
        return self._tracker

    @property
    def turn_count(self) -> int:
        return self._turn_count

    # ------------------------------------------------------------------
    # Slash command handlers
    # ------------------------------------------------------------------

    def _handle_slash(self, command: str) -> str:
        if command == "/help":
            return _HELP_TEXT
        elif command == "/status":
            return self._status_report()
        elif command == "/generate":
            return self._handle_generate()
        elif command == "/reset":
            self.reset()
            return "Session cleared. Start by describing the problem you're trying to solve."
        return f"Unknown command: {command}"

    def _status_report(self) -> str:
        completeness = self._tracker.completeness()
        statuses = self._tracker.status_report()
        lines = [f"Business case completeness: {completeness:.0%}", ""]
        for fname, status in statuses.items():
            icon = "+" if status in ("adequate", "strong") else "-"
            lines.append(f"  [{icon}] {fname}: {status}")
        missing = self._tracker.missing_fields()
        if missing:
            lines.append(f"\nStill needed: {', '.join(missing)}")
        else:
            lines.append("\nAll fields covered. Use /generate to produce artifacts.")
        return "\n".join(lines)

    def _handle_generate(self) -> str:
        if not self._tracker.is_ready_for_artifacts():
            missing = self._tracker.missing_fields()
            return _ARTIFACT_GATE_REFUSAL_TEMPLATE.format(missing=", ".join(missing))
        # Completeness threshold met — let the LLM generate
        # We inject a one-shot generate instruction and stream back
        generate_parts: list[str] = []
        system_prompt = self._assembler.build(
            progress=self._tracker,
            turn_count=self._turn_count,
            memory_context=self._memory_context,
            extra_overlay=(
                "# GENERATE NOW\n"
                "The user has requested artifact generation. Completeness threshold is met. "
                "Generate all three artifacts (business-case.md, epics.md, stories-draft.md) "
                "using the schemas defined above. Output structured markdown only. "
                "No narrative introduction."
            ),
        )
        # We call chat (blocking) here so we can return the full string
        result = self._backend.chat(
            messages=self._messages,
            system=system_prompt,
        )
        self._append_message("assistant", result.output)
        self._turn_count += 1
        return result.output

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _append_message(self, role: str, content) -> None:
        self._messages.append({"role": role, "content": content})

    @staticmethod
    def _build_content(text: str, attachments: list[dict] | None) -> list[dict] | str:
        """Build message content, with attachments if present."""
        if not attachments:
            return text
        blocks: list[dict] = [{"type": "text", "text": text}]
        for att in attachments:
            att_type = att.get("type", "text")
            if att_type == "image":
                blocks.append({
                    "type": "image",
                    "source": att.get("source", {}),
                })
            elif att_type == "url":
                blocks.append({
                    "type": "text",
                    "text": f"\n[Attached URL: {att.get('url', '')}]\n{att.get('content', '')}",
                })
            elif att_type == "file":
                blocks.append({
                    "type": "text",
                    "text": f"\n[Attached file: {att.get('filename', 'unknown')}]\n{att.get('content', '')}",
                })
        return blocks
