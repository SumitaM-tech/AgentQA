"""Bridges the in-memory agent contracts (`app.agent.legacy_state`) to the
persisted DB entities (`app.models`). Kept separate from `run_service.py`
(which serves the read-facing REST endpoints) since this module is
write-heavy and only ever called from the orchestrator's run loop.

Callers own the transaction boundary — every function here only
`flush()`es; call `db.commit()` at whatever cadence the caller wants
(the orchestrator commits once per step for crash-durability without
serializing every intermediate write).
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.legacy_state import Action, BugReport as AgentBugReport, ExpectedOutcome, Observation, Verdict
from app.core.logging import get_logger
from app.models.agent_action import AgentAction
from app.models.artifact import Artifact
from app.models.bug import Bug
from app.models.test_run import TestRun
from app.models.ui_state import UIState
from app.models.ui_transition import UITransition

logger = get_logger(__name__)


async def update_run_status(
    db: AsyncSession,
    test_run_id: UUID,
    status: str,
    steps_taken: int | None = None,
    error_message: str | None = None,
) -> None:
    result = await db.execute(select(TestRun).where(TestRun.id == test_run_id))
    run = result.scalar_one()
    run.status = status
    if steps_taken is not None:
        run.steps_taken = steps_taken
    if error_message is not None:
        run.error_message = error_message
    await db.flush()


async def record_artifact(
    db: AsyncSession, test_run_id: UUID, artifact_type: str, storage_path: str
) -> Artifact:
    artifact = Artifact(test_run_id=test_run_id, artifact_type=artifact_type, storage_path=storage_path)
    db.add(artifact)
    await db.flush()
    return artifact


async def get_or_create_ui_state(
    db: AsyncSession,
    test_run_id: UUID,
    node_id: UUID,
    observation: Observation,
    discovered_at_step: int,
) -> UIState:
    """`node_id` comes from `StateGraph.get_or_create_node` — the graph's
    fingerprint-dedup already decided whether this is a new state, so
    this just needs to check whether that node_id has been persisted yet."""
    result = await db.execute(select(UIState).where(UIState.id == node_id))
    existing = result.scalar_one_or_none()
    if existing is not None:
        return existing

    screenshot_artifact = await record_artifact(db, test_run_id, "screenshot", observation.screenshot_path)
    dom_artifact = await record_artifact(db, test_run_id, "dom_snapshot", observation.dom_snapshot_path)

    state = UIState(
        id=node_id,
        test_run_id=test_run_id,
        fingerprint=observation.state_fingerprint,
        url=observation.url,
        title=observation.title,
        screenshot_artifact_id=screenshot_artifact.id,
        dom_snapshot_artifact_id=dom_artifact.id,
        discovered_at_step=discovered_at_step,
    )
    db.add(state)
    await db.flush()
    return state


async def record_ui_transition(
    db: AsyncSession,
    test_run_id: UUID,
    edge_id: UUID,
    source_state_id: UUID,
    target_state_id: UUID,
    action: Action,
    step_index: int,
) -> UITransition:
    transition = UITransition(
        id=edge_id,
        test_run_id=test_run_id,
        source_state_id=source_state_id,
        target_state_id=target_state_id,
        action_type=action.action_type.value,
        target_element_id=action.target_element_id,
        action_value=action.value,
        step_index=step_index,
    )
    db.add(transition)
    await db.flush()
    return transition


async def record_agent_action(
    db: AsyncSession,
    test_run_id: UUID,
    step_index: int,
    action: Action,
    expected: ExpectedOutcome,
    verdict: Verdict | None,
) -> AgentAction:
    row = AgentAction(
        test_run_id=test_run_id,
        step_index=step_index,
        action_type=action.action_type.value,
        target_element_id=action.target_element_id,
        action_value=action.value,
        reasoning=action.reasoning,
        expected_summary=expected.expected_summary,
        verdict_outcome=verdict.outcome.value if verdict else None,
        verdict_confidence=verdict.confidence if verdict else None,
        verdict_reasoning=verdict.reasoning if verdict else None,
    )
    db.add(row)
    await db.flush()
    return row


async def record_bug(
    db: AsyncSession,
    test_run_id: UUID,
    report: AgentBugReport,
    related_state_id: UUID | None,
    related_transition_id: UUID | None,
) -> Bug:
    row = Bug(
        id=report.bug_id,
        test_run_id=test_run_id,
        title=report.title,
        severity=report.severity.value,
        description=report.description,
        steps_to_reproduce=report.steps_to_reproduce,
        expected_behavior=report.expected_behavior,
        actual_behavior=report.actual_behavior,
        related_state_id=related_state_id,
        related_transition_id=related_transition_id,
        fix_proposal=report.fix_proposal,
    )
    db.add(row)
    await db.flush()
    logger.info("bug_persisted", bug_id=str(row.id), severity=row.severity, test_run_id=str(test_run_id))
    return row
