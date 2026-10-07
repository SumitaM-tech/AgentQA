"""Policy layer: repeated clicks, loops, repeated-state exploration, invalid
targets, dangerous navigation, and out-of-domain actions."""
from __future__ import annotations

import pytest

from app.agent.memory import ExplorationMemory
from app.agent.policies import PolicyCode, PolicyConfig, PolicyEngine, detect_cycle
from app.agent.state import ActionArguments, ActionType, AgentAction, ExpectedOutcome
from tests.agent_helpers import eid, make_element, make_obs

EXP = ExpectedOutcome(summary="Something happens.")


def act(t: ActionType, target=None, **args) -> AgentAction:
    return AgentAction(action_type=t, target=target, arguments=ActionArguments(**args),
                       expected_outcome=EXP, reason="Testing.", exploration_priority=0.5)


def engine(**over) -> PolicyEngine:
    return PolicyEngine(PolicyConfig(allowed_domains=["app.test"], **over))


def assert_blocked(v, code: PolicyCode) -> None:
    assert not v.allowed and v.code == code, v
    assert v.message and v.suggestion


# ---------------------------------------------------------------- invalid targets

def test_unknown_target_blocked() -> None:
    obs = make_obs(elements=[make_element(1, name="Go")])
    v = engine().check(act(ActionType.CLICK, "e999999"), obs, ExplorationMemory(), step=1, max_steps=10)
    assert_blocked(v, PolicyCode.TARGET_NOT_FOUND)
    assert "e999999" in v.message


def test_disabled_target_blocked_for_click_type_select() -> None:
    obs = make_obs(elements=[make_element(1, "button", "Submit", enabled=False)])
    v = engine().check(act(ActionType.CLICK, eid(1)), obs, ExplorationMemory(), step=1, max_steps=10)
    assert_blocked(v, PolicyCode.TARGET_DISABLED)


def test_type_role_mismatch() -> None:
    obs = make_obs(elements=[make_element(1, "button", "Go")])
    v = engine().check(act(ActionType.TYPE, eid(1), text="x"), obs, ExplorationMemory(), step=1, max_steps=10)
    assert_blocked(v, PolicyCode.TARGET_ROLE_MISMATCH)


def test_type_into_readonly_blocked() -> None:
    obs = make_obs(elements=[make_element(1, "textbox", "Ref", readonly=True)])
    v = engine().check(act(ActionType.TYPE, eid(1), text="x"), obs, ExplorationMemory(), step=1, max_steps=10)
    assert_blocked(v, PolicyCode.TARGET_ROLE_MISMATCH)


def test_select_on_non_select_blocked() -> None:
    obs = make_obs(elements=[make_element(1, "combobox", "Sort", tag="div")])
    v = engine().check(act(ActionType.SELECT, eid(1), index=0), obs, ExplorationMemory(), step=1, max_steps=10)
    assert_blocked(v, PolicyCode.TARGET_ROLE_MISMATCH)


# ---------------------------------------------------------------- dangerous navigation

@pytest.mark.parametrize("url,cat", [
    ("http://app.test/logout", "logout"),
    ("http://app.test/sign-out", "logout"),
    ("http://app.test/delete-account", "destructive"),
    ("http://app.test/factory-reset", "destructive"),
    ("http://app.test/installer.exe", "download"),
])
def test_open_dangerous_path_blocked(url, cat) -> None:
    v = engine().url_verdict(url)
    assert_blocked(v, PolicyCode.DANGEROUS_NAVIGATION)
    assert v.category == cat


@pytest.mark.parametrize("scheme,url", [
    ("javascript", "javascript:alert(1)"), ("file", "file:///etc/passwd"), ("data", "data:text/html,hi"),
    ("mailto", "mailto:a@b.com"), ("tel", "tel:12345"), ("ftp", "ftp://app.test/x"),
])
def test_open_non_http_scheme_blocked(scheme, url) -> None:
    assert_blocked(engine().url_verdict(url), PolicyCode.DANGEROUS_NAVIGATION)


def test_open_safe_path_allowed() -> None:
    assert engine().url_verdict("http://app.test/products?x=1").allowed


