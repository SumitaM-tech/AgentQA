"""Bug verification: re-observe, replay when safe, compare evidence, recompute confidence.

Pipeline position (see agent.py):
    unexpected behaviour -> Critic (rules + Gemini) -> BugVerifier -> confirmed / unverified / discarded

Replay is deliberately conservative. Only idempotent actions are re-executed (OPEN, RELOAD, SCROLL,
WAIT, and clicks on plain same-page links replayed as a GET navigation). Clicks on buttons and
TYPE/SELECT/PRESS are NEVER replayed, because repeating them could submit a form twice or mutate
data; for those the verifier reloads the current page and checks whether the page-level evidence
(console errors, failed requests, exceptions) persists.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol

from app.agent.critic import BugCandidate, rule_checks
from app.agent.state import (
    ActionArguments,
    ActionType,
    AgentAction,
    ExecutionResult,
    ExpectedOutcome,
)
from app.core.logging import get_logger
from app.perception.models import PageObservation
from app.perception.sanitize import redact_secrets

logger = get_logger(__name__)

_IDEMPOTENT = frozenset({ActionType.OPEN, ActionType.RELOAD, ActionType.SCROLL, ActionType.WAIT})
_NOISE = re.compile(r"\d+|https?://\S+|\b[0-9a-f]{8,}\b", re.I)


class _Executor(Protocol):
    async def execute(self, action: AgentAction) -> ExecutionResult: ...
    async def observe(self) -> PageObservation: ...


@dataclass
class VerificationResult:
    reproduced: bool
    attempts: int
    confidence: float
    notes: list[str] = field(default_factory=list)
    final_observation: PageObservation | None = None

    def as_dict(self) -> dict:
        return {"reproduced": self.reproduced, "attempts": self.attempts,
                "confidence": round(self.confidence, 3), "notes": self.notes}


def _norm(msg: str) -> str:
    return _NOISE.sub("#", msg.lower()).strip()[:100]


def _mk(action_type: ActionType, reason: str, **args) -> AgentAction:
    return AgentAction(
        action_type=action_type, arguments=ActionArguments(**args),
        expected_outcome=ExpectedOutcome(summary="Same page state as before."),
        reason=reason, exploration_priority=0.0,
    )


def replay_plan(action: AgentAction, before: PageObservation) -> AgentAction | None:
    """The safe replay action for `action`, or None if it must not be repeated."""
    if action.action_type in _IDEMPOTENT:
        return action
    if action.action_type == ActionType.CLICK and action.target:
        el = next((e for e in before.interactive_elements if e.id == action.target), None)
        if el and el.role == "link" and el.href and el.href.startswith(("http://", "https://")):
            return _mk(ActionType.OPEN, "Replaying link navigation.", url=el.href)
    return None


class BugVerifier:
    def __init__(self, max_retries: int = 1) -> None:
        self.max_retries = max(0, max_retries)

    async def verify(
        self, bug: BugCandidate, action: AgentAction, before: PageObservation, after: PageObservation,
        executor: _Executor,
    ) -> VerificationResult:
        original = {_norm(m) for m in bug.evidence}
        notes: list[str] = []
        attempts, reproduced, latest = 0, False, after

        def matches(obs: PageObservation) -> bool:
            signals, _ = rule_checks(action, before, obs, None)
            return any(_norm(s.message) in original for s in signals)

        # 1) Re-observe the live page (no interaction).
        try:
            latest = await executor.observe()
            attempts += 1
            reproduced = matches(latest)
            notes.append("Re-observation " + ("still shows the problem." if reproduced else "did not show the problem."))
        except Exception as exc:  # noqa: BLE001 - verification must never crash the run
            notes.append(f"Re-observation failed: {type(exc).__name__}")

        # 2) Replay (safe) or reload, up to max_retries.
        plan = replay_plan(action, before)
        for i in range(self.max_retries):
            if reproduced:
                break
            step = plan or _mk(ActionType.RELOAD, "Reloading to re-check the page.")
            try:
                res = await executor.execute(step)
                latest = await executor.observe()
                attempts += 1
                reproduced = matches(latest) or (not res.ok and step.action_type == ActionType.OPEN
                                                 and any("navigation" in n for n in original))
                kind = "replayed the action" if plan else "reloaded the page"
                notes.append(f"Retry {i + 1}: {kind}; " + ("problem reproduced." if reproduced else "no repro."))
            except Exception as exc:  # noqa: BLE001
                notes.append(f"Retry {i + 1} failed: {type(exc).__name__}")
                break
            if not plan and reproduced is False:
                notes.append("Mutating action was not repeated (unsafe to replay).")

        hard = any(("uncaught exception" in m.lower() or "server error 5" in m.lower() or "blank" in m.lower())
                   for m in bug.evidence)
        conf = bug.confidence
        if reproduced:
            conf = min(1.0, conf + 0.2 + (0.05 if hard else 0.0))
        else:
            conf = max(0.0, conf - (0.15 if hard else 0.3))
        return VerificationResult(reproduced, attempts, conf, [redact_secrets(n) for n in notes], latest)


def decide(bug: BugCandidate, result: VerificationResult, *, min_report_confidence: float = 0.5) -> tuple[str, float]:
    """Return (status, confidence): status is 'verified' | 'unverified' | 'discarded'."""
    if result.reproduced:
        return "verified", result.confidence
    if result.confidence >= min_report_confidence:
        return "unverified", result.confidence
    return "discarded", result.confidence
