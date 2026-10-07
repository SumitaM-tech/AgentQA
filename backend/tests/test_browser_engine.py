"""Browser engine tests against real headless Chromium + a local HTTP server."""
from __future__ import annotations

import functools
import http.server
import threading
from pathlib import Path

import pytest

from app.browser.actions import ActionError, assert_url_allowed, validate_url_syntax
from app.browser.manager import BrowserCapacityError, BrowserManager
from app.browser.models import BrowserSessionConfig, ErrorCode
from app.browser.tools import TOOLS, BrowserToolbox, tool_schemas

FIXTURES = Path(__file__).parent / "fixtures"


def _chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            return Path(p.chromium.executable_path).exists()
    except Exception:  # noqa: BLE001
        return False


needs_chromium = pytest.mark.skipif(not _chromium_available(), reason="Playwright chromium not installed")


@pytest.fixture(scope="module")
def server():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(FIXTURES))
    handler.log_message = lambda *a, **k: None  # type: ignore[assignment]
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


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


def _el(state, tag=None, name=None, input_type=None, placeholder=None):
    return next(e for e in state.interactive_elements
                if (tag is None or e.tag == tag) and (name is None or name in e.name)
                and (input_type is None or e.input_type == input_type)
                and (placeholder is None or placeholder == e.placeholder))


# ---------------------------------------------------------------- pure validation (no browser)

def test_url_syntax_rules() -> None:
    assert validate_url_syntax("https://example.com/a?b=1")
    for bad in ["file:///etc/passwd", "javascript:alert(1)", "data:text/html,hi", "ftp://x.com",
                "http://user:pw@example.com", "http://", "", "x" * 3000]:
        with pytest.raises(ValueError):
            validate_url_syntax(bad)


async def test_ssrf_guard() -> None:
    with pytest.raises(ActionError):  # link-local / cloud metadata: always blocked
        await assert_url_allowed("http://169.254.169.254/latest/meta-data", allow_private=True)
    with pytest.raises(ActionError):
        await assert_url_allowed("http://127.0.0.1:8000", allow_private=False)
    with pytest.raises(ActionError):
        await assert_url_allowed("http://[::1]/", allow_private=False)
    await assert_url_allowed("http://127.0.0.1:8000", allow_private=True)


def test_tool_registry_is_closed_and_schemas_clean() -> None:
    names = set(TOOLS)
    assert {"browser_open", "browser_click", "browser_type", "browser_select", "browser_scroll",
            "browser_press", "browser_back", "browser_forward", "browser_reload", "browser_wait",
            "browser_screenshot", "browser_get_page_state"} <= names
    assert not any(bad in n for n in names for bad in ("eval", "js", "script", "exec", "shell", "python"))
    for spec in tool_schemas():
        blob = str(spec["parameters"])
        assert "anyOf" not in blob and "additionalProperties" not in blob and "'title'" not in blob


# ---------------------------------------------------------------- real browser

@needs_chromium
async def test_full_flow(manager, server) -> None:
    async with manager.session(headless=True) as s:
        r = await s.open_url(f"{server}/form.html")
        assert r.ok and r.details["http_status"] == 200 and r.screenshot_path
        assert Path(r.screenshot_path).exists()

        st = await s.get_page_state()
        assert st.title == "Form Fixture"
        assert any(n.status == 404 for n in st.network_errors)  # missing.png
        assert "Checkout" in st.visible_text and st.accessibility_tree
        pw = _el(st, input_type="password")

        name, country, agree = _el(st, placeholder="Your name"), _el(st, tag="select"), _el(st, input_type="checkbox")
        submit, boom = _el(st, name="Submit"), _el(st, name="Boom")

        assert (await s.type(name.id, "Ada")).ok
        assert (await s.type(pw.id, "hunter2secret")).ok
        assert (await s.select_option(country.id, label="India")).details["selected"] == ["in"]
        assert (await s.check(agree.id)).details["checked"] is True
        assert (await s.uncheck(agree.id)).details["checked"] is False
        assert (await s.click(submit.id)).ok
        assert (await s.click(boom.id)).ok

        st2 = await s.get_page_state(screenshot=False)
        assert "Submitted Ada" in st2.visible_text
        assert any("boom happened" in c.text for c in st2.console_errors)
        assert "hunter2secret" not in st2.model_dump_json()  # secrets never leave the page

        sc = await s.scroll("bottom")
        assert sc.ok and sc.details["scrollY"] > 0
        assert (await s.press_key("Tab")).ok
        assert (await s.wait(50)).ok

        st3 = await s.get_page_state(screenshot=False)
        assert (await s.click(_el(st3, name="Next page").id)).url.endswith("second.html")
        assert (await s.go_back()).url.endswith("form.html")
        assert (await s.go_forward()).url.endswith("second.html")
        assert (await s.reload()).ok

    assert s.closed
    # typed text must never appear in the action log
    assert all("Ada" not in str(r.args) for r in s.action_log)
    assert any(r.action == "type" and r.args.get("text_length") == 3 for r in s.action_log)


