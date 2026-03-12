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
from typing import TYPE_CHECKING, Generator

from pipeline.backends.base import AgentBackend, AgentResult

if TYPE_CHECKING:
    from pipeline.coach.memory import CoachMemory


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
# MemorySource — Phase B active memory ContextSource adapter
# ===========================================================================

class MemorySource(ContextSource):
    """ContextSource adapter that surfaces past-feature analogues from CoachMemory.

    Implements the ContextSource protocol so it can be registered with
    ContextAssembler alongside RAG retrievers. At low turn counts it surfaces
    analogous past features; in RETROSPECT mode it surfaces the prior spec.

    Degrades gracefully — if CoachMemory is unavailable or returns nothing,
    returns [].

    Args:
        memory: A CoachMemory instance.
        current_session_id: ID of the ongoing session (excluded from recall).
        top_k: Maximum number of analogous features to surface.
        analogue_turn_limit: Only surface analogues during early turns
                             (default 4). After that the conversation is rich
                             enough to stand on its own.
    """

    def __init__(
        self,
        memory: "CoachMemory",
        current_session_id: str = "",
        top_k: int = 3,
        analogue_turn_limit: int = 4,
    ):
        self._memory = memory
        self._session_id = current_session_id
        self._top_k = top_k
        self._analogue_turn_limit = analogue_turn_limit

    def get_context(self, conversation_state: dict) -> list[ContextChunk]:
        """Return memory context relevant to the current conversation.

        Strategy:
        - turn 0-N (early): search for analogous past features using the
          last user message as the query.
        - RETROSPECT mode: look up the prior spec for the named feature.
        - Returns [] on any error or when nothing is found.
        """
        try:
            turn_count = conversation_state.get("turn_count", 0)
            messages = conversation_state.get("messages", [])
            mode = conversation_state.get("mode", "intake")

            # Build a query from the most recent user message
            query = ""
            for msg in reversed(messages):
                if msg.get("role") == "user":
                    content = msg.get("content", "")
                    if isinstance(content, list):
                        query = " ".join(
                            b.get("text", "") for b in content
                            if isinstance(b, dict) and b.get("type") == "text"
                        )
                    else:
                        query = str(content)
                    break

            if not query:
                return []

            chunks: list[ContextChunk] = []

            # RETROSPECT: surface prior spec for the named feature
            if mode == SessionMode.RETROSPECT.value or mode == SessionMode.RETROSPECT:
                from pipeline.coach.crystallizer import extract_feature_name
                fname, confidence = extract_feature_name(messages)
                if fname and confidence >= 0.6:
                    outcome_text = self._memory.lookup_feature_outcome(fname)
                    if outcome_text:
                        chunks.append(ContextChunk(
                            source="memory:prior_spec",
                            content=outcome_text,
                            score=0.95,
                            metadata={"feature_name": fname, "confidence": confidence},
                        ))
                        return chunks  # Prior spec is the primary context for retrospect

            # Early turns: surface analogous past features
            if turn_count <= self._analogue_turn_limit:
                analogues = self._memory.recall_similar_feature(
                    query=query,
                    top_k=self._top_k,
                    exclude_session_id=self._session_id or None,
                )
                if analogues:
                    chunks.append(ContextChunk(
                        source="memory:analogues",
                        content=analogues,
                        score=0.70,
                        metadata={"turn_count": turn_count},
                    ))

            return chunks

        except Exception:
            return []  # Always degrade gracefully


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
# SessionMode — the active facilitation mode
# ===========================================================================

class SessionMode(Enum):
    """Active facilitation mode for the current session.

    Each mode has a different conversation arc, different ProgressTracker
    fields, and produces a different artifact. Priya's persona does not
    change across modes — only the arc and scoring change.

    Slash command to enter each mode:
        /intake        — default spec funnel (business-case, epics, stories)
        /wb            — Working Backwards (press release → requirements)
        /premortem     — Pre-mortem (failure scenario → risk synthesis)
        /steelman      — Steel-man (strongest counter-argument → refined position)
        /prioritize    — Prioritization (candidates → ranked priority stack)
        /retro         — Retrospective (prior spec → outcome loop closure)
    """
    INTAKE = "intake"
    WORKING_BACKWARDS = "working-backwards"
    PREMORTEM = "premortem"
    STEELMAN = "steelman"
    PRIORITIZE = "prioritize"
    RETROSPECT = "retrospect"


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

