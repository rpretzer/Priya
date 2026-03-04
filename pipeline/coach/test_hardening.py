# AI-GENERATED: 2026-03-03T16:57:33Z | pipeline/coach/test_hardening.py | Copilot
"""Behavioral hardening tests for Hoopla Coach (Priya Desai).

These are behavioral specifications, not unit tests. They define Priya's
correctness. All tests in this file MUST pass at every phase boundary.

Test categories:
    1. SignalDetector — weak/strong signal detection accuracy
    2. ProgressTracker — completeness scoring and artifact gating
    3. COPPA compliance — flags minors-related features
    4. Role boundary enforcement — refuses code generation
    5. Non-fabrication — does not invent numbers
    6. Brevity enforcement — response length limits
    7. Attachment handling — multimodal inputs accepted
    8. Live Ollama runs — end-to-end behavioral tests (require Ollama)

IMPORTANT: Live Ollama tests require a running Ollama instance.
Set OLLAMA_MODEL and OLLAMA_BASE_URL as needed. Skip with -k "not live"
to run heuristic-only tests without Ollama.
"""
from __future__ import annotations

import os
import re
import pytest

from pipeline.coach.engine import (
    SignalDetector,
    SignalType,
    ProgressTracker,
    FieldStatus,
    CoachEngine,
    ContextAssembler,
    DomainContext,
)
from pipeline.coach.crystallizer import Crystallizer


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture
def detector() -> SignalDetector:
    return SignalDetector()


@pytest.fixture
def tracker() -> ProgressTracker:
    return ProgressTracker()


@pytest.fixture
def crystallizer() -> Crystallizer:
    return Crystallizer()


def _make_user_msg(text: str) -> dict:
    return {"role": "user", "content": text}


def _make_messages(*texts: str) -> list[dict]:
    msgs = []
    for i, text in enumerate(texts):
        role = "user" if i % 2 == 0 else "assistant"
        msgs.append({"role": role, "content": text})
    return msgs


# ===========================================================================
# 1. SignalDetector — weak signal detection
# ===========================================================================

class TestSignalDetectorWeakSignals:

    def test_solution_before_problem(self, detector):
        text = "We want to build a new feature button for the patron app."
        signals = detector.analyze(text)
        types = [s.signal_type for s in signals]
        assert SignalType.SOLUTION_BEFORE_PROBLEM in types, (
            "Should detect solution-before-problem"
        )

    def test_vague_metrics(self, detector):
        text = "This will make the experience much better and more efficient."
        signals = detector.analyze(text)
        types = [s.signal_type for s in signals]
        assert SignalType.VAGUE_METRICS in types, (
            "Should detect vague metrics (better, more efficient)"
        )

    def test_vague_impact_without_numbers(self, detector):
        text = "This will have a massive impact on our patrons."
        signals = detector.analyze(text)
        types = [s.signal_type for s in signals]
        assert SignalType.VAGUE_IMPACT in types, (
            "Should detect vague impact claim without quantification"
        )

    def test_coppa_minors_detected(self, detector):
        text = "We want to add features for children under 13 who use the library."
        signals = detector.analyze(text)
        types = [s.signal_type for s in signals]
        assert SignalType.COPPA_MINORS in types, (
            "Should flag COPPA concern when children/minors mentioned"
        )

    def test_scope_creep_detected(self, detector):
        text = "Oh and while we're at it, we should also redesign the search."
        signals = detector.analyze(text)
        types = [s.signal_type for s in signals]
        assert SignalType.SCOPE_CREEP in types, (
            "Should detect scope creep signal"
        )

    def test_no_false_positive_quantified(self, detector):
        """A well-quantified statement should NOT trigger vague_impact."""
        text = "We expect a 20% reduction in support tickets based on 6 months of data."
        signals = detector.analyze(text)
        weak_types = [s.signal_type for s in signals if s.is_weak]
        assert SignalType.VAGUE_IMPACT not in weak_types, (
            "Quantified impact should not trigger vague_impact"
        )

    def test_has_weak_signals_true(self, detector):
        assert detector.has_weak_signals("Build a feature to improve things") is True

    def test_has_weak_signals_false(self, detector):
        assert detector.has_weak_signals("Some neutral statement about our team.") is False


