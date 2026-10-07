"""Verification pipeline: takes a `suspicious` (or already `confirmed_bug`)
Verdict and decides whether it's reproducible enough to report, or a
one-off false positive.

Deterministic responsibilities here (not Gemini's job):
  - Re-running the triggering action once or twice from the state it was
    first observed in, to check reproducibility.
  - Capturing fresh evidence (screenshot, DOM, console) on each retry.

Gemini's job (via `compare_outcome` again on each retry) is judgment
only — did the same discrepancy show up again.
"""
from __future__ import annotations

from app.agent.legacy_state import Action, ExpectedOutcome, Observation, Verdict, VerdictOutcome
from app.browser.interface import BrowserTool
from app.core.logging import get_logger
from app.llm.gemini_client import GeminiClient

logger = get_logger(__name__)

_REPRODUCIBLE_OUTCOMES = (VerdictOutcome.SUSPICIOUS, VerdictOutcome.CONFIRMED_BUG)


async def verify_suspicious_finding(
    action: Action,
    initial_verdict: Verdict,
    pre_observation: Observation,
    post_observation: Observation,
    browser_tool: BrowserTool,
    gemini_client: GeminiClient,
    max_retries: int = 2,
) -> tuple[bool, list[Observation]]:
    """Re-attempt `action` up to `max_retries` more times from the current
    (post-action) page state, re-observing and re-judging each time.
    Requires the discrepancy to reproduce at least once beyond the
    original finding before treating it as confirmed — a single
    observation is not enough to rule out a flaky/transient issue.

    Returns (confirmed, evidence_observations) where evidence_observations
    starts with `post_observation` (the original finding) followed by any
    retry observations, in order — this is exactly the evidence trail
    `GeminiClient.generate_bug_report` expects.
    """
    evidence: list[Observation] = [post_observation]
    reproduction_count = 1 if initial_verdict.outcome in _REPRODUCIBLE_OUTCOMES else 0
    reference_observation = post_observation

    verification_expectation = ExpectedOutcome(
        expected_summary=(
            "Verification retry: repeating the same action should NOT reproduce "
            f"the original discrepancy if it was transient. Original finding: {initial_verdict.reasoning}"
        ),
        expected_console_clean=True,
    )

    for attempt in range(max_retries):
        try:
            await browser_tool.execute(action)
        except Exception as exc:  # noqa: BLE001 - a failing retry action is itself evidence
            logger.warning("verification_retry_action_failed", attempt=attempt, error=str(exc))
            reproduction_count += 1
            continue

        retry_observation = await browser_tool.observe()
        evidence.append(retry_observation)

        retry_verdict = await gemini_client.compare_outcome(
            verification_expectation, retry_observation, reference_observation
        )
        if retry_verdict.outcome in _REPRODUCIBLE_OUTCOMES:
            reproduction_count += 1

        reference_observation = retry_observation

    confirmed = reproduction_count >= 2
    logger.info(
        "verification_complete",
        confirmed=confirmed,
        reproduction_count=reproduction_count,
        attempts=max_retries,
    )
    return confirmed, evidence


async def build_bug_report(
    action: Action,
    verdict: Verdict,
    evidence_observations: list[Observation],
    gemini_client: GeminiClient,
):
    """Convenience wrapper: assembles the (action, expected, verdict, obs)
    evidence trail `GeminiClient.generate_bug_report` expects from a flat
    list of Observations gathered during verification. All observations
    share the same triggering action/verdict — the trail's value is in
    the sequence of Observations showing the discrepancy recurring."""
    expected = ExpectedOutcome(expected_summary="See verdict.reasoning for the original expectation.")
    evidence = [(action, expected, verdict, obs) for obs in evidence_observations]
    return await gemini_client.generate_bug_report(evidence)
