# AI-GENERATED: 2026-03-03T16:57:33Z | pipeline/coach/crystallizer.py | Copilot
"""Crystallizer — heuristic session-end learning extractor.

Extracts constraints, decisions, assumptions, and preferences from a completed
coaching conversation WITHOUT making an LLM call. This is intentional: the
Crystallizer must be fast, deterministic, and zero-cost at session end.

Extracted items are stored in CoachMemory for retrieval in future sessions.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

ItemKind = Literal["constraint", "decision", "assumption", "preference"]


@dataclass
class CrystalItem:
    """A single extracted learning from a session."""

    kind: ItemKind
    text: str
    turn_index: int = 0
    confidence: float = 1.0  # 0.0–1.0; heuristic-derived


@dataclass
class CrystalResult:
    """All items extracted from one session."""

    items: list[CrystalItem] = field(default_factory=list)
    session_summary: str = ""

    def by_kind(self, kind: ItemKind) -> list[CrystalItem]:
        return [i for i in self.items if i.kind == kind]


# ---------------------------------------------------------------------------
# Pattern banks
# ---------------------------------------------------------------------------

_CONSTRAINT_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(must not|cannot|can't|won't|will not|prohibited|forbidden|never)\b", re.I),
    re.compile(r"\b(hard (limit|cap|deadline|requirement))\b", re.I),
    re.compile(r"\b(WCAG|COPPA|GDPR|DRM|contractually required)\b", re.I),
    re.compile(r"\b(budget (cap|ceiling|limit))\b", re.I),
    re.compile(r"\b(no more than|at most|maximum of)\s+\d+", re.I),
]

_DECISION_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(we('ve| have) decided|decision is|we('re| are) going with|we chose|chosen)\b", re.I),
    re.compile(r"\b(final(ly| answer| decision)?[:\s]+)\b", re.I),
    re.compile(r"\b(approved|signed off|agreed|confirmed)\b", re.I),
    re.compile(r"\b(will (use|implement|build|deploy|launch))\b", re.I),
]

_ASSUMPTION_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(assum(e|ing|ption)|presuppos|suppose|hypothes(is|ize))\b", re.I),
    re.compile(r"\b(ASSUMPTION:|ASSUMED:)\s*", re.I),
    re.compile(r"\b(we expect|we believe|we think|likely|probably|presumably)\b", re.I),
    re.compile(r"\b(pending (confirmation|data|approval|research))\b", re.I),
]

_PREFERENCE_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(prefer(ably|red)?|would rather|ideally|our preference)\b", re.I),
    re.compile(r"\b(nice to have|wishlist|desired|want(ed)? (to|a))\b", re.I),
    re.compile(r"\b(lean(ing)? toward(s)?|favor(ing)?)\b", re.I),
]

# Map pattern list → kind.
# Order matters: preference is checked before constraint so that sentences
# like "we'd prefer to avoid X" are classified as preference, not constraint.
_PATTERN_MAP: list[tuple[list[re.Pattern], ItemKind]] = [
    (_PREFERENCE_PATTERNS, "preference"),
    (_CONSTRAINT_PATTERNS, "constraint"),
    (_DECISION_PATTERNS, "decision"),
    (_ASSUMPTION_PATTERNS, "assumption"),
]


# ---------------------------------------------------------------------------
# Crystallizer
# ---------------------------------------------------------------------------

class Crystallizer:
    """Extract structured learnings from a completed coaching session.

    This is a pure heuristic extractor — no LLM calls. It scans the
    conversation history for signals that indicate constraints, decisions,
    assumptions, or preferences, and returns them as CrystalItem objects.

    Usage:
        crystallizer = Crystallizer()
        result = crystallizer.extract(messages)
        for item in result.items:
            print(item.kind, item.text)
    """

    def __init__(self, min_sentence_len: int = 10, max_items: int = 50):
        """
        Args:
            min_sentence_len: Minimum character length for a sentence to be
                              considered (filters noise).
            max_items: Maximum number of items to extract per session.
        """
        self._min_len = min_sentence_len
        self._max_items = max_items

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract(self, messages: list[dict]) -> CrystalResult:
        """Extract CrystalItems from a list of conversation message dicts.

        Only examines user-role messages (user inputs carry the product
        stakeholder's stated constraints, decisions, etc.).

        Args:
            messages: List of {"role": str, "content": str|list} dicts
                      in CoachEngine format.

        Returns:
            CrystalResult with all extracted items and a session summary.
        """
        result = CrystalResult()
        seen_texts: set[str] = set()

        for turn_index, msg in enumerate(messages):
            if msg.get("role") != "user":
                continue

            text = self._extract_text(msg)
            sentences = self._split_sentences(text)

            for sentence in sentences:
                if len(sentence) < self._min_len:
                    continue
                kind = self._classify(sentence)
                if kind is None:
                    continue
                # Dedup by normalized text
                norm = sentence.lower().strip()
                if norm in seen_texts:
                    continue
                seen_texts.add(norm)

                result.items.append(
                    CrystalItem(
                        kind=kind,
                        text=sentence.strip(),
                        turn_index=turn_index,
                        confidence=self._score_confidence(sentence, kind),
                    )
                )
                if len(result.items) >= self._max_items:
                    break

            if len(result.items) >= self._max_items:
                break

        result.session_summary = self._build_summary(result)
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_text(msg: dict) -> str:
        content = msg.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return " ".join(
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            )
        return ""

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        """Split text into sentence-like chunks."""
        # Split on sentence-ending punctuation, newlines, and bullet markers
        raw = re.split(r"(?<=[.!?])\s+|[\n\r]+|(?<=\w)\s*[-–—]\s*(?=\w)", text)
        return [s.strip() for s in raw if s.strip()]

    @staticmethod
    def _classify(sentence: str) -> ItemKind | None:
        """Return the kind of learning detected, or None if no match."""
        for patterns, kind in _PATTERN_MAP:
            for pattern in patterns:
                if pattern.search(sentence):
                    return kind
        return None

    @staticmethod
    def _score_confidence(sentence: str, kind: ItemKind) -> float:
        """Rough confidence based on specificity signals."""
        score = 0.7  # baseline
        # Numbers/percentages add specificity
        if re.search(r"\d+", sentence):
            score += 0.1
        # Explicit markers add confidence
        explicit_markers = ["CONSTRAINT:", "DECISION:", "ASSUMPTION:", "PREFERENCE:"]
        if any(m.lower() in sentence.lower() for m in explicit_markers):
            score += 0.15
        # Short sentences are less reliable
        if len(sentence) < 30:
            score -= 0.1
        return min(1.0, max(0.0, score))

    @staticmethod
    def _build_summary(result: CrystalResult) -> str:
        """Build a short plain-text summary of extracted items."""
        if not result.items:
            return "No structured learnings extracted from this session."
        counts = {}
        for item in result.items:
            counts[item.kind] = counts.get(item.kind, 0) + 1
        parts = [f"{v} {k}(s)" for k, v in sorted(counts.items())]
        return "Session learnings: " + ", ".join(parts) + f" ({len(result.items)} total)."