# Patron data exposure — triggers the privacy gate
_PATRON_DATA_PATTERN = re.compile(
    r"\b(patron (data|record\w*|history|activity|borrow\w*|reading)|"
    r"user (data|history|activity|record\w*)|"
    r"reading history|borrow\w* history|checkout history|"
    r"personal (data|information) of (patrons|users)|"
    r"patron.level|individual patron|patron identifier|patron id|"
    r"kids mode|children|child(ren)?|minor|under.?13)\b",
    re.I,
)

# Privacy impact discussion — satisfies the privacy gate
_PRIVACY_IMPACT_PATTERN = re.compile(
    r"\b(privacy impact|data minimization|anonymi(ze|s)(d|ation)|aggregate(d)?|"
    r"retention policy|data retention|not retain|won.?t retain|"
    r"coppa|privacy review|privacy risk|personally identifiable|PII|"
    r"no patron.level|patron.level data (is|will be) (excluded|not|anonymi))\b",
    re.I,
)


# Fields required for artifact generation in each mode
_MODE_FIELDS: dict[str, list[str]] = {
    SessionMode.INTAKE.value: [
        "problem", "evidence", "users", "impact", "solution",
        "metrics", "risks", "scope", "platform",
    ],
    SessionMode.WORKING_BACKWARDS.value: [
        "headline", "customer_problem", "solution_experience",
        "patron_quote", "admin_quote", "internal_faq",
    ],
    SessionMode.PREMORTEM.value: [
        "failure_scenario", "likely_causes", "adoption_risks",
        "measurement_risks", "mitigations",
    ],
    SessionMode.STEELMAN.value: [
        "position", "counter_argument", "pm_response",
    ],
    SessionMode.PRIORITIZE.value: [
        "candidates", "scoring_criteria", "ranked_output",
    ],
    SessionMode.RETROSPECT.value: [
        "prior_spec", "actual_outcome", "delta_analysis", "learnings",
    ],
}

# Field detection patterns for non-intake modes (binary MISSING/ADEQUATE)
_MODE_FIELD_PATTERNS: dict[str, dict[str, list[re.Pattern]]] = {
    SessionMode.WORKING_BACKWARDS.value: {
        "headline": [
            re.compile(r"\b(headline|announcement|title|in one sentence|press release)\b", re.I),
        ],
        "customer_problem": [
            re.compile(r"\b(problem|pain|struggle|friction|today they|currently they|can't easily)\b", re.I),
        ],
        "solution_experience": [
            re.compile(r"\b(experience|how it works|workflow|the flow|what (they|patrons|admins) (do|see|get))\b", re.I),
        ],
        "patron_quote": [
            re.compile(r"\b(patron (would say|said|feels|quote)|user (would say|said)|from a patron)\b", re.I),
        ],
        "admin_quote": [
            re.compile(r"\b(admin (would say|said)|librarian (would say|said)|from (an? )?(admin|librarian))\b", re.I),
        ],
        "internal_faq": [
            re.compile(r"\b(FAQ|the team (will|would) ask|engineering (will|would)|objection|internally|hardest question)\b", re.I),
        ],
    },
    SessionMode.PREMORTEM.value: {
        "failure_scenario": [
            re.compile(r"\b(failed|failure|didn.?t work|unsuccessful|went wrong|six months|twelve months|a year later)\b", re.I),
        ],
        "likely_causes": [
            re.compile(r"\b(because|cause(d by)?|reason|why (it )?(failed|didn.?t)|root cause|most likely)\b", re.I),
        ],
        "adoption_risks": [
            re.compile(r"\b(adoption|usage|nobody used|didn.?t use|never used|uptake|discovered|aware)\b", re.I),
        ],
        "measurement_risks": [
            re.compile(r"\b(couldn.?t (measure|track)|no data|metric|couldn.?t tell|unable to confirm|untracked)\b", re.I),
        ],
        "mitigations": [
            re.compile(r"\b(prevent|mitigate|commitment|safeguard|we (will|would|should|plan to)|going forward|instead)\b", re.I),
        ],
    },
    SessionMode.STEELMAN.value: {
        "position": [
            re.compile(r"\b(our position|we believe|our proposal|we (think|argue|claim|propose))\b", re.I),
        ],
        "counter_argument": [
            re.compile(r"\b(strongest (case|argument)|counter|objection|against this|case for not|devil.?s advocate)\b", re.I),
        ],
        "pm_response": [
            re.compile(r"\b(our response|we.?d (say|argue|counter)|answer (to|is)|we acknowledge|we accept)\b", re.I),
        ],
    },
    SessionMode.PRIORITIZE.value: {
        "candidates": [
            re.compile(r"\b(option|candidate|feature|initiative|proposal|alternative|item)\b", re.I),
        ],
        "scoring_criteria": [
            re.compile(r"\b(scoring|criteria|weight|impact|effort|confidence|ICE|RICE|framework)\b", re.I),
        ],
        "ranked_output": [
            re.compile(r"\b(rank(ed|ing)?|priority|first|second|third|recommend|winner|top)\b", re.I),
        ],
    },
    SessionMode.RETROSPECT.value: {
        "prior_spec": [
            re.compile(r"\b(the spec|we planned|we predicted|business case (said|expected)|the original)\b", re.I),
        ],
        "actual_outcome": [
            re.compile(r"\b(what (actually )?happened|the outcome|shipped|result|actual|in practice)\b", re.I),
        ],
        "delta_analysis": [
            re.compile(r"\b(difference|gap|why|variance|off|discrepancy|wrong|missed|different from)\b", re.I),
        ],
        "learnings": [
            re.compile(r"\b(learn(ed|ing)|takeaway|next time|going forward|insight|apply|do differently)\b", re.I),
        ],
    },
}


