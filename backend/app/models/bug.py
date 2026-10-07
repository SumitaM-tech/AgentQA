"""Bug — a confirmed, evidence-backed finding for a TestRun. Generated
(later) by the AI agent after a verification pass; for now this is a
plain persisted entity with no AI wiring."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, uuid_pk

if TYPE_CHECKING:
    from app.models.test_run import TestRun


class Bug(Base):
    __tablename__ = "bugs"

    id: Mapped[uuid.UUID] = uuid_pk()
    test_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("test_runs.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(512))
    severity: Mapped[str] = mapped_column(String(16))
    # "critical" | "high" | "medium" | "low" | "cosmetic"
    description: Mapped[str] = mapped_column(Text)
    steps_to_reproduce: Mapped[list] = mapped_column(JSON, default=list)
    expected_behavior: Mapped[str] = mapped_column(Text)
    actual_behavior: Mapped[str] = mapped_column(Text)
    related_state_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ui_states.id"), nullable=True
    )
    related_transition_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ui_transitions.id"), nullable=True
    )
    fix_proposal: Mapped[str | None] = mapped_column(Text, nullable=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)
    category: Mapped[str] = mapped_column(String(64), default="functional")
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    status: Mapped[str] = mapped_column(String(16), default="unverified")  # "verified" | "unverified"
    url: Mapped[str] = mapped_column(String(2048), default="")
    state_key: Mapped[str] = mapped_column(String(64), default="")  # UIState.fingerprint
    fingerprint: Mapped[str] = mapped_column(String(64), default="", index=True)  # dedup key
    screenshot_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    console_errors: Mapped[list] = mapped_column(JSON, default=list)
    network_errors: Mapped[list] = mapped_column(JSON, default=list)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    severity_reason: Mapped[str] = mapped_column(Text, default="")
    verification: Mapped[dict] = mapped_column(JSON, default=dict)  # reproduction attempts + outcome
    resolution: Mapped[str] = mapped_column(String(16), default="open")  # "open" | "resolved"
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    seen_before_count: Mapped[int] = mapped_column(Integer, default=0)  # same fingerprint in earlier runs
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    test_run: Mapped["TestRun"] = relationship(back_populates="bugs")
