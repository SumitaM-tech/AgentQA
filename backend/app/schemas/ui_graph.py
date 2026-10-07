from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class UIStateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    test_run_id: UUID
    fingerprint: str
    url: str
    title: str
    discovered_at_step: int
    created_at: datetime


class UITransitionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    test_run_id: UUID
    source_state_id: UUID
    target_state_id: UUID
    action_type: str
    target_element_id: str | None
    step_index: int
    created_at: datetime
