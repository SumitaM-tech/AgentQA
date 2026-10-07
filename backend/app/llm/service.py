"""GeminiService — the reusable, high-level Gemini integration.

  1. Text requests            -> generate_text
  2. Image + text requests    -> generate_text(image_bytes=...)
  3. Structured JSON          -> generate_structured (response_schema; SDK-parsed)
  4. Function/tool calling    -> generate_with_tool (forced function call)
  5-7. Retry / timeout / rate-limit handling -> client.py
  8. Logging without the API key             -> client.py

Standalone: not yet wired to Playwright or the existing orchestrator
(which still uses `app.llm.gemini_client`). Reconcile later by having the
orchestrator adopt AgentDecision / BugAnalysis.
"""
from __future__ import annotations

from typing import TypeVar

from google.genai import types
from pydantic import BaseModel

from app.core.logging import get_logger
from app.llm.client import GeminiClient
from app.llm.prompts import (
    AGENT_DECISION_SYSTEM_PROMPT,
    BUG_ANALYSIS_SYSTEM_PROMPT,
    BUG_REPORT_SYSTEM_PROMPT,
    build_agent_decision_context,
    build_bug_analysis_context,
    build_bug_report_context,
)
from app.llm.schemas import AgentDecision, BugAnalysis, BugReport
from app.llm.tool_definitions import forced_tool_config, tool_for

logger = get_logger(__name__)

SchemaT = TypeVar("SchemaT", bound=BaseModel)


def _contents(prompt: str, image_bytes: bytes | None, mime: str) -> list:
    contents: list = [prompt]
    if image_bytes is not None:
        contents.append(types.Part.from_bytes(data=image_bytes, mime_type=mime))
    return contents


class GeminiService:
    def __init__(self, client: GeminiClient | None = None) -> None:
        self._client = client or GeminiClient()

    @property
    def model_name(self) -> str:
        return self._client.model_name

    async def generate_text(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        image_bytes: bytes | None = None,
        image_mime_type: str = "image/png",
        max_output_tokens: int | None = None,
    ) -> str:
        config = types.GenerateContentConfig(
            system_instruction=system_instruction, max_output_tokens=max_output_tokens
        )
        response = await self._client.generate(_contents(prompt, image_bytes, image_mime_type), config)
        return response.text or ""

    async def generate_structured(
        self,
        prompt: str,
        response_model: type[SchemaT],
        *,
        system_instruction: str | None = None,
        image_bytes: bytes | None = None,
        image_mime_type: str = "image/png",
        max_output_tokens: int | None = None,
    ) -> SchemaT:
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=response_model,
            max_output_tokens=max_output_tokens,
        )
        response = await self._client.generate(_contents(prompt, image_bytes, image_mime_type), config)
        parsed = response.parsed
        if isinstance(parsed, response_model):
            return parsed
        if response.text:  # fall back to validating raw JSON text
            return response_model.model_validate_json(response.text)
        raise ValueError(f"Gemini returned no parseable {response_model.__name__}.")

    async def generate_with_tool(
        self,
        prompt: str,
        declaration: types.FunctionDeclaration,
        *,
        system_instruction: str | None = None,
        image_bytes: bytes | None = None,
        image_mime_type: str = "image/png",
        max_output_tokens: int | None = None,
    ) -> dict:
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=[tool_for(declaration)],
            tool_config=forced_tool_config(declaration.name),
            max_output_tokens=max_output_tokens,
        )
        response = await self._client.generate(_contents(prompt, image_bytes, image_mime_type), config)
        for candidate in response.candidates or []:
            for part in (candidate.content.parts if candidate.content else []) or []:
                if getattr(part, "function_call", None):
                    return dict(part.function_call.args)
        raise ValueError("Gemini response contained no function call.")

    # -- QA-domain helpers ------------------------------------------------------

    async def decide_next_action(
        self,
        *,
        goal: str,
        current_url: str,
        page_title: str,
        accessibility_tree_summary: str,
        interactive_elements_summary: str,
        previous_action_summary: str = "(none — first step)",
        previous_expected_outcome: str | None = None,
        previous_observed_outcome: str | None = None,
        discovered_states_summary: str = "(none yet)",
        unexplored_actions_summary: str = "(none yet)",
        page_text_summary: str = "",
        page_issues_summary: str = "",
        screenshot_bytes: bytes | None = None,
    ) -> AgentDecision:
        prompt = build_agent_decision_context(
            goal=goal,
            current_url=current_url,
            page_title=page_title,
            accessibility_tree_summary=accessibility_tree_summary,
            interactive_elements_summary=interactive_elements_summary,
            previous_action_summary=previous_action_summary,
            previous_expected_outcome=previous_expected_outcome,
            previous_observed_outcome=previous_observed_outcome,
            discovered_states_summary=discovered_states_summary,
            unexplored_actions_summary=unexplored_actions_summary,
            page_text_summary=page_text_summary,
            page_issues_summary=page_issues_summary,
        )
        decision = await self.generate_structured(
            prompt, AgentDecision, system_instruction=AGENT_DECISION_SYSTEM_PROMPT, image_bytes=screenshot_bytes
        )
        logger.info("agent_decision", action=decision.action_type.value, confidence=decision.confidence)
        return decision

    async def analyze_outcome(
        self,
        *,
        expected_outcome: str,
        actual_url: str,
        actual_title: str,
        console_messages: list[str] | None = None,
        failed_network_requests: list[str] | None = None,
        screenshot_bytes: bytes | None = None,
    ) -> BugAnalysis:
        prompt = build_bug_analysis_context(
            expected_outcome=expected_outcome,
            actual_url=actual_url,
            actual_title=actual_title,
            console_messages=console_messages or [],
            failed_network_requests=failed_network_requests or [],
        )
        return await self.generate_structured(
            prompt, BugAnalysis, system_instruction=BUG_ANALYSIS_SYSTEM_PROMPT, image_bytes=screenshot_bytes
        )

    async def generate_bug_report(
        self, evidence_trail: str, *, screenshot_bytes: bytes | None = None
    ) -> BugReport:
        return await self.generate_structured(
            build_bug_report_context(evidence_trail),
            BugReport,
            system_instruction=BUG_REPORT_SYSTEM_PROMPT,
            image_bytes=screenshot_bytes,
        )
