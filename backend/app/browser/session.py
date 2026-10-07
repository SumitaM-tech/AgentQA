"""BrowserSession: one isolated Chromium context + active page.

Every public action: validates arguments -> enforces limits -> runs under a
hard timeout -> maps failures to structured `ActionResult`s (never raises for
expected failures) -> captures a screenshot after important actions (and on
failure) -> logs the action. `close()` is idempotent and best-effort per step,
so resources are released even when errors occur.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import urlsplit

from playwright.async_api import Browser, BrowserContext, Page
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeout
from pydantic import BaseModel, ValidationError

from app.browser import actions as A
from app.browser.models import ActionResult, BrowserSessionConfig, ErrorCode
from app.browser.perception import capture_screenshot
from app.browser.telemetry import ActionLogger, TelemetryCollector, redact_url
from app.core.config import get_settings
from app.core.logging import get_logger
from app.perception import (
    ElementRegistry,
    ElementResolutionError,
    ElementResolver,
    ObservationLimits,
    PageObservation,
    observe_page,
)

logger = get_logger(__name__)

_NAV_ACTIONS = frozenset({"open_url", "go_back", "go_forward", "reload"})
_OBSERVATIONAL = frozenset({"get_page_state", "screenshot"})
_NOT_ACTIONABLE_HINTS = ("not visible", "not enabled", "intercepts pointer", "not editable", "not stable", "detached")
_TIMEOUT_SLACK_S = 6.0


class BrowserSessionError(RuntimeError):
    """Raised only for non-recoverable session-level problems."""


class BrowserSession:
    def __init__(
        self,
        session_id: str,
        context: BrowserContext,
        config: BrowserSessionConfig,
        on_close: Callable[[str], None] | None = None,
        limits: ObservationLimits | None = None,
    ) -> None:
        settings = get_settings()
        self.session_id = session_id
        self.config = config
        self.trace_path: str | None = None
        self.screenshot_dir = Path(settings.screenshot_dir) / session_id
        self._trace_dir = Path(settings.trace_dir)
        self._context = context
        self._page: Page | None = None
        self._telemetry = TelemetryCollector()
        self._log = ActionLogger(session_id)
        self._lock = asyncio.Lock()
        self._closed = False
        self._tracing = False
        self._seq = 0
        self._action_count = 0
        self._created = time.monotonic()
        self._host_cache: dict[str, bool] = {}
        self._on_close = on_close
        self.limits = limits or ObservationLimits()
        self._registry = ElementRegistry()
        self._resolver = ElementResolver(self._registry)

    # ------------------------------------------------------------------ lifecycle

    @classmethod
    async def create(
        cls,
        browser: Browser,
        config: BrowserSessionConfig,
        session_id: str | None = None,
        on_close: Callable[[str], None] | None = None,
        limits: ObservationLimits | None = None,
    ) -> "BrowserSession":
        context = await browser.new_context(
            viewport={"width": config.viewport.width, "height": config.viewport.height},
            accept_downloads=False,
            service_workers="block",
            locale="en-US",
        )
        session = cls(session_id or uuid.uuid4().hex, context, config, on_close, limits)
        try:
            context.set_default_timeout(config.action_timeout_ms)
            context.set_default_navigation_timeout(config.navigation_timeout_ms)
            session._telemetry.attach(context)
            await context.route("**/*", session._route_guard)
            if config.trace_enabled:
                await context.tracing.start(screenshots=True, snapshots=True, sources=False)
                session._tracing = True
            page = await context.new_page()
            session._page = page
            page.on("close", lambda: session._on_page_closed(page))
            context.on("page", session._on_new_page)  # popups / target=_blank
        except BaseException:
            await session.close()
            raise
        logger.info("browser_session_started", session_id=session.session_id,
                    headless=config.headless, trace=config.trace_enabled)
        return session

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def expired(self) -> bool:
        return time.monotonic() - self._created > self.config.ttl_seconds

    @property
    def action_log(self) -> list[ActionResult]:
        return list(self._log.records)

    @property
    def current_url(self) -> str | None:
        return self._page.url if self._page and not self._page.is_closed() else None

    async def close(self) -> None:
        """Idempotent; each step is guarded so one failure can't leak the rest."""
        if self._closed:
            return
        self._closed = True
        if self._tracing:
            try:
                self._trace_dir.mkdir(parents=True, exist_ok=True)
                path = self._trace_dir / f"{self.session_id}.zip"
                await self._context.tracing.stop(path=str(path))
                self.trace_path = str(path)
            except Exception as exc:  # noqa: BLE001
                logger.warning("browser_trace_stop_failed", session_id=self.session_id, error=type(exc).__name__)
        try:
            await self._context.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("browser_context_close_failed", session_id=self.session_id, error=type(exc).__name__)
        if self._on_close:
            try:
                self._on_close(self.session_id)
            except Exception:  # noqa: BLE001
                pass
        logger.info("browser_session_closed", session_id=self.session_id,
                    actions=len(self._log.records), trace=self.trace_path)

    async def __aenter__(self) -> "BrowserSession":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    # ------------------------------------------------------------------ page tracking / SSRF guard

    def _on_new_page(self, page: Page) -> None:
        self._page = page
        page.on("close", lambda: self._on_page_closed(page))

    def _on_page_closed(self, page: Page) -> None:
        if page is self._page:
            alive = [p for p in self._context.pages if not p.is_closed()]
            self._page = alive[-1] if alive else None

    async def _route_guard(self, route, request) -> None:  # noqa: ANN001
        """Block http(s) requests (incl. redirects/subresources) to disallowed hosts."""
        url = request.url
        if not url.startswith(("http://", "https://")):
            await route.continue_()
            return
        host = urlsplit(url).hostname or ""
        if (
            self.config.allowed_domains
            and request.is_navigation_request()
            and request.frame.parent_frame is None  # top-level navigations only (CDNs/iframes unaffected)
            and not A.host_allowed(host, self.config.allowed_domains, self.config.allow_subdomains)
        ):
            logger.warning("browser_navigation_blocked_domain", session_id=self.session_id, host=host)
            await route.abort("blockedbyclient")
            return
        allowed = self._host_cache.get(host)
        if allowed is None:
            try:
                await A.assert_url_allowed(url, self.config.allow_private_networks)
                allowed = True
            except A.ActionError as exc:
                allowed = exc.code == "navigation_failed"  # DNS failure: let the browser report it
            self._host_cache[host] = allowed
        if allowed:
            await route.continue_()
        else:
            logger.warning("browser_request_blocked", session_id=self.session_id, host=host)
            await route.abort("blockedbyclient")

    # ------------------------------------------------------------------ core executor

    def _r(self, page: Page):
        """Resolver bound to `page`: element id -> Locator (verified), errors as ActionError."""
        async def resolve(element_id: str):
            try:
                return await self._resolver.locate(page, element_id)
            except ElementResolutionError as exc:
                raise A.ActionError("element_not_found", str(exc)) from exc
        return resolve

    def _require_page(self) -> Page:
        if self._closed:
            raise A.ActionError("session_closed", "Browser session is closed.")
        if self._page is None or self._page.is_closed():
            raise A.ActionError("session_closed", "No open page in this session.")
        return self._page

    @staticmethod
    def _summarize(args: BaseModel) -> dict[str, Any]:
        d = args.model_dump()
        if "text" in d:  # never log typed text (may be credentials)
            d["text_length"] = len(d.pop("text"))
        if "url" in d:
            d["url"] = redact_url(d["url"])
        return {k: v for k, v in d.items() if v is not None}

    def _map_exception(self, exc: BaseException) -> tuple[ErrorCode, str]:
        if isinstance(exc, A.ActionError):
            return ErrorCode(exc.code), exc.message
        if isinstance(exc, asyncio.TimeoutError):
            return ErrorCode.TIMEOUT, "Action exceeded its time limit."
        if isinstance(exc, PlaywrightTimeout):
            full = str(exc)
            if any(h in full for h in _NOT_ACTIONABLE_HINTS):
                return ErrorCode.ELEMENT_NOT_ACTIONABLE, "Element is not visible/enabled/clickable right now."
            return ErrorCode.TIMEOUT, (full.splitlines() or ["Timed out"])[0][:300]
        if isinstance(exc, PlaywrightError):
            msg = (str(exc).splitlines() or ["Playwright error"])[0][:300]
            if "net::ERR_" in msg or "NS_ERROR" in msg:
                return ErrorCode.NAVIGATION_FAILED, msg
            if "has been closed" in msg:
                return ErrorCode.SESSION_CLOSED, "Page or browser was closed."
            if any(h in str(exc) for h in _NOT_ACTIONABLE_HINTS):
                return ErrorCode.ELEMENT_NOT_ACTIONABLE, msg
            return ErrorCode.INTERNAL, msg
        logger.exception("browser_action_unexpected_error", session_id=self.session_id)
        return ErrorCode.INTERNAL, "Unexpected error while executing the action."

    async def _screenshot(self, label: str, full_page: bool = False) -> str | None:
        page = self._page
        if page is None or page.is_closed():
            return None
        self._seq += 1
        try:
            return await capture_screenshot(page, self.screenshot_dir / f"{self._seq:04d}_{label}.png", full_page=full_page)
        except Exception as exc:  # noqa: BLE001
            logger.warning("browser_screenshot_failed", session_id=self.session_id, error=type(exc).__name__)
            return None

    def _fail(self, action: str, code: ErrorCode, message: str, args: dict[str, Any] | None = None) -> ActionResult:
        result = ActionResult(ok=False, action=action, args=args or {}, error=message, error_code=code, url=self.current_url)
        self._log.record(result)
        return result

    async def _act(
        self,
        action: str,
        model: type[BaseModel],
        raw: dict[str, Any],
        runner: Callable[[Page, Any], Awaitable[dict[str, Any]]],
    ) -> ActionResult:
        try:
            args = model(**raw)
        except ValidationError as exc:
            msg = "; ".join(f"{'.'.join(map(str, e['loc'])) or 'args'}: {e['msg']}" for e in exc.errors())[:500]
            return self._fail(action, ErrorCode.INVALID_ARGUMENTS, msg)
        summary = self._summarize(args)

        if self._closed:
            return self._fail(action, ErrorCode.SESSION_CLOSED, "Browser session is closed.", summary)
        if self.expired:
            return self._fail(action, ErrorCode.LIMIT_EXCEEDED, "Session time limit reached.", summary)
        if action not in _OBSERVATIONAL and self._action_count >= self.config.max_actions:
            return self._fail(action, ErrorCode.LIMIT_EXCEEDED, "Maximum actions per session reached.", summary)

        async with self._lock:
            started = time.monotonic()
            ok, error, code, details = True, None, None, {}
            timeout_ms = self.config.navigation_timeout_ms if action in _NAV_ACTIONS else self.config.action_timeout_ms
            try:
                page = self._require_page()
                details = await asyncio.wait_for(runner(page, args), timeout=timeout_ms / 1000 + _TIMEOUT_SLACK_S)
            except Exception as exc:  # noqa: BLE001 - mapped to a structured result
                ok = False
                code, error = self._map_exception(exc)
            if action not in _OBSERVATIONAL:
                self._action_count += 1

            shot = None
            if (ok and action in self.config.screenshot_actions) or (not ok and code != ErrorCode.SESSION_CLOSED):
                shot = await self._screenshot(action if ok else f"{action}_failed")

            page = self._page
            result = ActionResult(
                ok=ok, action=action, args=summary, error=error, error_code=code,
                duration_ms=int((time.monotonic() - started) * 1000),
                url=page.url if page and not page.is_closed() else None,
                title=await self._safe_title(),
                screenshot_path=shot, details=details or {},
            )
            self._log.record(result)
            return result

    async def _safe_title(self) -> str | None:
        try:
            return await asyncio.wait_for(self._page.title(), 2) if self._page and not self._page.is_closed() else None
        except Exception:  # noqa: BLE001
            return None

    # ------------------------------------------------------------------ public actions

    async def open_url(self, url: str) -> ActionResult:
        return await self._act("open_url", A.OpenArgs, {"url": url}, lambda p, a: A.do_open(
            p, a, nav_timeout_ms=self.config.navigation_timeout_ms, allow_private=self.config.allow_private_networks,
            allowed_domains=self.config.allowed_domains, allow_subdomains=self.config.allow_subdomains))

    async def click(self, element_id: str) -> ActionResult:
        return await self._act("click", A.ClickArgs, {"element_id": element_id},
                               lambda p, a: A.do_click(p, a, timeout_ms=self.config.action_timeout_ms, resolve=self._r(p)))

    async def type(self, element_id: str, text: str, clear_first: bool = True, press_enter: bool = False) -> ActionResult:
        return await self._act("type", A.TypeArgs,
                               {"element_id": element_id, "text": text, "clear_first": clear_first, "press_enter": press_enter},
                               lambda p, a: A.do_type(p, a, timeout_ms=self.config.action_timeout_ms, resolve=self._r(p)))

    async def select_option(self, element_id: str, *, value: str | None = None,
                            label: str | None = None, index: int | None = None) -> ActionResult:
        return await self._act("select_option", A.SelectArgs,
                               {"element_id": element_id, "value": value, "label": label, "index": index},
                               lambda p, a: A.do_select(p, a, timeout_ms=self.config.action_timeout_ms, resolve=self._r(p)))

    async def check(self, element_id: str) -> ActionResult:
        return await self._act("check", A.CheckArgs, {"element_id": element_id},
                               lambda p, a: A.do_check(p, a, timeout_ms=self.config.action_timeout_ms, resolve=self._r(p), checked=True))

    async def uncheck(self, element_id: str) -> ActionResult:
        return await self._act("uncheck", A.CheckArgs, {"element_id": element_id},
                               lambda p, a: A.do_check(p, a, timeout_ms=self.config.action_timeout_ms, resolve=self._r(p), checked=False))

    async def scroll(self, direction: str = "down", amount: int = 600, element_id: str | None = None) -> ActionResult:
        return await self._act("scroll", A.ScrollArgs,
                               {"direction": direction, "amount": amount, "element_id": element_id},
                               lambda p, a: A.do_scroll(p, a, timeout_ms=self.config.action_timeout_ms, resolve=self._r(p)))

    async def press_key(self, key: str, element_id: str | None = None) -> ActionResult:
        return await self._act("press_key", A.PressArgs, {"key": key, "element_id": element_id},
                               lambda p, a: A.do_press(p, a, timeout_ms=self.config.action_timeout_ms, resolve=self._r(p)))

    async def go_back(self) -> ActionResult:
        return await self._act("go_back", A.NoArgs, {}, lambda p, a: A.do_history(
            p, direction="back", nav_timeout_ms=self.config.navigation_timeout_ms))

    async def go_forward(self) -> ActionResult:
        return await self._act("go_forward", A.NoArgs, {}, lambda p, a: A.do_history(
            p, direction="forward", nav_timeout_ms=self.config.navigation_timeout_ms))

    async def reload(self) -> ActionResult:
        return await self._act("reload", A.NoArgs, {},
                               lambda p, a: A.do_reload(p, nav_timeout_ms=self.config.navigation_timeout_ms))

    async def wait(self, milliseconds: int = 1000, load_state: str | None = None) -> ActionResult:
        return await self._act("wait", A.WaitArgs, {"milliseconds": milliseconds, "load_state": load_state},
                               lambda p, a: A.do_wait(p, a, timeout_ms=self.config.navigation_timeout_ms))

    async def screenshot(self, full_page: bool = False) -> ActionResult:
        async def run(page: Page, a: A.ScreenshotArgs) -> dict[str, Any]:
            path = await self._screenshot("screenshot", full_page=a.full_page)
            if path is None:
                raise A.ActionError("internal_error", "Screenshot failed.")
            return {"path": path}
        result = await self._act("screenshot", A.ScreenshotArgs, {"full_page": full_page}, run)
        if result.ok:
            result.screenshot_path = result.details.get("path")
        return result

    async def observe(self, *, screenshot: bool = True, full_page: bool = False) -> PageObservation:
        """Perceive the page (screenshot, a11y tree, DOM metadata, elements, text,
        console/network/exception telemetry). Refreshes the element registry.
        Raises BrowserSessionError if the page is unavailable."""
        async with self._lock:
            try:
                page = self._require_page()
            except A.ActionError as exc:
                raise BrowserSessionError(exc.message) from exc
            self._seq += 1
            path = self.screenshot_dir / f"{self._seq:04d}_state.png" if screenshot else None
            try:
                obs = await asyncio.wait_for(
                    observe_page(page, self._telemetry, screenshot_path=path,
                                 full_page_screenshot=full_page, limits=self.limits),
                    timeout=self.config.action_timeout_ms / 1000 + _TIMEOUT_SLACK_S,
                )
            except Exception as exc:  # noqa: BLE001
                code, msg = self._map_exception(exc)
                self._log.record(ActionResult(ok=False, action="get_page_state", error=msg, error_code=code))
                raise BrowserSessionError(msg) from exc
            self._registry.update(obs.interactive_elements)
            self._log.record(ActionResult(
                ok=True, action="get_page_state", url=obs.url, title=obs.title,
                screenshot_path=obs.screenshot_path, details={"elements": len(obs.interactive_elements)}))
            return obs

    async def get_page_state(self, *, screenshot: bool = True, full_page: bool = False) -> PageObservation:
        return await self.observe(screenshot=screenshot, full_page=full_page)
