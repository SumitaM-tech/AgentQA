"""Thin wrapper around google-genai, exposing exactly the three semantic
operations the orchestrator needs. Nothing outside this module (and
`prompts.py`) should import google-genai directly.

Model name, token limits and timeout are all env-configurable via
`app.core.config.Settings` — never hardcoded here.

Note: this module could not be exercised against a live Gemini API key in
the build sandbox (no network egress to googleapis.com there). Structure
follows the documented google-genai function-calling flow; validate
against a real key before relying on it in production.
"""
from __future__ import annotations

from pathlib import Path

from google import genai
from google.genai import types
from tenacity import retry, stop_after_attempt, wait_exponential

from app.agent.legacy_state import (
    Action,
    ActionType,
    AgentState,
    BugReport,
    BugSeverity,
    ExpectedOutcome,
    InteractiveElement,
    Observation,
    StepRecord,
    Verdict,
    VerdictOutcome,
)
from app.core.config import get_settings
from app.core.logging import get_logger
from app.llm.prompts import (
    COMPARE_OUTCOME_SYSTEM_PROMPT,
    GENERATE_BUG_REPORT_SYSTEM_PROMPT,
    PLAN_ACTION_SYSTEM_PROMPT,
)
from app.llm.tools import COMPARE_OUTCOME_TOOL, GENERATE_BUG_REPORT_TOOL, PLAN_ACTION_TOOL

logger = get_logger(__name__)

_RETRY = dict(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))


def _tool_from_schema(schema: dict) -> "types.Tool":
    return types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name=schema["name"],
                description=schema["description"],
                parameters=schema["parameters"],
            )
        ]
    )


def _forced_tool_config(function_name: str) -> "types.ToolConfig":
    return types.ToolConfig(
        function_calling_config=types.FunctionCallingConfig(
            mode=types.FunctionCallingConfigMode.ANY,
            allowed_function_names=[function_name],
        )
    )


def _extract_function_call_args(response) -> dict:  # noqa: ANN001 - genai GenerateContentResponse
    for candidate in response.candidates:
        for part in candidate.content.parts:
            if getattr(part, "function_call", None):
                return dict(part.function_call.args)
    raise ValueError("Gemini response contained no function call.")


def _image_part_from_path(path: str) -> "types.Part | None":
    file_path = Path(path)
    if not file_path.exists():
        return None
    return types.Part.from_bytes(data=file_path.read_bytes(), mime_type="image/png")


def _format_elements(elements: list[InteractiveElement]) -> str:
    lines = [
        f"- id={el.element_id} role={el.role} name={el.accessible_name!r} "
        f"tag={el.tag} visible={el.is_visible} enabled={el.is_enabled}"
        for el in elements[:60]
    ]
    return "\n".join(lines) if lines else "(no interactive elements found)"


def _format_history(history: list[StepRecord]) -> str:
    if not history:
        return "(no actions taken yet this run)"
    lines = []
    for record in history[-5:]:
        outcome = record.verdict.outcome.value if record.verdict else "pending"
        lines.append(
            f"step {record.step_index}: {record.action.action_type.value} "
            f"target={record.action.target_element_id} value={record.action.value!r} -> {outcome}"
        )
    return "\n".join(lines)


