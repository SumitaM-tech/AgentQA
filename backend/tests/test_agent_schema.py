"""Decision schema: exactly one well-formed, code-free AgentAction."""
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.agent.state import (
    ActionArguments, ActionType, AgentAction, DecisionError, ExpectedOutcome, parse_decision,
)
from tests.agent_helpers import eid

EXP = {"summary": "The page changes."}


def action(t: str, target=None, args=None, **over) -> dict:
    d = {"action_type": t, "target": target, "arguments": args or {}, "expected_outcome": EXP,
         "reason": "Testing the flow.", "exploration_priority": 0.5}
    d.update(over)
    return d


VALID = [
    ("OPEN", None, {"url": "http://app.test/x"}),
    ("CLICK", eid(1), {}),
    ("TYPE", eid(2), {"text": "hello", "press_enter": True}),
    ("SELECT", eid(3), {"label": "India"}),
    ("SELECT", eid(3), {"index": 1}),
    ("SCROLL", None, {"direction": "down", "amount": 400}),
    ("SCROLL", eid(4), {}),
    ("PRESS", None, {"key": "Escape"}),
    ("PRESS", eid(2), {"key": "Control+A"}),
    ("BACK", None, {}), ("FORWARD", None, {}), ("RELOAD", None, {}),
    ("WAIT", None, {"milliseconds": 500}), ("WAIT", None, {"load_state": "networkidle"}),
    ("SCREENSHOT", None, {}),
    ("FINISH", None, {}),
]


def test_exactly_the_specified_action_types() -> None:
    assert [a.value for a in ActionType] == [
        "OPEN", "CLICK", "TYPE", "SELECT", "SCROLL", "PRESS", "BACK", "FORWARD", "RELOAD", "WAIT", "SCREENSHOT", "FINISH"]


@pytest.mark.parametrize("t,target,args", VALID)
def test_valid_actions(t, target, args) -> None:
    a = AgentAction.model_validate(action(t, target, args))
    assert a.action_type.value == t and a.target == target
    assert 0 <= a.exploration_priority <= 1 and a.expected_outcome.summary and a.reason


def test_every_field_the_spec_requires_is_present() -> None:
    props = AgentAction.model_json_schema()["properties"]
    assert {"action_type", "target", "arguments", "expected_outcome", "reason", "exploration_priority"} <= set(props)
    required = set(AgentAction.model_json_schema()["required"])
    assert {"action_type", "expected_outcome", "reason", "exploration_priority"} <= required
    assert not ({"code", "script", "selector", "javascript", "command"} & set(props))


