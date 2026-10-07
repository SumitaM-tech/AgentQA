"""Business logic for Projects. Routes call into here rather than talking
to SQLAlchemy directly, so the same logic is reusable/testable outside the
HTTP layer."""
from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.project import Project
from app.models.bug import Bug
from app.models.test_run import TestRun
from app.schemas.project import ProjectCreate, ProjectRead, ProjectUpdate

logger = get_logger(__name__)


async def create_project(db: AsyncSession, payload: ProjectCreate) -> Project:
    project = Project(
        name=payload.name,
        description=payload.description,
        base_url=str(payload.base_url),
        allowed_domains=payload.allowed_domains,
        default_goals=payload.default_goals,
    )
    db.add(project)
    await db.flush()
    await db.refresh(project)
    logger.info("project_created", project_id=str(project.id), name=project.name)
    return project


async def list_projects(db: AsyncSession, limit: int = 100, offset: int = 0) -> list[Project]:
    result = await db.execute(
        select(Project).order_by(Project.created_at.desc()).limit(limit).offset(offset)
    )
    return list(result.scalars().all())


async def get_project(db: AsyncSession, project_id: UUID) -> Project:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


async def update_project(db: AsyncSession, project_id: UUID, payload: ProjectUpdate) -> Project:
    project = await get_project(db, project_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is not None or field == "description":
            setattr(project, field, value)
    await db.flush()
    return project


async def delete_project(db: AsyncSession, project_id: UUID) -> None:
    from app.services.run_manager import ACTIVE_STATUSES

    project = await get_project(db, project_id)
    active = (await db.execute(select(func.count()).select_from(TestRun).where(
        TestRun.project_id == project_id, TestRun.status.in_(ACTIVE_STATUSES)))).scalar_one()
    if active:
        raise HTTPException(status.HTTP_409_CONFLICT, "Stop the project's active runs before deleting it.")
    await db.delete(project)


async def with_counts(db: AsyncSession, projects: list[Project]) -> list[ProjectRead]:
    ids = [p.id for p in projects]
    runs = dict((await db.execute(select(TestRun.project_id, func.count()).where(TestRun.project_id.in_(ids))
                                  .group_by(TestRun.project_id))).all()) if ids else {}
    bugs = dict((await db.execute(select(Bug.project_id, func.count()).where(Bug.project_id.in_(ids))
                                  .group_by(Bug.project_id))).all()) if ids else {}
    out = []
    for p in projects:
        r = ProjectRead.model_validate(p)
        r.run_count, r.bug_count = runs.get(p.id, 0), bugs.get(p.id, 0)
        out.append(r)
    return out
