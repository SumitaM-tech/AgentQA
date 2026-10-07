"""UIState — a distinct, de-duplicated UI state discovered during a
TestRun (a node in the exploration graph), keyed by a structural
fingerprint. Screenshot/DOM snapshot are stored as Artifacts and
referenced by id."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, uuid_pk

if TYPE_CHECKING:
    from app.models.test_run import TestRun


class UIState(Base):
    __tablename__ = "ui_states"
    __table_args__ = (UniqueConstraint("test_run_id", "fingerprint", name="uq_ui_states_run_fingerprint"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    test_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("test_runs.id", ondelete="CASCADE"))
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)  # deterministic hash, not raw DOM
    url: Mapped[str] = mapped_column(String(2048))
    title: Mapped[str] = mapped_column(String(512))
    screenshot_artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("artifacts.id"), nullable=True
    )
    dom_snapshot_artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("artifacts.id"), nullable=True
    )
    discovered_at_step: Mapped[int] = mapped_column(Integer)
    visit_count: Mapped[int] = mapped_column(Integer, default=1)
    depth: Mapped[int] = mapped_column(Integer, default=0)
    screenshot_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    visible_text_summary: Mapped[str] = mapped_column(Text, default="")
    interactive_elements: Mapped[list] = mapped_column(JSON, default=list)  # compact summaries, not raw DOM
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    test_run: Mapped["TestRun"] = relationship(back_populates="ui_states")
