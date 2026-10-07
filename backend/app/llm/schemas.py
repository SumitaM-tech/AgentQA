"""Pydantic schemas for the Gemini QA-reasoning integration.

`reason` fields are user-facing operational notes ONLY (e.g. "Testing
invalid checkout input.") — never internal chain-of-thought. Enums are
reused from `app.agent.legacy_state` so both layers share one vocabulary.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.agent.legacy_state import ActionType, BugSeverity

__all__ = ["ActionType", "BugSeverity", "ExpectedOutcome", "AgentDecision", "BugAnalysis", "BugReport"]


class ExpectedOutcome(BaseModel):
    summary: str = Field(
        description="One concrete, falsifiable sentence, e.g. 'Submitting the empty form shows a required-field error.'"
    )
    url_change: str | None = Field(default=None, description="Expected new URL/path, if navigation is expected.")
    new_elements: list[str] = Field(default_factory=list, description="UI elements expected to appear.")
    console_clean: bool = Field(default=True, description="Whether the console should stay free of errors.")


class AgentDecision(BaseModel):
    action_type: ActionType
    target: str | None = Field(
        default=None, description="element_id from the provided interactive elements list, if the action targets one."
    )
    arguments: dict[str, str] = Field(
        default_factory=dict, description="e.g. {'value': 'text'} for fill, {'key': 'Enter'} for press_key."
    )
    reason: str = Field(
        max_length=200,
        description="ONE short user-facing sentence, e.g. 'Testing invalid checkout input.' "
        "Never internal step-by-step reasoning.",
    )
    expected_outcome: ExpectedOutcome
    confidence: float = Field(ge=0.0, le=1.0)
    exploration_priority: float = Field(
        ge=0.0, le=1.0, description="1.0 = mainly reaching unexplored states, 0.0 = mainly pursuing the QA goal."
    )


class BugAnalysis(BaseModel):
    is_bug: bool
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(max_length=300, description="One concise user-facing sentence, not internal reasoning.")
    discrepancies: list[str] = Field(default_factory=list)


class BugReport(BaseModel):
    title: str
    severity: BugSeverity
    description: str
    steps_to_reproduce: list[str]
    expected_behavior: str
    actual_behavior: str
    fix_proposal: str | None = None