@pytest.mark.parametrize("name,cat", [
    ("Log out", "logout"), ("Sign Out", "logout"), ("Delete my account", "destructive"),
    ("Permanently delete workspace", "destructive"), ("Place your order", "payment"), ("Pay now", "payment"),
])
def test_click_dangerous_element_by_name_blocked(name, cat) -> None:
    obs = make_obs(elements=[make_element(1, "button", name)])
    v = engine().check(act(ActionType.CLICK, eid(1)), obs, ExplorationMemory(), step=1, max_steps=10)
    assert_blocked(v, PolicyCode.DANGEROUS_ELEMENT)
    assert v.category == cat


def test_click_dangerous_href_blocked_even_with_safe_name() -> None:
    obs = make_obs(elements=[make_element(1, "link", "Click here", href="/delete-account")])
    v = engine().check(act(ActionType.CLICK, eid(1)), obs, ExplorationMemory(), step=1, max_steps=10)
    assert_blocked(v, PolicyCode.DANGEROUS_ELEMENT)


def test_categories_are_configurable() -> None:
    permissive = engine(blocked_categories=frozenset({"destructive"}))
    obs = make_obs(elements=[make_element(1, "button", "Log out")])
    assert permissive.check(act(ActionType.CLICK, eid(1)), obs, ExplorationMemory(), step=1, max_steps=10).allowed
    obs2 = make_obs(elements=[make_element(2, "button", "Delete account")])
    assert_blocked(permissive.check(act(ActionType.CLICK, eid(2)), obs2, ExplorationMemory(), step=1, max_steps=10),
                   PolicyCode.DANGEROUS_ELEMENT)


def test_press_enter_on_dangerous_element_blocked() -> None:
    obs = make_obs(elements=[make_element(1, "button", "Delete account")])
    v = engine().check(act(ActionType.PRESS, eid(1), key="Enter"), obs, ExplorationMemory(), step=1, max_steps=10)
    assert_blocked(v, PolicyCode.DANGEROUS_ELEMENT)


def test_finish_never_blocked_by_dangerous_or_repetition_rules() -> None:
    assert engine().check(act(ActionType.FINISH), make_obs(), ExplorationMemory(), step=999, max_steps=10).allowed


# ---------------------------------------------------------------- domain restriction

def test_open_outside_allowed_domain_blocked() -> None:
    v = engine().check(act(ActionType.OPEN, url="http://evil.test/"), make_obs(), ExplorationMemory(), step=1, max_steps=10)
    assert_blocked(v, PolicyCode.DOMAIN_NOT_ALLOWED)


def test_click_link_to_external_domain_blocked() -> None:
    obs = make_obs(elements=[make_element(1, "link", "Docs", href="http://evil.test/docs")])
    v = engine().check(act(ActionType.CLICK, eid(1)), obs, ExplorationMemory(), step=1, max_steps=10)
    assert_blocked(v, PolicyCode.DOMAIN_NOT_ALLOWED)


def test_subdomains_allowed_only_when_configured() -> None:
    obs = make_obs(elements=[make_element(1, "link", "Docs", href="http://docs.app.test/x")])
    m = ExplorationMemory()
    assert engine(allow_subdomains=True).check(act(ActionType.CLICK, eid(1)), obs, m, step=1, max_steps=10).allowed
    assert_blocked(engine(allow_subdomains=False).check(act(ActionType.CLICK, eid(1)), obs, m, step=1, max_steps=10),
                   PolicyCode.DOMAIN_NOT_ALLOWED)


def test_hash_links_never_treated_as_external() -> None:
    obs = make_obs(elements=[make_element(1, "link", "Jump", href="#section")])
    assert engine().check(act(ActionType.CLICK, eid(1)), obs, ExplorationMemory(), step=1, max_steps=10).allowed


def test_unrestricted_when_no_allowed_domains_configured() -> None:
    p = PolicyEngine(PolicyConfig(allowed_domains=[]))
    assert p.url_verdict("http://anything.test/x").allowed


# ---------------------------------------------------------------- repeated clicks / elements

def test_identical_action_blocked_after_limit() -> None:
    obs = make_obs(elements=[make_element(1, "button", "Refresh")])
    p, m = engine(max_identical_actions_per_state=2), ExplorationMemory()
    a = act(ActionType.CLICK, eid(1))
    for _ in range(2):
        assert p.check(a, obs, m, step=1, max_steps=10).allowed
        m.note_action(obs.state_fingerprint, a)
    assert_blocked(p.check(a, obs, m, step=1, max_steps=10), PolicyCode.REPEATED_ACTION)


