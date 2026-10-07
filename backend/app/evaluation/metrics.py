"""Run evaluation metrics, computed ONLY from persisted run data (states, transitions, bugs, counters).

Measured exactly: unique states, unique transitions, tested elements, verified/unverified bugs, candidate and
discarded counts, time-to-first-verified-bug, action efficiency, verification rate.
Estimated (labelled `estimated: true`): exploration coverage — the share of interactive elements *seen* that the
agent actually exercised. The true reachable state space of a site is unknowable, so no "% of the app" is claimed.
Detection rate (known bugs found) needs a ground-truth list and is produced by `python -m app.evaluation.run_eval`.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bug import Bug
from app.models.test_run import TestRun
from app.models.ui_state import UIState
from app.models.ui_transition import UITransition

_NOT_USEFUL = {"action_failed"}


def _ratio(n: int, d: int) -> float | None:
    return round(n / d, 3) if d else None


async def evaluate_run(db: AsyncSession, run: TestRun) -> dict[str, Any]:
    states = (await db.execute(select(UIState).where(UIState.test_run_id == run.id))).scalars().all()
    edges = (await db.execute(select(UITransition).where(UITransition.test_run_id == run.id))).scalars().all()
    bugs = (await db.execute(select(Bug).where(Bug.test_run_id == run.id))).scalars().all()

    unique_transitions = {(e.source_state_id, e.target_state_id, e.action_type, e.target_element_id) for e in edges}
    tested_elements = {(e.source_state_id, e.target_element_id) for e in edges if e.target_element_id}
    seen_elements = sum(len(s.interactive_elements or []) for s in states)
    pages = {s.url.split("#")[0].split("?")[0] for s in states}
    # An action is "useful" when it reached a new state, changed state, or surfaced a finding.
    useful = sum(1 for e in edges if e.source_state_id != e.target_state_id or (e.verdict not in (None, "as_expected") and e.verdict not in _NOT_USEFUL))
    verified = sum(1 for b in bugs if b.status == "verified")
    candidates = max(run.candidates_count, len(bugs))
    ttfb = None
    if run.first_bug_at and run.started_at:
        ttfb = round(max(0.0, (run.first_bug_at - run.started_at).total_seconds()), 1)
    discarded = run.discarded_count
    return {
        "run_id": str(run.id),
        "states_explored": len(states),
        "transitions": len(unique_transitions),
        "pages_tested": len(pages),
        "interactive_elements_tested": len(tested_elements),
        "interactive_elements_seen": seen_elements,
        "actions_total": len(edges),
        "actions_useful": useful,
        "action_efficiency": _ratio(useful, len(edges)),
        "bugs_reported": len(bugs),
        "bugs_verified": verified,
        "bugs_unverified": len(bugs) - verified,
        "candidates": candidates,
        "false_positives": discarded,  # candidates that failed verification and were NOT reported
        "false_positive_rate": _ratio(discarded, discarded + len(bugs)),
        "bug_verification_rate": _ratio(verified, candidates),
        "time_to_first_bug_seconds": ttfb,
        "exploration_coverage": _ratio(len(tested_elements), seen_elements),
        "exploration_coverage_estimated": True,
        "notes": [
            "Coverage is an ESTIMATE: tested elements / interactive elements observed (capped at 30 per state). "
            "It is not a percentage of the whole application.",
            "False positives = candidates discarded because they could not be reproduced; reported-but-unverified "
            "bugs are counted separately (bugs_unverified).",
            "Detection rate against known bugs requires a ground-truth file: python -m app.evaluation.run_eval.",
        ],
    }