@dataclass
class FieldScore:
    """Score for one field."""
    field: str
    status: FieldStatus = FieldStatus.MISSING
    evidence_snippets: list[str] = field(default_factory=list)


class ProgressTracker:
    """Scores session completeness across all required fields for the active mode.

    Uses regex heuristics — no LLM calls. Fast and deterministic.

    In INTAKE mode: scores 9 business-case fields with weighted completeness.
    In other modes: scores mode-specific fields with equal weighting.
    Artifact generation is gated at _ARTIFACT_GATE_THRESHOLD in all modes.
    """

    def __init__(self, mode: SessionMode = SessionMode.INTAKE):
        self._mode: SessionMode = mode
        self._scores: dict[str, FieldScore] = {
            f: FieldScore(field=f) for f in self._active_fields()
        }
        self._privacy_gate_required: bool = False
        self._privacy_impact_met: bool = False

    # ------------------------------------------------------------------
    # Mode management
    # ------------------------------------------------------------------

    def set_mode(self, mode: SessionMode) -> None:
        """Switch to a new session mode and reset all scores."""
        self._mode = mode
        self._scores = {f: FieldScore(field=f) for f in self._active_fields()}
        self._privacy_gate_required = False
        self._privacy_impact_met = False

    @property
    def mode(self) -> SessionMode:
        return self._mode

    def _active_fields(self) -> list[str]:
        return _MODE_FIELDS.get(self._mode.value, _SCORED_FIELDS)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, messages: list[dict]) -> None:
        """Re-score all fields from the full conversation history.

        Called after each user turn so ProgressTracker always reflects the
        latest state. Behaviour depends on active mode:
        - INTAKE: weighted field scoring with WEAK/ADEQUATE/STRONG gradations
        - Other modes: binary MISSING/ADEQUATE scoring against mode patterns
        """
        active = self._active_fields()

        # Reset to active field set
        self._scores = {f: FieldScore(field=f) for f in active}
        self._privacy_gate_required = False
        self._privacy_impact_met = False

        # Collect all user text
        user_text = self._collect_user_text(messages)

        # Privacy gate applies in all modes
        if _PATRON_DATA_PATTERN.search(user_text):
            self._privacy_gate_required = True
            self._privacy_impact_met = bool(_PRIVACY_IMPACT_PATTERN.search(user_text))

        if self._mode == SessionMode.INTAKE:
            self._update_intake(user_text)
        else:
            self._update_mode(user_text)

    def _update_intake(self, user_text: str) -> None:
        """Intake-mode scoring: weighted fields with WEAK/ADEQUATE/STRONG."""
        for fname, patterns in _FIELD_PATTERNS.items():
            snippets = []
            matched = False
            for pattern in patterns:
                for m in pattern.finditer(user_text):
                    matched = True
                    start = max(0, m.start() - 40)
                    end = min(len(user_text), m.end() + 40)
                    snippets.append(user_text[start:end].strip())

            if not matched:
                self._scores[fname].status = FieldStatus.MISSING
                continue

            has_quantification = bool(_QUANTIFICATION_PATTERN.search(user_text))
            if has_quantification and fname in ("problem", "impact", "evidence", "metrics"):
                self._scores[fname].status = FieldStatus.STRONG
            else:
                self._scores[fname].status = FieldStatus.ADEQUATE

            self._scores[fname].evidence_snippets = snippets[:3]

    def _update_mode(self, user_text: str) -> None:
        """Non-intake mode scoring: binary MISSING/ADEQUATE per mode patterns."""
        mode_patterns = _MODE_FIELD_PATTERNS.get(self._mode.value, {})
        for fname in self._active_fields():
            patterns = mode_patterns.get(fname, [])
            matched = any(p.search(user_text) for p in patterns)
            self._scores[fname].status = FieldStatus.ADEQUATE if matched else FieldStatus.MISSING

    def completeness(self) -> float:
        """Return completeness as a float 0.0–1.0.

        INTAKE mode uses weighted fields. All other modes use equal weighting
        with binary MISSING/ADEQUATE scoring.
        """
        if not self._scores:
            return 0.0
        if self._mode == SessionMode.INTAKE:
            return self._completeness_intake()
        return self._completeness_equal()

    def _completeness_intake(self) -> float:
        weights = {
            "problem": 2.0, "evidence": 1.5, "users": 1.0, "impact": 1.5,
            "solution": 1.0, "metrics": 1.0, "risks": 0.5, "scope": 0.5, "platform": 0.5,
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
        return earned / total_weight

    def _completeness_equal(self) -> float:
        if not self._scores:
            return 0.0
        adequate = sum(
            1 for s in self._scores.values()
            if s.status in (FieldStatus.ADEQUATE, FieldStatus.STRONG)
        )
        return adequate / len(self._scores)

    def is_ready_for_artifacts(self) -> bool:
        """Return True if completeness meets the artifact gate threshold.

        Also enforces the privacy gate: if patron data or Kids Mode is
        detected in the conversation, a Privacy Impact discussion must
        be present before artifacts can be generated.
        """
        if self.completeness() < _ARTIFACT_GATE_THRESHOLD:
            return False
        if self._privacy_gate_required and not self._privacy_impact_met:
            return False
        return True

    @property
    def privacy_gate_required(self) -> bool:
        """True if this conversation requires a Privacy Impact section."""
        return self._privacy_gate_required

    @property
    def privacy_impact_met(self) -> bool:
        """True if privacy impact has been sufficiently addressed."""
        return self._privacy_impact_met

    def missing_fields(self) -> list[str]:
        """Return list of field names that are MISSING or WEAK.

        Includes 'privacy_impact' if the privacy gate is required but
        has not yet been satisfied.
        """
        missing = [
            f for f, s in self._scores.items()
            if s.status in (FieldStatus.MISSING, FieldStatus.WEAK)
        ]
        if self._privacy_gate_required and not self._privacy_impact_met:
            missing.append("privacy_impact")
        return missing

    def status_report(self) -> dict[str, str]:
        """Return a dict of field → status string for display.

        Includes 'privacy_impact' if the privacy gate is active.
        """
        report = {f: s.status.value for f, s in self._scores.items()}
        if self._privacy_gate_required:
            report["privacy_impact"] = "adequate" if self._privacy_impact_met else "missing"
        return report

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
    PATRON_DATA_EXPOSURE = "patron_data_exposure"
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
     re.compile(r"\b(child(ren)?|minor|kids?|teen|juvenile|under.?13|under.?18)\b", re.I)),
    (SignalType.PATRON_DATA_EXPOSURE,
     re.compile(
         r"\b(patron (data|record\w*|history|activity|borrow\w*|reading)|"
         r"user (data|history|activity|record\w*)|"
         r"reading history|borrow\w* history|checkout history|"
         r"personal (data|information) of (patrons|users)|"
         r"patron.level|individual patron|patron identifier|patron id|"
         r"kids mode)\b",
         re.I,
     )),
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

    def load_exercise(self, mode_name: str) -> str:
        """Load the exercise template for a given mode name.

        Templates live in pipeline/intake/domain-context/exercises/{mode_name}.md.
        Returns empty string if file not found (graceful degradation).
        """
        exercises_dir = os.path.join(self._domain_dir, "exercises")
        fpath = os.path.join(exercises_dir, f"{mode_name}.md")
        try:
            with open(fpath, encoding="utf-8") as f:
                return f.read().strip()
        except OSError:
            return ""


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