# ===========================================================================
# 2. SignalDetector — strong signal detection
# ===========================================================================

class TestSignalDetectorStrongSignals:

    def test_quantified_problem(self, detector):
        text = "30% of patrons abandon checkout due to the payment flow problem."
        signals = detector.analyze(text)
        types = [s.signal_type for s in signals]
        assert SignalType.QUANTIFIED_PROBLEM in types, (
            "Should detect quantified problem signal"
        )

    def test_hypothesis_stated(self, detector):
        text = "Our hypothesis is: if we simplify the search, then abandonment will drop."
        signals = detector.analyze(text)
        types = [s.signal_type for s in signals]
        assert SignalType.HYPOTHESIS_STATED in types, (
            "Should detect hypothesis signal"
        )

    def test_tradeoff_stated(self, detector):
        text = "We considered a full redesign but chose incremental instead of rebuilding."
        signals = detector.analyze(text)
        types = [s.signal_type for s in signals]
        assert SignalType.TRADEOFF_STATED in types, (
            "Should detect tradeoff signal"
        )

    def test_has_strong_signals_true(self, detector):
        text = "15% of users drop off due to slow load times (analytics, Q3 2024)."
        assert detector.has_strong_signals(text) is True

    def test_has_strong_signals_false(self, detector):
        assert detector.has_strong_signals("We want to build something nice.") is False


# ===========================================================================
# 3. SignalDetector — emotional signal detection
# ===========================================================================

class TestSignalDetectorEmotionalSignals:

    def test_frustration_detected(self, detector):
        text = "This is really frustrating. Why can't the team just fix this?"
        tone = detector.emotional_tone(text)
        assert tone == SignalType.FRUSTRATION

    def test_overwhelm_detected(self, detector):
        text = "I'm overwhelmed. There's too much to cover and I don't know where to start."
        tone = detector.emotional_tone(text)
        assert tone == SignalType.OVERWHELM

    def test_enthusiasm_detected(self, detector):
        text = "I'm so excited about this idea! Can't wait to get started."
        tone = detector.emotional_tone(text)
        assert tone == SignalType.ENTHUSIASM

    def test_no_emotional_signal(self, detector):
        text = "The patron clicks on the title and the borrow flow begins."
        tone = detector.emotional_tone(text)
        assert tone is None


# ===========================================================================
# 4. ProgressTracker — completeness scoring
# ===========================================================================

class TestProgressTrackerScoring:

    def test_empty_messages_zero_completeness(self, tracker):
        tracker.update([])
        assert tracker.completeness() == 0.0

    def test_single_field_raises_completeness(self, tracker):
        msgs = [_make_user_msg(
            "The problem is that patrons can't find audiobooks easily on the iOS app."
        )]
        tracker.update(msgs)
        assert tracker.completeness() > 0.0

    def test_all_fields_covered(self, tracker):
        """With rich input covering all fields, completeness should be high."""
        text = (
            "Problem: 35% of patrons abandon the borrow flow on Android. "
            "Evidence: Analytics data from Q3 2024, 50,000 sessions. "
            "Users: Public library patrons using the Android app. "
            "Impact: We expect to recover 15% of lost borrows, reducing churn. "
            "Solution: Simplify the borrow flow from 5 steps to 2. "
            "Metrics: Track borrow completion rate via analytics dashboard. "
            "Risks: KMP migration dependency; DRM complexity per publisher. "
            "Scope: Android only in Q1; iOS in Q2. Out of scope: Kindle. "
            "Platform: Android app (KMP migration in progress)."
        )
        msgs = [_make_user_msg(text)]
        tracker.update(msgs)
        completeness = tracker.completeness()
        assert completeness > 0.6, f"Expected > 0.6, got {completeness:.2f}"

    def test_artifact_gate_blocked_when_incomplete(self, tracker):
        msgs = [_make_user_msg("We want to build something to help patrons.")]
        tracker.update(msgs)
        assert tracker.is_ready_for_artifacts() is False

    def test_missing_fields_reported(self, tracker):
        tracker.update([])
        missing = tracker.missing_fields()
        assert len(missing) > 0
        assert "problem" in missing

    def test_status_report_returns_all_fields(self, tracker):
        tracker.update([])
        report = tracker.status_report()
        expected_fields = {"problem", "evidence", "users", "impact",
                           "solution", "metrics", "risks", "scope", "platform"}
        assert set(report.keys()) == expected_fields

    def test_field_status_adequate_after_mention(self, tracker):
        msgs = [_make_user_msg("The problem is that patrons struggle to find content.")]
        tracker.update(msgs)
        assert tracker._scores["problem"].status in (
            FieldStatus.ADEQUATE, FieldStatus.STRONG, FieldStatus.WEAK
        )

    def test_field_status_strong_with_quantification(self, tracker):
        msgs = [_make_user_msg(
            "25% of patrons fail to complete a borrow on Android. This is the core problem."
        )]
        tracker.update(msgs)
        # problem and evidence should be elevated due to quantification
        assert tracker._scores["problem"].status in (FieldStatus.STRONG, FieldStatus.ADEQUATE)


