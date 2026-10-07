"""Persistence boundary for the exploration graph.

`GraphStore` is a Protocol so a Neo4j implementation can be dropped in later without touching
the agent or recorder. `SqlGraphStore` (PostgreSQL/SQLite via SQLAlchemy) is the default.
A state is identified by its deterministic fingerprint; raw DOM is never stored.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.ui_state import UIState
from app.models.ui_transition import UITransition


@dataclass
class StateWrite:
    fingerprint: str
    url: str
    title: str
    step: int
    depth: int
    summary: str
    elements: list[dict[str, Any]]
    screenshot: str | None


@dataclass
class EdgeWrite:
    source_fingerprint: str
    target_fingerprint: str
    step: int
    action_type: str
    label: str
    parameters: dict[str, Any]
    expected: str
    actual: str
    verdict: str | None
    target_element_id: str | None = None


class GraphStore(Protocol):
    async def upsert_state(self, run_id: UUID, s: StateWrite) -> tuple[UUID, bool]: ...
    async def add_transition(self, run_id: UUID, e: EdgeWrite) -> UUID | None: ...
    async def state_id(self, run_id: UUID, fingerprint: str) -> UUID | None: ...


class SqlGraphStore:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sm = sessionmaker

    async def upsert_state(self, run_id: UUID, s: StateWrite) -> tuple[UUID, bool]:
        """Insert the state, or bump visit_count/last_seen on a revisit. Returns (id, created)."""
        async with self._sm() as db:
            row = (await db.execute(select(UIState).where(
                UIState.test_run_id == run_id, UIState.fingerprint == s.fingerprint))).scalar_one_or_none()
            if row is None:
                row = UIState(
                    test_run_id=run_id, fingerprint=s.fingerprint, url=s.url[:2048], title=s.title[:512],
                    discovered_at_step=s.step, depth=s.depth, screenshot_path=s.screenshot,
                    visible_text_summary=s.summary, interactive_elements=s.elements, visit_count=1,
                )
                db.add(row)
                await db.commit()
                return row.id, True
            values: dict[str, Any] = {"visit_count": UIState.visit_count + 1, "last_seen_at": datetime.utcnow()}
            if s.screenshot:
                values["screenshot_path"] = s.screenshot
            await db.execute(update(UIState).where(UIState.id == row.id).values(**values))
            await db.commit()
            return row.id, False

    async def state_id(self, run_id: UUID, fingerprint: str) -> UUID | None:
        async with self._sm() as db:
            return (await db.execute(select(UIState.id).where(
                UIState.test_run_id == run_id, UIState.fingerprint == fingerprint))).scalar_one_or_none()

    async def add_transition(self, run_id: UUID, e: EdgeWrite) -> UUID | None:
        src = await self.state_id(run_id, e.source_fingerprint)
        dst = await self.state_id(run_id, e.target_fingerprint)
        if src is None or dst is None:
            return None
        async with self._sm() as db:
            row = UITransition(
                test_run_id=run_id, source_state_id=src, target_state_id=dst, action_type=e.action_type,
                target_element_id=e.target_element_id, step_index=e.step, action_label=e.label[:512],
                action_parameters=e.parameters, expected_result=e.expected, actual_result=e.actual, verdict=e.verdict,
            )
            db.add(row)
            await db.commit()
            return row.id