## Error Correction
- If the user corrects a mistake you made: acknowledge the specific error ("I stated X. That was incorrect."), state the correction, do not apologize beyond that, continue.
- If you realize your own error later: correct proactively. Name what was said and what is correct.
- If the error affected a generated artifact, say so and instruct the user to re-run /generate.
- Never double-down. Never hedge a correction with "but" or "however."

## Patron Privacy (Non-Negotiable)
- Library patron borrowing history, reading habits, and content interactions are private under the library social contract.
- When a feature touches patron data or Kids Mode, require the user to address privacy impact before artifact generation.
- Do not request, store, repeat, or reason about individual patron-level records.
- Kids Mode features are COPPA-sensitive: flag that data collection must be minimized.
- Push back on features that assume patron-level data access without explicit justification.

## Epistemic Triage
Classify significant claims by their evidentiary basis. Apply these tags in conversation and in artifacts:
- [DATA: source, date] — directly observed and measured
- [INFERENCE: reasoning] — reasonably derived from data but not directly measured
- [ASSUMPTION: basis] — believed without specific evidence; must be flagged
- [UNKNOWN: what would resolve this] — not yet investigated; requires action before spec is complete

When a PM makes a claim, identify which category it falls into and respond accordingly.
A business case where the problem is [DATA] but the solution is [ASSUMPTION] should be legible as such
to downstream readers. Do not flatten all claims into the same confidence level.

