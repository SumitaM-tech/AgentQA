"""Planner: turns an `AgentInput` into exactly one policy-approved `AgentAction`.

Flow: prompt -> model (structured output) -> schema validation -> policy check.
A rejected proposal is fed back to the model (bounded retries). If the model
keeps failing, a deterministic, policy-checked fallback picks the best untried
element (or FINISH), so the agent always makes safe progress and never stalls.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from app.agent.memory import ExplorationMemory
from app.agent.policies import PolicyEngine
from app.agent.prompts import PLANNER_SYSTEM_PROMPT, build_planner_prompt
from app.agent.state import (
    ActionArguments,
    ActionType,
    AgentAction,
    AgentInput,
    DecisionError,
    ExpectedOutcome,
    UnexploredTransition,
    parse_decision,
    validation_summary,
)
from app.core.logging import get_logger
from app.perception.models import PageObservation

logger = get_logger(__name__)
T = TypeVar("T", bound=BaseModel)

_MAX_SCREENSHOT_BYTES = 4 * 1024 * 1024


class DecisionModel(Protocol):
    """Anything that can return a schema-validated object for a prompt."""

    async def generate(
        self, prompt: str, *, system_instruction: str, schema: type[T], image_bytes: bytes | None = None
    ) -> T: ...


class GeminiDecisionModel:
    """DecisionModel backed by GeminiService structured output (`response_schema`)."""

    def __init__(self, service=None) -> None:  # noqa: ANN001 - GeminiService
        from app.llm.service import GeminiService

        self._service = service or GeminiService()

    async def generate(self, prompt, *, system_instruction, schema, image_bytes=None):  # noqa: ANN001
        return await self._service.generate_structured(
            prompt, schema, system_instruction=system_instruction, image_bytes=image_bytes
        )


def screenshot_bytes(obs: PageObservation) -> bytes | None:
    if not obs.screenshot_path:
        return None
    p = Path(obs.screenshot_path)
    try:
        return p.read_bytes() if p.is_file() and p.stat().st_size <= _MAX_SCREENSHOT_BYTES else None
    except OSError:
        return None


@dataclass
class PlanResult:
    action: AgentAction
    attempts: int = 0
    rejections: list[str] = field(default_factory=list)
    rejection_codes: list[str] = field(default_factory=list)
    used_fallback: bool = False


def finish_action(reason: str = "No safe, untried actions remain.") -> AgentAction:
    return AgentAction(
        action_type=ActionType.FINISH,
        expected_outcome=ExpectedOutcome(summary="The exploration run ends."),
        reason=reason, exploration_priority=0.0,
    )


def sample_text(input_type: str | None, name: str) -> str:
    """Deterministic edge-case-flavoured input for the fallback planner."""
    n = (input_type or "").lower()
    lname = name.lower()
    if n == "email" or "email" in lname:
        return "not-an-email"
    if n in ("number", "tel") or "phone" in lname or "quantity" in lname or "qty" in lname:
        return "-1"
    if n == "url":
        return "notaurl"
    if n == "password" or "password" in lname:
        return "Test1234!"
    return "test input"


class Planner:
    def __init__(
        self, model: DecisionModel, policy: PolicyEngine, *, max_attempts: int = 3, send_screenshot: bool = True
    ) -> None:
        self.model = model
        self.policy = policy
        self.max_attempts = max(1, max_attempts)
        self.send_screenshot = send_screenshot

    async def plan(self, inp: AgentInput, memory: ExplorationMemory) -> PlanResult:
        result = PlanResult(action=finish_action())
        feedback: list[str] = list(inp.feedback)
        image = screenshot_bytes(inp.observation) if self.send_screenshot else None

        for attempt in range(1, self.max_attempts + 1):
            result.attempts = attempt
            attempt_input = inp.model_copy(update={"feedback": feedback})
            try:
                raw = await self.model.generate(
                    build_planner_prompt(attempt_input), system_instruction=PLANNER_SYSTEM_PROMPT,
                    schema=AgentAction, image_bytes=image,
                )
                action = raw if isinstance(raw, AgentAction) else parse_decision(raw)
            except ValidationError as exc:
                msg = f"Invalid decision: {validation_summary(exc)}"
            except DecisionError as exc:
                msg = f"Invalid decision: {exc}"
            except ValueError as exc:
                msg = f"Invalid decision: {str(exc)[:300]}"
            except Exception as exc:  # noqa: BLE001 - model/network failure => stop retrying, use fallback
                logger.warning("planner_model_failed", error_type=type(exc).__name__)
                result.rejections.append(f"model unavailable: {type(exc).__name__}")
                result.rejection_codes.append("model_error")
                break
            else:
                verdict = self.policy.check(action, inp.observation, memory, step=inp.step, max_steps=inp.max_steps)
                if verdict.allowed:
                    result.action = action
                    return result
                msg = f"{action.describe()} rejected: {verdict.feedback}"
                result.rejection_codes.append(verdict.code.value)
                logger.info("planner_action_rejected", code=verdict.code.value, action=action.action_type.value)
            if len(result.rejection_codes) <= len(result.rejections):
                result.rejection_codes.append("invalid_decision")
            result.rejections.append(msg)
            feedback.append(msg)

        result.used_fallback = True
        result.action = self.fallback_action(inp, memory)
        return result

    # ------------------------------------------------------------------ deterministic fallback
    def fallback_action(self, inp: AgentInput, memory: ExplorationMemory) -> AgentAction:
        obs = inp.observation
        present = {e.id: e for e in obs.interactive_elements}
        tried_urls: set[str] = set()
        for t in inp.unexplored_transitions:
            action = self._candidate(t, present, tried_urls)
            if action is None:
                continue
            if self.policy.check(action, obs, memory, step=inp.step, max_steps=inp.max_steps).allowed:
                return action
        return finish_action()

    def _candidate(
        self, t: UnexploredTransition, present: dict, tried_urls: set[str]
    ) -> AgentAction | None:
        if not t.in_current_state:
            if t.state_url in tried_urls:
                return None
            tried_urls.add(t.state_url)
            return AgentAction(
                action_type=ActionType.OPEN, arguments=ActionArguments(url=t.state_url),
                expected_outcome=ExpectedOutcome(summary="An area with untried elements loads.", expects_navigation=True),
                reason="Returning to a state with untried elements.", exploration_priority=0.8,
            )
        el = present.get(t.element_id)
        if el is None:
            return None
        label = (t.name or t.role)[:40]
        if t.suggested_action == ActionType.TYPE:
            return AgentAction(
                action_type=ActionType.TYPE, target=el.id,
                arguments=ActionArguments(text=sample_text(el.input_type, el.name), clear_first=True),
                expected_outcome=ExpectedOutcome(summary=f'The "{label}" field accepts the input.'),
                reason=f'Exercising the "{label}" field.', exploration_priority=0.7,
            )
        if t.suggested_action == ActionType.SELECT:
            return AgentAction(
                action_type=ActionType.SELECT, target=el.id, arguments=ActionArguments(index=0),
                expected_outcome=ExpectedOutcome(summary=f'The "{label}" selection changes.'),
                reason=f'Exploring the "{label}" options.', exploration_priority=0.7,
            )
        nav = t.role == "link" and bool(t.href and not t.href.startswith("#"))
        return AgentAction(
            action_type=ActionType.CLICK, target=el.id,
            expected_outcome=ExpectedOutcome(
                summary=f'Activating "{label}" navigates or shows feedback.', expects_navigation=nav),
            reason=f'Exploring untried {t.role} "{label}".', exploration_priority=0.9,
        )
