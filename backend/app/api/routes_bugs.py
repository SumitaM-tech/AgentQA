"""Cross-run bug queries, resolution workflow, exports, candidate fixes, dashboard analytics, artifacts."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.artifacts import resolve_screenshot
from app.core.config import get_settings
from app.core.logging import get_logger
from app.database.session import get_db_session
from app.fixes.service import MAX_CONTEXT_CHARS, generate_candidate_fix
from app.models.bug import Bug
from app.models.test_run import TestRun
from app.schemas.runs_api import BugOut, RunRead

logger = get_logger(__name__)
router = APIRouter(tags=["bugs"])


class BugPatch(BaseModel):
    resolution: str = Field(pattern="^(open|resolved)$")


class FixRequest(BaseModel):
    source_context: str | None = Field(default=None, max_length=MAX_CONTEXT_CHARS)


async def _get(db: AsyncSession, bug_id: UUID) -> Bug:
    bug = (await db.execute(select(Bug).where(Bug.id == bug_id))).scalar_one_or_none()
    if bug is None:
        raise HTTPException(404, "Bug not found")
    return bug


@router.get("/api/bugs", response_model=list[BugOut])
async def list_bugs(
    severity: str | None = None, status_: str | None = Query(default=None, alias="status"), resolution: str | None = None,
    run_id: UUID | None = None, project_id: UUID | None = None, category: str | None = None,
    q: str | None = Query(default=None, max_length=100), limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db_session),
) -> list[BugOut]:
    stmt = select(Bug).order_by(Bug.created_at.desc()).limit(limit).offset(offset)
    for col, val in ((Bug.severity, severity), (Bug.status, status_), (Bug.resolution, resolution), (Bug.test_run_id, run_id),
                     (Bug.project_id, project_id), (Bug.category, category)):
        if val is not None:
            stmt = stmt.where(col == val)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Bug.title.ilike(like), Bug.url.ilike(like), Bug.description.ilike(like)))
    return [BugOut.from_row(b) for b in (await db.execute(stmt)).scalars().all()]


@router.get("/api/bugs/stats")
async def bug_stats(project_id: UUID | None = None, db: AsyncSession = Depends(get_db_session)) -> dict:
    stmt = select(Bug.severity, Bug.category, Bug.status, Bug.resolution, Bug.confidence)
    if project_id:
        stmt = stmt.where(Bug.project_id == project_id)
    rows = (await db.execute(stmt)).all()
    return {
        "total": len(rows),
        "by_severity": dict(Counter(r[0] for r in rows)),
        "by_category": dict(Counter(r[1] for r in rows)),
        "verified": sum(1 for r in rows if r[2] == "verified"),
        "unverified": sum(1 for r in rows if r[2] != "verified"),
        "open": sum(1 for r in rows if r[3] == "open"),
        "resolved": sum(1 for r in rows if r[3] == "resolved"),
        "avg_confidence": round(sum(r[4] for r in rows) / len(rows), 3) if rows else None,
    }


@router.get("/api/bugs/{bug_id}", response_model=BugOut)
async def get_bug(bug_id: UUID, db: AsyncSession = Depends(get_db_session)) -> BugOut:
    return BugOut.from_row(await _get(db, bug_id))


@router.patch("/api/bugs/{bug_id}", response_model=BugOut)
async def patch_bug(bug_id: UUID, payload: BugPatch, db: AsyncSession = Depends(get_db_session)) -> BugOut:
    bug = await _get(db, bug_id)
    bug.resolution = payload.resolution
    bug.resolved_at = datetime.utcnow() if payload.resolution == "resolved" else None
    return BugOut.from_row(bug)


def _markdown(b: BugOut) -> str:
    steps = "\n".join(f"{i}. {s}" for i, s in enumerate(b.steps_to_reproduce, 1)) or "_none recorded_"
    block = lambda lines: ("```\n" + "\n".join(lines) + "\n```") if lines else "_none captured_"  # noqa: E731
    v = b.verification or {}
    return (
        f"# {b.bug_ref}: {b.title}\n\n"
        f"- **Severity:** {b.severity} ({b.severity_reason or 'n/a'})\n- **Confidence:** {round(b.confidence * 100)}%\n"
        f"- **Category:** {b.category}\n- **Status:** {b.status} / {b.resolution}\n- **URL:** {b.url}\n"
        f"- **Detected:** {b.created_at.isoformat()}Z\n- **Run:** {b.test_run_id}\n- **Fingerprint:** `{b.fingerprint}`\n\n"
        f"## Description\n{b.description}\n\n## Steps to reproduce\n{steps}\n\n"
        f"## Expected\n{b.expected_behavior}\n\n## Actual\n{b.actual_behavior}\n\n"
        f"## Evidence\n{block(b.evidence)}\n\n## Console errors\n{block(b.console_errors)}\n\n## Network errors\n{block(b.network_errors)}\n\n"
        f"## Verification\n" + ("\n".join(f"- {n}" for n in v.get("notes", [])) or "_none_") + "\n"
    )


@router.get("/api/bugs/{bug_id}/export")
async def export_bug(bug_id: UUID, format: str = Query("json", pattern="^(json|md)$"), db: AsyncSession = Depends(get_db_session)) -> Response:
    out = BugOut.from_row(await _get(db, bug_id))
    name = out.bug_ref.lower()
    if format == "md":
        return Response(_markdown(out), media_type="text/markdown; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{name}.md"'})
    return Response(out.model_dump_json(indent=2), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{name}.json"'})


@router.get("/api/bugs/{bug_id}/candidate-fix")
async def get_candidate_fix(bug_id: UUID, db: AsyncSession = Depends(get_db_session)) -> dict:
    bug = await _get(db, bug_id)
    if not bug.fix_proposal:
        raise HTTPException(404, "No candidate fix has been generated for this bug.")
    return json.loads(bug.fix_proposal)


@router.post("/api/bugs/{bug_id}/candidate-fix")
async def create_candidate_fix(bug_id: UUID, payload: FixRequest, db: AsyncSession = Depends(get_db_session)) -> dict:
    """Generate (never apply) a candidate fix. Disabled unless FIX_AGENT_ENABLED=true."""
    if not get_settings().fix_agent_enabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Candidate fixes are disabled. Set FIX_AGENT_ENABLED=true to enable them.")
    if not get_settings().gemini_api_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "GEMINI_API_KEY is not configured.")
    bug = await _get(db, bug_id)
    try:
        result = await generate_candidate_fix(bug, payload.source_context)
    except Exception as exc:  # noqa: BLE001 - Gemini timeouts / rate limits / invalid output
        logger.warning("candidate_fix_failed", bug_id=str(bug_id), error_type=type(exc).__name__)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "The AI service could not produce a fix right now. Try again later.") from exc
    bug.fix_proposal = json.dumps(result)
    return result


@router.get("/api/dashboard/summary")
async def dashboard_summary(db: AsyncSession = Depends(get_db_session)) -> dict:
    runs_total = (await db.execute(select(func.count()).select_from(TestRun))).scalar_one()
    by_sev = dict((await db.execute(select(Bug.severity, func.count()).group_by(Bug.severity))).all())
    verified = (await db.execute(select(func.count()).select_from(Bug).where(Bug.status == "verified"))).scalar_one()
    states = (await db.execute(select(func.coalesce(func.sum(TestRun.states_count), 0)))).scalar_one()
    status_counts = dict((await db.execute(select(TestRun.status, func.count()).group_by(TestRun.status))).all())
    since = datetime.utcnow() - timedelta(days=13)
    recent_all = (await db.execute(select(TestRun).where(TestRun.created_at >= since).order_by(TestRun.created_at))).scalars().all()
    days = [(since + timedelta(days=i)).date() for i in range(14)]
    per_day = Counter(r.created_at.date() for r in recent_all)
    durations = [(r.finished_at - r.started_at).total_seconds() for r in
                 (await db.execute(select(TestRun).where(TestRun.finished_at.is_not(None), TestRun.started_at.is_not(None)).limit(500))).scalars().all()]
    latest = (await db.execute(select(TestRun).order_by(TestRun.created_at.desc()).limit(10))).scalars().all()
    active = sum(status_counts.get(s, 0) for s in ("queued", "initializing", "running", "paused"))
    return {
        "runs_total": runs_total, "runs_active": active, "bugs_total": sum(by_sev.values()), "bugs_verified": verified,
        "bugs_by_severity": by_sev, "states_total": int(states), "status_counts": status_counts,
        "avg_run_duration_seconds": round(sum(durations) / len(durations), 1) if durations else None,
        "runs_by_day": [{"date": d.isoformat(), "runs": per_day.get(d, 0)} for d in days],
        "recent_activity": [{"run_id": str(r.id), "label": r.target_url.split("//")[-1][:24], "states": r.states_count,
                             "actions": r.actions_count, "bugs": r.bugs_count} for r in reversed(latest)],
        "recent_runs": [RunRead.from_row(r).model_dump(mode="json") for r in latest[:5]],
    }


@router.get("/api/settings")
async def read_settings() -> dict:
    """Read-only, non-secret view of the effective configuration (values come from the environment / .env)."""
    s = get_settings()
    return {
        "ai": {"model": s.gemini_model, "temperature": s.gemini_temperature, "api_key_configured": bool(s.gemini_api_key),
               "max_steps": s.max_steps, "max_runtime_seconds": s.max_runtime_seconds, "max_depth": s.max_depth,
               "max_retries": s.max_retries, "fix_agent_enabled": s.fix_agent_enabled},
        "browser": {"engine": "chromium", "headless": s.browser_headless, "max_concurrent_browsers": s.max_concurrent_browsers,
                    "max_sessions": s.browser_max_sessions},
        "security": {"allowed_domains": s.allowed_domains, "private_networks_allowed": s.browser_allow_private_networks,
                     "downloads": "blocked"},
        "retention": {"max_artifact_size_mb": s.max_artifact_size_mb, "max_screenshots_per_run": s.max_screenshots_per_run,
                      "run_retention_days": s.run_retention_days},
        "system": {"environment": s.environment},
    }


@router.get("/api/artifacts/screenshots/{path:path}")
async def get_screenshot(path: str) -> FileResponse:
    file = resolve_screenshot(path)
    if file is None:
        raise HTTPException(404, "Screenshot not found")
    return FileResponse(file, headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"})
