# AI-GENERATED: 2026-03-03T16:57:33Z | pipeline/coach/__init__.py | Copilot
"""Hoopla Coach — Priya Desai spec-funnel coaching system.

Entry point:
    python3 -m pipeline.coach [--port PORT] [--backend BACKEND] [--model MODEL]

Public surface:
    CoachEngine       — multi-turn conversation controller
    ProgressTracker   — business-case completeness scoring
    SignalDetector    — weak/strong signal detection
    ContextAssembler  — layered system-prompt builder
    DomainContext     — file-driven domain knowledge loader
    CoachMemory       — SQLite episodic memory
    Crystallizer      — heuristic session-end learning extractor
"""

from .engine import (  # noqa: F401
    CoachEngine,
    ProgressTracker,
    FieldStatus,
    SignalDetector,
    DomainContext,
    ContextAssembler,
)
from .memory import CoachMemory  # noqa: F401
from .crystallizer import Crystallizer  # noqa: F401

__all__ = [
    "CoachEngine",
    "ProgressTracker",
    "FieldStatus",
    "SignalDetector",
    "DomainContext",
    "ContextAssembler",
    "CoachMemory",
    "Crystallizer",
]
