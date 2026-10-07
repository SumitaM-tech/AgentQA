"""QAAgent end-to-end: scripted model + fake site, no browser/LLM. Exercises the full
loop, safeguards, FSM termination, deterministic fallback, and bug detection."""
from __future__ import annotations

import asyncio

import pytest

from app.agent.agent import AgentConfig, QAAgent, to_tool_call
from app.agent.critic import CriticAssessment, Verdict
from app.agent.state import (
    ActionArguments, ActionType, AgentAction, ExpectedOutcome, TerminationReason,
)
from tests.agent_helpers import ScriptedModel, eid, make_element, make_obs, shop_site

EXP = ExpectedOutcome(summary="Something happens.")


def click(target: str, **over) -> AgentAction:
    d = dict(action_type=ActionType.CLICK, target=target, expected_outcome=EXP,
            reason="Testing.", exploration_priority=0.8)
    d.update(over)
    return AgentAction(**d)


def finish(reason: str = "Goal covered.") -> AgentAction:
    return AgentAction(action_type=ActionType.FINISH, expected_outcome=ExpectedOutcome(summary="Done."),
                       reason=reason, exploration_priority=0.0)


AS_EXPECTED = CriticAssessment(verdict="as_expected", confidence=1.0, reason="Matches prediction.")


def test_to_tool_call_maps_every_action_type_to_a_fixed_tool() -> None:
    a = AgentAction(action_type=ActionType.TYPE, target=eid(1),
                    arguments=ActionArguments(text="hi", press_enter=True),
                    expected_outcome=EXP, reason="try it", exploration_priority=0.1)
    assert to_tool_call(a) == ("browser_type", {"element_id": eid(1), "text": "hi",
                                                "clear_first": True, "press_enter": True})
    assert to_tool_call(click(eid(1))) == ("browser_click", {"element_id": eid(1)})
    with pytest.raises(ValueError):
        to_tool_call(finish())  # FINISH is not a browser action at all; the agent loop never sends it


async def test_full_run_reaches_finish_and_visits_pages() -> None:
    site = shop_site()
    model = ScriptedModel(
        planner=[click(eid(1)), click(eid(11)), click(eid(10)), click(eid(2)), finish("Explored home, products, about.")],
        critic=[AS_EXPECTED] * 4,
    )
    agent = QAAgent(model, critic_model=model, config=AgentConfig(max_steps=10))
    result = await agent.run("Explore the shop", f"{site.url}", site)

    assert result.termination == TerminationReason.GOAL_COMPLETE
    assert [s.action.action_type for s in result.steps] == [ActionType.CLICK] * 4 + [ActionType.FINISH]
    assert {s.url_after for s in result.steps if s.url_after} == {
        "http://app.test/products", "http://app.test/", "http://app.test/about"}
    assert result.states_discovered >= 3 and result.actions_executed == 5  # 1 bootstrap OPEN + 4 clicks
    assert all(s.verdict != "rejected" for s in result.steps)


async def test_max_steps_is_a_hard_ceiling() -> None:
    site = shop_site()
    # The model tries to run forever (never FINISH); each click targets a different,
    # always-present element so nothing else would stop it early.
    endless = ScriptedModel(factory=lambda p, s: click(eid(6)))
    agent = QAAgent(endless, critic_model=ScriptedModel(factory=lambda p, s: AS_EXPECTED),
                    config=AgentConfig(max_steps=4, max_consecutive_rejections=999, max_stagnant_steps=999))
    result = await agent.run("Never stop", site.url, site)
    assert result.termination == TerminationReason.MAX_STEPS
    assert result.steps_taken == 4
    assert len(result.steps) <= 4 + 2  # a couple of rejected-but-recorded attempts is fine; unbounded growth is not


async def test_requested_max_steps_cannot_exceed_deployment_ceiling(monkeypatch) -> None:
    from app.core.config import get_settings
    monkeypatch.setenv("AGENT_ABSOLUTE_MAX_STEPS", "3")
    get_settings.cache_clear()
    try:
        site = shop_site()
        endless = ScriptedModel(factory=lambda p, s: click(eid(6)))
        agent = QAAgent(endless, critic_model=ScriptedModel(factory=lambda p, s: AS_EXPECTED),
                        config=AgentConfig(max_steps=1000))  # way over the ceiling
        result = await agent.run("x", site.url, site)
        assert result.steps_taken == 3 and result.termination == TerminationReason.MAX_STEPS
    finally:
        get_settings.cache_clear()


