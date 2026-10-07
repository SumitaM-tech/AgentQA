"""Run lifecycle + read APIs.

POST   /api/runs                  create (status=queued)
GET    /api/runs                  list
GET    /api/runs/{id}             detail
POST   /api/runs/{id}/start|stop|pause|resume
GET    /api/runs/{id}/states|graph|bugs|events|actions
POST   /api/targets/validate      URL safety check for the UI
"""
from __future__ import annotations

from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status, Response
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.url_security import check_target_url, host_matches
from app.database.session import get_db_session
from app.models.bug import Bug
from app.models.project import Project
from app.models.run_event import RunEvent
from app.models.test_run import TestRun
from app.models.ui_state import UIState
from app.models.ui_transition import UITransition
from app.schemas.agent_action import AgentActionRead
from app.schemas.runs_api import (
    BugOut, EdgeOut, EventOut, GraphOut, RunCreate, RunCreated, RunRead, StateOut, TargetCheckOut, TargetCheckRequest,
)
from app.services import run_service
from app.services.run_manager import ACTIVE_STATUSES, get_run_manager

router = APIRouter(tags=["runs"])


@router.post("/api/targets/validate", response_model=TargetCheckOut)
async def validate_target(payload: TargetCheckRequest) -> TargetCheckOut:
    r = await check_target_url(payload.url)
    return TargetCheckOut(ok=r.ok, url=r.url, error=r.error, warnings=r.warnings)


async def _project_for(db: AsyncSession, url: str) -> Project:
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    host = parts.hostname or origin
    found = (await db.execute(select(Project).where(Project.base_url == origin))).scalars().first()
    if found:
        return found
    project = Project(name=host, base_url=origin, description="Created automatically from a QA run.")
    db.add(project)
    await db.flush()
    return project


@router.post("/api/runs", response_model=RunCreated, status_code=status.HTTP_201_CREATED)
async def create_run(payload: RunCreate, db: AsyncSession = Depends(get_db_session)) -> RunCreated:
    project: Project | None = None
    if payload.project_id:
        project = (await db.execute(select(Project).where(Project.id == payload.project_id))).scalar_one_or_none()
        if project is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    allowed = None
    if project is not None and project.allowed_domains:
        allowed = list(project.allowed_domains)
        if get_settings().allowed_domains:  # the server-wide list is the outer boundary
            allowed = [d for d in allowed if host_matches(d, get_settings().allowed_domains)]
    check = await check_target_url(payload.url, allowed_domains=allowed)
    if not check.ok:
        raise HTTPException(status.HTTP_403_FORBIDDEN if check.blocked else status.HTTP_400_BAD_REQUEST, check.error)
    warnings = list(check.warnings)
    if not get_settings().gemini_api_key:
        warnings.append("GEMINI_API_KEY is not set: the agent will fall back to a deterministic explorer.")
    project = project or await _project_for(db, check.url)
    limits = payload.resolved()
    auth = payload.auth
    run = TestRun(
        project_id=project.id, goal=payload.goal, target_url=check.url, status="queued",
        has_credentials=bool(auth and (auth.username or auth.password)), **limits)
    db.add(run)
    await db.flush()
    if auth:
        get_run_manager().set_credentials(run.id, auth.username, auth.password)
    return RunCreated(run_id=run.id, status=run.status, warnings=warnings)


@router.get("/api/runs", response_model=list[RunRead])
async def list_runs(
    status_filter: str | None = Query(default=None, alias="status"), project_id: UUID | None = None,
    q: str | None = Query(default=None, max_length=100), limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0), db: AsyncSession = Depends(get_db_session),
) -> list[RunRead]:
    stmt = select(TestRun).order_by(TestRun.created_at.desc()).limit(limit).offset(offset)
    if status_filter:
        stmt = stmt.where(TestRun.status == status_filter)
    if project_id:
        stmt = stmt.where(TestRun.project_id == project_id)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(TestRun.target_url.ilike(like), TestRun.goal.ilike(like), cast(TestRun.id, String).ilike(like)))
    q = stmt
    return [RunRead.from_row(r) for r in (await db.execute(q)).scalars().all()]


@router.get("/api/runs/{run_id}", response_model=RunRead)
async def get_run(run_id: UUID, db: AsyncSession = Depends(get_db_session)) -> RunRead:
    return RunRead.from_row(await run_service.get_test_run(db, run_id))


@router.delete("/api/runs/{run_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response, response_model=None)
async def delete_run(run_id: UUID, db: AsyncSession = Depends(get_db_session)):
    """Delete a finished run and its states, bugs, events and screenshots."""
    from app.services.retention import delete_run_artifacts

    run = await run_service.get_test_run(db, run_id)
    if run.status in ACTIVE_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, "Stop the run before deleting it.")
    await delete_run_artifacts(db, run_id)
    await db.delete(run)


@router.get("/api/runs/{run_id}/evaluation")
async def get_evaluation(run_id: UUID, db: AsyncSession = Depends(get_db_session)) -> dict:
    from app.evaluation.metrics import evaluate_run

    return await evaluate_run(db, await run_service.get_test_run(db, run_id))


