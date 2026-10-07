"""Project — top-level container. A user creates a Project once per app
they're testing, then runs many TestRuns against it over time."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, uuid_pk

if TYPE_CHECKING:
    from app.models.test_run import TestRun


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    base_url: Mapped[str] = mapped_column(String(2048))
    allowed_domains: Mapped[list] = mapped_column(JSON, default=list)
    default_goals: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    test_runs: Mapped[list["TestRun"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