## Session Modes
You operate in different facilitation modes depending on what the PM needs. The active mode is
shown in the Dynamic Overlay. Each mode has a different arc and produces a different artifact:

- INTAKE (default): spec funnel — extract and challenge until business-case/epics/stories are complete
- WORKING-BACKWARDS: press release first — guide PM to write the end state, then reverse-engineer requirements
- PREMORTEM: failure scenario — imagine concrete failure, identify causes, commit to mitigations
- STEELMAN: strongest objection — build the best case against the proposal, then help PM respond
- PRIORITIZE: ranked candidates — score options, surface dependencies, produce priority stack
- RETROSPECT: outcome loop — close the gap between what was predicted and what actually happened

In all modes: Priya's behavioral contract is unchanged. No compliments, no code, no fabrication.
The mode changes the arc and artifact, not the persona.

## Prohibited
- Compliments ("Great question!", "I love that idea", etc.)
- Code generation of any kind
- Fabricated numbers or invented evidence
- Emotional labor or companionship language
- Re-asking questions already asked in this session
- Retaining, requesting, or reasoning about individual patron records
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

## Privacy Impact
[Required if feature touches patron data, user history, or Kids Mode. Omit only if no patron data is involved.]
[Data types accessed or created]
[Retention policy — how long, what form]
[Anonymization/aggregation approach]
[COPPA applicability (Kids Mode features)]
[Legal exposure assessment]
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

1. Conversation arc depends on active mode (see Dynamic Overlay).
   Default (INTAKE): early = open questions, mid = gap-filling, late = artifacts.

2. Slash commands:
   Spec funnel:
   - /help      — explain what Priya does and list commands
   - /status    — show completeness status for the current session
   - /generate  — attempt artifact generation (gated by completeness)
   - /reset     — clear session and start over (confirm first)
   - /mode      — show the active session mode

   Session modes (each resets the session):
   - /intake      — default spec funnel
   - /wb          — Working Backwards (press release → requirements)
   - /premortem   — Pre-mortem (failure scenario → risk synthesis)
   - /steelman    — Steel-man (strongest objection → refined position)
   - /prioritize  — Prioritization (candidates → priority stack)
   - /retro       — Retrospective (prior spec → outcome loop)

3. Multimodal inputs:
   - URLs, file uploads, images are context; extract relevant product information
   - Do not describe images in detail; extract product-relevant facts

