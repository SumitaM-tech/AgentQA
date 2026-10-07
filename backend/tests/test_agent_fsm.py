"""Finite state machine: legal transitions only, and every hard limit actually
stops the machine (max steps enforced, action budget enforced, ...)."""
from __future__ import annotations

import pytest

from app.agent.state import (
    AgentPhase, AgentStateMachine, BudgetExceeded, FSMLimits, InvalidTransition, TerminationReason,
)


def limits(**over) -> FSMLimits:
    return FSMLimits.create(over.pop("max_steps", 5), absolute_max_steps=200,
                            max_wall_seconds=over.pop("max_wall_seconds", 900),
                            absolute_max_wall_seconds=900, **over)


def advance(fsm: AgentStateMachine) -> None:
    """One full legal lap, mirroring app.agent.agent.QAAgent.run() exactly:
    PLANNING -> begin_step -> VALIDATING -> authorize_execution -> EXECUTING
    -> OBSERVING -> EVALUATING -> PLANNING."""
    fsm.begin_step()
    fsm.transition(AgentPhase.VALIDATING)
    fsm.authorize_execution("step")
    fsm.transition(AgentPhase.OBSERVING)
    fsm.transition(AgentPhase.EVALUATING)
    fsm.transition(AgentPhase.PLANNING)


def test_bootstrap_sequence() -> None:
    fsm = AgentStateMachine(limits())
    assert fsm.phase == AgentPhase.INIT
    fsm.transition(AgentPhase.VALIDATING)
    fsm.authorize_execution("bootstrap")
    assert fsm.phase == AgentPhase.EXECUTING and fsm.actions_executed == 1
    fsm.transition(AgentPhase.OBSERVING)
    fsm.transition(AgentPhase.PLANNING)
    assert fsm.phase == AgentPhase.PLANNING


@pytest.mark.parametrize("bad", [AgentPhase.EXECUTING, AgentPhase.EVALUATING, AgentPhase.RECOVERING])
def test_illegal_transitions_rejected(bad) -> None:
    fsm = AgentStateMachine(limits())
    with pytest.raises(InvalidTransition):
        fsm.transition(bad)
    assert fsm.phase == AgentPhase.INIT  # rejected transition does not move the phase


def test_cannot_execute_outside_validating_or_recovering() -> None:
    fsm = AgentStateMachine(limits())
    with pytest.raises(InvalidTransition):
        fsm.authorize_execution("step")


def test_terminated_is_a_sink() -> None:
    fsm = AgentStateMachine(limits())
    fsm.terminate(TerminationReason.STOPPED)
    assert fsm.is_terminal
    with pytest.raises(InvalidTransition):
        fsm.transition(AgentPhase.PLANNING)
    with pytest.raises(InvalidTransition):
        fsm.begin_step()
    with pytest.raises(InvalidTransition):
        fsm.authorize_execution("step")


def test_terminate_is_idempotent_first_reason_wins() -> None:
    fsm = AgentStateMachine(limits())
    fsm.terminate(TerminationReason.MAX_STEPS, "first")
    fsm.terminate(TerminationReason.FATAL_ERROR, "second")
    assert fsm.termination == TerminationReason.MAX_STEPS and fsm.detail == "first"


# ---------------------------------------------------------------- hard limits

def test_max_steps_enforced() -> None:
    fsm = AgentStateMachine(limits(max_steps=3))
    fsm.transition(AgentPhase.VALIDATING)
    fsm.authorize_execution("bootstrap")
    fsm.transition(AgentPhase.OBSERVING)
    fsm.transition(AgentPhase.PLANNING)
    for _ in range(3):
        advance(fsm)
    with pytest.raises(BudgetExceeded) as e:
        fsm.begin_step()
    assert e.value.reason == TerminationReason.MAX_STEPS
    assert fsm.is_terminal and fsm.steps_started == 3


def test_requested_steps_clamped_to_deployment_ceiling() -> None:
    fsm_limits = FSMLimits.create(max_steps=10_000, absolute_max_steps=50, max_wall_seconds=900,
                                  absolute_max_wall_seconds=900)
    assert fsm_limits.max_steps == 50   # never unbounded, regardless of what was requested