async def test_policy_rejects_model_proposal_and_fallback_makes_progress() -> None:
    """The model repeatedly proposes a dangerous action; the policy rejects every attempt,
    the planner exhausts its retries, and the deterministic fallback picks a safe, untried
    element instead of the run stalling."""
    site = shop_site()
    dangerous = click(eid(3))  # "Log out"
    model = ScriptedModel(planner=[dangerous, dangerous, dangerous],
                          critic=[AS_EXPECTED] * 3, factory=lambda p, s: dangerous)
    agent = QAAgent(model, critic_model=model, config=AgentConfig(max_steps=1, planning_attempts=3))
    result = await agent.run("Explore", site.url, site)

    assert len(result.steps) == 1
    step = result.steps[0]
    assert step.used_fallback is True and step.policy_rejections == 3
    assert step.action.target != eid(3)              # never executed the dangerous action
    assert step.action.action_type in (ActionType.CLICK, ActionType.FINISH)
    assert dangerous not in site.executed


async def test_model_never_executes_outside_the_fixed_tool_set() -> None:
    """Even a maximally adversarial model (extra fields, arbitrary payload) can only ever
    produce a validated AgentAction that maps to the closed browser tool set."""
    site = shop_site()

    class Adversarial:
        async def generate(self, prompt, *, system_instruction, schema, image_bytes=None):
            if schema.__name__ == "AgentAction":
                # Pydantic's extra="forbid" rejects this; the planner must recover via fallback.
                return {"action_type": "CLICK", "target": eid(1),
                       "arguments": {"__proto__": "x", "code": "import os; os.system('rm -rf /')"},
                       "expected_outcome": {"summary": "pwned"}, "reason": "x", "exploration_priority": 1.0}
            return AS_EXPECTED

    agent = QAAgent(Adversarial(), critic_model=Adversarial(), config=AgentConfig(max_steps=1))
    result = await agent.run("Explore", site.url, site)
    assert result.steps[0].used_fallback is True
    for name, args in (to_tool_call(s.action) for s in result.steps if s.action.action_type != ActionType.FINISH):
        assert name.startswith("browser_")
        assert "code" not in args and "__proto__" not in args


async def test_out_of_domain_click_triggers_recovery_not_a_crash() -> None:
    site = shop_site()
    model = ScriptedModel(planner=[click(eid(4)), finish()], critic=[AS_EXPECTED])
    agent = QAAgent(model, critic_model=model, config=AgentConfig(max_steps=5))
    result = await agent.run("Explore", site.url, site)
    # policy blocks the CLICK on the external link outright (defense in depth), so the
    # agent never actually leaves the domain in this scenario
    assert result.termination == TerminationReason.GOAL_COMPLETE
    assert all(s.action.target != eid(4) or s.verdict == "rejected" for s in result.steps)
    assert "evil.test" not in (result.final_url or "")


async def test_actual_domain_escape_is_recovered_from() -> None:
    """If the browser ends up outside the allowed domain despite policy (e.g. a redirect
    the policy layer couldn't see coming), the FSM recovers instead of continuing there."""
    site = shop_site()
    model = ScriptedModel(planner=[click(eid(1)), finish()], critic=[AS_EXPECTED])
    agent = QAAgent(model, critic_model=model, config=AgentConfig(max_steps=5, max_recoveries=2))

    real_execute = site.execute

    async def sneaky_execute(action):
        res = await real_execute(action)
        if action.action_type == ActionType.CLICK and action.target == eid(1):
            site.url = "http://evil.test/redirected"  # simulate a same-click redirect off-domain
        return res

    site.execute = sneaky_execute
    result = await agent.run("Explore", site.url, site)
    assert result.recoveries >= 1
    assert "evil.test" not in (result.final_url or "")
    assert result.termination == TerminationReason.GOAL_COMPLETE


async def test_repeated_identical_action_is_blocked_across_the_whole_run() -> None:
    site = shop_site()
    same = click(eid(6))  # "Help" button, no navigation effect
    model = ScriptedModel(factory=lambda p, s: same if "reject" not in "".join(f for f in []) else finish())
    # After repeated rejection, the deterministic fallback should eventually choose FINISH
    # once nothing untried remains reachable this way.
    agent = QAAgent(model, critic_model=ScriptedModel(factory=lambda p, s: AS_EXPECTED),
                    config=AgentConfig(max_steps=6, planning_attempts=2))
    result = await agent.run("Explore", site.url, site)
    click_help_count = sum(1 for s in result.steps if s.action.target == eid(6) and s.result and s.result.ok)
    assert click_help_count <= 2  # policy's max_identical_actions_per_state default


