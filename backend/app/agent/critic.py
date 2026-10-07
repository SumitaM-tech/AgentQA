"""Critic: evaluates the observation AFTER an action against the outcome that was
predicted BEFORE it.

Two stages. (1) Deterministic checks: uncaught exceptions, 5xx / failed requests,
console errors, blank page, and the prediction's own checkable claims (URL,
phrases, navigation, validation feedback). (2) An LLM assessment (only when
something needs judging) that is guard-railed so it can never dismiss hard
evidence such as an uncaught exception or a 5xx response.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from app.agent.planner import DecisionModel, screenshot_bytes
from app.agent.prompts import CRITIC_SYSTEM_PROMPT, build_critic_prompt
from app.agent.state import (
    MUTATING,
    ActionType,
    AgentAction,
    ExecutionResult,
    Severity,
)
from app.core.logging import get_logger
from app.perception.models import PageObservation
from app.perception.sanitize import redact_secrets

logger = get_logger(__name__)


class Verdict(str, Enum):
    AS_EXPECTED = "as_expected"
    UNEXPECTED_OK = "unexpected_ok"
    SUSPICIOUS = "suspicious"
    BUG = "bug"
    ACTION_FAILED = "action_failed"  # the agent's action could not run (stale target, not clickable, ...)


Category = Literal["functional", "validation", "error_handling", "navigation", "console_error",
                   "network_error", "exception", "accessibility", "performance", "visual", "other"]


class CriticAssessment(BaseModel):
    """Structured output requested from the LLM."""
    verdict: Literal["as_expected", "unexpected_ok", "suspicious", "bug"]
    severity: Severity | None = None
    category: Category = "functional"
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(max_length=300, description="One concise sentence, never deliberation.")
    discrepancies: list[str] = Field(default_factory=list, max_length=8)
    bug_title: str | None = Field(default=None, max_length=120)


@dataclass(frozen=True)
class Signal:
    kind: str
    severity: Severity
    category: str
    message: str
    hard: bool = False  # hard evidence the LLM may not dismiss


class BugCandidate(BaseModel):
    bug_id: str = Field(default_factory=lambda: uuid4().hex)
    title: str
    severity: Severity
    category: str
    description: str
    evidence: list[str] = Field(default_factory=list)
    step_index: int
    url: str
    state_id: str
    action_summary: str
    expected: str
    actual: str
    confidence: float
    needs_verification: bool
    screenshot_path: str | None = None
    # Filled in by the verification pipeline / recorder
    fingerprint: str = ""
    status: str = "unverified"          # "verified" | "unverified"
    severity_reason: str = ""
    console_errors: list[str] = Field(default_factory=list)
    network_errors: list[str] = Field(default_factory=list)
    verification: dict = Field(default_factory=dict)


class CriticVerdict(BaseModel):
    verdict: Verdict
    severity: Severity | None = None
    category: str = "functional"
    confidence: float = 1.0
    reason: str = ""
    discrepancies: list[str] = Field(default_factory=list)
    signals: list[str] = Field(default_factory=list)
    needs_verification: bool = False
    bug: BugCandidate | None = None
    used_llm: bool = False


_SEV_ORDER = {Severity.COSMETIC: 0, Severity.LOW: 1, Severity.MEDIUM: 2, Severity.HIGH: 3, Severity.CRITICAL: 4}
_AGENT_SIDE_CODES = frozenset({"element_not_found", "element_not_actionable", "invalid_arguments",
                               "session_closed", "limit_exceeded", "unknown_tool", "no_history"})
_NAV_ACTIONS = frozenset({ActionType.OPEN, ActionType.RELOAD, ActionType.BACK, ActionType.FORWARD})
_VALIDATION_STATUSES = frozenset({400, 401, 403, 404, 409, 422})
_ERROR_WORDS = re.compile(
    r"\b(error|invalid|required|must|cannot|can't|failed|incorrect|too (short|long)|not (valid|allowed|found)|"
    r"please (enter|provide|select|fill)|already (exists|taken))\b", re.IGNORECASE)


def _max_sev(a: Severity | None, b: Severity | None) -> Severity | None:
    if a is None or b is None:
        return a or b
    return a if _SEV_ORDER[a] >= _SEV_ORDER[b] else b


def _new_lines(before: str, after: str) -> list[str]:
    seen = {l.strip().lower() for l in before.splitlines()}
    return [l.strip() for l in after.splitlines() if l.strip() and l.strip().lower() not in seen]


def rule_checks(
    action: AgentAction, before: PageObservation, after: PageObservation, result: ExecutionResult | None
) -> tuple[list[Signal], list[str]]:
    """Deterministic evidence. Returns (signals, failed_expectation_notes)."""
    exp = action.expected_outcome
    signals: list[Signal] = []
    notes: list[str] = []

    if result is not None and not result.ok:
        code = result.error_code or ""
        if code not in _AGENT_SIDE_CODES and action.action_type in _NAV_ACTIONS:
            signals.append(Signal("navigation_failed", Severity.MEDIUM, "navigation",
                                  f"{action.action_type.value} failed: {(result.error or code)[:160]}"))

    for ex in after.browser_exceptions[:5]:
        signals.append(Signal("exception", Severity.HIGH, "exception",
                              f"Uncaught exception{f' x{ex.count}' if ex.count > 1 else ''}: {ex.message[:200]}", hard=True))

    if exp.console_clean:
        for c in after.console_errors[:3]:
            signals.append(Signal("console_error", Severity.MEDIUM, "console_error", f"console.error: {c.text[:200]}"))

    for n in after.network_errors[:6]:
        if n.kind == "request_failed":
            signals.append(Signal("request_failed", Severity.MEDIUM, "network_error",
                                  f"Request failed: {n.method} {n.url} ({n.failure})"))
        elif n.status and n.status >= 500:
            signals.append(Signal("http_5xx", Severity.HIGH, "network_error",
                                  f"Server error {n.status}: {n.method} {n.url}", hard=True))
        elif n.status in _VALIDATION_STATUSES and n.resource_type in ("xhr", "fetch", "document"):
            if exp.expects_error_feedback and n.resource_type != "document":
                continue  # a 4xx API answer is the CORRECT result of deliberately invalid input
            signals.append(Signal("http_4xx", Severity.MEDIUM, "network_error", f"HTTP {n.status}: {n.method} {n.url}"))
        elif n.status and n.status >= 400:
            signals.append(Signal("asset_4xx", Severity.LOW, "network_error", f"HTTP {n.status}: {n.method} {n.url}"))

    if after.page_load_state in ("load", "networkidle") and not after.visible_text.strip() and not after.interactive_elements:
        signals.append(Signal("blank_page", Severity.HIGH, "functional", "The page is blank after the action.", hard=True))

    # --- the prediction's own claims -------------------------------------
    if exp.url_contains and exp.url_contains.lower() not in after.url.lower():
        notes.append(f"expected URL to contain '{exp.url_contains}', got {after.url}")
    haystack = (after.visible_text + "\n" + (after.accessibility_tree or "")).lower()
    missing = [p for p in exp.text_contains if p.lower() not in haystack]
    if missing:
        notes.append(f"expected text not found: {missing}")
    changed = after.url != before.url or after.state_fingerprint != before.state_fingerprint
    if exp.expects_navigation and not changed and action.action_type != ActionType.FINISH:
        notes.append("expected the page/state to change, but it did not")

    fresh = [l for l in _new_lines(before.visible_text, after.visible_text) if _ERROR_WORDS.search(l)]
    if action.action_type in MUTATING:
        if exp.expects_error_feedback and not fresh and "alert" not in (after.accessibility_tree or "").lower():
            notes.append("expected validation/error feedback, but none was shown")
            signals.append(Signal("missing_validation", Severity.MEDIUM, "validation",
                                  "Invalid input produced no validation feedback."))
        elif not exp.expects_error_feedback and fresh:
            # Input-validation feedback ("Please enter…", "Invalid password") is correct behaviour for an exploratory
            # input, not a defect; only failure-style messages ("Something went wrong", "failed") are suspicious.
            suspicious = [l for l in fresh if not _VALIDATION_FEEDBACK.search(l)]
            if suspicious:
                notes.append(f"unexpected error message displayed: {suspicious[0][:120]}")
                signals.append(Signal("unexpected_error_message", Severity.MEDIUM, "functional",
                                      f"Unexpected error message: {suspicious[0][:160]}"))
    for n in notes:
        if not any(s.message.startswith(n[:20]) for s in signals):
            signals.append(Signal("expectation_mismatch", Severity.LOW, "functional", n))
    return signals, notes


_VALIDATION_FEEDBACK = re.compile(
    r"\b(please (enter|provide|fill|select|choose|type)|invalid|incorrect|required|must (be|contain)|too (short|long)|"
    r"not (a )?valid|try again with|already (exists|registered|taken)|do(es)? not match)\b", re.I)


class Critic:
    def __init__(self, model: DecisionModel | None = None, *, always_use_llm: bool = False,
                 send_screenshot: bool = True) -> None:
        self.model = model
        self.always_use_llm = always_use_llm
        self.send_screenshot = send_screenshot

    async def evaluate(
        self, *, step: int, action: AgentAction, target_label: str | None,
        before: PageObservation, after: PageObservation, result: ExecutionResult | None,
    ) -> CriticVerdict:
        signals, notes = rule_checks(action, before, after, result)
        signal_text = [s.message for s in signals]
        summary = action.describe(target_label)

        if result is not None and not result.ok and (result.error_code or "") in _AGENT_SIDE_CODES:
            return CriticVerdict(verdict=Verdict.ACTION_FAILED, reason=(result.error or "action failed")[:200],
                                 signals=signal_text)
        if not signals and not self.always_use_llm:
            return CriticVerdict(verdict=Verdict.AS_EXPECTED, reason="Outcome matches the prediction.")

        rule_sev: Severity | None = None
        for s in signals:
            rule_sev = _max_sev(rule_sev, s.severity)
        hard = any(s.hard for s in signals)
        category = max(signals, key=lambda s: _SEV_ORDER[s.severity]).category if signals else "functional"

        assessment: CriticAssessment | None = None
        if self.model is not None:
            try:
                assessment = await self.model.generate(
                    build_critic_prompt(action_summary=summary, expected=action.expected_outcome.summary,
                                        expectation_notes=notes, signals=signal_text, before=before, after=after),
                    system_instruction=CRITIC_SYSTEM_PROMPT, schema=CriticAssessment,
                    image_bytes=screenshot_bytes(after) if self.send_screenshot else None,
                )
            except Exception as exc:  # noqa: BLE001 - critic must never crash the run
                logger.warning("critic_model_failed", error_type=type(exc).__name__)

        verdict = self._merge(assessment, signals, rule_sev, hard, category)
        verdict.used_llm = assessment is not None
        verdict.signals = signal_text
        verdict.needs_verification = verdict.verdict == Verdict.SUSPICIOUS or (
            verdict.verdict == Verdict.BUG and verdict.confidence < 0.85)
        if verdict.verdict in (Verdict.BUG, Verdict.SUSPICIOUS) and verdict.severity in (
                Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL):
            verdict.bug = self._bug(step, summary, action, before, after, verdict, signal_text)
        return verdict

    @staticmethod
    def _merge(a: CriticAssessment | None, signals: list[Signal], rule_sev: Severity | None,
               hard: bool, category: str) -> CriticVerdict:
        if a is None:  # rules only
            if hard or (rule_sev and _SEV_ORDER[rule_sev] >= _SEV_ORDER[Severity.HIGH]):
                v, conf = Verdict.BUG, 0.8
            elif rule_sev and _SEV_ORDER[rule_sev] >= _SEV_ORDER[Severity.MEDIUM]:
                v, conf = Verdict.SUSPICIOUS, 0.6
            else:
                v, conf = Verdict.UNEXPECTED_OK, 0.5
            return CriticVerdict(verdict=v, severity=rule_sev, category=category, confidence=conf,
                                 reason=(signals[0].message if signals else "Rule-based finding.")[:300],
                                 discrepancies=[s.message for s in signals][:8])
        v = Verdict(a.verdict)
        sev = _max_sev(a.severity, rule_sev) if v in (Verdict.BUG, Verdict.SUSPICIOUS) else a.severity
        # Guardrails: the model may not dismiss hard evidence, nor invent bugs without any.
        if hard and v in (Verdict.AS_EXPECTED, Verdict.UNEXPECTED_OK):
            v, sev = Verdict.SUSPICIOUS, _max_sev(rule_sev, Severity.MEDIUM)
        if v == Verdict.BUG and not signals and not (a.confidence >= 0.8 and a.discrepancies):
            v = Verdict.SUSPICIOUS
        return CriticVerdict(verdict=v, severity=sev, category=a.category if not hard else category,
                             confidence=a.confidence, reason=a.reason,
                             discrepancies=list(a.discrepancies) or [s.message for s in signals][:8])

    @staticmethod
    def _bug(step: int, summary: str, action: AgentAction, before: PageObservation, after: PageObservation,
             v: CriticVerdict, signal_text: list[str]) -> BugCandidate:
        return BugCandidate(
            title=(v.reason or "Unexpected behaviour")[:120], severity=v.severity or Severity.MEDIUM,
            category=v.category, description=f"After {summary}: {v.reason}",
            evidence=(v.discrepancies + signal_text)[:10], step_index=step, url=after.url,
            state_id=after.state_fingerprint, action_summary=summary,
            expected=action.expected_outcome.summary, actual=v.reason, confidence=v.confidence,
            needs_verification=v.needs_verification, screenshot_path=after.screenshot_path,
            console_errors=[redact_secrets(c.text[:300]) for c in after.console_errors[:5]],
            network_errors=[redact_secrets(f"{n.method} {n.url} -> {n.status or n.failure}")[:300]
                            for n in after.network_errors[:8]],
        )