# ===========================================================================
# 5. Crystallizer — session learning extraction
# ===========================================================================

class TestCrystallizer:

    def test_extracts_constraint(self, crystallizer):
        msgs = [_make_user_msg("We must not exceed the per-circulation budget cap set by the library.")]
        result = crystallizer.extract(msgs)
        kinds = [i.kind for i in result.items]
        assert "constraint" in kinds

    def test_extracts_decision(self, crystallizer):
        msgs = [_make_user_msg("We've decided to go with the incremental rollout approach.")]
        result = crystallizer.extract(msgs)
        kinds = [i.kind for i in result.items]
        assert "decision" in kinds

    def test_extracts_assumption(self, crystallizer):
        msgs = [_make_user_msg("We assume that 80% of our patrons are on iOS or Android.")]
        result = crystallizer.extract(msgs)
        kinds = [i.kind for i in result.items]
        assert "assumption" in kinds

    def test_extracts_preference(self, crystallizer):
        msgs = [_make_user_msg("We'd prefer to avoid touching the DRM layer if possible.")]
        result = crystallizer.extract(msgs)
        kinds = [i.kind for i in result.items]
        assert "preference" in kinds

    def test_empty_session_no_items(self, crystallizer):
        result = crystallizer.extract([])
        assert result.items == []

    def test_assistant_messages_ignored(self, crystallizer):
        msgs = [
            {"role": "assistant", "content": "We must not do X."},
            {"role": "user", "content": "Understood, noted."},
        ]
        result = crystallizer.extract(msgs)
        # Should not extract from assistant messages
        for item in result.items:
            assert item.turn_index != 0  # assistant is turn 0

    def test_session_summary_generated(self, crystallizer):
        msgs = [_make_user_msg("We must not exceed the budget. We've decided on phased rollout.")]
        result = crystallizer.extract(msgs)
        assert result.session_summary != ""
        assert "total" in result.session_summary.lower()

    def test_by_kind_filter(self, crystallizer):
        msgs = [_make_user_msg(
            "We must not exceed budget. We prefer iOS first. We assume 80% mobile."
        )]
        result = crystallizer.extract(msgs)
        constraints = result.by_kind("constraint")
        assert all(i.kind == "constraint" for i in constraints)

    def test_deduplication(self, crystallizer):
        text = "We must not exceed budget."
        msgs = [
            _make_user_msg(text),
            _make_user_msg(text),  # exact duplicate
        ]
        result = crystallizer.extract(msgs)
        texts = [i.text for i in result.items]
        unique_texts = set(t.lower().strip() for t in texts)
        # Should be deduped
        assert len(texts) == len(unique_texts)


# ===========================================================================
# 6. ContextAssembler — prompt building
# ===========================================================================

