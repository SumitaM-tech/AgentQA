"""Request/response models for the run, bug, graph and event APIs."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.artifacts import to_url
from app.core.config import get_settings
from app.schemas.test_run import TestRunStatus


class AuthConfig(BaseModel):
    username: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, max_length=255, repr=False)


class RunCreate(BaseModel):
    url: str = Field(min_length=4, max_length=2048)
    goal: str = Field(default="Explore the application and look for bugs.", min_length=1, max_length=2000)
    max_steps: int | None = Field(default=None, ge=1, le=500)
    max_runtime_seconds: int | None = Field(default=None, ge=10, le=3600)
    max_depth: int | None = Field(default=None, ge=1, le=50)
    max_retries: int | None = Field(default=None, ge=0, le=5)
    project_id: UUID | None = None
    auth: AuthConfig | None = None

    @field_validator("url")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    def resolved(self) -> dict[str, int]:
        s = get_settings()
        return {
            "max_steps": self.max_steps or s.max_steps,
            "max_runtime_seconds": self.max_runtime_seconds or s.max_runtime_seconds,
            "max_depth": self.max_depth or s.max_depth,
            "max_retries": s.max_retries if self.max_retries is None else self.max_retries,
        }


class RunCreated(BaseModel):
    run_id: UUID
    status: TestRunStatus
    warnings: list[str] = Field(default_factory=list)


class RunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    goal: str
    target_url: str
    status: TestRunStatus
    max_steps: int
    max_runtime_seconds: int
    max_depth: int
    max_retries: int
    steps_taken: int
    states_count: int
    actions_count: int
    bugs_count: int
    errors_count: int
    coverage: float
    candidates_count: int = 0
    discarded_count: int = 0
    first_bug_at: datetime | None = None
    has_credentials: bool
    error_message: str | None
    termination_reason: str | None
    termination_detail: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime
    last_screenshot: str | None = None
    last_screenshot_url: str | None = None
    duration_seconds: float | None = None

    @classmethod
    def from_row(cls, row: Any) -> "RunRead":
        out = cls.model_validate(row)
        out.last_screenshot_url = to_url(row.last_screenshot)
        if row.started_at:
            end = row.finished_at or datetime.utcnow()
            out.duration_seconds = round((end - row.started_at).total_seconds(), 1)
        return out


class BugOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    test_run_id: UUID
    title: str
    severity: str
    category: str
    confidence: float
    status: str
    description: str
    steps_to_reproduce: list[str]
    expected_behavior: str
    actual_behavior: str
    url: str
    state_key: str
    related_state_id: UUID | None
    fingerprint: str
    resolution: str = "open"
    resolved_at: datetime | None = None
    bug_ref: str = ""
    severity_reason: str
    evidence: list[str]
    console_errors: list[str]
    network_errors: list[str]
    verification: dict[str, Any]
    seen_before_count: int
    fix_proposal: str | None
    created_at: datetime
    screenshot_url: str | None = None

    @classmethod
    def from_row(cls, row: Any) -> "BugOut":
        out = cls.model_validate(row)
        out.screenshot_url = to_url(row.screenshot_path)
        out.bug_ref = "BUG-" + str(row.id).split("-")[0].upper()
        return out


class StateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    test_run_id: UUID
    fingerprint: str
    url: str
    title: str
    depth: int
    visit_count: int
    discovered_at_step: int
    visible_text_summary: str
    interactive_elements: list[dict[str, Any]]
    created_at: datetime
    last_seen_at: datetime
    screenshot_url: str | None = None
    bug_count: int = 0

    @classmethod
    def from_row(cls, row: Any, bug_count: int = 0) -> "StateOut":
        out = cls.model_validate(row)
        out.screenshot_url = to_url(row.screenshot_path)
        out.bug_count = bug_count
        return out


class EdgeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_state_id: UUID
    target_state_id: UUID
    action_type: str
    action_label: str
    action_parameters: dict[str, Any]
    expected_result: str
    actual_result: str
    verdict: str | None
    target_element_id: str | None = None
    step_index: int
    created_at: datetime


class GraphOut(BaseModel):
    states: list[StateOut]
    edges: list[EdgeOut]
    current_state_id: UUID | None = None


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    seq: int
    type: str
    message: str
    data: dict[str, Any]
    timestamp: datetime


class TargetCheckRequest(BaseModel):
    url: str = Field(max_length=2048)


class TargetCheckOut(BaseModel):
    ok: bool
    url: str
    error: str | None = None
    warnings: list[str] = Field(default_factory=list)
