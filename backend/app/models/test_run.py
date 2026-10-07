"""TestRun — one autonomous QA exploration run against a Project's target
URL, with a specific goal and max_steps budget. Parent of AgentAction,
UIState, UITransition, Bug and Artifact for that run."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, uuid_pk

if TYPE_CHECKING:
    from app.models.agent_action import AgentAction
    from app.models.artifact import Artifact
    from app.models.bug import Bug
    from app.models.project import Project
    from app.models.run_event import RunEvent
    from app.models.ui_state import UIState
    from app.models.ui_transition import UITransition


class TestRun(Base):
    __tablename__ = "test_runs"

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    goal: Mapped[str] = mapped_column(Text)
    target_url: Mapped[str] = mapped_column(String(2048))
    max_steps: Mapped[int] = mapped_column(Integer, default=25)
    steps_taken: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="queued")
    # "queued" | "initializing" | "running" | "paused" | "completed" | "failed" | "stopped"
    max_runtime_seconds: Mapped[int] = mapped_column(Integer, default=600)
    max_depth: Mapped[int] = mapped_column(Integer, default=6)
    max_retries: Mapped[int] = mapped_column(Integer, default=1)
    termination_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    termination_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    states_count: Mapped[int] = mapped_column(Integer, default=0)
    actions_count: Mapped[int] = mapped_column(Integer, default=0)
    bugs_count: Mapped[int] = mapped_column(Integer, default=0)
    errors_count: Mapped[int] = mapped_column(Integer, default=0)
    coverage: Mapped[float] = mapped_column(Float, default=0.0)  # tried / discovered interactive elements
    candidates_count: Mapped[int] = mapped_column(Integer, default=0)   # potential bugs that entered verification
    discarded_count: Mapped[int] = mapped_column(Integer, default=0)    # candidates dropped: could not be reproduced
    first_bug_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # first VERIFIED bug
    last_screenshot: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    has_credentials: Mapped[bool] = mapped_column(default=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    project: Mapped["Project"] = relationship(back_populates="test_runs")
    actions: Mapped[list["AgentAction"]] = relationship(
        back_populates="test_run", cascade="all, delete-orphan"
    )
    ui_states: Mapped[list["UIState"]] = relationship(
        back_populates="test_run", cascade="all, delete-orphan"
    )
    ui_transitions: Mapped[list["UITransition"]] = relationship(
        back_populates="test_run", cascade="all, delete-orphan"
    )
    bugs: Mapped[list["Bug"]] = relationship(
        back_populates="test_run", cascade="all, delete-orphan"
    )
    events: Mapped[list["RunEvent"]] = relationship(
        back_populates="test_run", cascade="all, delete-orphan"
    )
    artifacts: Mapped[list["Artifact"]] = relationship(
        back_populates="test_run", cascade="all, delete-orphan"
    )