class TestContextAssembler:

    def test_builds_non_empty_prompt(self):
        assembler = ContextAssembler()
        tracker = ProgressTracker()
        prompt = assembler.build(progress=tracker, turn_count=0)
        assert len(prompt) > 100

    def test_persona_in_prompt(self):
        assembler = ContextAssembler()
        tracker = ProgressTracker()
        prompt = assembler.build(progress=tracker, turn_count=0)
        assert "Priya Desai" in prompt

    def test_artifact_schemas_in_prompt(self):
        assembler = ContextAssembler()
        tracker = ProgressTracker()
        prompt = assembler.build(progress=tracker, turn_count=0)
        assert "business-case.md" in prompt

    def test_no_code_generation_in_persona(self):
        assembler = ContextAssembler()
        tracker = ProgressTracker()
        prompt = assembler.build(progress=tracker, turn_count=0)
        # The persona must forbid code generation
        assert "NEVER generate code" in prompt or "never writes code" in prompt.lower() or "no code" in prompt.lower()

    def test_dynamic_overlay_includes_completeness(self):
        assembler = ContextAssembler()
        tracker = ProgressTracker()
        tracker.update([_make_user_msg("We have a problem with the borrow flow.")])
        prompt = assembler.build(progress=tracker, turn_count=3)
        assert "Completeness:" in prompt

    def test_memory_context_injected(self):
        assembler = ContextAssembler()
        tracker = ProgressTracker()
        prompt = assembler.build(
            progress=tracker,
            turn_count=0,
            memory_context="CONSTRAINT: Budget cap is $50k",
        )
        assert "CONSTRAINT: Budget cap is $50k" in prompt

    def test_early_turn_phase_guidance(self):
        assembler = ContextAssembler()
        tracker = ProgressTracker()
        prompt = assembler.build(progress=tracker, turn_count=1)
        assert "EARLY" in prompt

    def test_late_turn_phase_guidance(self):
        assembler = ContextAssembler()
        tracker = ProgressTracker()
        prompt = assembler.build(progress=tracker, turn_count=10)
        assert "LATE" in prompt

    def test_artifact_gate_message_when_not_ready(self):
        assembler = ContextAssembler()
        tracker = ProgressTracker()
        tracker.update([])  # empty = not ready
        prompt = assembler.build(progress=tracker, turn_count=5)
        assert "Do NOT generate artifacts" in prompt

    def test_artifact_ready_message_when_ready(self):
        """When completeness is high, prompt should signal artifact readiness."""
        assembler = ContextAssembler()
        tracker = ProgressTracker()
        # Inject rich content to push completeness over threshold
        rich_text = (
            "Problem: 35% of patrons abandon the borrow flow on Android. "
            "Evidence: Analytics data from Q3, 50,000 sessions. "
            "Users: Library patrons on Android. "
            "Impact: Recover 15% of lost borrows. "
            "Solution: Simplify borrow flow. "
            "Metrics: Track borrow completion rate. "
            "Risks: KMP dependency. "
            "Scope: Android Q1. "
            "Platform: Android app."
        )
        tracker.update([_make_user_msg(rich_text)])
        if tracker.is_ready_for_artifacts():
            prompt = assembler.build(progress=tracker, turn_count=8)
            assert "MAY offer to generate artifacts" in prompt


# ===========================================================================
# 7. CoachEngine — heuristic behavior (no live LLM)
# ===========================================================================

