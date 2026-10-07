"""Run-level telemetry: step timings, Gemini token usage, browser action
latency. Separate from `core.logging` (which is general structured
logging) — this module is specifically for numeric metrics that could
later be exported to Prometheus/StatsD without touching business logic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic


@dataclass
class StepTiming:
    step_index: int
    plan_action_ms: float = 0.0
    browser_execute_ms: float = 0.0
    observe_ms: float = 0.0
    compare_outcome_ms: float = 0.0


@dataclass
class SessionMetrics:
    session_id: str
    step_timings: list[StepTiming] = field(default_factory=list)
    gemini_input_tokens: int = 0
    gemini_output_tokens: int = 0
    bugs_confirmed: int = 0
    bugs_false_positive: int = 0

    def record_gemini_usage(self, input_tokens: int, output_tokens: int) -> None:
        self.gemini_input_tokens += input_tokens
        self.gemini_output_tokens += output_tokens


class Stopwatch:
    """Small context-manager timer used around each pipeline sub-step."""

    def __enter__(self) -> "Stopwatch":
        self._start = monotonic()
        return self

    def __exit__(self, *exc) -> None:
        self.elapsed_ms = (monotonic() - self._start) * 1000