@pytest.mark.parametrize("payload,why", [
    (action("CLICK"), "requires a target"),
    (action("TYPE", args={"text": "x"}), "requires a target"),
    (action("SELECT", args={"value": "a"}), "requires a target"),
    (action("BACK", eid(1)), "does not take a target"),
    (action("OPEN", eid(1), {"url": "http://app.test"}), "does not take a target"),
    (action("CLICK", "#login > button"), "element id"),
    (action("CLICK", "//button[1]"), "element id"),
    (action("CLICK", "javascript:alert(1)"), "element id"),
    (action("CLICK", "http://evil.test"), "element id"),
    (action("CLICK", "el-12"), "element id"),
    (action("CLICK", eid(1), {"text": "x"}), "does not accept arguments"),
    (action("OPEN", args={}), "requires arguments"),
    (action("OPEN", args={"url": "file:///etc/passwd"}), "invalid url"),
    (action("OPEN", args={"url": "javascript:alert(1)"}), "invalid url"),
    (action("OPEN", args={"url": "http://user:pw@app.test"}), "invalid url"),
    (action("TYPE", eid(1), {}), "requires arguments"),
    (action("TYPE", eid(1), {"text": "x" * 501}), "at most 500"),
    (action("SELECT", eid(1), {}), "exactly one"),
    (action("SELECT", eid(1), {"value": "a", "label": "b"}), "exactly one"),
    (action("SCROLL", None, {}), "direction or a target"),
    (action("SCROLL", None, {"direction": "sideways"}), "direction"),
    (action("PRESS", None, {}), "requires arguments"),
    (action("PRESS", None, {"key": "Control+Alt+Delete+X"}), "invalid key"),
    (action("PRESS", None, {"key": "rm -rf /"}), "invalid key"),
    (action("WAIT", None, {}), "milliseconds or load_state"),
    (action("WAIT", None, {"milliseconds": 60_000}), "less than or equal to 10000"),
    (action("FINISH", None, {"url": "http://app.test"}), "does not accept arguments"),
    (action("CLICK", eid(1), exploration_priority=1.5), "less than or equal to 1"),
    (action("CLICK", eid(1), exploration_priority=-0.1), "greater than or equal to 0"),
    (action("CLICK", eid(1), reason="x" * 201), "at most 200"),
    (action("CLICK", eid(1), reason="Let me think about which button to press first"), "deliberation"),
    (action("CLICK", eid(1), reason="Step by step I will click it"), "deliberation"),
    (action("CLICK", eid(1), reason="Click A. Then click B. Then click C. Done."), "single short sentence"),
    (action("CLICK", eid(1), reason=""), "at least 3"),
    (action("CLICK", eid(1), expected_outcome={"summary": ""}), "at least 3"),
    (action("CLICK", eid(1), expected_outcome={"summary": "ok fine", "text_contains": ["a"] * 6}), "at most 5"),
    (action("CLICK", eid(1), expected_outcome={"summary": "ok fine", "text_contains": ["x" * 81]}), "80 characters"),
    (action("CLICK", eid(1), code="import os"), "Extra inputs"),
    (action("CLICK", eid(1), args={"js": "alert(1)"}), "Extra inputs"),
])
def test_invalid_decisions_are_rejected(payload, why) -> None:
    with pytest.raises(ValidationError) as e:
        AgentAction.model_validate(payload)
    assert why in str(e.value), str(e.value)


def test_missing_expected_outcome_is_rejected() -> None:
    p = action("CLICK", eid(1))
    del p["expected_outcome"]
    with pytest.raises(ValidationError):
        AgentAction.model_validate(p)


def test_parse_decision_accepts_json_and_dicts() -> None:
    a = parse_decision(json.dumps(action("CLICK", eid(1))))
    assert a.action_type == ActionType.CLICK
    assert parse_decision(action("BACK")).action_type == ActionType.BACK


def test_parse_decision_requires_exactly_one_action() -> None:
    with pytest.raises(DecisionError, match="exactly one action, got a list of 2"):
        parse_decision([action("BACK"), action("RELOAD")])
    with pytest.raises(DecisionError, match="not valid JSON"):
        parse_decision("click the button")
    with pytest.raises(DecisionError, match="JSON object"):
        parse_decision("42")
    with pytest.raises(DecisionError) as e:
        parse_decision(action("CLICK"))
    assert "target" in str(e.value)


def test_action_key_identity() -> None:
    a = AgentAction.model_validate(action("TYPE", eid(1), {"text": "a"}))
    same = AgentAction.model_validate(action("TYPE", eid(1), {"text": "a"}, reason="Different wording here."))
    other_text = AgentAction.model_validate(action("TYPE", eid(1), {"text": "b"}))
    other_target = AgentAction.model_validate(action("TYPE", eid(2), {"text": "a"}))
    assert a.key() == same.key()
    assert len({a.key(), other_text.key(), other_target.key()}) == 3


def test_describe_is_compact() -> None:
    a = AgentAction.model_validate(action("TYPE", eid(1), {"text": "hello"}))
    assert a.describe("Name") == f"TYPE {eid(1)} \"Name\" text='hello'"


def test_expected_outcome_defaults_and_cleaning() -> None:
    e = ExpectedOutcome(summary="Works", text_contains=["  hello   world ", "", "  "])
    assert e.text_contains == ["hello world"] and e.console_clean and not e.expects_navigation
    assert ActionArguments().provided() == {}
