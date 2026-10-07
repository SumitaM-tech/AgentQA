"""UITransition — an edge in the exploration graph: an action taken from
one UIState that led to another (or the same) UIState."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, uuid_pk

if TYPE_CHECKING:
    from app.models.test_run import TestRun


class UITransition(Base):
    __tablename__ = "ui_transitions"

    id: Mapped[uuid.UUID] = uuid_pk()
    test_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("test_runs.id", ondelete="CASCADE"))
    source_state_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ui_states.id", ondelete="CASCADE"))
    target_state_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ui_states.id", ondelete="CASCADE"))
    action_type: Mapped[str] = mapped_column(String(32))
    target_element_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    action_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    step_index: Mapped[int] = mapped_column(Integer)
    action_label: Mapped[str] = mapped_column(String(512), default="")
    action_parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    expected_result: Mapped[str] = mapped_column(Text, default="")
    actual_result: Mapped[str] = mapped_column(Text, default="")
    verdict: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    test_run: Mapped["TestRun"] = relationship(back_populates="ui_transitions")