class GeminiClient:
    """All Gemini calls use function calling with a forced tool choice, so
    responses are guaranteed to be parseable into the matching Pydantic
    model."""

    def __init__(self) -> None:
        settings = get_settings()
        self._model_name = settings.gemini_model
        self._api_key = settings.gemini_api_key
        self._timeout = settings.gemini_request_timeout_seconds
        self._max_output_tokens = settings.gemini_max_output_tokens
        self._client: genai.Client | None = None

    def _ensure_client(self) -> genai.Client:
        if self._client is None:
            if not self._api_key:
                raise RuntimeError("GEMINI_API_KEY is not set.")
            self._client = genai.Client(api_key=self._api_key)
        return self._client

    @retry(**_RETRY)
    async def plan_action(self, state: AgentState) -> tuple[Action, ExpectedOutcome]:
        client = self._ensure_client()
        obs = state.current_observation

        text_prompt = (
            f"QA goal: {state.goal}\n"
            f"Step {state.steps_taken + 1} of max {state.max_steps}.\n"
            f"Current URL: {obs.url}\nTitle: {obs.title}\n\n"
            f"Interactive elements:\n{_format_elements(obs.interactive_elements)}\n\n"
            f"Recent action history:\n{_format_history(state.recent_history)}\n\n"
            f"Graph so far: {state.graph_summary.total_states} states discovered, "
            f"{len(state.graph_summary.unexplored_state_ids)} with unexplored actions.\n"
            f"Test credentials available: {state.credentials_available}\n"
        )
        contents: list = [text_prompt]
        image_part = _image_part_from_path(obs.screenshot_path)
        if image_part is not None:
            contents.append(image_part)

        response = client.models.generate_content(
            model=self._model_name,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=PLAN_ACTION_SYSTEM_PROMPT,
                tools=[_tool_from_schema(PLAN_ACTION_TOOL)],
                tool_config=_forced_tool_config(PLAN_ACTION_TOOL["name"]),
                max_output_tokens=self._max_output_tokens,
            ),
        )
        args = _extract_function_call_args(response)

        action = Action(
            action_type=ActionType(args["action_type"]),
            target_element_id=args.get("target_element_id"),
            value=args.get("value"),
            reasoning=args["reasoning"],
        )
        expected = ExpectedOutcome(
            expected_summary=args["expected_summary"],
            expected_url_change=args.get("expected_url_change"),
            expected_new_elements=args.get("expected_new_elements") or [],
            expected_console_clean=args.get("expected_console_clean", True),
        )
        logger.info(
            "gemini_plan_action",
            action_type=action.action_type.value,
            target=action.target_element_id,
        )
        return action, expected

    @retry(**_RETRY)
    async def compare_outcome(
        self, expected: ExpectedOutcome, actual: Observation, pre_action_observation: Observation
    ) -> Verdict:
        client = self._ensure_client()

        text_prompt = (
            f"Expected outcome: {expected.expected_summary}\n"
            f"Expected URL change: {expected.expected_url_change}\n"
            f"Expected new elements: {expected.expected_new_elements}\n"
            f"Expected console clean: {expected.expected_console_clean}\n\n"
            f"Pre-action URL: {pre_action_observation.url}\n"
            f"Actual URL: {actual.url}\nActual title: {actual.title}\n"
            f"Actual console messages: {[m.text for m in actual.console_messages][:20]}\n"
            f"Actual failed network requests: {[n.url for n in actual.network_events if not n.ok][:20]}\n"
        )
        contents: list = [text_prompt]
        image_part = _image_part_from_path(actual.screenshot_path)
        if image_part is not None:
            contents.append(image_part)

        response = client.models.generate_content(
            model=self._model_name,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=COMPARE_OUTCOME_SYSTEM_PROMPT,
                tools=[_tool_from_schema(COMPARE_OUTCOME_TOOL)],
                tool_config=_forced_tool_config(COMPARE_OUTCOME_TOOL["name"]),
                max_output_tokens=self._max_output_tokens,
            ),
        )
        args = _extract_function_call_args(response)
        verdict = Verdict(
            outcome=VerdictOutcome(args["outcome"]),
            confidence=float(args["confidence"]),
            reasoning=args["reasoning"],
            discrepancies=args.get("discrepancies") or [],
        )
        logger.info("gemini_compare_outcome", outcome=verdict.outcome.value, confidence=verdict.confidence)
        return verdict

    @retry(**_RETRY)
    async def generate_bug_report(
        self, evidence: list[tuple[Action, ExpectedOutcome, Verdict, Observation]]
    ) -> BugReport:
        client = self._ensure_client()

        trail_lines = []
        for i, (action, expected, verdict, obs) in enumerate(evidence):
            trail_lines.append(
                f"Attempt {i + 1}: action={action.action_type.value} "
                f"target={action.target_element_id} value={action.value!r}\n"
                f"  expected: {expected.expected_summary}\n"
                f"  verdict: {verdict.outcome.value} (confidence {verdict.confidence}) — {verdict.reasoning}\n"
                f"  discrepancies: {verdict.discrepancies}\n"
                f"  resulting URL: {obs.url}"
            )
        text_prompt = "Evidence trail (chronological):\n\n" + "\n\n".join(trail_lines)

        contents: list = [text_prompt]
        for _, _, _, obs in evidence:
            image_part = _image_part_from_path(obs.screenshot_path)
            if image_part is not None:
                contents.append(image_part)

        response = client.models.generate_content(
            model=self._model_name,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=GENERATE_BUG_REPORT_SYSTEM_PROMPT,
                tools=[_tool_from_schema(GENERATE_BUG_REPORT_TOOL)],
                tool_config=_forced_tool_config(GENERATE_BUG_REPORT_TOOL["name"]),
                max_output_tokens=self._max_output_tokens,
            ),
        )
        args = _extract_function_call_args(response)
        report = BugReport(
            title=args["title"],
            severity=BugSeverity(args["severity"]),
            description=args["description"],
            steps_to_reproduce=args["steps_to_reproduce"],
            expected_behavior=args["expected_behavior"],
            actual_behavior=args["actual_behavior"],
            evidence_screenshot_paths=[obs.screenshot_path for _, _, _, obs in evidence],
        )
        logger.info("gemini_bug_report_generated", title=report.title, severity=report.severity.value)
        return report
