"""Reasoning-engine contracts: the decision schema, run-state models and the
finite state machine (FSM) that bounds the agent.

The LLM only ever returns an `AgentAction` — plain, validated data. It is never
code, and it is never executed directly: every action is re-validated by the
policy layer (`policies.py`) and then mapped to a fixed browser tool.

(The first-generation contracts live in `legacy_state.py`.)
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.browser.actions import ELEMENT_ID_RE, PressArgs, validate_url_syntax
from app.perception.models import PageObservation


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Decision schema
# ---------------------------------------------------------------------------

class ActionType(str, Enum):
    OPEN = "OPEN"
    CLICK = "CLICK"
    TYPE = "TYPE"
    SELECT = "SELECT"
    SCROLL = "SCROLL"
    PRESS = "PRESS"
    BACK = "BACK"
    FORWARD = "FORWARD"
    RELOAD = "RELOAD"
    WAIT = "WAIT"
    SCREENSHOT = "SCREENSHOT"
    FINISH = "FINISH"

    @classmethod
    def _missing_(cls, value):  # noqa: ANN001, ANN206 - accept "click", "Click", " CLICK "
        if isinstance(value, str):
            key = value.strip().upper()
            for member in cls:
                if member.value == key:
                    return member
        return None


REQUIRES_TARGET = frozenset({ActionType.CLICK, ActionType.TYPE, ActionType.SELECT})
OPTIONAL_TARGET = frozenset({ActionType.SCROLL, ActionType.PRESS})
MUTATING = frozenset({ActionType.CLICK, ActionType.TYPE, ActionType.SELECT, ActionType.PRESS})

_ALLOWED_ARGS: dict[ActionType, frozenset[str]] = {
    ActionType.OPEN: frozenset({"url"}),
    ActionType.CLICK: frozenset(),
    ActionType.TYPE: frozenset({"text", "clear_first", "press_enter"}),
    ActionType.SELECT: frozenset({"value", "label", "index"}),
    ActionType.SCROLL: frozenset({"direction", "amount"}),
    ActionType.PRESS: frozenset({"key"}),
    ActionType.BACK: frozenset(),
    ActionType.FORWARD: frozenset(),
    ActionType.RELOAD: frozenset(),
    ActionType.WAIT: frozenset({"milliseconds", "load_state"}),
    ActionType.SCREENSHOT: frozenset(),
    ActionType.FINISH: frozenset(),
}
_REQUIRED_ARGS: dict[ActionType, frozenset[str]] = {
    ActionType.OPEN: frozenset({"url"}),
    ActionType.TYPE: frozenset({"text"}),
    ActionType.PRESS: frozenset({"key"}),
}

MAX_TEXT_CHARS = 500
MAX_WAIT_MS = 10_000

# Phrases that indicate leaked deliberation instead of a concise operational note.
_CHAIN_OF_THOUGHT = re.compile(
    r"\b(let me|let's think|step by step|on second thought|thinking about|i think|i need to consider|"
    r"first,? i|hmm|wait,|alternatively|considering the options)\b",
    re.IGNORECASE,
)


class ActionArguments(BaseModel):
    """Flat, typed arguments. Only the fields relevant to the action type may be set."""

    model_config = ConfigDict(extra="forbid")

    url: str | None = Field(default=None, description="OPEN: absolute http(s) URL.")
    text: str | None = Field(default=None, max_length=MAX_TEXT_CHARS, description="TYPE: text to enter.")
    clear_first: bool | None = Field(default=None, description="TYPE: replace (true) or append (false).")
    press_enter: bool | None = Field(default=None, description="TYPE: press Enter afterwards.")
    value: str | None = Field(default=None, max_length=200, description="SELECT: option value.")
    label: str | None = Field(default=None, max_length=200, description="SELECT: visible option label.")
    index: int | None = Field(default=None, ge=0, le=10_000, description="SELECT: zero-based option index.")
    direction: Literal["up", "down", "top", "bottom"] | None = Field(default=None, description="SCROLL direction.")
    amount: int | None = Field(default=None, ge=1, le=5000, description="SCROLL: pixels for up/down.")
    key: str | None = Field(default=None, max_length=40, description="PRESS: e.g. Enter, Tab, Escape, Control+A.")
    milliseconds: int | None = Field(default=None, ge=0, le=MAX_WAIT_MS, description="WAIT: delay in ms.")
    load_state: Literal["load", "domcontentloaded", "networkidle"] | None = Field(
        default=None, description="WAIT: wait for this load state instead of a delay."
    )

    def provided(self) -> dict[str, Any]:
        return {k: v for k, v in self.model_dump().items() if v is not None}


class ExpectedOutcome(BaseModel):
    """Prediction made BEFORE acting; the critic checks it against the next observation."""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=3, max_length=240, description="One falsifiable sentence.")
    url_contains: str | None = Field(default=None, max_length=200, description="Substring expected in the new URL.")
    text_contains: list[str] = Field(default_factory=list, max_length=5, description="Phrases expected on the page.")
    expects_navigation: bool = Field(default=False, description="The page/state should change.")
    expects_error_feedback: bool = Field(
        default=False, description="A validation/error message is the CORRECT result (e.g. invalid input)."
    )
    console_clean: bool = Field(default=True, description="No console errors/exceptions are expected.")

    @field_validator("text_contains")
    @classmethod
    def _short_phrases(cls, v: list[str]) -> list[str]:
        cleaned = [" ".join(p.split()) for p in v if p and p.strip()]
        if any(len(p) > 80 for p in cleaned):
            raise ValueError("each text_contains phrase must be <= 80 characters")
        return cleaned


class AgentAction(BaseModel):
    """Exactly one next action, as decided by the model."""

    model_config = ConfigDict(extra="forbid")

    action_type: ActionType
    target: str | None = Field(default=None, description="Element id from the observation (CLICK/TYPE/SELECT/...).")
    arguments: ActionArguments = Field(default_factory=ActionArguments)
    expected_outcome: ExpectedOutcome
    reason: str = Field(
        min_length=3, max_length=200,
        description="ONE concise operational sentence, e.g. 'Testing invalid checkout input.' Never reasoning.",
    )
    exploration_priority: float = Field(
        ge=0.0, le=1.0, description="1.0 = reaching unexplored functionality, 0.0 = re-verifying known behaviour."
    )

    @field_validator("reason")
    @classmethod
    def _concise_reason(cls, v: str) -> str:
        v = " ".join(v.split())
        if _CHAIN_OF_THOUGHT.search(v):
            raise ValueError("reason must be a concise operational note, not deliberation")
        if v.count(". ") >= 2:
            raise ValueError("reason must be a single short sentence")
        return v

    @model_validator(mode="after")
    def _consistent(self) -> "AgentAction":
        t = self.action_type
        if t in REQUIRES_TARGET and not self.target:
            raise ValueError(f"{t.value} requires a target element id")
        if t not in REQUIRES_TARGET and t not in OPTIONAL_TARGET and self.target is not None:
            raise ValueError(f"{t.value} does not take a target")
        if self.target is not None and not ELEMENT_ID_RE.match(self.target):
            raise ValueError("target must be an element id such as 'e3fa91c' (never a selector, URL or script)")

        provided = set(self.arguments.provided())
        extra = provided - _ALLOWED_ARGS[t]
        if extra:
            raise ValueError(f"{t.value} does not accept arguments: {sorted(extra)}")
        missing = _REQUIRED_ARGS.get(t, frozenset()) - provided
        if missing:
            raise ValueError(f"{t.value} requires arguments: {sorted(missing)}")

        a = self.arguments
        if t == ActionType.OPEN:
            try:
                validate_url_syntax(a.url or "")
            except ValueError as exc:
                raise ValueError(f"invalid url: {exc}") from exc
        elif t == ActionType.SELECT:
            if sum(x is not None for x in (a.value, a.label, a.index)) != 1:
                raise ValueError("SELECT needs exactly one of value, label, index")
        elif t == ActionType.SCROLL:
            if self.target is None and a.direction is None:
                raise ValueError("SCROLL needs a direction or a target element")
        elif t == ActionType.PRESS:
            try:
                PressArgs(key=a.key or "")
            except ValidationError as exc:
                raise ValueError(f"invalid key: {exc.errors()[0]['msg']}") from exc
        elif t == ActionType.WAIT:
            if a.milliseconds is None and a.load_state is None:
                raise ValueError("WAIT needs milliseconds or load_state")
        return self

    def key(self) -> str:
        """Canonical identity used for repetition tracking: type + target + arguments."""
        args = json.dumps(self.arguments.provided(), sort_keys=True, separators=(",", ":"))
        return f"{self.action_type.value}:{self.target or ''}:{hashlib.sha1(args.encode()).hexdigest()[:8]}"

    def describe(self, name: str | None = None) -> str:
        parts = [self.action_type.value]
        if self.target:
            parts.append(self.target + (f' "{name}"' if name else ""))
        a = self.arguments.provided()
        if "url" in a:
            parts.append(str(a["url"]))
        if "text" in a:
            parts.append(f'text={str(a["text"])[:40]!r}')
        for k in ("value", "label", "index", "direction", "amount", "key", "milliseconds", "load_state"):
            if k in a:
                parts.append(f"{k}={a[k]}")
        return " ".join(parts)


class DecisionError(ValueError):
    """The model output was not exactly one valid AgentAction."""


def parse_decision(payload: str | bytes | dict | list) -> AgentAction:
    """Parse model output into exactly one AgentAction; anything else is rejected."""
    if isinstance(payload, (str, bytes)):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise DecisionError(f"not valid JSON: {exc.msg}") from exc
    if isinstance(payload, list):
        raise DecisionError(f"expected exactly one action, got a list of {len(payload)}")
    if not isinstance(payload, dict):
        raise DecisionError("decision must be a JSON object")
    try:
        return AgentAction.model_validate(payload)
    except ValidationError as exc:
        raise DecisionError("; ".join(_fmt_error(e) for e in exc.errors())[:600]) from exc


def _fmt_error(e: dict[str, Any]) -> str:
    loc = ".".join(str(p) for p in e["loc"]) or "decision"
    return f"{loc}: {e['msg'].removeprefix('Value error, ')}"


def validation_summary(exc: ValidationError) -> str:
    return "; ".join(_fmt_error(e) for e in exc.errors())[:600]


# ---------------------------------------------------------------------------
# Run-state models (what the agent receives / records)
# ---------------------------------------------------------------------------

class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    COSMETIC = "cosmetic"


class KnownState(BaseModel):
    """One discovered UI state (a node in the exploration graph)."""
    state_id: str
    url: str
    title: str = ""
    visit_count: int = 0
    first_seen_step: int = 0
    last_seen_step: int = 0
    element_count: int = 0
    untried_count: int = 0
    exhausted: bool = False


class UnexploredTransition(BaseModel):
    """An element that has not been exercised yet in a known state."""
    state_id: str
    state_url: str
    element_id: str
    role: str
    name: str
    suggested_action: ActionType
    href: str | None = None
    in_current_state: bool = True


class BugSummary(BaseModel):
    bug_id: str
    title: str
    severity: Severity
    category: str = "functional"
    step_index: int = 0


class ExecutionResult(BaseModel):
    ok: bool
    error: str | None = None
    error_code: str | None = None
    url: str | None = None
    title: str | None = None
    screenshot_path: str | None = None
    duration_ms: int = 0


class StepRecord(BaseModel):
    step_index: int
    action: AgentAction
    target_label: str | None = None
    state_before: str | None = None
    state_after: str | None = None
    url_after: str | None = None
    result: ExecutionResult | None = None
    verdict: str | None = None
    verdict_reason: str | None = None
    new_state: bool = False
    policy_rejections: int = 0
    used_fallback: bool = False
    timestamp: datetime = Field(default_factory=utcnow)

    def summary(self) -> str:
        ok = "" if self.result is None else (" ok" if self.result.ok else f" FAILED({self.result.error_code})")
        v = f" -> {self.verdict}" if self.verdict else ""
        return f"#{self.step_index} {self.action.describe(self.target_label)}{ok}{v}"


class AgentInput(BaseModel):
    """Everything the agent receives to decide the next action."""

    goal: str
    observation: PageObservation
    previous_actions: list[StepRecord] = Field(default_factory=list)
    current_state: KnownState
    known_states: list[KnownState] = Field(default_factory=list)
    unexplored_transitions: list[UnexploredTransition] = Field(default_factory=list)
    recent_bugs: list[BugSummary] = Field(default_factory=list)
    step: int = Field(ge=1, description="1-based number of the action being decided")
    max_steps: int = Field(ge=1)
    allowed_domains: list[str] = Field(default_factory=list)
    feedback: list[str] = Field(default_factory=list, description="Why earlier proposals this step were rejected.")
    hints: list[str] = Field(default_factory=list, description="Deterministic nudges (loops, stagnation, ...).")


# ---------------------------------------------------------------------------
# Finite state machine
# ---------------------------------------------------------------------------

class AgentPhase(str, Enum):
    INIT = "init"
    OBSERVING = "observing"
    PLANNING = "planning"
    VALIDATING = "validating"
    EXECUTING = "executing"
    EVALUATING = "evaluating"
    RECOVERING = "recovering"
    TERMINATED = "terminated"


class TerminationReason(str, Enum):
    GOAL_COMPLETE = "goal_complete"           # the agent chose FINISH
    MAX_STEPS = "max_steps"
    MAX_ACTIONS = "max_actions"
    LOOP_DETECTED = "loop_detected"
    STAGNATION = "stagnation"
    TOO_MANY_REJECTIONS = "too_many_rejections"
    TOO_MANY_FAILURES = "too_many_failures"
    DOMAIN_VIOLATION = "domain_violation"
    UNREACHABLE = "site_unreachable"
    TIMEOUT = "timeout"
    STOPPED = "stopped"
    FATAL_ERROR = "fatal_error"


TRANSITIONS: dict[AgentPhase, frozenset[AgentPhase]] = {
    AgentPhase.INIT: frozenset({AgentPhase.VALIDATING, AgentPhase.TERMINATED}),
    AgentPhase.OBSERVING: frozenset({AgentPhase.PLANNING, AgentPhase.EVALUATING, AgentPhase.TERMINATED}),
    AgentPhase.PLANNING: frozenset({AgentPhase.VALIDATING, AgentPhase.TERMINATED}),
    AgentPhase.VALIDATING: frozenset({AgentPhase.PLANNING, AgentPhase.EXECUTING, AgentPhase.TERMINATED}),
    AgentPhase.EXECUTING: frozenset({AgentPhase.OBSERVING, AgentPhase.TERMINATED}),
    AgentPhase.EVALUATING: frozenset({AgentPhase.PLANNING, AgentPhase.RECOVERING, AgentPhase.TERMINATED}),
    AgentPhase.RECOVERING: frozenset({AgentPhase.OBSERVING, AgentPhase.TERMINATED}),
    AgentPhase.TERMINATED: frozenset(),
}


class InvalidTransition(RuntimeError):
    pass


class BudgetExceeded(RuntimeError):
    """A hard limit was hit; the machine has already terminated."""

    def __init__(self, reason: TerminationReason, message: str = "") -> None:
        super().__init__(message or reason.value)
        self.reason = reason


@dataclass
class FSMLimits:
    max_steps: int = 25
    max_recoveries: int = 3
    max_consecutive_rejections: int = 5
    max_consecutive_failures: int = 4
    max_stagnant_steps: int = 12
    max_loop_flags: int = 3
    max_wall_seconds: float = 900.0

    @classmethod
    def create(
        cls, max_steps: int, *, absolute_max_steps: int, max_wall_seconds: float,
        absolute_max_wall_seconds: float, **kw: Any,
    ) -> "FSMLimits":
        """Requested limits are clamped to the deployment ceilings; never unbounded."""
        return cls(
            max_steps=max(1, min(int(max_steps), int(absolute_max_steps))),
            max_wall_seconds=max(1.0, min(float(max_wall_seconds), float(absolute_max_wall_seconds))),
            **kw,
        )

    @property
    def max_actions(self) -> int:
        return 1 + self.max_steps + self.max_recoveries  # bootstrap OPEN + steps + recoveries


class AgentStateMachine:
    """Bounds the agent. Every browser action must be `authorize_execution()`-ed here,
    so no code path can execute more than `limits.max_actions` actions."""

    def __init__(self, limits: FSMLimits, clock: Callable[[], float] = time.monotonic) -> None:
        self.limits = limits
        self._clock = clock
        self._started = clock()
        self.phase = AgentPhase.INIT
        self.steps_started = 0
        self.actions_executed = 0
        self.recoveries = 0
        self.consecutive_rejections = 0
        self.consecutive_failures = 0
        self.stagnant_steps = 0
        self.loop_flags = 0
        self.termination: TerminationReason | None = None
        self.detail = ""
        self._stop = False

    @property
    def is_terminal(self) -> bool:
        return self.phase == AgentPhase.TERMINATED

    @property
    def elapsed(self) -> float:
        return self._clock() - self._started

    def transition(self, to: AgentPhase) -> None:
        if to not in TRANSITIONS[self.phase]:
            raise InvalidTransition(f"{self.phase.value} -> {to.value} is not allowed")
        self.phase = to

    def terminate(self, reason: TerminationReason, detail: str = "") -> None:
        if self.is_terminal:
            return  # first reason wins
        self.phase, self.termination, self.detail = AgentPhase.TERMINATED, reason, detail

    def request_stop(self) -> None:
        self._stop = True

    def begin_step(self) -> int:
        """Start a planning step (1-based). Enforces the step budget."""
        if self.is_terminal:
            raise InvalidTransition("machine is terminated")
        if self.steps_started >= self.limits.max_steps:
            self.terminate(TerminationReason.MAX_STEPS, f"reached {self.limits.max_steps} steps")
            raise BudgetExceeded(TerminationReason.MAX_STEPS)
        self.steps_started += 1
        return self.steps_started

    def authorize_execution(self, kind: Literal["bootstrap", "step", "recovery"] = "step") -> None:
        """Gate for EVERY browser action. Raises BudgetExceeded once the budget is spent."""
        expected = AgentPhase.RECOVERING if kind == "recovery" else AgentPhase.VALIDATING
        if self.phase != expected:
            raise InvalidTransition(f"cannot execute a {kind} action while {self.phase.value}")
        if kind == "recovery":
            if self.recoveries >= self.limits.max_recoveries:
                self.terminate(TerminationReason.DOMAIN_VIOLATION, "recovery budget exhausted")
                raise BudgetExceeded(TerminationReason.DOMAIN_VIOLATION)
            self.recoveries += 1
        if self.actions_executed >= self.limits.max_actions:
            self.terminate(TerminationReason.MAX_ACTIONS, f"reached {self.limits.max_actions} actions")
            raise BudgetExceeded(TerminationReason.MAX_ACTIONS)
        self.actions_executed += 1
        if kind != "recovery":  # recovery actions run inside the RECOVERING phase itself
            self.transition(AgentPhase.EXECUTING)

    # -- counters -----------------------------------------------------------
    def record_rejections(self, n: int) -> None:
        self.consecutive_rejections = self.consecutive_rejections + n if n else 0

    def record_action_result(self, ok: bool) -> None:
        self.consecutive_failures = 0 if ok else self.consecutive_failures + 1

    def record_progress(self, new_state: bool) -> None:
        self.stagnant_steps = 0 if new_state else self.stagnant_steps + 1

    def record_loop(self, looping: bool) -> None:
        self.loop_flags = self.loop_flags + 1 if looping else 0

    def check_limits(self) -> TerminationReason | None:
        """Evaluate every soft limit; terminates the machine when one is hit."""
        if self.is_terminal:
            return self.termination
        checks = [
            (self._stop, TerminationReason.STOPPED, "stop requested"),
            (self.elapsed > self.limits.max_wall_seconds, TerminationReason.TIMEOUT,
             f"exceeded {self.limits.max_wall_seconds:.0f}s"),
            (self.consecutive_failures >= self.limits.max_consecutive_failures,
             TerminationReason.TOO_MANY_FAILURES, f"{self.consecutive_failures} consecutive failed actions"),
            (self.consecutive_rejections >= self.limits.max_consecutive_rejections,
             TerminationReason.TOO_MANY_REJECTIONS, f"{self.consecutive_rejections} consecutive rejected proposals"),
            (self.loop_flags >= self.limits.max_loop_flags, TerminationReason.LOOP_DETECTED,
             "the agent is cycling between the same states"),
            (self.stagnant_steps >= self.limits.max_stagnant_steps, TerminationReason.STAGNATION,
             f"{self.stagnant_steps} steps without discovering anything new"),
        ]
        for hit, reason, detail in checks:
            if hit:
                self.terminate(reason, detail)
                return reason
        return None