@router.post("/api/runs/{run_id}/start", response_model=RunRead)
async def start_run(run_id: UUID, db: AsyncSession = Depends(get_db_session)) -> RunRead:
    run = await run_service.get_test_run(db, run_id)
    if run.status != "queued":
        raise HTTPException(status.HTTP_409_CONFLICT, f"Run is '{run.status}' — only a 'queued' run can be started.")
    mgr = get_run_manager()
    if mgr.is_active(run_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Run is already starting.")
    await db.commit()  # the background task reads the row in its own session
    mgr.start(run_id)
    return RunRead.from_row(run)


@router.post("/api/runs/{run_id}/stop", response_model=RunRead)
async def stop_run(run_id: UUID, db: AsyncSession = Depends(get_db_session)) -> RunRead:
    run = await run_service.get_test_run(db, run_id)
    if run.status not in ACTIVE_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Run is '{run.status}' and not active.")
    if not await get_run_manager().stop(run_id):
        if run.status == "queued":  # created but never started
            run.status, run.termination_reason = "stopped", "stopped"
        else:
            raise HTTPException(status.HTTP_409_CONFLICT, "Run is not active in this server process.")
    return RunRead.from_row(run)


@router.post("/api/runs/{run_id}/pause", response_model=RunRead)
async def pause_run(run_id: UUID, db: AsyncSession = Depends(get_db_session)) -> RunRead:
    run = await run_service.get_test_run(db, run_id)
    if not await get_run_manager().pause(run_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Only a running run can be paused.")
    await db.refresh(run)
    return RunRead.from_row(run)


@router.post("/api/runs/{run_id}/resume", response_model=RunRead)
async def resume_run(run_id: UUID, db: AsyncSession = Depends(get_db_session)) -> RunRead:
    run = await run_service.get_test_run(db, run_id)
    if not await get_run_manager().resume(run_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Only a paused run can be resumed.")
    await db.refresh(run)
    return RunRead.from_row(run)


async def _bug_counts(db: AsyncSession, run_id: UUID) -> dict[str, int]:
    rows = (await db.execute(select(Bug.state_key, func.count()).where(Bug.test_run_id == run_id)
                             .group_by(Bug.state_key))).all()
    return {k: c for k, c in rows}


@router.get("/api/runs/{run_id}/states", response_model=list[StateOut])
async def get_states(run_id: UUID, db: AsyncSession = Depends(get_db_session)) -> list[StateOut]:
    await run_service.get_test_run(db, run_id)
    counts = await _bug_counts(db, run_id)
    rows = (await db.execute(select(UIState).where(UIState.test_run_id == run_id)
                             .order_by(UIState.discovered_at_step, UIState.created_at))).scalars().all()
    return [StateOut.from_row(r, counts.get(r.fingerprint, 0)) for r in rows]


@router.get("/api/runs/{run_id}/graph", response_model=GraphOut)
async def get_graph(run_id: UUID, db: AsyncSession = Depends(get_db_session)) -> GraphOut:
    await run_service.get_test_run(db, run_id)
    counts = await _bug_counts(db, run_id)
    states = (await db.execute(select(UIState).where(UIState.test_run_id == run_id)
                               .order_by(UIState.discovered_at_step, UIState.created_at))).scalars().all()
    edges = (await db.execute(select(UITransition).where(UITransition.test_run_id == run_id)
                              .order_by(UITransition.step_index))).scalars().all()
    current = max(states, key=lambda s: s.last_seen_at).id if states else None
    return GraphOut(states=[StateOut.from_row(s, counts.get(s.fingerprint, 0)) for s in states],
                    edges=[EdgeOut.model_validate(e) for e in edges], current_state_id=current)


@router.get("/api/runs/{run_id}/bugs", response_model=list[BugOut])
async def get_run_bugs(run_id: UUID, db: AsyncSession = Depends(get_db_session)) -> list[BugOut]:
    await run_service.get_test_run(db, run_id)
    rows = (await db.execute(select(Bug).where(Bug.test_run_id == run_id).order_by(Bug.created_at))).scalars().all()
    return [BugOut.from_row(b) for b in rows]


@router.get("/api/runs/{run_id}/events", response_model=list[EventOut])
async def get_events(
    run_id: UUID, after: int = Query(0, ge=0), limit: int = Query(500, ge=1, le=2000),
    db: AsyncSession = Depends(get_db_session),
) -> list[EventOut]:
    await run_service.get_test_run(db, run_id)
    rows = (await db.execute(select(RunEvent).where(RunEvent.test_run_id == run_id, RunEvent.seq > after)
                             .order_by(RunEvent.seq).limit(limit))).scalars().all()
    return [EventOut.model_validate(e) for e in rows]


@router.get("/api/runs/{run_id}/actions", response_model=list[AgentActionRead])
async def get_run_actions(run_id: UUID, db: AsyncSession = Depends(get_db_session)) -> list[AgentActionRead]:
    return [AgentActionRead.model_validate(a) for a in await run_service.list_actions_for_run(db, run_id)]