def test_same_element_different_args_not_treated_as_repeat() -> None:
    obs = make_obs(elements=[make_element(1, "textbox", "Search")])
    p, m = engine(max_identical_actions_per_state=1), ExplorationMemory()
    a1, a2 = act(ActionType.TYPE, eid(1), text="a"), act(ActionType.TYPE, eid(1), text="b")
    m.note_action(obs.state_fingerprint, a1)
    assert p.check(a1, obs, m, step=1, max_steps=10).allowed is False       # exact repeat blocked
    assert p.check(a2, obs, m, step=1, max_steps=10).allowed is True        # different text allowed


def test_repeated_element_across_action_types_capped() -> None:
    # distinct PRESS keys count as different actions but the same element -> element cap, not action cap
    obs = make_obs(elements=[make_element(1, "button", "Like")])
    p, m = engine(max_identical_actions_per_state=99, max_actions_per_element=3), ExplorationMemory()
    for key in ("Enter", "Space", "Tab"):
        m.note_action(obs.state_fingerprint, act(ActionType.PRESS, eid(1), key=key))
    v = p.check(act(ActionType.PRESS, eid(1), key="a"), obs, m, step=1, max_steps=10)
    assert_blocked(v, PolicyCode.REPEATED_ELEMENT)


def test_wait_limited_and_no_more_than_two_in_a_row() -> None:
    p, m = engine(max_wait_ms=5000, max_identical_actions_per_state=99), ExplorationMemory()
    obs = make_obs()
    assert_blocked(p.check(act(ActionType.WAIT, milliseconds=9000), obs, m, step=1, max_steps=10), PolicyCode.WAIT_LIMIT)
    # two different WAITs in a row still trip the "too many waits" rule, distinct from repeated-action
    m.note_action(obs.state_fingerprint, act(ActionType.WAIT, milliseconds=100))
    m.note_action(obs.state_fingerprint, act(ActionType.WAIT, milliseconds=200))
    assert_blocked(p.check(act(ActionType.WAIT, milliseconds=300), obs, m, step=1, max_steps=10), PolicyCode.WAIT_LIMIT)


def test_scroll_and_reload_capped_per_state() -> None:
    obs = make_obs()
    p, m = engine(max_scrolls_per_state=2, max_reloads_per_state=1, max_identical_actions_per_state=99), ExplorationMemory()
    m.note_action(obs.state_fingerprint, act(ActionType.SCROLL, direction="down"))
    m.note_action(obs.state_fingerprint, act(ActionType.SCROLL, direction="up"))   # different args, same TYPE cap
    assert_blocked(p.check(act(ActionType.SCROLL, direction="down"), obs, m, step=1, max_steps=10), PolicyCode.SCROLL_LIMIT)
    m.note_action(obs.state_fingerprint, act(ActionType.RELOAD))
    assert_blocked(p.check(act(ActionType.RELOAD), obs, m, step=1, max_steps=10), PolicyCode.RELOAD_LIMIT)


def test_back_forward_pingpong_blocked() -> None:
    m = ExplorationMemory()
    m.note_action("s1", act(ActionType.FORWARD))
    assert_blocked(engine().check(act(ActionType.BACK), make_obs(), m, step=1, max_steps=10), PolicyCode.HISTORY_PINGPONG)


def test_repeated_open_of_same_url_blocked() -> None:
    p, m = engine(max_opens_of_same_url=2), ExplorationMemory()
    url = "http://app.test/products"
    for _ in range(2):
        m.note_action("s", act(ActionType.OPEN, url=url))
    assert_blocked(p.check(act(ActionType.OPEN, url=url), make_obs(), m, step=1, max_steps=10), PolicyCode.REPEATED_ACTION)


# ---------------------------------------------------------------- repeated-state exploration & loops