@needs_chromium
async def test_errors_are_structured(manager, server) -> None:
    async with manager.session() as s:
        await s.open_url(f"{server}/form.html")
        st = await s.get_page_state(screenshot=False)

        bad = await s.click("eabcdef")
        assert not bad.ok and bad.error_code == ErrorCode.ELEMENT_NOT_FOUND and bad.screenshot_path

        assert (await s.click("'; drop table")).error_code == ErrorCode.INVALID_ARGUMENTS
        assert (await s.press_key("Control+Alt+Delete+X")).error_code == ErrorCode.INVALID_ARGUMENTS
        assert (await s.select_option("eabcdef")).error_code == ErrorCode.INVALID_ARGUMENTS  # none given

        s.config.action_timeout_ms = 800
        dis = await s.click(_el(st, name="Disabled").id)
        assert not dis.ok and dis.error_code in (ErrorCode.ELEMENT_NOT_ACTIONABLE, ErrorCode.TIMEOUT)

        blocked = await s.open_url("http://169.254.169.254/latest")
        assert blocked.error_code == ErrorCode.NAVIGATION_BLOCKED
        assert (await s.open_url("file:///etc/passwd")).error_code == ErrorCode.INVALID_ARGUMENTS


@needs_chromium
async def test_toolbox_validation_and_dispatch(manager, server) -> None:
    async with manager.session() as s:
        tb = BrowserToolbox(s)
        assert (await tb.execute("browser_evaluate", {"js": "alert(1)"})).error_code == ErrorCode.UNKNOWN_TOOL
        assert (await tb.execute("os.system", {})).error_code == ErrorCode.UNKNOWN_TOOL
        assert (await tb.execute("browser_open", {"url": "javascript:alert(1)"})).error_code == ErrorCode.INVALID_ARGUMENTS
        assert (await tb.execute("browser_open", {"url": f"{server}/form.html", "extra": 1})).error_code == ErrorCode.INVALID_ARGUMENTS
        assert (await tb.execute("browser_click", "el-1")).error_code == ErrorCode.INVALID_ARGUMENTS

        assert (await tb.execute("browser_open", {"url": f"{server}/form.html"})).ok
        state = await tb.execute("browser_get_page_state")
        assert state.ok and state.result["title"] == "Form Fixture" and state.result["elements"]
        shot = await tb.execute("browser_screenshot", {"full_page": True})
        assert shot.ok and Path(shot.screenshot_path).exists()


@needs_chromium
async def test_popup_becomes_active_page(manager, server) -> None:
    async with manager.session() as s:
        await s.open_url(f"{server}/form.html")
        st = await s.get_page_state(screenshot=False)
        await s.click(_el(st, name="Popup").id)
        await s.wait(300)
        assert s.current_url.endswith("second.html")


@needs_chromium
async def test_trace_written_on_close(manager, server, artifacts) -> None:
    async with manager.session(trace=True) as s:
        await s.open_url(f"{server}/form.html")
    assert s.trace_path and Path(s.trace_path).exists() and Path(s.trace_path).stat().st_size > 0


@needs_chromium
async def test_cleanup_on_error_and_capacity(manager, server, monkeypatch) -> None:
    with pytest.raises(RuntimeError):
        async with manager.session() as s:
            raise RuntimeError("boom")
    assert s.closed and manager.active_sessions == 0

    monkeypatch.setenv("BROWSER_MAX_SESSIONS", "1")
    from app.core.config import get_settings

    get_settings.cache_clear()
    first = await manager.create_session()
    with pytest.raises(BrowserCapacityError):
        await manager.create_session()
    await first.close()
    await first.close()  # idempotent
    assert manager.active_sessions == 0
    get_settings.cache_clear()


@needs_chromium
async def test_action_limit(manager, server) -> None:
    cfg = BrowserSessionConfig.from_settings()
    cfg.max_actions = 2
    async with manager.session(config=cfg) as s:
        await s.wait(10)
        await s.wait(10)
        assert (await s.wait(10)).error_code == ErrorCode.LIMIT_EXCEEDED


@needs_chromium
def test_browser_test_endpoint(server, artifacts, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.api import routes_browser
    from app.main import app

    m = BrowserManager()
    monkeypatch.setattr(routes_browser, "get_browser_manager", lambda: m)
    monkeypatch.setattr("app.main.get_browser_manager", lambda: m)
    with TestClient(app) as client:  # single loop for the whole block; lifespan closes the browser
        r = client.post("/api/browser/test", json={"url": f"{server}/form.html"})
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["title"] == "Form Fixture" and b["element_count"] > 5 and b["screenshot_base64"]
        assert b["observation"]["interactive_elements"] and "ELEMENTS" in b["compact_prompt"]
        assert b["compact_prompt_chars"] == len(b["compact_prompt"])
        assert b["http_status"] == 200 and Path(b["screenshot_path"]).exists()

        assert client.post("/api/browser/test", json={"url": "file:///etc/passwd"}).status_code == 422
        r = client.post("/api/browser/test", json={"url": "http://169.254.169.254/"})
        assert r.status_code == 400 and r.json()["detail"]["error_code"] == "navigation_blocked"
        assert m.active_sessions == 0