4. Artifact gating:
   - Do NOT generate artifacts if ProgressTracker completeness is below threshold
   - Tell the user which fields are still incomplete
   - Do not offer to "generate a partial" artifact — it degrades downstream quality
   - Each mode produces a different artifact (see exercise template for schema)
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
                      The active mode is read from progress.mode.
            turn_count: Number of turns so far (drives phase-awareness).
            memory_context: Text from CoachMemory for this session.
            extra_overlay: Any additional instruction text to append.
            conversation_state: Optional dict with "messages", "missing_fields",
                "turn_count" keys for Phase 2 RAG retrieval. If None, RAG
                sources are not queried (graceful degradation).

        Returns:
            Complete system prompt string ready for the LLM.
        """
        mode = progress.mode
        sections: list[str] = []

        # Layer 1: Persona and protocol
        sections.append(_PERSONA_BLOCK)

        # Layer 2: Domain context (static file-driven baseline — always active)
        domain_text = self._domain.load()
        if domain_text:
            sections.append("# Domain Knowledge\n\n" + domain_text)

        # Layer 2b: RAG-retrieved context (Phase 2, additive only)
        if self._context_sources and conversation_state is not None:
            rag_text = self._build_rag_layer(conversation_state, domain_text or "")
            if rag_text:
                sections.append("# Additional Retrieved Context\n\n" + rag_text)

        # Layer 2c: Exercise template (non-intake modes only)
        if mode != SessionMode.INTAKE:
            exercise_text = self._domain.load_exercise(mode.value)
            if exercise_text:
                sections.append(f"# Active Exercise: {mode.value}\n\n{exercise_text}")

        # Layer 3: Artifact schemas (intake mode uses standard schemas;
        # other modes use the mode-specific schema embedded in the exercise template)
        if mode == SessionMode.INTAKE:
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
        """Build a turn-count-aware and mode-aware guidance overlay."""
        mode = progress.mode
        completeness = progress.completeness()
        missing = progress.missing_fields()
        ready = progress.is_ready_for_artifacts()

        lines: list[str] = ["# Current Session State (Dynamic Overlay)"]
        lines.append(f"Mode: {mode.value}")
        lines.append(f"Turn count: {turn_count}")
        lines.append(f"Completeness: {completeness:.0%}")
        lines.append(f"Artifact ready: {ready}")

        if missing:
            lines.append(f"Missing/weak fields: {', '.join(missing)}")
            lines.append(
                "Focus your next question on the highest-priority missing field. "
                "Do not ask about fields already covered."
            )

        if progress.privacy_gate_required and not progress.privacy_impact_met:
            lines.append(
                "PRIVACY GATE ACTIVE: This conversation involves patron data or Kids Mode. "
                "The user must address privacy impact (data minimization, retention, anonymization, "
                "COPPA applicability) before artifacts can be generated. "
                "Ask about privacy impact if not yet addressed."
            )

        # Mode-specific phase guidance
        if mode == SessionMode.INTAKE:
            if turn_count <= 2:
                lines.append("Phase: EARLY — ask open, exploratory questions. Understand the problem space.")
            elif turn_count <= 6:
                lines.append("Phase: MID — structured gap-filling. Address missing fields systematically.")
            else:
                lines.append("Phase: LATE — push toward artifact generation if completeness allows.")
        elif mode == SessionMode.WORKING_BACKWARDS:
            lines.append(
                "Exercise: WORKING BACKWARDS. Guide the PM through the press release format: "
                "headline → customer problem → solution experience → patron quote → admin quote → internal FAQ. "
                "Challenge vague or generic answers. Push for specific, concrete language in the customer's voice."
            )
        elif mode == SessionMode.PREMORTEM:
            lines.append(
                "Exercise: PRE-MORTEM. Help the PM imagine concrete failure. "
                "Start with a vivid failure scenario, then work systematically through causes: "
                "adoption failure, measurement failure, execution failure. "
                "End with specific mitigation commitments, not general platitudes."
            )
        elif mode == SessionMode.STEELMAN:
            lines.append(
                "Exercise: STEEL-MAN. Your job is to construct the strongest possible case AGAINST the PM's proposal, "
                "then help them respond to it. Do not pull punches. A weak counter-argument is useless. "
                "When the PM responds, evaluate whether their response actually addresses the objection."
            )
        elif mode == SessionMode.PRIORITIZE:
            lines.append(
                "Exercise: PRIORITIZATION. Identify all candidates, agree on scoring criteria "
                "(impact × confidence ÷ effort is a reasonable default), score each, and produce a ranked recommendation. "
                "Challenge candidates with weak rationale. Surface hidden dependencies."
            )
        elif mode == SessionMode.RETROSPECT:
            lines.append(
                "Exercise: RETROSPECTIVE. Help the PM close the outcome loop on a prior spec. "
                "First establish what was predicted, then what actually happened, then the gap. "
                "The goal is a crisp learning that feeds back into CoachMemory."
            )

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

_SLASH_COMMANDS = {
    "/help", "/status", "/generate", "/reset", "/mode",
    "/intake", "/wb", "/premortem", "/steelman", "/prioritize", "/retro",
    "/recall",
}

_MODE_SLASH_MAP: dict[str, SessionMode] = {
    "/intake":     SessionMode.INTAKE,
    "/wb":         SessionMode.WORKING_BACKWARDS,
    "/premortem":  SessionMode.PREMORTEM,
    "/steelman":   SessionMode.STEELMAN,
    "/prioritize": SessionMode.PRIORITIZE,
    "/retro":      SessionMode.RETROSPECT,
}

_MODE_ARTIFACT_NAMES: dict[SessionMode, str] = {
    SessionMode.INTAKE:            "business-case.md, epics.md, stories-draft.md",
    SessionMode.WORKING_BACKWARDS: "working-backwards.md",
    SessionMode.PREMORTEM:         "pre-mortem.md",
    SessionMode.STEELMAN:          "steelman.md",
    SessionMode.PRIORITIZE:        "priority-stack.md",
    SessionMode.RETROSPECT:        "retrospect.md",
}

# Artifact generation refused response (used when gating)
_ARTIFACT_GATE_REFUSAL_TEMPLATE = (
    "The business case isn't complete enough to generate artifacts yet. "
    "These fields still need detail: {missing}. "
    "Let's work through those before generating the spec."
)

# Help text for /help command
_HELP_TEXT = """
Priya Desai — Product Development Coach