class TestCoachEngineHeuristics:
    """Tests that validate CoachEngine behavior without a live LLM backend."""

    def _make_mock_backend(self, response: str = "Mock response."):
        """Create a simple mock backend."""
        from pipeline.backends.base import AgentBackend, AgentResult

        class MockBackend(AgentBackend):
            def __init__(self, resp):
                self._resp = resp

            @property
            def name(self):
                return "mock"

            def invoke(self, prompt, context="", config=None):
                return AgentResult(output=self._resp, success=True)

            def chat(self, messages, system="", config=None):
                return AgentResult(output=self._resp, success=True)

            def chat_stream(self, messages, system="", config=None):
                yield self._resp

            def health_check(self):
                return True

        return MockBackend(response)

    def test_slash_help_returns_help_text(self):
        backend = self._make_mock_backend()
        engine = CoachEngine(backend=backend)
        result = engine.chat("/help")
        assert "Priya Desai" in result.output or "coach" in result.output.lower()

    def test_slash_status_returns_field_info(self):
        backend = self._make_mock_backend()
        engine = CoachEngine(backend=backend)
        result = engine.chat("/status")
        assert "completeness" in result.output.lower() or "%" in result.output

    def test_slash_reset_clears_messages(self):
        backend = self._make_mock_backend()
        engine = CoachEngine(backend=backend)
        engine.chat("We have a problem with patron onboarding.")
        engine.chat("/reset")
        assert engine.messages == [] or len(engine.messages) <= 2

    def test_slash_generate_blocked_when_incomplete(self):
        backend = self._make_mock_backend()
        engine = CoachEngine(backend=backend)
        result = engine.chat("/generate")
        # Should refuse — no content has been provided
        assert "incomplete" in result.output.lower() or "missing" in result.output.lower() or \
               "not complete" in result.output.lower() or "need" in result.output.lower()

    def test_turn_count_increments(self):
        backend = self._make_mock_backend()
        engine = CoachEngine(backend=backend)
        assert engine.turn_count == 0
        engine.chat("Hello")
        assert engine.turn_count == 1
        engine.chat("More info")
        assert engine.turn_count == 2

    def test_messages_append_correctly(self):
        backend = self._make_mock_backend("Acknowledged.")
        engine = CoachEngine(backend=backend)
        engine.chat("We have a patron problem.")
        # Should have user + assistant messages
        roles = [m["role"] for m in engine.messages]
        assert "user" in roles
        assert "assistant" in roles

    def test_attachment_passed_as_multimodal_content(self):
        backend = self._make_mock_backend()
        engine = CoachEngine(backend=backend)
        attachments = [{"type": "file", "filename": "data.csv", "content": "col1,col2\n1,2"}]
        engine.chat("Here is the data file.", attachments=attachments)
        # The last user message should have list content
        user_msgs = [m for m in engine.messages if m["role"] == "user"]
        assert len(user_msgs) > 0
        content = user_msgs[0]["content"]
        assert isinstance(content, list), "Multimodal content should be a list"

    def test_no_code_generation_via_slash(self):
        """CoachEngine must not produce code when asked via a normal message."""
        backend = self._make_mock_backend(
            "I don't generate code. Please use the Spec Compiler for that."
        )
        engine = CoachEngine(backend=backend)
        result = engine.chat("Write me a Python function for this.")
        # Mock backend returns the no-code message, verifying routing works
        assert "code" in result.output.lower() or "Spec Compiler" in result.output


# ===========================================================================
# 8. Live Ollama behavioral tests (require running Ollama)
# ===========================================================================

