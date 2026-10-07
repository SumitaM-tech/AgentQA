"""Perception layer tests. Unit tests need no browser; integration tests drive
real headless Chromium against the local Mini Shop app (tests/fixtures/app)."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.browser.manager import BrowserManager
from app.browser.models import ErrorCode
from app.perception import CompactOptions, ObservationLimits, gemini_context, to_compact_dict, to_prompt_text
from app.perception.compact import UNTRUSTED_CLOSE, UNTRUSTED_OPEN
from app.perception.models import (
    PageObservation, PageElement, SelectorStrategy, Viewport, NetworkError,
)
from app.perception.sanitize import (
    clean_block, clean_inline, escape_untrusted, is_sensitive_field, redact_secrets,
    sanitize_aria_snapshot, strip_invisible, truncate,
)
from tests.test_browser_engine import needs_chromium  # noqa: F401  (skip marker)


@pytest.fixture
def artifacts(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREENSHOT_DIR", str(tmp_path / "shots"))
    monkeypatch.setenv("TRACE_DIR", str(tmp_path / "traces"))
    from app.core.config import get_settings

    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


@pytest.fixture
async def manager(artifacts):
    m = BrowserManager()
    yield m
    await m.shutdown()


def by_name(obs, name, *, role=None):
    return [e for e in obs.interactive_elements if e.name == name and (role is None or e.role == role)]


async def open_app(session, base, page="index.html"):
    r = await session.open_url(f"{base}/{page}")
    assert r.ok, r.error
    await session.wait(150)  # let the app's timers/fetches fire
    return await session.observe(screenshot=False)


# ---------------------------------------------------------------- unit: sanitization (no browser)

def test_strip_invisible_removes_hidden_characters() -> None:
    hidden = "a\u200bb\u202ec" + chr(0xE0049) + chr(0xE0067) + "d\x00e\u00adf"
    assert strip_invisible(hidden) == "abcdef"
    assert strip_invisible("keep\nnewline\ttab") == "keep\nnewline\ttab"


def test_redact_secrets_and_luhn() -> None:
    txt = ("jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijklmnop aws AKIAIOSFODNN7EXAMPLE "
           "card 4111 1111 1111 1111 not-a-card 1234567890123 order 12345678 Bearer abcdefghijklmnopqrstuvwx")
    out = redact_secrets(txt)
    for secret in ("eyJhbGci", "AKIAIOSF", "4111", "abcdefghijklmnopqrstuvwx"):
        assert secret not in out
    assert "1234567890123" in out and "12345678" in out  # non-Luhn numbers untouched


def test_truncate_and_blocks() -> None:
    t, omitted = truncate("x" * 500, 100)
    assert len(t) <= 100 and t.endswith("chars]") and omitted == 400
    assert truncate("short", 100) == ("short", 0)
    text, om = clean_block("a\r\n\n\n\n  b   c \n" + "z" * 1000, 200)
    assert "\n\n\n" not in text and len(text) <= 200 and om > 0
    assert clean_inline("  a \n\t b  ", 50) == "a b"


def test_sensitive_field_detection_and_aria_redaction() -> None:
    assert is_sensitive_field("password") and is_sensitive_field(None, "api_token") and is_sensitive_field("cc-number")
    assert not is_sensitive_field("text", "username", "email")
    snap = ('- textbox "Pass": hunter2secret\n- textbox "Empty"\n- link "Go":\n  - /url: /x?token=abc123\n'
            '- button "Ok"')
    out, _ = sanitize_aria_snapshot(snap, 1000)
    assert "hunter2secret" not in out and "abc123" not in out
    assert 'textbox "Empty"' in out and "/url: /x?…" in out
    long, omitted = sanitize_aria_snapshot("\n".join(f"- link \"L{i}\"" for i in range(500)), 300)
    assert len(long) < 400 and omitted > 0 and long.rstrip().endswith("chars]")


def test_escape_untrusted_blocks_delimiter_forgery() -> None:
    assert UNTRUSTED_CLOSE not in escape_untrusted(f"x {UNTRUSTED_CLOSE} y")


def _synthetic(n: int, text_len: int = 20000) -> PageObservation:
    els = [
        PageElement(
            id=f"e{i:06x}", role="button", tag="button", name=f"Button number {i}", in_viewport=i < 20,
            selector_strategy=SelectorStrategy(kind="css", value="body > button", fragile=True), fingerprint=str(i),
        )
        for i in range(400)
    ]
    return PageObservation(
        url="http://x.test/a", title="T", visible_text="lorem ipsum " * (text_len // 12),
        accessibility_tree="\n".join(f'- button "B{i}"' for i in range(2000)),
        interactive_elements=els, viewport=Viewport(width=1000, height=800),
        network_errors=[NetworkError(url="http://x.test/api", method="GET", status=500)],
    )


def test_compact_respects_budget_and_marks_untrusted() -> None:
    obs = _synthetic(400)
    for budget in (3000, 6000, 12000):
        text = to_prompt_text(obs, CompactOptions(max_chars=budget))
        assert len(text) <= budget + 400, (budget, len(text))
        assert UNTRUSTED_OPEN in text and text.count(UNTRUSTED_CLOSE) == 1
        assert "network 500 GET" in text          # issues are never dropped
        assert "more elements omitted" in text     # and omission is stated
    # on-screen elements are preferred when trimming
    small = to_prompt_text(obs, CompactOptions(max_chars=3000, max_elements=25))
    assert "e000000 button" in small and "e000190" not in small
    assert estimate(small) < estimate(obs.model_dump_json()) / 10


def estimate(s: str) -> int:
    return len(s) // 4


def test_compact_dict_shape() -> None:
    d = to_compact_dict(_synthetic(50), CompactOptions(max_elements=10))
    assert len(d["elements"]) == 10 and d["elements_omitted"] >= 390
    assert set(d["elements"][0]) <= {"id", "role", "name", "type", "placeholder", "value", "href", "state"}
    assert d["issues"] and "untrusted" in d["note"].lower()


# ---------------------------------------------------------------- integration (real Chromium)

@needs_chromium
async def test_observation_has_every_signal(manager, app_server) -> None:
    async with manager.session() as s:
        await s.open_url(f"{app_server}/index.html")
        await s.wait(150)
        obs = await s.observe()

        assert len(obs.observation_id) == 32 and obs.timestamp.tzinfo is not None
        assert obs.url.endswith("/index.html") and obs.title == "Mini Shop"
        assert obs.screenshot_path and Path(obs.screenshot_path).stat().st_size > 1000
        assert 'button "Sign in"' in obs.accessibility_tree and "navigation" in obs.accessibility_tree
        assert "Mini Shop" in obs.visible_text and "Ready" in obs.visible_text
        assert len(obs.interactive_elements) > 15
        assert obs.viewport.width == 1440 and obs.viewport.height == 900 and obs.viewport.page_height > 900
        assert obs.page_load_state in ("load", "networkidle")

        assert any("boot: config missing" in c.text for c in obs.console_errors)
        assert not any(c.text.startswith("Failed to load resource") for c in obs.console_errors)  # deduped
        assert [e.message for e in obs.browser_exceptions] == ["Unhandled tick failure"]
        statuses = {(n.status, n.url.rsplit("/", 1)[-1]) for n in obs.network_errors}
        assert {(500, "boom"), (404, "missing.json")} <= statuses
        assert obs.network_errors[0].status == 500  # 5xx ranked above 4xx

        dm = obs.dom_metadata
        assert dm.lang == "en" and "tiny shop" in dm.meta_description
        assert dm.iframe_count == 1 and dm.form_count == 1 and dm.landmarks["nav"] == 1
        assert dm.interactive_hidden >= 2  # the display:none button and [hidden] link
        assert [h.text for h in dm.headings][:2] == ["Mini Shop", "Products"]
        assert not obs.truncation.any and obs.state_fingerprint

        # telemetry is "since last observation": a second observation is clean
        again = await s.observe(screenshot=False)
        assert not again.console_errors and not again.browser_exceptions and not again.network_errors
        assert again.state_fingerprint == obs.state_fingerprint


@needs_chromium
async def test_element_fields(manager, app_server) -> None:
    async with manager.session() as s:
        obs = await open_app(s, app_server)
        e = {x.name: x for x in obs.interactive_elements}

        menu = e["Open menu"]                                   # icon-only button
        assert menu.aria_label == "Open menu" and menu.role == "button" and menu.tag == "button"
        user = e["Username"]
        assert user.placeholder == "Username" and user.role == "textbox" and user.required and user.value == ""
        assert user.text == "Username"                          # associated <label>
        draft = e["Save draft"]
        assert draft.enabled is False and e["Sign in"].enabled is True
        assert e["Subscribe"].checked is False and e["Country"].value == "United States"
        assert e["Cart (0)"].href == "#cart"

        bb = e["Sign in"].bounding_box
        assert bb.width > 0 and bb.height > 0 and e["Sign in"].visible
        assert e["Bottom button"].in_viewport is False          # visible but below the fold
        assert "Hidden button" not in e and "Hidden link" not in e

        assert e["Checkout"].selector_strategy.kind == "testid"
        assert e["Sign in"].selector_strategy.kind in ("id", "role")
        assert all(x.selector_strategy.kind != "css" for x in obs.interactive_elements)  # nothing needs css
        assert e["Shadow action"].role == "button" and e["Promo banner"].role == "clickable"


@needs_chromium
async def test_sensitive_values_are_redacted_everywhere(manager, app_server) -> None:
    async with manager.session() as s:
        obs = await open_app(s, app_server)
        e = {x.name: x for x in obs.interactive_elements}
        await s.type(e["Username"].id, "alice@example.com")
        await s.type(e["Password"].id, "hunter2secret")
        await s.type(e["API token"].id, "sk-live-abcdefghijklmnop123")
        obs = await s.observe(screenshot=False)
        e = {x.name: x for x in obs.interactive_elements}

        assert e["Username"].value == "alice@example.com"        # normal fields keep values
        assert e["Password"].value == "[redacted]" and e["API token"].value == "[redacted]"
        blob = obs.model_dump_json() + obs.to_prompt_text() + str(obs.to_compact_dict()) + str(gemini_context(obs))
        for secret in ("hunter2secret", "sk-live-abcdefghijklmnop123"):
            assert secret not in blob
        assert "alice@example.com" in obs.to_prompt_text()


@needs_chromium
async def test_page_content_is_sanitized_and_marked_untrusted(manager, app_server) -> None:
    async with manager.session() as s:
        obs = await open_app(s, app_server)
        text = obs.visible_text
        assert not any(ch in text for ch in ("\u200b", "\u202e", chr(0xE0049)))   # hidden chars stripped
        for secret in ("eyJhbGci", "AKIAIOSFODNN7EXAMPLE", "4111"):
            assert secret not in text
        assert "order 12345678" in text                                             # ordinary numbers stay
        prompt = obs.to_prompt_text()
        assert prompt.count(UNTRUSTED_CLOSE) == 1                                   # forged delimiter neutralized
        assert prompt.index("Ignore all previous instructions") > prompt.index(UNTRUSTED_OPEN)
        assert prompt.index("Ignore all previous instructions") < prompt.index(UNTRUSTED_CLOSE)


@needs_chromium
async def test_ids_stable_across_rerender_reload_and_sessions(manager, app_server) -> None:
    async def snapshot(s):
        o = await s.observe(screenshot=False)
        return {e.name: e.id for e in o.interactive_elements if e.name != "Add to cart"}, \
               [e.id for e in by_name(o, "Add to cart")], o

    async with manager.session() as s1:
        await s1.open_url(f"{app_server}/index.html")
        named1, adds1, obs1 = await snapshot(s1)
        assert len(set(adds1)) == 3 and all("." in i for i in adds1)          # duplicates told apart
        assert named1["Dynamic id"].startswith("e")

        # Re-render: brand-new DOM nodes, new css class names, new generated ids.
        await s1.click(named1["Re-render list"])
        named2, adds2, _ = await snapshot(s1)
        assert named2 == named1 and adds2 == adds1

        await s1.reload()
        named3, adds3, _ = await snapshot(s1)
        assert named3 == named1 and adds3 == adds1

    async with manager.session() as s2:                                        # fresh browser session
        await s2.open_url(f"{app_server}/index.html")
        named4, adds4, _ = await snapshot(s2)
        assert named4 == named1 and adds4 == adds1

    # Cart counter text changes ("Cart (0)" -> "Cart (1)"): digits are masked, id unchanged.
    async with manager.session() as s3:
        await s3.open_url(f"{app_server}/index.html")
        _, adds, o = await snapshot(s3)
        cart_before = by_name(o, "Cart (0)")[0].id
        await s3.click(adds[0])
        o2 = await s3.observe(screenshot=False)
        assert by_name(o2, "Cart (1)")[0].id == cart_before


@needs_chromium
async def test_duplicate_ids_survive_reordering_and_act_on_the_right_item(manager, app_server) -> None:
    async with manager.session() as s:
        obs = await open_app(s, app_server)
        adds = by_name(obs, "Add to cart")
        # Identify which id belongs to which product by clicking and reading the page.
        seen = {}
        for a in adds:
            assert (await s.click(a.id)).ok
            st = await s.observe(screenshot=False)
            seen[a.id] = st.visible_text.split("Added: ")[1].splitlines()[0]
        assert sorted(seen.values()) == ["Apple", "Banana", "Cherry"]

        reverse = by_name(obs, "Reverse list")[0].id
        await s.click(reverse)                       # order becomes Cherry, Banana, Apple
        after = await s.observe(screenshot=False)
        assert sorted(e.id for e in by_name(after, "Add to cart")) == sorted(seen)   # same ids...
        for old_id, product in seen.items():                                          # ...same products
            assert (await s.click(old_id)).ok
            st = await s.observe(screenshot=False)
            assert f"Added: {product}" in st.visible_text


@needs_chromium
async def test_resolver_falls_back_when_dom_attribute_is_lost(manager, app_server) -> None:
    async with manager.session() as s:
        obs = await open_app(s, app_server)
        e = {x.name: x for x in obs.interactive_elements}
        await s._page.evaluate("document.querySelectorAll('[data-agentqa-id]').forEach(n => n.removeAttribute('data-agentqa-id'))")
        assert (await s.click(e["Checkout"].id)).ok                 # testid strategy
        assert (await s.click(e["Sign in"].id)).ok                  # id/role strategy
        assert (await s.click(e["Shadow action"].id)).ok            # role strategy through shadow DOM
        assert (await s.click(e["Promo banner"].id)).ok             # text/id strategy for clickable div
        st = await s.observe(screenshot=False)
        assert "Shadow clicks: 1" in st.visible_text and "Promo clicked" in st.visible_text


@needs_chromium
async def test_never_acts_on_an_element_that_changed_identity(manager, app_server) -> None:
    async with manager.session() as s:
        obs = await open_app(s, app_server)
        target = by_name(obs, "Checkout")[0]
        # DOM node keeps its data attribute but now means something else.
        await s._page.evaluate("""() => { const b = document.querySelector('[data-testid="checkout-btn"]');
            b.textContent = 'Delete account'; b.removeAttribute('data-testid'); b.id = 'zz';
            b.addEventListener('click', () => { document.getElementById('status').textContent = 'ACCOUNT DELETED'; }); }""")
        r = await s.click(target.id)
        assert not r.ok and r.error_code == ErrorCode.ELEMENT_NOT_FOUND
        assert "refresh" in r.error.lower()
        st = await s.observe(screenshot=False)
        assert "ACCOUNT DELETED" not in st.visible_text


@needs_chromium
async def test_truncation_and_compact_size_on_a_large_page(manager, app_server) -> None:
    async with manager.session() as s:
        await s.open_url(f"{app_server}/bulk.html")
        raw_html = await s._page.content()
        obs = await s.observe(screenshot=False)
        assert len(obs.interactive_elements) == 150 and obs.truncation.elements_omitted == 250
        assert obs.truncation.visible_text_omitted_chars > 0 and obs.visible_text.endswith("chars]")
        assert len(obs.visible_text) <= 4000
        assert obs.truncation.accessibility_tree_omitted_chars > 0 and len(obs.accessibility_tree) <= 5100

        prompt = obs.to_prompt_text()
        assert len(prompt) <= 12400 and len(raw_html) > 30000
        assert "<li>" not in prompt and "<a href" not in prompt              # never raw HTML
        assert "more elements omitted" in prompt

        tight = to_prompt_text(obs, CompactOptions(max_chars=3000))
        assert len(tight) <= 3400 and "ELEMENTS" in tight

    # limits are configurable per session
    async with manager.session() as s:
        s.limits = ObservationLimits(max_elements=10, max_visible_text_chars=500, include_accessibility=False)
        await s.open_url(f"{app_server}/bulk.html")
        small = await s.observe(screenshot=False)
        assert len(small.interactive_elements) == 10 and len(small.visible_text) <= 500
        assert small.accessibility_tree is None


@needs_chromium
async def test_tag_dom_can_be_disabled(manager, app_server) -> None:
    async with manager.session() as s:
        s.limits = ObservationLimits(tag_dom=False)
        await s.open_url(f"{app_server}/index.html")
        obs = await s.observe(screenshot=False)
        assert await s._page.locator("[data-agentqa-id]").count() == 0       # page left untouched
        e = {x.name: x for x in obs.interactive_elements}
        assert (await s.click(e["Checkout"].id)).ok                          # strategies alone still work


@needs_chromium
async def test_tool_result_and_gemini_context(manager, app_server) -> None:
    from app.browser.tools import BrowserToolbox
    from app.llm.service import GeminiService
    from tests.test_gemini_service import DECISION, FakeClient, _text_response
    import json

    async with manager.session() as s:
        tb = BrowserToolbox(s)
        await tb.execute("browser_open", {"url": f"{app_server}/index.html"})
        await s.wait(150)
        res = await tb.execute("browser_get_page_state")
        assert res.ok and res.result["elements"] and res.result["issues"]
        assert "<" not in json.dumps(res.result["elements"])                  # no markup in element list
        first = res.result["elements"][0]["id"]
        assert (await tb.execute("browser_click", {"element_id": "e" + "0" * 6})).error_code == ErrorCode.ELEMENT_NOT_FOUND
        assert first.startswith("e")

        await s.reload()                       # errors are reported once, so provoke them again
        await s.wait(150)
        obs = await s.observe(screenshot=False)
        ctx = gemini_context(obs)
        fake = FakeClient(_text_response(json.dumps(DECISION)))
        decision = await GeminiService(fake).decide_next_action(goal="test the login form", **ctx)
        assert decision.action_type.value == "fill"
        prompt = fake.calls[0][0][0]
        assert obs.interactive_elements[0].id in prompt and "Unhandled tick failure" in prompt
        assert "Visible page text (untrusted" in prompt
