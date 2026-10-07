from app.agent.critic import BugCandidate
from app.agent.state import ActionArguments, ActionType, AgentAction, ExpectedOutcome, Severity
from app.bugs.fingerprint import bug_fingerprint, normalize_url
from app.bugs.severity import assess_severity
from app.bugs.verifier import VerificationResult, decide, replay_plan
from tests.agent_helpers import eid, make_element, make_obs


def _bug(**kw) -> BugCandidate:
    base = dict(title="Console error after clicking Pay", severity=Severity.MEDIUM, category="console_error",
                description="d", evidence=["console.error: x"], step_index=3, url="http://a.test/checkout?id=42",
                state_id="s1", action_summary="CLICK e1", expected="e", actual="a", confidence=0.7,
                needs_verification=True)
    base.update(kw)
    return BugCandidate(**base)


def test_fingerprint_is_deterministic_and_ignores_volatile_parts():
    a = bug_fingerprint("network", "http://a.test/orders/123?x=1#top", "Server error 500 for order 123")
    b = bug_fingerprint("network", "http://a.test/orders/987?x=2", "Server error 500 for order 987")
    assert a == b and len(a) == 32
    assert a == bug_fingerprint("network", "http://a.test/orders/123?x=1#top", "Server error 500 for order 123")


def test_fingerprint_differs_for_different_bugs():
    base = bug_fingerprint("network", "http://a.test/cart", "Server error 500")
    assert base != bug_fingerprint("validation", "http://a.test/cart", "Server error 500")
    assert base != bug_fingerprint("network", "http://a.test/checkout", "Server error 500")
    assert base != bug_fingerprint("network", "http://a.test/cart", "Payment declined incorrectly")


def test_duplicate_detection_with_fingerprint_set():
    seen: set[str] = set()
    dups = 0
    for i in (1, 2, 3):
        fp = bug_fingerprint("console_error", f"http://a.test/p/{i}", f"Unexpected error {i}")
        dups += fp in seen
        seen.add(fp)
    assert dups == 2 and len(seen) == 1


def test_normalize_url_collapses_ids():
    assert normalize_url("https://Shop.test/items/42/reviews/?page=2") == "shop.test/items/:id/reviews"


def test_severity_floor_for_hard_evidence_and_flow_bump():
    sev, why = assess_severity(Severity.LOW, category="exception", evidence=["Uncaught exception: boom"])
    assert sev == Severity.HIGH and "uncaught" in why.lower()
    sev, _ = assess_severity(Severity.MEDIUM, category="functional", evidence=["x"], text="Payment form checkout")
    assert sev == Severity.HIGH
    sev, _ = assess_severity(Severity.HIGH, category="console_error", evidence=["console.error: x"])
    assert sev == Severity.MEDIUM


def test_decide_statuses():
    b = _bug()
    assert decide(b, VerificationResult(True, 2, 0.9))[0] == "verified"
    assert decide(b, VerificationResult(False, 2, 0.55))[0] == "unverified"
    assert decide(b, VerificationResult(False, 2, 0.3))[0] == "discarded"


def _act(t, target=None, **args):
    return AgentAction(action_type=t, target=target, arguments=ActionArguments(**args),
                       expected_outcome=ExpectedOutcome(summary="Page responds normally."), reason="Testing something.",
                       exploration_priority=0.5)


def test_replay_is_only_planned_for_safe_actions():
    link = make_element(1, "link", "Docs", href="http://a.test/docs")
    button = make_element(2, "button", "Pay")
    box = make_element(3, "textbox", "Card")
    before = make_obs(elements=[link, button, box])
    assert replay_plan(_act(ActionType.CLICK, eid(1)), before).action_type == ActionType.OPEN
    assert replay_plan(_act(ActionType.CLICK, eid(2)), before) is None      # would re-submit
    assert replay_plan(_act(ActionType.TYPE, eid(3), text="4111"), before) is None
    assert replay_plan(_act(ActionType.RELOAD), before) is not None