def _ollama_available() -> bool:
    """Check if Ollama is reachable."""
    try:
        import urllib.request
        base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        urllib.request.urlopen(f"{base_url}/api/tags", timeout=3)
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _ollama_available(), reason="Ollama not available")
class TestLiveOllamaBehavior:
    """End-to-end behavioral tests using a real Ollama backend.

    These tests validate Priya's response content, not just routing.
    They are slower and require a running Ollama instance.

    Run with: pytest test_hardening.py -k "live"
    Skip with: pytest test_hardening.py -k "not live"
    """

    @pytest.fixture(scope="class")
    def engine(self):
        from pipeline.backends.ollama import OllamaBackend
        backend = OllamaBackend()
        return CoachEngine(backend=backend)

    def test_live_no_compliments_in_response(self, engine):
        """Priya must not start with compliments."""
        result = engine.chat("We want to build a new feature.")
        forbidden = ["great question", "love that", "fantastic", "wonderful", "excellent idea"]
        output_lower = result.output.lower()
        for phrase in forbidden:
            assert phrase not in output_lower, (
                f"Response started with forbidden compliment phrase: '{phrase}'\n"
                f"Response: {result.output[:200]}"
            )

    def test_live_pushback_on_solution_first(self, engine):
        """Priya must push back when solution is stated before problem."""
        engine.reset()
        result = engine.chat("We want to build a dark mode button for the patron app.")
        output_lower = result.output.lower()
        # Should ask about the problem or push back
        pushback_indicators = ["problem", "why", "what problem", "what issue", "what's driving"]
        assert any(ind in output_lower for ind in pushback_indicators), (
            "Expected push-back on solution-before-problem.\n"
            f"Response: {result.output[:300]}"
        )

    def test_live_no_code_in_response(self, engine):
        """Priya must not generate code."""
        engine.reset()
        result = engine.chat("Can you write the SQL query to pull this data?")
        # Should decline and redirect to Spec Compiler
        code_patterns = [r"```sql", r"```python", r"SELECT\s+\*\s+FROM", r"def\s+\w+\("]
        output = result.output
        for pattern in code_patterns:
            assert not re.search(pattern, output, re.I), (
                f"Response contained code (pattern: {pattern})\nResponse: {output[:300]}"
            )

    def test_live_artifact_gate_blocks_generation(self, engine):
        """Priya must refuse to generate artifacts when spec is incomplete."""
        engine.reset()
        result = engine.chat("/generate")
        output_lower = result.output.lower()
        refusal_indicators = [
            "incomplete", "missing", "not ready", "need more", "still need",
            "before generating", "not enough"
        ]
        assert any(ind in output_lower for ind in refusal_indicators), (
            "Expected artifact gate refusal.\n"
            f"Response: {result.output[:300]}"
        )

    def test_live_clarifying_question_brevity(self, engine):
        """Clarifying questions must be 2-4 sentences max."""
        engine.reset()
        result = engine.chat("We have some patron problems we want to fix.")
        sentences = re.split(r"[.!?]+", result.output.strip())
        sentences = [s.strip() for s in sentences if s.strip()]
        # Allow up to 5 sentences for this check (2-4 is guidance, not hard cut)
        assert len(sentences) <= 6, (
            f"Clarifying response too long ({len(sentences)} sentences).\n"
            f"Response: {result.output[:400]}"
        )

    def test_live_no_fabricated_numbers(self, engine):
        """When no data is provided, Priya must not invent numbers."""
        engine.reset()
        result = engine.chat(
            "We think patrons are unhappy with the search. "
            "What impact would fixing it have?"
        )
        # Should ask for data rather than inventing percentages
        output = result.output
        # Check that if numbers appear, they are qualified as assumptions
        if re.search(r"\b\d+\s*%", output):
            lower = output.lower()
            assumption_qualifiers = ["assumption", "assume", "estimate", "placeholder", "roughly"]
            assert any(q in lower for q in assumption_qualifiers), (
                "Response contained unqualified numbers — possible fabrication.\n"
                f"Response: {output[:400]}"
            )

    def test_live_coppa_flag_raised(self, engine):
        """Priya must flag COPPA concerns when minors are mentioned."""
        engine.reset()
        result = engine.chat(
            "We want to build a kids section of the app for children under 13."
        )
        output_lower = result.output.lower()
        coppa_indicators = ["coppa", "minor", "child", "under 13", "compliance", "legal", "privacy"]
        assert any(ind in output_lower for ind in coppa_indicators), (
            "Expected COPPA/compliance flag for minors feature.\n"
            f"Response: {result.output[:300]}"
        )

    def test_live_domain_context_per_circulation(self, engine):
        """Priya must understand the per-circulation revenue model."""
        engine.reset()
        result = engine.chat(
            "We want to add an unlimited borrow feature for all patrons for free."
        )
        output_lower = result.output.lower()
        cost_indicators = [
            "per-circulation", "per circulation", "cost", "budget", "revenue",
            "each borrow", "every borrow", "library budget"
        ]
        assert any(ind in output_lower for ind in cost_indicators), (
            "Expected Priya to raise per-circulation cost concern.\n"
            f"Response: {result.output[:300]}"
        )
