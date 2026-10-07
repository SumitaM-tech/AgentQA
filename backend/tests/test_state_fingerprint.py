from app.perception.extractor import _state_fingerprint
from app.perception.observation import compute_state_fingerprint
from tests.agent_helpers import make_element


def test_observation_fingerprint_deterministic():
    a = compute_state_fingerprint("http://a.test/x", "T", "sig")
    assert a == compute_state_fingerprint("http://a.test/x", "T", "sig")
    assert a != compute_state_fingerprint("http://a.test/y", "T", "sig")
    assert a != compute_state_fingerprint("http://a.test/x", "T", "sig2")


def test_extractor_fingerprint_ignores_query_fragment_and_element_order():
    e1, e2 = make_element(1, "button", "A"), make_element(2, "link", "B", href="/b")
    a = _state_fingerprint("http://a.test/p?utm=1#frag", "Title", [e1, e2])
    b = _state_fingerprint("http://a.test/p?utm=2", "Title", [e2, e1])
    assert a == b
    assert a != _state_fingerprint("http://a.test/p", "Other title", [e1, e2])
    assert a != _state_fingerprint("http://a.test/p", "Title", [e1])
    assert len(a) <= 64  # a hash, never a raw DOM dump
