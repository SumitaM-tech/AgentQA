"""In-process registry of running `AgentOrchestrator` instances, keyed by
test_run_id, so `POST /api/runs/{id}/stop` can signal a loop running in a
background asyncio task within this same process.

Deliberately process-local (not Redis-backed): a production deployment
with multiple backend workers would need a job queue (Celery/RQ, or a
Redis-backed control channel) instead of an in-memory dict. Fine for a
single uvicorn process during development.
"""
from __future__ import annotations

import asyncio
from uuid import UUID

from sqlalchemy import select

from app.agent.orchestrator import AgentOrchestrator
from app.browser.playwright_driver import PlaywrightBrowserTool
from app.core.logging import get_logger
from app.database.session import AsyncSessionLocal
from app.exploration.graph import StateGraph
from app.llm.gemini_client import GeminiClient
from app.models.test_run import TestRun

logger = get_logger(__name__)

_active_orchestrators: dict[UUID, AgentOrchestrator] = {}


async def _run_and_cleanup(test_run_id: UUID) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(TestRun).where(TestRun.id == test_run_id))
        run = result.scalar_one()

        orchestrator = AgentOrchestrator(
            test_run_id=test_run_id,
            goal=run.goal,
            target_url=run.target_url,
            max_steps=run.max_steps,
            browser_tool=PlaywrightBrowserTool(run_id=test_run_id),
            gemini_client=GeminiClient(),
            state_graph=StateGraph(),
            db_session=db,
        )
        _active_orchestrators[test_run_id] = orchestrator
        try:
            await orchestrator.run()
        except Exception:  # noqa: BLE001 - orchestrator.run() already persisted the failure + logged it
            logger.error("background_run_ended_with_error", test_run_id=str(test_run_id))
        finally:
            _active_orchestrators.pop(test_run_id, None)


def start_run_in_background(test_run_id: UUID) -> None:
    asyncio.create_task(_run_and_cleanup(test_run_id))


async def stop_run(test_run_id: UUID) -> bool:
    """Returns False if this run isn't active in this process (already
    finished, never started, or running in a different worker)."""
    orchestrator = _active_orchestrators.get(test_run_id)
    if orchestrator is None:
        return False
    await orchestrator.stop()
    return True
