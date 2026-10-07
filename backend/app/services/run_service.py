"""Business logic for TestRuns and their child collections (actions, bugs).

Creating a run only persists it in status="pending" here — actually
starting the AI agent's exploration loop is out of scope until the agent
layer is implemented (see AgentOrchestrator in app/agent/orchestrator.py).
"""
from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.agent_action import AgentAction
from app.models.bug import Bug
from app.models.test_run import TestRun
from app.schemas.test_run import TestRunCreate
from app.services.project_service import get_project

logger = get_logger(__name__)


async def create_test_run(db: AsyncSession, payload: TestRunCreate) -> TestRun:
    project = await get_project(db, payload.project_id)

    run = TestRun(
        project_id=project.id,
        goal=payload.goal,
        target_url=str(payload.target_url) if payload.target_url else project.base_url,
        max_steps=payload.max_steps,
        status="pending",
        has_credentials=bool(payload.username and payload.password),
    )
    db.add(run)
    await db.flush()
    await db.refresh(run)
    logger.info("test_run_created", test_run_id=str(run.id), project_id=str(project.id))
    return run


async def get_test_run(db: AsyncSession, test_run_id: UUID) -> TestRun:
    result = await db.execute(select(TestRun).where(TestRun.id == test_run_id))
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test run not found")
    return run


async def list_actions_for_run(db: AsyncSession, test_run_id: UUID) -> list[AgentAction]:
    await get_test_run(db, test_run_id)  # 404s if the run doesn't exist
    result = await db.execute(
        select(AgentAction)
        .where(AgentAction.test_run_id == test_run_id)
        .order_by(AgentAction.step_index.asc())
    )
    return list(result.scalars().all())


async def list_bugs_for_run(db: AsyncSession, test_run_id: UUID) -> list[Bug]:
    await get_test_run(db, test_run_id)
    result = await db.execute(
        select(Bug).where(Bug.test_run_id == test_run_id).order_by(Bug.created_at.asc())
    )
    return list(result.scalars().all())
