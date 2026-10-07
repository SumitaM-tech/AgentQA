from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class BugSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    COSMETIC = "cosmetic"


class BugRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    test_run_id: UUID
    title: str
    severity: BugSeverity
    description: str
    steps_to_reproduce: list[str]
    expected_behavior: str
    actual_behavior: str
    related_state_id: UUID | None
    related_transition_id: UUID | None
    fix_proposal: str | None
    created_at: datetime