async def test_loop_between_two_pages_is_detected_and_stopped() -> None:
    import re

    site = shop_site()

    def bounce(prompt: str, schema) -> AgentAction:
        url = re.search(r"Current URL: (\S+)", prompt).group(1)
        return click(eid(1)) if url.rstrip("/").endswith("app.test") else click(eid(10))

    # Home -> Products -> Home -> Products ... forever, if nothing stopped it.
    model = ScriptedModel(factory=bounce)
    agent = QAAgent(model, critic_model=ScriptedModel(factory=lambda p, s: AS_EXPECTED),
                    config=AgentConfig(max_steps=40, max_loop_flags=2, max_consecutive_rejections=999))
    result = await agent.run("Explore", site.url, site)
    # The safeguards intervene well before the 40-step ceiling — either the cycle detector
    # fires directly, or repeated-action/state-exhaustion rejections push the deterministic
    # fallback to FINISH once nothing untried remains reachable. Either is a correct stop.
    assert result.steps_taken < 40
    assert result.termination in (TerminationReason.LOOP_DETECTED, TerminationReason.STAGNATION,
                                  TerminationReason.GOAL_COMPLETE)
    if result.termination == TerminationReason.GOAL_COMPLETE:
        assert any(s.policy_rejections > 0 for s in result.steps)  # confirms safeguards actually engaged


async def test_too_many_consecutive_failures_stops_the_run() -> None:
    site = shop_site()
    site.fail_with = "element_not_actionable"
    model = ScriptedModel(factory=lambda p, s: click(eid(6)))
    agent = QAAgent(model, critic_model=ScriptedModel(factory=lambda p, s: AS_EXPECTED),
                    config=AgentConfig(max_steps=20, max_consecutive_failures=3))
    result = await agent.run("Explore", site.url, site)
    assert result.termination == TerminationReason.TOO_MANY_FAILURES
    assert result.steps_taken <= 4


async def test_invalid_model_output_never_reaches_the_browser() -> None:
    site = shop_site()
    model = ScriptedModel(planner=[
        {"action_type": "CLICK"},                                           # missing target
        {"action_type": "OPEN", "arguments": {"url": "javascript:alert(1)"}, "expected_outcome": {"summary": "x"},
         "reason": "y", "exploration_priority": 0.1},
        "not even json",
    ], critic=[AS_EXPECTED])
    agent = QAAgent(model, critic_model=model, config=AgentConfig(max_steps=1, planning_attempts=3))
    result = await agent.run("Explore", site.url, site)
    assert len(result.steps) == 1 and result.steps[0].used_fallback
    assert all(a.action_type != ActionType.OPEN or a.arguments.url != "javascript:alert(1)" for a in site.executed)


async def test_model_exception_falls_back_instead_of_crashing_the_run() -> None:
    site = shop_site()
    model = ScriptedModel(planner=[RuntimeError("Gemini is down")], critic=[AS_EXPECTED])
    agent = QAAgent(model, critic_model=model, config=AgentConfig(max_steps=1))
    result = await agent.run("Explore", site.url, site)
    assert result.steps[0].used_fallback and result.termination in (
        TerminationReason.GOAL_COMPLETE, TerminationReason.MAX_STEPS)


async def test_bug_is_detected_recorded_and_deduplicated() -> None:
    site = shop_site()
    # A concrete, checkable prediction ("Added" should appear) that will NOT come true —
    # this is what gives the critic a deterministic signal worth escalating to the LLM for.
    add_to_cart = click(eid(11), expected_outcome=ExpectedOutcome(summary="Item is added to the cart.",
                                                                   text_contains=["Added"]))
    model = ScriptedModel(planner=[click(eid(1)), add_to_cart, finish()])
    bug = CriticAssessment(verdict="bug", severity="high", category="functional", confidence=0.95,
                           reason="Add to cart did nothing.", discrepancies=["cart count unchanged"],
                           bug_title="Add to cart is broken")
    # Only one action (add_to_cart) produces a deterministic signal worth escalating to the
    # LLM at all; clicking a plain nav link with no expectation mismatch never calls the critic.
    model.critic.append(bug)
    agent = QAAgent(model, critic_model=model, config=AgentConfig(max_steps=5))
    result = await agent.run("Buy a product", site.url, site)

    assert len(result.bugs) == 1
    assert result.bugs[0].severity.value == "high" and "cart count unchanged" in result.bugs[0].evidence
    assert result.bugs[0].url == "http://app.test/products"
    bug_step = next(s for s in result.steps if s.verdict == "bug")
    assert bug_step.action.target == eid(11)


