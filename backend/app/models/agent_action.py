"""AgentAction — full audit log of every action the agent attempted during
a TestRun, with predicted vs actual outcome. This is the complete
step-by-step trail, independent of whether an action produced a new
UITransition in the graph."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, uuid_pk

if TYPE_CHECKING:
    from app.models.test_run import TestRun


class AgentAction(Base):
    __tablename__ = "agent_actions"

    id: Mapped[uuid.UUID] = uuid_pk()
    test_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("test_runs.id", ondelete="CASCADE"))
    step_index: Mapped[int] = mapped_column(Integer)
    action_type: Mapped[str] = mapped_column(String(32))
    # "click" | "fill" | "select" | "hover" | "scroll" | "navigate" |
    # "press_key" | "wait" | "go_back" | "assert" | "finish"
    target_element_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    action_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    reasoning: Mapped[str] = mapped_column(Text)
    expected_summary: Mapped[str] = mapped_column(Text)
    verdict_outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # "as_expected" | "suspicious" | "confirmed_bug" | "false_positive"
    verdict_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    verdict_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    test_run: Mapped["TestRun"] = relationship(back_populates="actions")
