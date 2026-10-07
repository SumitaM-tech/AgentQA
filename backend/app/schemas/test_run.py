from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class TestRunStatus(str, Enum):
    QUEUED = "queued"
    INITIALIZING = "initializing"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


class TestRunCreate(BaseModel):
    project_id: UUID
    goal: str = Field(min_length=1, max_length=2000)
    target_url: HttpUrl | None = Field(
        default=None,
        description="Overrides the project's base_url for this run, if provided.",
    )
    max_steps: int = Field(default=25, ge=1, le=500)
    username: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, max_length=255)


class TestRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    goal: str
    target_url: str
    max_steps: int
    steps_taken: int
    status: TestRunStatus
    has_credentials: bool
    error_message: str | None
    created_at: datetime
    updated_at: datetime
