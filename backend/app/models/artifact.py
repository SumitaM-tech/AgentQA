"""Artifact — a stored file produced during a TestRun: screenshot, DOM
snapshot, or Playwright trace. Referenced by id from UIState."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, uuid_pk

if TYPE_CHECKING:
    from app.models.test_run import TestRun


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[uuid.UUID] = uuid_pk()
    test_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("test_runs.id", ondelete="CASCADE"))
    artifact_type: Mapped[str] = mapped_column(String(32))
    # "screenshot" | "dom_snapshot" | "trace"
    storage_path: Mapped[str] = mapped_column(String(2048))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    test_run: Mapped["TestRun"] = relationship(back_populates="artifacts")