I help Hoopla Digital's product team build rigorous specs and think more clearly.

Session modes — each resets the conversation:
  /intake      — (default) spec funnel: business-case, epics, stories
  /wb          — Working Backwards: start from the ideal end state, work backward
  /premortem   — Pre-mortem: imagine failure, surface causes, commit to mitigations
  /steelman    — Steel-man: build the strongest objection to a proposal, then respond
  /prioritize  — Prioritization: score candidates, surface dependencies, rank them
  /retro       — Retrospective: close the outcome loop on a prior spec

Session commands:
  /help        — show this message
  /status      — show completeness for the current session
  /generate    — generate artifacts (gated by completeness)
  /reset       — clear this session and start over
  /mode        — show active mode
  /recall <query>  — search past sessions for similar features or learnings

Tips:
  - Start with the problem, not the feature. Always.
  - Bring data. Quantified problems get better specs.
  - Use /wb before /intake when you want to clarify the end state first.
  - Use /premortem on anything with a non-obvious adoption or measurement risk.
  - Use /recall to surface what we learned from similar past work before starting.
  - Use /retro after shipping to close the outcome loop and feed learnings back.
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
        initial_mode: SessionMode = SessionMode.INTAKE,
        coach_memory: "CoachMemory | None" = None,
    ):
        self._backend = backend
        self._assembler = ContextAssembler(
            domain_context=domain_context,
            context_sources=context_sources,
        )
        self._tracker = ProgressTracker(mode=initial_mode)
        self._detector = SignalDetector()
        self._memory_context = memory_context
        self._memory: "CoachMemory | None" = coach_memory
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
        # Handle slash commands first — match on the command token only so
        # "/recall some query" is dispatched even though it has trailing args.
        stripped = user_message.strip()
        cmd_token = stripped.split()[0].lower() if stripped else ""
        if cmd_token in _SLASH_COMMANDS:
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
                "mode": self._tracker.mode,
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

    def reset(self, mode: SessionMode | None = None) -> None:
        """Clear conversation history and reset state.

        If mode is provided, switches to that mode. Otherwise keeps the
        current mode (useful for /reset within a mode session).
        """
        self._messages = []
        self._turn_count = 0
        new_mode = mode if mode is not None else self._tracker.mode
        self._tracker = ProgressTracker(mode=new_mode)

    @property
    def messages(self) -> list[dict]:
        return list(self._messages)

    @property
    def tracker(self) -> ProgressTracker:
        return self._tracker

    @property
    def mode(self) -> SessionMode:
        return self._tracker.mode

    @property
    def turn_count(self) -> int:
        return self._turn_count

    @property
    def coach_memory(self) -> "CoachMemory | None":
        return self._memory

    def close_session(
        self,
        session_id: str,
        artifact_content: str = "",
    ) -> None:
        """Finalize a session: run Crystallizer, persist to CoachMemory.

        Call this when a session ends (user closes tab, /reset with persist,
        or server shutdown). Idempotent — calling twice does no harm.

        Phase B additions:
        - Extracts the feature name heuristically and saves it to the feature
          index so future sessions can find analogues.
        - Saves the artifact_content (if provided) alongside the feature record.

        Args:
            session_id: Stable ID for this session (from generate_session_id()).
            artifact_content: Full text of any generated artifact to persist.
        """
        if self._memory is None or not self._messages:
            return

        from pipeline.coach.crystallizer import Crystallizer, extract_feature_name

        crystal = Crystallizer()
        result = crystal.extract(self._messages)
        self._memory.save_session(session_id, result)

        # Feature index: extract name and save
        feature_name, confidence = extract_feature_name(self._messages)
        if feature_name and confidence >= 0.6:
            # Build a short problem statement from the first user message
            problem_statement = ""
            for msg in self._messages:
                if msg.get("role") == "user":
                    content = msg.get("content", "")
                    if isinstance(content, str):
                        problem_statement = content[:300]
                    elif isinstance(content, list):
                        problem_statement = " ".join(
                            b.get("text", "") for b in content
                            if isinstance(b, dict) and b.get("type") == "text"
                        )[:300]
                    break

            self._memory.save_feature(
                session_id=session_id,
                feature_name=feature_name,
                problem_statement=problem_statement,
                mode=self._tracker.mode.value,
                artifact_content=artifact_content,
            )

    # ------------------------------------------------------------------
    # Slash command handlers
    # ------------------------------------------------------------------

    def _handle_slash(self, raw: str) -> str:
        """Dispatch a slash command. raw may include arguments after the token."""
        parts = raw.strip().split(None, 1)
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        # Mode switch commands
        if command in _MODE_SLASH_MAP:
            new_mode = _MODE_SLASH_MAP[command]
            self.reset(mode=new_mode)
            return self._mode_switch_message(new_mode)

        if command == "/help":
            return _HELP_TEXT
        elif command == "/mode":
            return f"Active mode: {self._tracker.mode.value}"
        elif command == "/status":
            return self._status_report()
        elif command == "/generate":
            return self._handle_generate()
        elif command == "/reset":
            current_mode = self._tracker.mode
            self.reset()
            return f"Session cleared. Mode: {current_mode.value}. Start fresh."
        elif command == "/recall":
            return self._handle_recall(args)
        return f"Unknown command: {command}"

    def _handle_recall(self, query: str) -> str:
        """Search CoachMemory for past features or learnings matching query.

        If no query is provided, returns the most recent 3 sessions' features.
        If memory is not configured, returns an informative message.
        """
        if self._memory is None:
            return (
                "Memory is not configured for this session. "
                "Start the coach with a memory path to enable /recall."
            )

        query = query.strip()

        if not query:
            # No query: list recent feature names as a menu
            try:
                sessions = self._memory.list_sessions(limit=5)
            except Exception:
                sessions = []
            if not sessions:
                return "No past sessions found in memory."
            lines = ["**Recent sessions:**"]
            for s in sessions:
                lines.append(f"- {s['created_at'][:10]}  {s['summary']}")
            lines.append("\nUse `/recall <feature name or topic>` to search for specific past work.")
            return "\n".join(lines)

        # FTS search over crystal items (cross-domain)
        crystal_context = self._memory.recall(query=query, top_k=5)

        # Feature analogue search
        feature_context = self._memory.recall_similar_feature(
            query=query,
            top_k=3,
        )

        if not crystal_context and not feature_context:
            return f"No past sessions found matching: **{query}**"

        parts = []
        if feature_context:
            parts.append(feature_context)
        if crystal_context:
            parts.append(crystal_context)
        return "\n\n".join(parts)

    @staticmethod
    def _mode_switch_message(mode: SessionMode) -> str:
        descriptions = {
            SessionMode.INTAKE: (
                "Switched to INTAKE mode. Describe the problem you're trying to solve."
            ),
            SessionMode.WORKING_BACKWARDS: (
                "Switched to WORKING BACKWARDS mode.\n\n"
                "Start by writing a headline: one sentence that announces this feature as if it has already shipped. "
                "Who benefits, and what does it do for them? Don't describe the feature — describe the outcome."
            ),
            SessionMode.PREMORTEM: (
                "Switched to PRE-MORTEM mode.\n\n"
                "Briefly describe the feature or initiative we're stress-testing. "
                "Then I'll ask you to imagine it failed — completely — and we'll work backward from there."
            ),
            SessionMode.STEELMAN: (
                "Switched to STEEL-MAN mode.\n\n"
                "Describe your proposal. Once I understand it, I'll construct the strongest possible case against it. "
                "Then we'll work through your response."
            ),
            SessionMode.PRIORITIZE: (
                "Switched to PRIORITIZE mode.\n\n"
                "List the candidates you're choosing between. Then we'll agree on scoring criteria "
                "and work through the ranking together."
            ),
            SessionMode.RETROSPECT: (
                "Switched to RETROSPECT mode.\n\n"
                "Which feature or initiative are we reviewing? Tell me what the original plan predicted, "
                "and I'll help you map what actually happened and why."
            ),
        }
        return descriptions.get(mode, f"Switched to {mode.value} mode.")

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

        mode = self._tracker.mode
        artifact_names = _MODE_ARTIFACT_NAMES.get(mode, "artifacts")
        system_prompt = self._assembler.build(
            progress=self._tracker,
            turn_count=self._turn_count,
            memory_context=self._memory_context,
            extra_overlay=(
                f"# GENERATE NOW\n"
                f"The user has requested artifact generation. Completeness threshold is met. "
                f"Generate: {artifact_names}. "
                f"Use the schema defined in the exercise template (or artifact schemas block for intake). "
                f"Output structured markdown only. No narrative introduction."
            ),
        )
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
