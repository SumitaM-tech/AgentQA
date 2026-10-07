"""MemoryRecord — long-term agent memory shared by all runs of a project.

kind = "action"  key = "<state_fingerprint>|<action_key>"  payload = {"useful": bool, "failed": bool, "count": n}
kind = "url"     key = normalized URL                       payload = {"count": n}
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, uuid_pk


class MemoryRecord(Base):
    __tablename__ = "memory_records"
    __table_args__ = (UniqueConstraint("project_id", "kind", "key", name="uq_memory_project_kind_key"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    key: Mapped[str] = mapped_column(String(600))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    count: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
