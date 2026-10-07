from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session
from app.schemas.project import ProjectCreate, ProjectRead, ProjectUpdate
from app.services import project_service

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreate, db: AsyncSession = Depends(get_db_session)
) -> ProjectRead:
    project = await project_service.create_project(db, payload)
    return (await project_service.with_counts(db, [project]))[0]


@router.get("", response_model=list[ProjectRead])
async def list_projects(
    limit: int = 100, offset: int = 0, db: AsyncSession = Depends(get_db_session)
) -> list[ProjectRead]:
    projects = await project_service.list_projects(db, limit=limit, offset=offset)
    return await project_service.with_counts(db, projects)


@router.get("/{project_id}", response_model=ProjectRead)
async def get_project(
    project_id: UUID, db: AsyncSession = Depends(get_db_session)
) -> ProjectRead:
    project = await project_service.get_project(db, project_id)
    return (await project_service.with_counts(db, [project]))[0]


@router.patch("/{project_id}", response_model=ProjectRead)
async def update_project(
    project_id: UUID, payload: ProjectUpdate, db: AsyncSession = Depends(get_db_session)
) -> ProjectRead:
    project = await project_service.update_project(db, project_id, payload)
    return (await project_service.with_counts(db, [project]))[0]


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response, response_model=None)
async def delete_project(project_id: UUID, db: AsyncSession = Depends(get_db_session)):
    await project_service.delete_project(db, project_id)
