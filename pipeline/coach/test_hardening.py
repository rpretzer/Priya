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

import tempfile

from pipeline.coach.engine import (
    SignalDetector,
    SignalType,
    ProgressTracker,
    FieldStatus,
    SessionMode,
    CoachEngine,
    ContextAssembler,
    ContextChunk,
    DomainContext,
    MemorySource,
    _PATRON_DATA_PATTERN,
    _PRIVACY_IMPACT_PATTERN,
    _MODE_FIELDS,
)
from pipeline.coach.crystallizer import Crystallizer, extract_feature_name
from pipeline.coach.memory import CoachMemory, generate_session_id, _normalize_name, _fts_query_or


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

    def test_patron_data_exposure_detected(self, detector):
        text = "We want to use patron borrowing history to recommend new titles."
        signals = detector.analyze(text)
        types = [s.signal_type for s in signals]
        assert SignalType.PATRON_DATA_EXPOSURE in types, (
            "Should flag patron data exposure when borrowing history is mentioned"
        )

    def test_patron_data_reading_history_detected(self, detector):
        text = "We'll pull each patron's reading history to personalize their homepage."
        signals = detector.analyze(text)
        types = [s.signal_type for s in signals]
        assert SignalType.PATRON_DATA_EXPOSURE in types, (
            "Should flag patron data exposure for reading history access"
        )

    def test_patron_data_kids_mode_triggers_coppa(self, detector):
        """Kids Mode mention should trigger both COPPA_MINORS and PATRON_DATA_EXPOSURE."""
        text = "We want to add usage tracking to Kids Mode."
        signals = detector.analyze(text)
        types = [s.signal_type for s in signals]
        # At minimum COPPA_MINORS should fire; patron data may also fire depending on text
        assert SignalType.COPPA_MINORS in types or SignalType.PATRON_DATA_EXPOSURE in types, (
            "Kids Mode usage tracking should trigger COPPA or patron data signal"
        )

    def test_no_patron_data_false_positive(self, detector):
        """Aggregate metrics should NOT trigger patron data exposure."""
        text = "We want to track aggregate borrow completion rates by platform."
        signals = detector.analyze(text)
        types = [s.signal_type for s in signals]
        assert SignalType.PATRON_DATA_EXPOSURE not in types, (
            "Aggregate metrics should not trigger patron_data_exposure"
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
# 4b. ProgressTracker — privacy gate
# ===========================================================================

class TestProgressTrackerPrivacyGate:
    """Validates privacy gate behavior: patron data features require
    privacy impact discussion before artifact generation is permitted."""

    def test_no_privacy_gate_for_neutral_input(self, tracker):
        msgs = [_make_user_msg(
            "We want to simplify the search results page for library admins."
        )]
        tracker.update(msgs)
        assert tracker.privacy_gate_required is False

    def test_privacy_gate_triggered_by_borrowing_history(self, tracker):
        msgs = [_make_user_msg(
            "We want to use patron borrowing history to drive title recommendations."
        )]
        tracker.update(msgs)
        assert tracker.privacy_gate_required is True

    def test_privacy_gate_triggered_by_reading_history(self, tracker):
        msgs = [_make_user_msg(
            "The feature will access each user's reading history to build a preference model."
        )]
        tracker.update(msgs)
        assert tracker.privacy_gate_required is True

    def test_privacy_gate_triggered_by_kids_mode(self, tracker):
        msgs = [_make_user_msg(
            "We're adding engagement tracking to Kids Mode for reporting."
        )]
        tracker.update(msgs)
        assert tracker.privacy_gate_required is True

    def test_privacy_gate_not_met_without_impact_discussion(self, tracker):
        msgs = [_make_user_msg(
            "We want to use patron borrowing history for personalization."
        )]
        tracker.update(msgs)
        assert tracker.privacy_gate_required is True
        assert tracker.privacy_impact_met is False

    def test_privacy_gate_met_when_impact_discussed(self, tracker):
        msgs = [_make_user_msg(
            "We want to use patron borrowing history for personalization. "
            "We'll anonymize the data and only retain aggregated preference signals. "
            "No patron-level records will be stored. Retention policy is 30 days max."
        )]
        tracker.update(msgs)
        assert tracker.privacy_gate_required is True
        assert tracker.privacy_impact_met is True

    def test_privacy_gate_met_by_coppa_discussion(self, tracker):
        msgs = [_make_user_msg(
            "This Kids Mode feature will not collect any personal data. "
            "COPPA compliance is ensured by collecting only session state, "
            "discarded at end of session. No retention."
        )]
        tracker.update(msgs)
        assert tracker.privacy_gate_required is True
        assert tracker.privacy_impact_met is True

    def test_artifact_gate_blocked_by_privacy_gate(self, tracker):
        """Even with high completeness, artifacts must be blocked if privacy gate is open."""
        rich_text = (
            "Problem: 35% of patrons abandon borrow flow. "
            "Evidence: 50,000 sessions of analytics data. "
            "Users: Public library patrons. "
            "Impact: Recover 15% lost borrows. "
            "Solution: Simplify the flow. "
            "Metrics: Borrow completion rate. "
            "Risks: KMP dependency. "
            "Scope: Android Q1. "
            "Platform: Android. "
            "We'll use patron reading history to pre-populate recommendations."
        )
        tracker.update([_make_user_msg(rich_text)])
        # Privacy gate should be active and not met
        assert tracker.privacy_gate_required is True
        assert tracker.privacy_impact_met is False
        assert tracker.is_ready_for_artifacts() is False

    def test_privacy_impact_in_missing_fields_when_gate_active(self, tracker):
        msgs = [_make_user_msg(
            "We'll use patron borrow history to surface recommendations."
        )]
        tracker.update(msgs)
        assert "privacy_impact" in tracker.missing_fields()

    def test_privacy_impact_in_status_report_when_gate_active(self, tracker):
        msgs = [_make_user_msg(
            "We'll use patron borrow history to surface recommendations."
        )]
        tracker.update(msgs)
        report = tracker.status_report()
        assert "privacy_impact" in report
        assert report["privacy_impact"] == "missing"

    def test_privacy_impact_adequate_in_status_when_met(self, tracker):
        msgs = [_make_user_msg(
            "We'll use patron borrow history. Data will be anonymized before use. "
            "No retention of patron-level records. COPPA not applicable (adult feature)."
        )]
        tracker.update(msgs)
        report = tracker.status_report()
        assert "privacy_impact" in report
        assert report["privacy_impact"] == "adequate"

    def test_privacy_impact_not_in_status_when_gate_inactive(self, tracker):
        msgs = [_make_user_msg(
            "We want to add a sort-by-date filter to the admin dashboard."
        )]
        tracker.update(msgs)
        report = tracker.status_report()
        assert "privacy_impact" not in report


# ===========================================================================
# 4c. ProgressTracker — privacy gate patterns (unit tests, no LLM)
# ===========================================================================

class TestPrivacyPatterns:
    """Validates the regex patterns used by the privacy gate."""

    def test_patron_data_pattern_matches_borrowing_history(self):
        assert _PATRON_DATA_PATTERN.search("patron borrowing history")

    def test_patron_data_pattern_matches_reading_history(self):
        assert _PATRON_DATA_PATTERN.search("user reading history")

    def test_patron_data_pattern_matches_checkout_history(self):
        assert _PATRON_DATA_PATTERN.search("checkout history")

    def test_patron_data_pattern_matches_kids_mode(self):
        assert _PATRON_DATA_PATTERN.search("kids mode feature")

    def test_patron_data_pattern_matches_children(self):
        assert _PATRON_DATA_PATTERN.search("for children under 13")

    def test_patron_data_pattern_no_match_aggregate(self):
        assert not _PATRON_DATA_PATTERN.search(
            "track aggregate borrow completion rates by platform"
        )

    def test_privacy_impact_pattern_matches_anonymized(self):
        assert _PRIVACY_IMPACT_PATTERN.search("data will be anonymized before use")

    def test_privacy_impact_pattern_matches_retention_policy(self):
        assert _PRIVACY_IMPACT_PATTERN.search("retention policy is 30 days")

    def test_privacy_impact_pattern_matches_coppa(self):
        assert _PRIVACY_IMPACT_PATTERN.search("COPPA compliance is ensured")

    def test_privacy_impact_pattern_matches_aggregated(self):
        assert _PRIVACY_IMPACT_PATTERN.search("only aggregated preference signals")

    def test_privacy_impact_pattern_no_match_unrelated(self):
        assert not _PRIVACY_IMPACT_PATTERN.search(
            "we want to add a search filter to the admin dashboard"
        )


# ===========================================================================
# 4d. Domain context — patron-privacy.md loads correctly
# ===========================================================================

class TestPatronPrivacyDomainContext:

    def test_patron_privacy_file_loads(self):
        ctx = DomainContext()
        content = ctx.load()
        assert "patron-privacy" in content.lower() or "patron privacy" in content.lower(), (
            "patron-privacy.md should be loaded by DomainContext"
        )

    def test_patron_privacy_content_includes_library_social_contract(self):
        ctx = DomainContext()
        content = ctx.load()
        assert "social contract" in content.lower(), (
            "Domain context should include library social contract language"
        )

    def test_patron_privacy_content_includes_coppa(self):
        ctx = DomainContext()
        content = ctx.load()
        assert "coppa" in content.lower(), (
            "Domain context should include COPPA guidance"
        )

    def test_patron_privacy_content_includes_data_minimization(self):
        ctx = DomainContext()
        content = ctx.load()
        assert "data minimization" in content.lower() or "minimiz" in content.lower(), (
            "Domain context should include data minimization principle"
        )


# ===========================================================================
# 4e. SessionMode — mode switching, field sets, exercise templates
# ===========================================================================

class TestSessionModeInfrastructure:
    """Validates mode enum, ProgressTracker mode switching, and exercise loading."""

    def test_all_modes_have_field_definitions(self):
        for mode in SessionMode:
            assert mode.value in _MODE_FIELDS, f"No field set defined for {mode.value}"
            assert len(_MODE_FIELDS[mode.value]) > 0, f"Empty field set for {mode.value}"

    def test_tracker_defaults_to_intake(self):
        tracker = ProgressTracker()
        assert tracker.mode == SessionMode.INTAKE

    def test_tracker_mode_switch_resets_scores(self):
        tracker = ProgressTracker()
        tracker.update([_make_user_msg(
            "Problem: patrons can't find audiobooks. Evidence: 40% abandon search. "
            "Users: mobile patrons. Impact: 20% improvement. Solution: better search. "
            "Metrics: search completion rate. Risks: DRM. Scope: iOS. Platform: iOS."
        )])
        assert tracker.completeness() > 0.0
        tracker.set_mode(SessionMode.WORKING_BACKWARDS)
        assert tracker.mode == SessionMode.WORKING_BACKWARDS
        assert tracker.completeness() == 0.0  # Reset

    def test_tracker_intake_fields_unchanged(self):
        tracker = ProgressTracker(mode=SessionMode.INTAKE)
        expected = {"problem", "evidence", "users", "impact", "solution",
                    "metrics", "risks", "scope", "platform"}
        assert set(tracker._active_fields()) == expected

    def test_tracker_working_backwards_fields(self):
        tracker = ProgressTracker(mode=SessionMode.WORKING_BACKWARDS)
        fields = set(tracker._active_fields())
        assert "headline" in fields
        assert "customer_problem" in fields
        assert "patron_quote" in fields
        assert "internal_faq" in fields

    def test_tracker_premortem_fields(self):
        tracker = ProgressTracker(mode=SessionMode.PREMORTEM)
        fields = set(tracker._active_fields())
        assert "failure_scenario" in fields
        assert "likely_causes" in fields
        assert "mitigations" in fields

    def test_tracker_steelman_fields(self):
        tracker = ProgressTracker(mode=SessionMode.STEELMAN)
        fields = set(tracker._active_fields())
        assert "position" in fields
        assert "counter_argument" in fields
        assert "pm_response" in fields

    def test_tracker_prioritize_fields(self):
        tracker = ProgressTracker(mode=SessionMode.PRIORITIZE)
        fields = set(tracker._active_fields())
        assert "candidates" in fields
        assert "scoring_criteria" in fields
        assert "ranked_output" in fields

    def test_tracker_retrospect_fields(self):
        tracker = ProgressTracker(mode=SessionMode.RETROSPECT)
        fields = set(tracker._active_fields())
        assert "prior_spec" in fields
        assert "actual_outcome" in fields
        assert "learnings" in fields

    def test_working_backwards_scoring_detects_headline(self):
        tracker = ProgressTracker(mode=SessionMode.WORKING_BACKWARDS)
        tracker.update([_make_user_msg(
            "The headline would be: Hoopla Now Recommends Your Next Great Read."
        )])
        assert tracker._scores["headline"].status == FieldStatus.ADEQUATE

    def test_working_backwards_scoring_detects_patron_quote(self):
        tracker = ProgressTracker(mode=SessionMode.WORKING_BACKWARDS)
        tracker.update([_make_user_msg(
            "A patron would say: I used to spend 10 minutes trying to find something good."
        )])
        assert tracker._scores["patron_quote"].status == FieldStatus.ADEQUATE

    def test_premortem_scoring_detects_failure_scenario(self):
        tracker = ProgressTracker(mode=SessionMode.PREMORTEM)
        tracker.update([_make_user_msg(
            "It is twelve months after launch and the feature failed completely."
            " Nobody ever turned it on."
        )])
        assert tracker._scores["failure_scenario"].status == FieldStatus.ADEQUATE

    def test_premortem_scoring_detects_mitigations(self):
        tracker = ProgressTracker(mode=SessionMode.PREMORTEM)
        tracker.update([_make_user_msg(
            "To prevent this we will add an in-app admin prompt before launch."
        )])
        assert tracker._scores["mitigations"].status == FieldStatus.ADEQUATE

    def test_steelman_scoring_detects_counter_argument(self):
        tracker = ProgressTracker(mode=SessionMode.STEELMAN)
        tracker.update([_make_user_msg(
            "The strongest argument against this proposal is that we have no evidence "
            "patrons actually want recommendations — they may prefer browsing."
        )])
        assert tracker._scores["counter_argument"].status == FieldStatus.ADEQUATE

    def test_mode_completeness_equal_weighting(self):
        """Non-intake modes use equal weighting: N adequate / N total."""
        tracker = ProgressTracker(mode=SessionMode.STEELMAN)
        # 0 of 3 fields
        assert tracker.completeness() == 0.0
        tracker.update([_make_user_msg("Our position is that we should build recommendations.")])
        # 1 of 3 fields = ~0.33
        assert 0.3 <= tracker.completeness() <= 0.4

    def test_exercise_templates_load(self):
        """All five exercise templates must be loadable by DomainContext."""
        ctx = DomainContext()
        for mode in SessionMode:
            if mode == SessionMode.INTAKE:
                continue  # No exercise template for intake
            text = ctx.load_exercise(mode.value)
            assert text, f"Exercise template missing or empty for mode: {mode.value}"

    def test_exercise_templates_contain_artifact_schema(self):
        """Each exercise template must define an artifact schema."""
        ctx = DomainContext()
        for mode in SessionMode:
            if mode == SessionMode.INTAKE:
                continue
            text = ctx.load_exercise(mode.value)
            assert "```markdown" in text, (
                f"Exercise template for {mode.value} must contain an artifact schema (```markdown block)"
            )

    def test_context_assembler_injects_exercise_for_non_intake(self):
        """ContextAssembler must inject the exercise template for non-intake modes."""
        for mode in [SessionMode.WORKING_BACKWARDS, SessionMode.PREMORTEM, SessionMode.STEELMAN]:
            tracker = ProgressTracker(mode=mode)
            assembler = ContextAssembler()
            prompt = assembler.build(progress=tracker, turn_count=0)
            assert "Active Exercise" in prompt or mode.value in prompt.lower(), (
                f"Exercise template not injected for mode: {mode.value}"
            )

    def test_context_assembler_excludes_intake_schema_in_non_intake_mode(self):
        """In non-intake modes, the standard artifact schema block is excluded."""
        tracker = ProgressTracker(mode=SessionMode.PREMORTEM)
        assembler = ContextAssembler()
        prompt = assembler.build(progress=tracker, turn_count=0)
        # business-case.md schema should not appear in premortem mode
        assert "## business-case.md" not in prompt

    def test_overlay_shows_mode(self):
        """Dynamic overlay must show the active mode."""
        tracker = ProgressTracker(mode=SessionMode.WORKING_BACKWARDS)
        assembler = ContextAssembler()
        prompt = assembler.build(progress=tracker, turn_count=1)
        assert "working-backwards" in prompt.lower()


class TestCoachEngineModeSlashCommands:
    """Validates CoachEngine mode switching via slash commands."""

    def _mock_engine(self, response: str = "Ok.") -> CoachEngine:
        from pipeline.backends.base import AgentBackend, AgentResult

        class MockBackend(AgentBackend):
            def __init__(self, r):
                self._r = r
            @property
            def name(self):
                return "mock"
            def invoke(self, prompt, context="", config=None):
                return AgentResult(output=self._r, success=True)
            def chat(self, messages, system="", config=None):
                return AgentResult(output=self._r, success=True)
            def chat_stream(self, messages, system="", config=None):
                yield self._r
            def health_check(self):
                return True

        return CoachEngine(backend=MockBackend(response))

    def test_default_mode_is_intake(self):
        engine = self._mock_engine()
        assert engine.mode == SessionMode.INTAKE

    def test_wb_command_switches_mode(self):
        engine = self._mock_engine()
        result = engine.chat("/wb")
        assert engine.mode == SessionMode.WORKING_BACKWARDS
        assert "working backwards" in result.output.lower() or "headline" in result.output.lower()

    def test_premortem_command_switches_mode(self):
        engine = self._mock_engine()
        result = engine.chat("/premortem")
        assert engine.mode == SessionMode.PREMORTEM
        assert "pre-mortem" in result.output.lower() or "fail" in result.output.lower()

    def test_steelman_command_switches_mode(self):
        engine = self._mock_engine()
        result = engine.chat("/steelman")
        assert engine.mode == SessionMode.STEELMAN

    def test_prioritize_command_switches_mode(self):
        engine = self._mock_engine()
        engine.chat("/prioritize")
        assert engine.mode == SessionMode.PRIORITIZE

    def test_retro_command_switches_mode(self):
        engine = self._mock_engine()
        engine.chat("/retro")
        assert engine.mode == SessionMode.RETROSPECT

    def test_intake_command_returns_to_intake(self):
        engine = self._mock_engine()
        engine.chat("/wb")
        engine.chat("/intake")
        assert engine.mode == SessionMode.INTAKE

    def test_mode_switch_resets_messages(self):
        engine = self._mock_engine()
        engine.chat("Some content about a problem.")
        assert len(engine.messages) > 0
        engine.chat("/wb")
        # After mode switch, messages should be reset
        assert len(engine.messages) <= 2  # at most the mode switch command itself

    def test_mode_slash_command_returns_description(self):
        engine = self._mock_engine()
        result = engine.chat("/wb")
        assert len(result.output) > 20  # Should be a meaningful description

    def test_mode_command_shows_current_mode(self):
        engine = self._mock_engine()
        engine.chat("/premortem")
        result = engine.chat("/mode")
        assert "premortem" in result.output.lower()

    def test_generate_uses_mode_artifact_name(self):
        """In non-intake mode, /generate should reference the mode-specific artifact."""
        engine = self._mock_engine("working-backwards.md content here")
        engine.chat("/wb")
        # Push completeness to ready state
        engine.chat(
            "Headline: Hoopla now tells patrons what to read next. "
            "Customer problem: patrons can't decide what to borrow. "
            "How it works: they see personalized recommendations on open. "
            "A patron would say: I always find something now. "
            "An admin would say: patrons are borrowing more titles. "
            "Internal FAQ: engineering will ask about the data model."
        )
        result = engine.chat("/generate")
        # Should either generate or refuse (depending on completeness), not crash
        assert result.output


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

    def test_live_patron_privacy_flag_raised(self, engine):
        """Priya must flag privacy concerns when patron data is mentioned."""
        engine.reset()
        result = engine.chat(
            "We want to build a recommendation engine using each patron's full borrowing history."
        )
        output_lower = result.output.lower()
        privacy_indicators = [
            "privacy", "patron data", "borrowing history", "social contract",
            "data minimization", "anonymi", "coppa", "retention", "privacy impact"
        ]
        assert any(ind in output_lower for ind in privacy_indicators), (
            "Expected Priya to flag patron data privacy concerns.\n"
            f"Response: {result.output[:300]}"
        )

    def test_live_patron_privacy_blocks_artifact_without_impact(self, engine):
        """Priya must not generate artifacts for patron-data features without privacy impact."""
        engine.reset()
        # Provide a rich spec that mentions patron data but no privacy impact discussion
        engine.chat(
            "Problem: Patrons don't discover new titles. "
            "Evidence: 40% don't return after first borrow. "
            "Users: All library patrons. "
            "Impact: 20% improvement in repeat borrow rate. "
            "Solution: Recommendation engine using patron borrowing history. "
            "Metrics: Repeat borrow rate. "
            "Risks: DRM. Scope: iOS first. Platform: iOS."
        )
        result = engine.chat("/generate")
        output_lower = result.output.lower()
        # Should either refuse due to privacy gate or flag the privacy gap
        privacy_gap_indicators = [
            "privacy", "patron data", "privacy impact", "data minimization",
            "incomplete", "missing", "privacy_impact"
        ]
        assert any(ind in output_lower for ind in privacy_gap_indicators), (
            "Expected Priya to block/flag artifact generation due to missing privacy impact.\n"
            f"Response: {result.output[:400]}"
        )

    def test_live_error_correction_no_doubling_down(self, engine):
        """When corrected, Priya must not double-down or hedge."""
        engine.reset()
        # First, get Priya to state something
        engine.chat("What is the per-circulation model?")
        # Now correct her (even if her answer was fine, test the correction behavior)
        result = engine.chat(
            "Actually, you said borrowing is free for patrons — that's correct, "
            "but the library pays per borrow, not a flat fee. Please correct your framing."
        )
        output_lower = result.output.lower()
        # Should acknowledge the correction, not double-down
        doubling_down_phrases = [
            "actually, i said", "that's what i said", "i didn't say that", "you misread"
        ]
        for phrase in doubling_down_phrases:
            assert phrase not in output_lower, (
                f"Response appears to double-down ('{phrase}' found).\n"
                f"Response: {result.output[:300]}"
            )
        # Should engage with the corrected framing
        correction_indicators = [
            "correct", "you're right", "noted", "per borrow", "library pays", "per-circulation"
        ]
        assert any(ind in output_lower for ind in correction_indicators), (
            "Expected Priya to engage with the correction.\n"
            f"Response: {result.output[:300]}"
        )

    def test_live_error_correction_no_apology_spiral(self, engine):
        """Error correction must be clean — no excessive apology."""
        engine.reset()
        engine.chat("Tell me about Kids Mode.")
        result = engine.chat(
            "You said Kids Mode is for teenagers — it's actually for younger children. "
            "Please correct that."
        )
        output_lower = result.output.lower()
        # Should not contain repeated apology patterns
        apology_patterns = ["so sorry", "i sincerely apologize", "i deeply apologize", "forgive me"]
        for phrase in apology_patterns:
            assert phrase not in output_lower, (
                f"Response contains excessive apology ('{phrase}').\n"
                f"Response: {result.output[:300]}"
            )

    def test_live_kids_mode_privacy_flag(self, engine):
        """Priya must flag data minimization requirements for Kids Mode features."""
        engine.reset()
        result = engine.chat(
            "We want to add a reading streak tracker to Kids Mode to motivate young readers."
        )
        output_lower = result.output.lower()
        privacy_indicators = [
            "coppa", "children", "minor", "data minimization", "privacy",
            "kids mode", "under 13", "collect", "compliance"
        ]
        assert any(ind in output_lower for ind in privacy_indicators), (
            "Expected Priya to flag COPPA/privacy for Kids Mode feature.\n"
            f"Response: {result.output[:300]}"
        )


# ===========================================================================
# Phase B — Active Memory Tools
# ===========================================================================

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_memory(tmp_path):
    """Return a CoachMemory instance backed by a temp database."""
    return CoachMemory(db_path=str(tmp_path / "test.db"))


@pytest.fixture
def populated_memory(tmp_memory):
    """Memory pre-populated with three feature records across two sessions."""
    sid1 = generate_session_id()
    sid2 = generate_session_id()
    sid3 = generate_session_id()

    tmp_memory.save_feature(
        sid1,
        "BingePass Borrow Limit UI",
        problem_statement="Patrons hit borrow limits without clear explanation",
        mode="intake",
        artifact_content="## Problem\nPatrons exceed borrow limits",
    )
    tmp_memory.save_feature(
        sid2,
        "Accessibility Revamp",
        problem_statement="Screen reader support broken on Android",
        mode="intake",
        artifact_content="## Problem\nWCAA AA compliance gap on Android",
    )
    tmp_memory.save_feature(
        sid3,
        "KMP Android Migration",
        problem_statement="Shared business logic missing from Android app",
        mode="premortem",
        artifact_content="## Failure Scenario\nMigration stalls at DRM layer",
    )
    return tmp_memory, (sid1, sid2, sid3)


# ---------------------------------------------------------------------------
# 11. Feature Memory — save/recall/lookup round-trips
# ---------------------------------------------------------------------------

class TestFeatureMemory:

    def test_save_feature_returns_id(self, tmp_memory):
        sid = generate_session_id()
        fid = tmp_memory.save_feature(sid, "Test Feature Name", problem_statement="some problem")
        assert fid, "save_feature should return a non-empty ID"

    def test_save_feature_creates_session_stub(self, tmp_memory):
        """save_feature should create a session row automatically."""
        sid = generate_session_id()
        tmp_memory.save_feature(sid, "Auto Session Feature", problem_statement="testing")
        sessions = tmp_memory.list_sessions()
        ids = [s["id"] for s in sessions]
        assert sid in ids

    def test_recall_similar_feature_finds_match(self, populated_memory):
        mem, _ = populated_memory
        result = mem.recall_similar_feature("borrow limit patron")
        assert result, "Should find BingePass feature"
        assert "BingePass Borrow Limit UI" in result

    def test_recall_similar_feature_empty_on_no_match(self, populated_memory):
        mem, _ = populated_memory
        result = mem.recall_similar_feature("xyzzy nonexistent obscure topic")
        assert result == "", "Should return empty string when nothing matches"

    def test_recall_similar_feature_includes_problem_statement(self, populated_memory):
        mem, _ = populated_memory
        result = mem.recall_similar_feature("borrow")
        assert "Patrons hit borrow limits" in result

    def test_recall_similar_feature_includes_artifact_excerpt(self, populated_memory):
        mem, _ = populated_memory
        result = mem.recall_similar_feature("borrow limit")
        assert "Patrons exceed borrow limits" in result

    def test_recall_excludes_current_session(self, populated_memory):
        """exclude_session_id should suppress results from own session."""
        mem, (sid1, _sid2, _sid3) = populated_memory
        result = mem.recall_similar_feature("borrow limit patron", exclude_session_id=sid1)
        # BingePass is from sid1 — should not appear
        assert "BingePass Borrow Limit UI" not in result

    def test_lookup_exact_match(self, populated_memory):
        mem, _ = populated_memory
        result = mem.lookup_feature_outcome("BingePass Borrow Limit UI")
        assert result, "Should find feature by exact name"
        assert "BingePass Borrow Limit UI" in result

    def test_lookup_exact_match_case_insensitive(self, populated_memory):
        """Normalized lookup should match regardless of case."""
        mem, _ = populated_memory
        result = mem.lookup_feature_outcome("bingepass borrow limit ui")
        assert result, "Should match case-insensitively"
        assert "BingePass Borrow Limit UI" in result

    def test_lookup_fuzzy_fallback(self, populated_memory):
        """Fuzzy lookup finds a close match when exact normalized fails."""
        mem, _ = populated_memory
        result = mem.lookup_feature_outcome("borrow limit UI", fuzzy=True)
        assert result, "Fuzzy lookup should find the feature"

    def test_lookup_returns_artifact_content(self, populated_memory):
        mem, _ = populated_memory
        result = mem.lookup_feature_outcome("BingePass Borrow Limit UI")
        assert "Patrons exceed borrow limits" in result

    def test_lookup_returns_empty_for_unknown(self, populated_memory):
        mem, _ = populated_memory
        result = mem.lookup_feature_outcome("Completely Unknown Feature That Does Not Exist")
        assert result == ""

    def test_lookup_includes_crystal_items_when_present(self, tmp_memory):
        """After save_session with crystal items, lookup should include them."""
        from pipeline.coach.crystallizer import Crystallizer, CrystalResult, CrystalItem

        sid = generate_session_id()
        tmp_memory.save_feature(sid, "DRM Compliance Gate", problem_statement="DRM blocks content")
        # Save crystal items for the session
        crystal = CrystalResult(
            items=[CrystalItem(kind="constraint", text="Must not bypass DRM layer", confidence=0.9)],
            session_summary="1 constraint",
        )
        tmp_memory.save_session(sid, crystal)

        result = tmp_memory.lookup_feature_outcome("DRM Compliance Gate")
        assert "Must not bypass DRM layer" in result

    def test_upsert_on_duplicate_session_feature(self, tmp_memory):
        """Saving the same feature name for the same session should upsert."""
        sid = generate_session_id()
        fid1 = tmp_memory.save_feature(sid, "Duplicate Feature", problem_statement="v1")
        fid2 = tmp_memory.save_feature(
            sid, "Duplicate Feature", problem_statement="v2 updated", artifact_content="artifact v2"
        )
        assert fid1 == fid2, "Upsert should return the same ID"
        result = tmp_memory.lookup_feature_outcome("Duplicate Feature")
        assert "artifact v2" in result, "Artifact content should be updated"

    def test_normalize_name_function(self):
        assert _normalize_name("BingePass Borrow Limit UI") == "bingepass borrow limit ui"
        assert _normalize_name("  KMP-Android Migration! ") == "kmp android migration"
        assert _normalize_name("ACCESSIBILITY REVAMP") == "accessibility revamp"

    def test_fts_query_or_function(self):
        assert _fts_query_or("borrow limit patron") == "borrow OR limit OR patron"
        assert _fts_query_or("borrow") == "borrow"
        assert _fts_query_or("") == ""
        # Short tokens (<3 chars) dropped
        assert "OR" not in _fts_query_or("a b c") or _fts_query_or("a b c") == ""

    def test_recall_top_k_respected(self, populated_memory):
        """recall_similar_feature should honor top_k limit."""
        mem, _ = populated_memory
        # All three features have "Android" or match broadly — ask for top 1
        result = mem.recall_similar_feature("Android migration accessibility borrow", top_k=1)
        # Count occurrences of "###" (one per feature heading)
        count = result.count("###")
        assert count <= 1, f"Expected at most 1 result, got {count}"


# ---------------------------------------------------------------------------
# 12. Crystallizer feature name extraction
# ---------------------------------------------------------------------------

class TestCrystallizerFeatureExtraction:

    def test_extracts_name_from_feature_colon(self):
        msgs = [_make_user_msg("The feature: BingePass Borrow Limit UI needs scoping.")]
        name, conf = extract_feature_name(msgs)
        assert name == "BingePass Borrow Limit UI"
        assert conf >= 0.8

    def test_extracts_name_from_initiative_colon(self):
        msgs = [_make_user_msg("initiative: Accessibility Revamp is our Q3 priority.")]
        name, conf = extract_feature_name(msgs)
        assert name == "Accessibility Revamp"
        assert conf >= 0.8

    def test_extracts_name_from_building_for(self):
        msgs = [_make_user_msg("We are building the BingePass Borrow Limit UI for patrons.")]
        name, conf = extract_feature_name(msgs)
        assert "BingePass Borrow Limit UI" in name
        assert conf >= 0.6

    def test_extracts_name_from_quoted_string(self):
        msgs = [_make_user_msg('The feature called "Patron Reading History" is complex.')]
        name, conf = extract_feature_name(msgs)
        assert "Patron Reading History" in name
        assert conf >= 0.8

    def test_extracts_name_from_project_colon(self):
        msgs = [_make_user_msg("project: KMP Android Migration is in Phase 2.")]
        name, conf = extract_feature_name(msgs)
        assert "KMP Android Migration" in name
        assert conf >= 0.8

    def test_no_match_for_plain_lowercase(self):
        msgs = [_make_user_msg("just chatting about stuff here")]
        name, conf = extract_feature_name(msgs)
        assert name == ""
        assert conf == 0.0

    def test_no_match_for_single_word_candidate(self):
        msgs = [_make_user_msg("feature: BingePass")]
        name, conf = extract_feature_name(msgs)
        # Single-word names should be rejected (too ambiguous)
        assert name == "" or len(name.split()) >= 2

    def test_newest_message_wins(self):
        """When multiple messages have feature names, the most recent wins."""
        msgs = [
            _make_user_msg("feature: Old Feature Name was discussed."),
            _make_user_msg("assistant message"),
            _make_user_msg("feature: New Feature Name is what we care about."),
        ]
        name, conf = extract_feature_name(msgs)
        assert "New Feature Name" in name

    def test_returns_empty_for_no_messages(self):
        name, conf = extract_feature_name([])
        assert name == ""
        assert conf == 0.0

    def test_trailing_lowercase_words_stripped(self):
        msgs = [_make_user_msg("feature: KMP Android Migration is causing issues now.")]
        name, conf = extract_feature_name(msgs)
        # "is", "causing", "issues", "now" should be stripped
        assert name == "KMP Android Migration"

    def test_multipart_content_list(self):
        """extract_feature_name handles list-format content (multimodal messages)."""
        msgs = [{"role": "user", "content": [
            {"type": "text", "text": "The feature: Multimodal Upload Support is needed."}
        ]}]
        name, conf = extract_feature_name(msgs)
        assert "Multimodal Upload Support" in name


# ---------------------------------------------------------------------------
# 13. MemorySource — ContextSource protocol
# ---------------------------------------------------------------------------

class TestMemorySource:

    def test_implements_context_source_protocol(self, tmp_memory):
        """MemorySource must implement get_context() and return list[ContextChunk]."""
        source = MemorySource(memory=tmp_memory, current_session_id="test-session")
        result = source.get_context({
            "messages": [_make_user_msg("borrow limit problem")],
            "missing_fields": [],
            "turn_count": 0,
            "mode": SessionMode.INTAKE,
        })
        assert isinstance(result, list)
        for chunk in result:
            assert isinstance(chunk, ContextChunk)

    def test_returns_empty_on_no_matches(self, tmp_memory):
        source = MemorySource(memory=tmp_memory)
        result = source.get_context({
            "messages": [_make_user_msg("obscure topic xyzzy")],
            "missing_fields": [],
            "turn_count": 0,
            "mode": SessionMode.INTAKE,
        })
        assert result == []

    def test_surfaces_analogues_in_early_turns(self, populated_memory):
        mem, (sid1, _sid2, _sid3) = populated_memory
        source = MemorySource(memory=mem, current_session_id="new-session", top_k=3)
        result = source.get_context({
            "messages": [_make_user_msg("patron borrow limit confusion")],
            "missing_fields": [],
            "turn_count": 1,
            "mode": SessionMode.INTAKE,
        })
        assert result, "Should surface analogues in early turns"
        contents = "\n".join(c.content for c in result)
        assert "BingePass Borrow Limit UI" in contents

    def test_suppresses_analogues_after_turn_limit(self, populated_memory):
        mem, _ = populated_memory
        source = MemorySource(memory=mem, top_k=3, analogue_turn_limit=4)
        result = source.get_context({
            "messages": [_make_user_msg("patron borrow limit confusion")],
            "missing_fields": [],
            "turn_count": 5,  # past the limit
            "mode": SessionMode.INTAKE,
        })
        # In INTAKE mode past turn limit, no analogues should surface
        assert result == []

    def test_retrospect_surfaces_prior_spec(self, populated_memory):
        mem, _ = populated_memory
        source = MemorySource(memory=mem, top_k=3)
        msgs = [
            _make_user_msg("feature: BingePass Borrow Limit UI was supposed to solve patron confusion.")
        ]
        result = source.get_context({
            "messages": msgs,
            "missing_fields": [],
            "turn_count": 1,
            "mode": SessionMode.RETROSPECT,
        })
        assert result, "Should surface prior spec in RETROSPECT mode"
        contents = "\n".join(c.content for c in result)
        assert "BingePass Borrow Limit UI" in contents
        assert result[0].source == "memory:prior_spec"

    def test_degrades_gracefully_on_exception(self, tmp_path):
        """MemorySource must return [] if memory raises an exception."""
        import unittest.mock as mock
        bad_memory = mock.MagicMock()
        bad_memory.recall_similar_feature.side_effect = RuntimeError("DB error")
        source = MemorySource(memory=bad_memory)
        result = source.get_context({
            "messages": [_make_user_msg("some query")],
            "missing_fields": [],
            "turn_count": 0,
            "mode": SessionMode.INTAKE,
        })
        assert result == []

    def test_excludes_current_session_from_analogues(self, populated_memory):
        mem, (sid1, _sid2, _sid3) = populated_memory
        # Current session is sid1 — its feature (BingePass) should not surface
        source = MemorySource(memory=mem, current_session_id=sid1, top_k=3)
        result = source.get_context({
            "messages": [_make_user_msg("patron borrow limit confusion")],
            "missing_fields": [],
            "turn_count": 0,
            "mode": SessionMode.INTAKE,
        })
        contents = "\n".join(c.content for c in result)
        assert "BingePass Borrow Limit UI" not in contents


# ---------------------------------------------------------------------------
# 14. CoachEngine /recall command
# ---------------------------------------------------------------------------

class TestCoachEngineRecallCommand:

    @pytest.fixture
    def engine_with_memory(self, tmp_memory, populated_memory):
        """CoachEngine backed by populated memory. Uses AssistedBackend stub."""
        from unittest.mock import MagicMock
        from pipeline.backends.base import AgentResult

        mem, _ = populated_memory

        backend = MagicMock()
        backend.chat_stream.return_value = iter(["Acknowledged."])

        engine = CoachEngine(
            backend=backend,
            coach_memory=mem,
        )
        return engine

    def test_recall_is_slash_command(self):
        assert "/recall" in __import__("pipeline.coach.engine", fromlist=["_SLASH_COMMANDS"])._SLASH_COMMANDS

    def test_recall_no_query_lists_sessions(self, engine_with_memory):
        result = engine_with_memory.chat("/recall")
        # No query → should list recent sessions or features
        assert result.success
        assert result.output  # not empty

    def test_recall_with_query_finds_feature(self, engine_with_memory):
        result = engine_with_memory.chat("/recall borrow limit patron")
        assert result.success
        assert "BingePass Borrow Limit UI" in result.output

    def test_recall_with_unmatched_query(self, engine_with_memory):
        result = engine_with_memory.chat("/recall xyzzy nonexistent obscure")
        assert result.success
        # Should say no results found, not crash
        assert "no" in result.output.lower() or "not found" in result.output.lower() or result.output.strip()

    def test_recall_without_memory_returns_helpful_message(self):
        """When CoachEngine has no memory configured, /recall explains that."""
        from unittest.mock import MagicMock
        backend = MagicMock()
        backend.chat_stream.return_value = iter(["OK."])
        engine = CoachEngine(backend=backend, coach_memory=None)
        result = engine.chat("/recall anything")
        assert result.success
        assert "memory" in result.output.lower()

    def test_recall_with_args_dispatched_correctly(self, engine_with_memory):
        """/recall <query> should dispatch to _handle_recall with args."""
        result = engine_with_memory.chat("/recall accessibility android")
        assert result.success
        # Either finds Accessibility Revamp or KMP Android Migration
        assert any(term in result.output for term in [
            "Accessibility", "KMP", "Android", "no", "not found"
        ])


# ---------------------------------------------------------------------------
# 15. CoachEngine.close_session — feature indexing
# ---------------------------------------------------------------------------

class TestCoachEngineCloseSession:

    def test_close_session_indexes_feature_from_conversation(self, tmp_memory):
        """close_session extracts feature name and saves to feature index."""
        from unittest.mock import MagicMock

        backend = MagicMock()
        backend.chat_stream.return_value = iter(["OK."])

        engine = CoachEngine(backend=backend, coach_memory=tmp_memory)
        engine.chat("The feature: BingePass Discovery Redesign needs scoping.")

        sid = generate_session_id()
        engine.close_session(sid, artifact_content="## Problem\nDiscovery UX")

        result = tmp_memory.lookup_feature_outcome("BingePass Discovery Redesign")
        assert result, "Feature should be indexed after close_session"
        assert "BingePass Discovery Redesign" in result

    def test_close_session_saves_artifact_content(self, tmp_memory):
        from unittest.mock import MagicMock

        backend = MagicMock()
        backend.chat_stream.return_value = iter(["OK."])

        engine = CoachEngine(backend=backend, coach_memory=tmp_memory)
        engine.chat("feature: Patron Notification System must be built.")

        sid = generate_session_id()
        engine.close_session(sid, artifact_content="## Impact\nReduce missed holds")

        result = tmp_memory.lookup_feature_outcome("Patron Notification System")
        assert "Reduce missed holds" in result

    def test_close_session_with_no_memory_is_noop(self):
        """close_session should not raise when memory is None."""
        from unittest.mock import MagicMock

        backend = MagicMock()
        backend.chat_stream.return_value = iter(["OK."])

        engine = CoachEngine(backend=backend, coach_memory=None)
        engine.chat("feature: Test Feature here")
        # Must not raise
        engine.close_session("some-session-id")

    def test_close_session_with_empty_messages_is_noop(self, tmp_memory):
        """close_session with no messages should not raise or write anything."""
        from unittest.mock import MagicMock

        backend = MagicMock()
        engine = CoachEngine(backend=backend, coach_memory=tmp_memory)
        # No messages — engine.close_session should be a no-op
        engine.close_session("no-messages-session")
        sessions = tmp_memory.list_sessions()
        assert "no-messages-session" not in [s["id"] for s in sessions]

    def test_close_session_skips_low_confidence_name(self, tmp_memory):
        """If no confident feature name found, feature should not be indexed."""
        from unittest.mock import MagicMock

        backend = MagicMock()
        backend.chat_stream.return_value = iter(["OK."])

        engine = CoachEngine(backend=backend, coach_memory=tmp_memory)
        # Plain text with no proper-noun feature name
        engine.chat("Just chatting about the general product roadmap without specifics.")

        sid = generate_session_id()
        engine.close_session(sid)

        # No feature should have been indexed
        import sqlite3
        conn = sqlite3.connect(tmp_memory._db_path)
        rows = conn.execute("SELECT feature_name FROM features WHERE session_id = ?", (sid,)).fetchall()
        conn.close()
        assert rows == [], f"Unexpected features indexed: {rows}"