async def test_hard_evidence_cannot_be_dismissed_by_the_critic_llm() -> None:
    """An uncaught exception is hard evidence; even if the LLM says 'as_expected', the
    critic must not agree — this is the guardrail, not the model's judgement call."""
    site = shop_site()
    real_observe = site.observe
    calls = {"n": 0}

    async def observe_with_exception_after_first_click():
        obs = await real_observe()
        calls["n"] += 1
        if calls["n"] == 2:  # the observation right after the CLICK (1st is the bootstrap observe)
            from app.perception.models import BrowserException
            obs = obs.model_copy(update={"browser_exceptions": [
                BrowserException(message="TypeError: cannot read property of undefined")]})
        return obs

    site.observe = observe_with_exception_after_first_click
    model = ScriptedModel(planner=[click(eid(6)), finish()],
                          critic=[CriticAssessment(verdict="as_expected", confidence=0.99, reason="looks fine")])
    agent = QAAgent(model, critic_model=model, config=AgentConfig(max_steps=5))
    result = await agent.run("Explore", site.url, site)
    first = result.steps[0]
    assert first.verdict in ("suspicious", "bug")
    assert len(result.bugs) <= 1 and (not result.bugs or "exception" in " ".join(result.bugs[0].evidence).lower())


async def test_validation_feedback_expected_is_not_reported_as_a_bug() -> None:
    site = shop_site()
    real_observe = site.observe
    calls = {"n": 0}

    async def observe_with_validation_message_after_click():
        obs = await real_observe()
        calls["n"] += 1
        if calls["n"] == 2:
            obs = obs.model_copy(update={"visible_text": obs.visible_text + "\nError: please enter a value"})
        return obs

    site.observe = observe_with_validation_message_after_click
    invalid_input = click(eid(6), expected_outcome=ExpectedOutcome(summary="Shows a validation error.",
                                                                    expects_error_feedback=True))
    model = ScriptedModel(planner=[invalid_input, finish()])
    agent = QAAgent(model, critic_model=model, config=AgentConfig(max_steps=5))
    result = await agent.run("Test validation", site.url, site)
    # expects_error_feedback=True + an error message actually appearing => no mismatch => no LLM
    # call needed at all; the deterministic rules alone correctly call this "as expected".
    assert result.steps[0].verdict == "as_expected" and not result.bugs
    assert not model.critic_prompts


async def test_finish_action_stops_immediately_without_executing() -> None:
    site = shop_site()
    model = ScriptedModel(planner=[finish("Nothing more to test.")])
    agent = QAAgent(model, critic_model=model, config=AgentConfig(max_steps=10))
    result = await agent.run("Explore", site.url, site)
    assert result.termination == TerminationReason.GOAL_COMPLETE
    assert result.actions_executed == 1  # only the bootstrap OPEN; FINISH itself never hits the browser
    assert not any(a.action_type == ActionType.FINISH for a in site.executed)


async def test_start_url_outside_configured_domain_fails_fast() -> None:
    site = shop_site()
    model = ScriptedModel(planner=[], critic=[])
    agent = QAAgent(model, critic_model=model,
                    config=AgentConfig(max_steps=5, allowed_domains=["other.test"]))
    result = await agent.run("Explore", site.url, site)
    assert result.termination == TerminationReason.FATAL_ERROR
    assert site.executed == []  # nothing was ever attempted


async def test_stop_takes_effect_before_the_next_step() -> None:
    site = shop_site()
    calls = {"n": 0}

    def factory(p, s):
        calls["n"] += 1
        if calls["n"] == 1:
            agent.stop()
        return click(eid(6))

    model = ScriptedModel(factory=factory)
    agent = QAAgent(model, critic_model=ScriptedModel(factory=lambda p, s: AS_EXPECTED),
                    config=AgentConfig(max_steps=20))
    result = await agent.run("Explore", site.url, site)
    assert result.termination == TerminationReason.STOPPED
    assert result.steps_taken <= 2


async def test_events_are_emitted_for_the_full_lifecycle() -> None:
    site = shop_site()
    model = ScriptedModel(planner=[click(eid(6)), finish()], critic=[AS_EXPECTED])
    events: list[str] = []
    agent = QAAgent(model, critic_model=model, config=AgentConfig(max_steps=5),
                    on_event=lambda name, data: events.append(name))
    await agent.run("Explore", site.url, site)
    assert events[0] == "run_started" and events[-1] == "run_finished"
    assert "step_planned" in events and "step_evaluated" in events


async def test_slow_model_is_bounded_by_step_timeout() -> None:
    site = shop_site()

    class SlowModel:
        async def generate(self, *a, **k):
            await asyncio.sleep(5)
            return finish()

    agent = QAAgent(SlowModel(), critic_model=SlowModel(),
                    config=AgentConfig(max_steps=3, step_timeout_s=0.05, planning_attempts=1))
    result = await agent.run("Explore", site.url, site)
    assert result.termination in (TerminationReason.MAX_STEPS, TerminationReason.TIMEOUT,
                                  TerminationReason.TOO_MANY_FAILURES)
