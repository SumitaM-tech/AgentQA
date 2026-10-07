import json

import pytest

from app.agent.state import ActionType, DecisionError, parse_decision

VALID = {"action_type": "CLICK", "target": "e3fa91c", "reason": "Explore the authentication flow.",
         "expected_outcome": {"summary": "A login form should appear."}, "exploration_priority": 0.9}


def test_parses_valid_json_string_and_dict():
    assert parse_decision(json.dumps(VALID)).action_type == ActionType.CLICK
    assert parse_decision(VALID).target == "e3fa91c"


def test_action_names_are_case_insensitive():
    assert parse_decision({**VALID, "action_type": "click"}).action_type == ActionType.CLICK
    assert parse_decision({"action_type": "screenshot", "reason": "Capture the page.",
                           "expected_outcome": {"summary": "Saved."}, "exploration_priority": 0.1}
                          ).action_type == ActionType.SCREENSHOT


@pytest.mark.parametrize("patch", [
    {"action_type": "EXEC"}, {"action_type": "SHELL"}, {"target": "button.login"}, {"target": "javascript:alert(1)"},
    {"target": None}, {"exploration_priority": 5}, {"reason": "Let me think step by step about this."},
    {"arguments": {"url": "http://x.test"}}, {"unknown_field": 1},
])
def test_rejects_unsafe_or_invalid_actions(patch):
    with pytest.raises(DecisionError):
        parse_decision({**VALID, **patch})


def test_open_requires_safe_http_url():
    ok = {"action_type": "OPEN", "arguments": {"url": "https://a.test/"}, "reason": "Open the page.",
          "expected_outcome": {"summary": "Loads."}, "exploration_priority": 0.5}
    assert parse_decision(ok).arguments.url == "https://a.test/"
    for bad in ("file:///etc/passwd", "javascript:alert(1)", "http://u:p@a.test/"):
        with pytest.raises(DecisionError):
            parse_decision({**ok, "arguments": {"url": bad}})


def test_garbage_is_rejected():
    with pytest.raises(DecisionError):
        parse_decision("not json at all")