def test_state_overexplored_forces_new_ground() -> None:
    # "visited N times" = arrived at this state N times (leaving and coming back), not N observe() calls in place.
    # Once the visit cap is hit, RE-trying an already-tried element/action is blocked, but a genuinely
    # untried element is still allowed — repeated visiting is fine as long as it finds new ground.
    el, fresh = make_element(1, "textbox", "Notes"), make_element(2, "button", "New")
    obs = make_obs(elements=[el, fresh])
    away = make_obs(url=f"{obs.url}other", fingerprint="away")
    p, m = engine(max_state_visits=3), ExplorationMemory()
    for step in range(3):
        m.observe(obs, step * 2)
        m.observe(away, step * 2 + 1)
    assert m.visits(obs.state_fingerprint) == 3
    m.note_action(obs.state_fingerprint, act(ActionType.TYPE, eid(1), text="hi"))   # el is now "tried"

    v = p.check(act(ActionType.TYPE, eid(1), text="different"), obs, m, step=7, max_steps=10)
    assert_blocked(v, PolicyCode.STATE_OVEREXPLORED)
    assert p.check(act(ActionType.CLICK, eid(2)), obs, m, step=7, max_steps=10).allowed  # untried: still fine


@pytest.mark.parametrize("seq,repeats,cycle,expected", [
    (["a", "b", "a", "b", "a", "b"], 3, 4, 2),
    (["a", "b", "c", "a", "b", "c", "a", "b", "c"], 3, 4, 3),
    (["x", "a", "b", "a", "b", "a", "b"], 3, 4, 2),
    (["a", "b", "a", "b"], 3, 4, None),
    (["a", "a", "a", "a"], 3, 4, None),                       # stagnation, not a loop
    (["a", "b", "c", "d", "e"], 3, 4, None),
])
def test_detect_cycle(seq, repeats, cycle, expected) -> None:
    assert detect_cycle(seq, min_repeats=repeats, max_cycle=cycle) == expected


def test_loop_blocks_the_repeated_action() -> None:
    obs = make_obs(elements=[make_element(1, "link", "Products", href="/products")])
    p, m = engine(loop_min_repeats=3, loop_max_cycle=2), ExplorationMemory()
    for i in range(6):
        m.state_sequence.append("s1" if i % 2 == 0 else "s2")
    m.note_action(obs.state_fingerprint, act(ActionType.CLICK, eid(1)))
    v = p.check(act(ActionType.CLICK, eid(1)), obs, m, step=7, max_steps=20)
    assert_blocked(v, PolicyCode.LOOP_DETECTED)


# ---------------------------------------------------------------- input hygiene & step budget

def test_overlong_text_blocked() -> None:
    obs = make_obs(elements=[make_element(1, "textbox", "Bio")])
    v = engine(max_text_length=10).check(act(ActionType.TYPE, eid(1), text="x" * 11), obs, ExplorationMemory(),
                                         step=1, max_steps=10)
    assert_blocked(v, PolicyCode.TEXT_TOO_LONG)


def test_secret_looking_text_blocked() -> None:
    obs = make_obs(elements=[make_element(1, "textbox", "Token")])
    v = engine().check(act(ActionType.TYPE, eid(1), text="AKIAIOSFODNN7EXAMPLE"), obs, ExplorationMemory(),
                       step=1, max_steps=10)
    assert_blocked(v, PolicyCode.SECRET_IN_TEXT)


def test_step_beyond_budget_blocked() -> None:
    v = engine().check(act(ActionType.CLICK, eid(1)), make_obs(elements=[make_element(1)]), ExplorationMemory(),
                       step=11, max_steps=10)
    assert_blocked(v, PolicyCode.STEP_BUDGET)


def test_no_target_no_regression_for_navigation_actions() -> None:
    m = ExplorationMemory()
    for t in (ActionType.BACK, ActionType.FORWARD, ActionType.RELOAD, ActionType.WAIT):
        args = {"milliseconds": 100} if t == ActionType.WAIT else {}
        assert engine().check(act(t, **args), make_obs(), m, step=1, max_steps=10).allowed


# ---------------------------------------------------------------- hints

def test_hints_flag_loop_and_exhaustion() -> None:
    m = ExplorationMemory()
    for i in range(6):
        m.state_sequence.append("s1" if i % 2 == 0 else "s2")
    p = engine(loop_min_repeats=3, loop_max_cycle=2)
    hints = p.hints(m, make_obs(), step=1, max_steps=10)
    assert any("cycling" in h for h in hints)


def test_hints_flag_low_remaining_budget() -> None:
    hints = engine().hints(ExplorationMemory(), make_obs(), step=9, max_steps=10)
    assert any("Few steps remain" in h for h in hints)