def test_requested_wall_time_clamped_to_deployment_ceiling() -> None:
    fsm_limits = FSMLimits.create(max_steps=5, absolute_max_steps=200, max_wall_seconds=99_999,
                                  absolute_max_wall_seconds=120)
    assert fsm_limits.max_wall_seconds == 120


def test_action_budget_enforced_independent_of_step_counter() -> None:
    """authorize_execution() enforces actions_executed <= max_actions on its own, separate
    from begin_step()'s step counter — drive it directly (bypassing begin_step) to prove
    the action-level gate is real and not just a side effect of the step gate."""
    fsm = AgentStateMachine(limits(max_steps=1, max_recoveries=0))
    assert fsm.limits.max_actions == 2   # 1 bootstrap + 1 step + 0 recoveries
    fsm.transition(AgentPhase.VALIDATING)
    fsm.authorize_execution("bootstrap")     # action 1 of 2
    fsm.transition(AgentPhase.OBSERVING)
    fsm.transition(AgentPhase.PLANNING)
    fsm.transition(AgentPhase.VALIDATING)
    fsm.authorize_execution("step")          # action 2 of 2 — steps_started is still 0 here
    assert fsm.steps_started == 0 and fsm.actions_executed == 2
    fsm.transition(AgentPhase.OBSERVING)
    fsm.transition(AgentPhase.PLANNING)
    fsm.transition(AgentPhase.VALIDATING)
    with pytest.raises(BudgetExceeded) as e:
        fsm.authorize_execution("step")      # action 3 -> over budget, purely on the action count
    assert e.value.reason == TerminationReason.MAX_ACTIONS
    assert fsm.is_terminal


def test_recovery_budget_enforced() -> None:
    fsm = AgentStateMachine(limits(max_recoveries=1))
    fsm.transition(AgentPhase.VALIDATING)
    fsm.authorize_execution("bootstrap")
    fsm.transition(AgentPhase.OBSERVING)
    fsm.transition(AgentPhase.EVALUATING)   # matches QAAgent.run(): domain check happens in EVALUATING
    fsm.transition(AgentPhase.RECOVERING)
    fsm.authorize_execution("recovery")   # 1 of 1
    assert fsm.recoveries == 1
    with pytest.raises(BudgetExceeded) as e:
        fsm.authorize_execution("recovery")
    assert e.value.reason == TerminationReason.DOMAIN_VIOLATION and fsm.is_terminal


@pytest.mark.parametrize("field,reason", [
    ("consecutive_failures", TerminationReason.TOO_MANY_FAILURES),
    ("consecutive_rejections", TerminationReason.TOO_MANY_REJECTIONS),
    ("loop_flags", TerminationReason.LOOP_DETECTED),
    ("stagnant_steps", TerminationReason.STAGNATION),
])
def test_soft_limits_terminate(field, reason) -> None:
    fsm = AgentStateMachine(limits(max_steps=50))
    setattr(fsm, field, getattr(fsm.limits, f"max_{field}"))
    assert fsm.check_limits() == reason and fsm.is_terminal


def test_wall_clock_timeout_enforced() -> None:
    t = [0.0]
    fsm = AgentStateMachine(limits(max_wall_seconds=10), clock=lambda: t[0])
    t[0] = 11.0
    assert fsm.check_limits() == TerminationReason.TIMEOUT and fsm.is_terminal


def test_stop_request_terminates() -> None:
    fsm = AgentStateMachine(limits())
    fsm.request_stop()
    assert fsm.check_limits() == TerminationReason.STOPPED


def test_check_limits_is_a_noop_once_terminal() -> None:
    fsm = AgentStateMachine(limits())
    fsm.terminate(TerminationReason.GOAL_COMPLETE)
    fsm.consecutive_failures = 999
    assert fsm.check_limits() == TerminationReason.GOAL_COMPLETE  # not overwritten
