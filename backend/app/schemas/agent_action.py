from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AgentActionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    test_run_id: UUID
    step_index: int
    action_type: str
    target_element_id: str | None
    action_value: str | None
    reasoning: str
    expected_summary: str
    verdict_outcome: str | None
    verdict_confidence: float | None
    verdict_reasoning: str | None
    created_at: datetime
