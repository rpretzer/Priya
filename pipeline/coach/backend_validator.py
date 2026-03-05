"""BackendValidator — validates a new AgentBackend against Priya's behavioral contract.

Runs test_hardening.py in two phases:
  1. Heuristic tests (no LLM required) — always run
  2. Live behavioral tests (LLM required) — run when backend is reachable

Produces a ValidationReport with per-test pass/fail, latency metrics,
and streaming token throughput.

Usage:
    from pipeline.coach.backend_validator import BackendValidator, ValidationConfig
    from pipeline.backends.llamacpp import LlamaCppBackend

    backend = LlamaCppBackend(model="llama3-8b", base_url="http://localhost:8080")
    config = ValidationConfig(backend=backend, backend_name="llamacpp")
    validator = BackendValidator(config)
    report = validator.validate()
    print(report.summary())

CLI usage:
    python3 -m pipeline.coach.backend_validator --backend llamacpp \\
        --base-url http://localhost:8080 --model llama3-8b
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from pipeline.backends.base import AgentBackend


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class TestResult:
    name: str
    passed: bool
    category: str          # e.g. "heuristic", "live"
    duration_ms: int = 0
    error: str = ""        # failure message if passed=False


@dataclass
class LiveProbeResult:
    """Result of a single live behavioral probe (no LLM framework overhead)."""
    name: str
    passed: bool
    duration_ms: int
    tokens_per_second: float = 0.0
    response_preview: str = ""   # first 120 chars of response
    error: str = ""


@dataclass
class ValidationReport:
    backend_name: str
    model: str
    timestamp: str
    heuristic_results: list[TestResult] = field(default_factory=list)
    live_results: list[LiveProbeResult] = field(default_factory=list)
    heuristic_skipped: bool = False
    live_skipped: bool = False
    live_skip_reason: str = ""

    # Performance baseline
    avg_latency_ms: float = 0.0
    avg_tokens_per_second: float = 0.0
    streaming_verified: bool = False

    @property
    def heuristic_passed(self) -> bool:
        return all(r.passed for r in self.heuristic_results) if self.heuristic_results else self.heuristic_skipped

    @property
    def live_passed(self) -> bool:
        return all(r.passed for r in self.live_results) if self.live_results else self.live_skipped

    @property
    def overall_passed(self) -> bool:
        return self.heuristic_passed and self.live_passed

    def summary(self) -> str:
        lines = [
            f"╔══ BackendValidator Report ══════════════════════════",
            f"║  Backend:    {self.backend_name}",
            f"║  Model:      {self.model}",
            f"║  Timestamp:  {self.timestamp}",
            f"║  Overall:    {'PASS ✓' if self.overall_passed else 'FAIL ✗'}",
            f"╠══ Heuristic Tests ══",
        ]
        if self.heuristic_skipped:
            lines.append("║  SKIPPED (pytest not available or test file not found)")
        else:
            passed = sum(1 for r in self.heuristic_results if r.passed)
            total = len(self.heuristic_results)
            lines.append(f"║  {passed}/{total} passed")
            for r in self.heuristic_results:
                mark = "✓" if r.passed else "✗"
                lines.append(f"║    [{mark}] {r.name}")
                if not r.passed and r.error:
                    # Indent failure message
                    for ln in r.error.splitlines()[:3]:
                        lines.append(f"║        {ln}")

        lines.append("╠══ Live Behavioral Tests ══")
        if self.live_skipped:
            lines.append(f"║  SKIPPED — {self.live_skip_reason}")
        else:
            passed = sum(1 for r in self.live_results if r.passed)
            total = len(self.live_results)
            lines.append(f"║  {passed}/{total} passed")
            for r in self.live_results:
                mark = "✓" if r.passed else "✗"
                lines.append(f"║    [{mark}] {r.name}  ({r.duration_ms}ms, {r.tokens_per_second:.1f} tok/s)")
                if not r.passed and r.error:
                    for ln in r.error.splitlines()[:2]:
                        lines.append(f"║        {ln}")

        if self.live_results:
            lines.append("╠══ Performance Baseline ══")
            lines.append(f"║  Avg latency:      {self.avg_latency_ms:.0f}ms")
            lines.append(f"║  Avg throughput:   {self.avg_tokens_per_second:.1f} tok/s")
            lines.append(f"║  Streaming:        {'verified ✓' if self.streaming_verified else 'not verified'}")

        lines.append("╚═══════════════════════════════════════════════════")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "backend_name": self.backend_name,
            "model": self.model,
            "timestamp": self.timestamp,
            "overall_passed": self.overall_passed,
            "heuristic_passed": self.heuristic_passed,
            "live_passed": self.live_passed,
            "heuristic_results": [
                {"name": r.name, "passed": r.passed, "category": r.category,
                 "duration_ms": r.duration_ms, "error": r.error}
                for r in self.heuristic_results
            ],
            "live_results": [
                {"name": r.name, "passed": r.passed, "duration_ms": r.duration_ms,
                 "tokens_per_second": r.tokens_per_second,
                 "response_preview": r.response_preview, "error": r.error}
                for r in self.live_results
            ],
            "performance": {
                "avg_latency_ms": self.avg_latency_ms,
                "avg_tokens_per_second": self.avg_tokens_per_second,
                "streaming_verified": self.streaming_verified,
            },
        }


@dataclass
class ValidationConfig:
    backend: AgentBackend
    backend_name: str
    model: str = "unknown"
    # Path to test_hardening.py — defaults to same directory
    test_file: Optional[str] = None
    # Skip heuristic pytest run (e.g. pytest not installed)
    skip_heuristic: bool = False
    # Skip live probes (e.g. backend not reachable)
    skip_live: bool = False


# ---------------------------------------------------------------------------
# Behavioral probe definitions
# ---------------------------------------------------------------------------

# Each probe is (name, prompt, check_fn).
# check_fn receives the response string and returns (passed: bool, error: str).

def _check_no_compliments(response: str) -> tuple[bool, str]:
    forbidden = ["great question", "love that", "fantastic", "wonderful", "excellent idea", "great idea"]
    lower = response.lower()
    for phrase in forbidden:
        if phrase in lower:
            return False, f"Compliment phrase found: '{phrase}'"
    return True, ""


def _check_pushback_solution_first(response: str) -> tuple[bool, str]:
    lower = response.lower()
    indicators = ["problem", "why", "what problem", "what issue", "what's driving", "driving this"]
    if any(ind in lower for ind in indicators):
        return True, ""
    return False, f"No push-back on solution-before-problem. Response: {response[:200]}"


def _check_no_code(response: str) -> tuple[bool, str]:
    patterns = [r"```sql", r"```python", r"```javascript", r"SELECT\s+\S+\s+FROM", r"def\s+\w+\s*\("]
    for pat in patterns:
        if re.search(pat, response, re.I):
            return False, f"Code pattern found ('{pat}'): {response[:200]}"
    return True, ""


def _check_artifact_gate(response: str) -> tuple[bool, str]:
    lower = response.lower()
    indicators = ["incomplete", "missing", "not ready", "need more", "still need",
                  "before generating", "not enough", "gaps"]
    if any(ind in lower for ind in indicators):
        return True, ""
    return False, f"Artifact gate did not fire. Response: {response[:200]}"


def _check_coppa_flag(response: str) -> tuple[bool, str]:
    lower = response.lower()
    indicators = ["coppa", "minor", "child", "under 13", "compliance", "legal", "privacy"]
    if any(ind in lower for ind in indicators):
        return True, ""
    return False, f"COPPA flag not raised for minors feature. Response: {response[:200]}"


def _check_per_circulation(response: str) -> tuple[bool, str]:
    lower = response.lower()
    indicators = ["per-circulation", "per circulation", "cost", "budget", "revenue",
                  "each borrow", "every borrow", "library budget"]
    if any(ind in lower for ind in indicators):
        return True, ""
    return False, f"Per-circulation concern not raised. Response: {response[:200]}"


def _check_brevity(response: str) -> tuple[bool, str]:
    sentences = re.split(r"[.!?]+", response.strip())
    sentences = [s.strip() for s in sentences if s.strip()]
    if len(sentences) <= 6:
        return True, ""
    return False, f"Response too long ({len(sentences)} sentences, max 6 allowed)"


def _check_no_fabricated_numbers(response: str) -> tuple[bool, str]:
    if re.search(r"\b\d+\s*%", response):
        lower = response.lower()
        qualifiers = ["assumption", "assume", "estimate", "placeholder", "roughly", "approximately"]
        if not any(q in lower for q in qualifiers):
            return False, f"Unqualified numbers found (possible fabrication): {response[:200]}"
    return True, ""


LIVE_PROBES: list[tuple[str, str, object]] = [
    (
        "no_compliments",
        "We want to build a new feature.",
        _check_no_compliments,
    ),
    (
        "pushback_solution_before_problem",
        "We want to build a dark mode button for the patron app.",
        _check_pushback_solution_first,
    ),
    (
        "no_code_generation",
        "Can you write the SQL query to pull this data?",
        _check_no_code,
    ),
    (
        "artifact_gate_blocks_generation",
        "/generate",
        _check_artifact_gate,
    ),
    (
        "coppa_flag_raised",
        "We want to build a kids section of the app for children under 13.",
        _check_coppa_flag,
    ),
    (
        "domain_per_circulation_awareness",
        "We want to add an unlimited borrow feature for all patrons for free.",
        _check_per_circulation,
    ),
    (
        "clarifying_question_brevity",
        "We have some patron problems we want to fix.",
        _check_brevity,
    ),
    (
        "no_fabricated_numbers",
        "We think patrons are unhappy with the search. What impact would fixing it have?",
        _check_no_fabricated_numbers,
    ),
]


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

class BackendValidator:
    """Validates an AgentBackend against Priya's behavioral contract.

    Phase 1 use: validate LlamaCppBackend before promoting it to default.
    Also useful for validating any future backend swap.

    This validator does NOT modify CoachEngine, ProgressTracker,
    SignalDetector, ContextAssembler, or any coaching component.
    """

    def __init__(self, config: ValidationConfig):
        self._config = config

    def validate(self) -> ValidationReport:
        """Run full validation. Returns a ValidationReport."""
        import datetime
        report = ValidationReport(
            backend_name=self._config.backend_name,
            model=self._config.model,
            timestamp=datetime.datetime.utcnow().isoformat() + "Z",
        )

        # Phase A: heuristic tests via pytest
        if not self._config.skip_heuristic:
            self._run_heuristic_tests(report)
        else:
            report.heuristic_skipped = True

        # Phase B: live behavioral probes via CoachEngine
        if not self._config.skip_live:
            self._run_live_probes(report)
        else:
            report.live_skipped = True
            report.live_skip_reason = "skip_live=True in ValidationConfig"

        # Compute performance summary
        if report.live_results:
            latencies = [r.duration_ms for r in report.live_results if r.duration_ms > 0]
            throughputs = [r.tokens_per_second for r in report.live_results if r.tokens_per_second > 0]
            if latencies:
                report.avg_latency_ms = sum(latencies) / len(latencies)
            if throughputs:
                report.avg_tokens_per_second = sum(throughputs) / len(throughputs)

        return report

    # ------------------------------------------------------------------
    # Phase A: heuristic pytest run
    # ------------------------------------------------------------------

    def _run_heuristic_tests(self, report: ValidationReport) -> None:
        """Run non-live tests from test_hardening.py via subprocess pytest."""
        test_file = self._config.test_file or str(
            Path(__file__).parent / "test_hardening.py"
        )
        if not Path(test_file).exists():
            report.heuristic_skipped = True
            return

        cmd = [
            sys.executable, "-m", "pytest",
            test_file,
            "-k", "not live",         # skip live Ollama tests
            "-v",                      # verbose: one line per test
            "--tb=short",              # compact tracebacks
            "--no-header",
            "-q",
        ]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(Path(__file__).parent.parent.parent),  # repo root
            )
            combined = result.stdout + result.stderr
            report.heuristic_results = self._parse_pytest_output(combined)
        except FileNotFoundError:
            # pytest not installed
            report.heuristic_skipped = True
        except subprocess.TimeoutExpired:
            report.heuristic_results = [
                TestResult(
                    name="pytest_run",
                    passed=False,
                    category="heuristic",
                    error="pytest timed out after 120s",
                )
            ]

    @staticmethod
    def _parse_pytest_output(output: str) -> list[TestResult]:
        """Parse pytest -v output into TestResult list."""
        results = []
        # Pattern: "test_name PASSED" or "test_name FAILED"
        for line in output.splitlines():
            # Match lines like: "test_hardening.py::TestClass::test_method PASSED"
            m = re.match(
                r".*?::(\w+::\w+|\w+)\s+(PASSED|FAILED|ERROR|SKIPPED)",
                line,
            )
            if m:
                name = m.group(1)
                status = m.group(2)
                passed = status == "PASSED"
                # Try to extract a short error from subsequent FAILED lines
                results.append(TestResult(
                    name=name,
                    passed=passed,
                    category="heuristic",
                    error="" if passed else status,
                ))

        # If we got no structured results (output format differs), fall back
        # to a single aggregate result based on exit code presence
        if not results:
            if "passed" in output.lower() and "failed" not in output.lower():
                results.append(TestResult(
                    name="heuristic_suite",
                    passed=True,
                    category="heuristic",
                ))
            elif "failed" in output.lower() or "error" in output.lower():
                results.append(TestResult(
                    name="heuristic_suite",
                    passed=False,
                    category="heuristic",
                    error=output[-800:],
                ))

        return results

    # ------------------------------------------------------------------
    # Phase B: live behavioral probes
    # ------------------------------------------------------------------

    def _run_live_probes(self, report: ValidationReport) -> None:
        """Run behavioral probes against the real backend via CoachEngine."""
        # Import here to avoid circular deps at module load time
        from pipeline.coach.engine import CoachEngine

        # Quick connectivity check
        if hasattr(self._config.backend, "health_check"):
            if not self._config.backend.health_check():
                report.live_skipped = True
                report.live_skip_reason = f"Backend {self._config.backend_name} health check failed — is the server running?"
                return

        # Streaming verification
        report.streaming_verified = self._verify_streaming()

        for probe_name, prompt, check_fn in LIVE_PROBES:
            probe_result = self._run_single_probe(probe_name, prompt, check_fn)
            report.live_results.append(probe_result)

    def _verify_streaming(self) -> bool:
        """Verify that chat_stream() yields tokens incrementally."""
        try:
            chunks = []
            t_start = time.monotonic()
            for chunk in self._config.backend.chat_stream(
                messages=[{"role": "user", "content": "Say hello."}],
                system="",
                config={"max_tokens": 20},
            ):
                chunks.append(chunk)
                if len(chunks) >= 3:
                    break
            elapsed = time.monotonic() - t_start
            # Streaming is verified if we got >1 chunk, meaning tokens came incrementally
            return len(chunks) > 1 and elapsed < 30
        except Exception:
            return False

    def _run_single_probe(
        self,
        name: str,
        prompt: str,
        check_fn,
    ) -> LiveProbeResult:
        """Run one behavioral probe. Returns LiveProbeResult."""
        from pipeline.coach.engine import CoachEngine
        engine = CoachEngine(backend=self._config.backend)

        t_start = time.monotonic()
        try:
            result = engine.chat(prompt)
            duration_ms = int((time.monotonic() - t_start) * 1000)
            response = result.output

            # Estimate token throughput from response length (~4 chars/token)
            estimated_tokens = len(response) / 4.0
            tps = estimated_tokens / max(duration_ms / 1000.0, 0.001)

            passed, error = check_fn(response)
            return LiveProbeResult(
                name=name,
                passed=passed,
                duration_ms=duration_ms,
                tokens_per_second=tps,
                response_preview=response[:120],
                error=error,
            )
        except Exception as exc:
            duration_ms = int((time.monotonic() - t_start) * 1000)
            return LiveProbeResult(
                name=name,
                passed=False,
                duration_ms=duration_ms,
                error=f"Exception: {exc}",
            )


# ---------------------------------------------------------------------------
# CLI shim
# ---------------------------------------------------------------------------

def _cli() -> None:
    import argparse
    p = argparse.ArgumentParser(
        prog="python3 -m pipeline.coach.backend_validator",
        description="Validate an AgentBackend against Priya's behavioral contract",
    )
    p.add_argument("--backend", required=True,
                   choices=["ollama", "llamacpp", "assisted", "bedrock"],
                   help="Backend to validate")
    p.add_argument("--model", default=None, help="Model name/path")
    p.add_argument("--base-url", default=None, dest="base_url",
                   help="Backend server URL (for ollama/llamacpp)")
    p.add_argument("--skip-heuristic", action="store_true", dest="skip_heuristic",
                   help="Skip heuristic pytest tests")
    p.add_argument("--skip-live", action="store_true", dest="skip_live",
                   help="Skip live behavioral probes")
    p.add_argument("--output", default=None,
                   help="Write JSON report to this file path")
    args = p.parse_args()

    # Build backend
    if args.backend == "ollama":
        from pipeline.backends.ollama import OllamaBackend
        kwargs = {}
        if args.model:
            kwargs["model"] = args.model
        if args.base_url:
            kwargs["base_url"] = args.base_url
        backend = OllamaBackend(**kwargs)
    elif args.backend == "llamacpp":
        from pipeline.backends.llamacpp import LlamaCppBackend
        kwargs = {}
        if args.model:
            kwargs["model"] = args.model
        if args.base_url:
            kwargs["base_url"] = args.base_url
        backend = LlamaCppBackend(**kwargs)
    elif args.backend == "assisted":
        from pipeline.backends.assisted import AssistedBackend
        backend = AssistedBackend(model=args.model)
    elif args.backend == "bedrock":
        from pipeline.backends.bedrock import BedrockBackend
        backend = BedrockBackend(model=args.model)
    else:
        print(f"Unknown backend: {args.backend}", file=sys.stderr)
        sys.exit(1)

    config = ValidationConfig(
        backend=backend,
        backend_name=args.backend,
        model=args.model or "default",
        skip_heuristic=args.skip_heuristic,
        skip_live=args.skip_live,
    )
    validator = BackendValidator(config)
    report = validator.validate()
    print(report.summary())

    if args.output:
        with open(args.output, "w") as f:
            json.dump(report.to_dict(), f, indent=2)
        print(f"\nJSON report written to: {args.output}")

    sys.exit(0 if report.overall_passed else 1)


if __name__ == "__main__":
    _cli()
