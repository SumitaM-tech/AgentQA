"""BrowserManager: owns the Playwright driver and Chromium process(es), hands
out isolated `BrowserSession`s, enforces a session cap + TTL, and guarantees
cleanup (context manager + `shutdown()` on app exit)."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from app.browser.models import BrowserSessionConfig
from app.browser.session import BrowserSession
from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class BrowserCapacityError(RuntimeError):
    """Too many concurrent browser sessions."""


class BrowserLaunchError(RuntimeError):
    """Chromium could not be launched (not installed, no display for headed mode, ...)."""


class BrowserManager:
    def __init__(self) -> None:
        self._playwright = None
        self._browsers: dict[bool, object] = {}  # headless flag -> Browser
        self._sessions: dict[str, BrowserSession] = {}
        self._lock = asyncio.Lock()

    @property
    def active_sessions(self) -> int:
        return len(self._sessions)

    async def _get_browser(self, headless: bool):
        if self._playwright is None:
            from playwright.async_api import async_playwright

            self._playwright = await async_playwright().start()
        browser = self._browsers.get(headless)
        if browser is not None and browser.is_connected():
            return browser
        try:
            browser = await self._playwright.chromium.launch(headless=headless)
        except Exception as exc:  # noqa: BLE001
            hint = ""
            if not headless:
                hint = " (headed mode needs a display; it is not available inside Docker)"
            elif "Executable doesn't exist" in str(exc):
                hint = " (run: playwright install chromium)"
            raise BrowserLaunchError(f"Could not launch Chromium{hint}: {(str(exc).splitlines() or [''])[0][:200]}") from exc
        self._browsers[headless] = browser
        logger.info("browser_launched", headless=headless)
        return browser

    async def _reap_expired(self) -> None:
        for session in [s for s in self._sessions.values() if s.expired]:
            logger.warning("browser_session_expired", session_id=session.session_id)
            await session.close()

    async def create_session(
        self, *, headless: bool | None = None, trace: bool | None = None, config: BrowserSessionConfig | None = None
    ) -> BrowserSession:
        cfg = config or BrowserSessionConfig.from_settings(headless=headless, trace=trace)
        async with self._lock:
            await self._reap_expired()
            if len(self._sessions) >= get_settings().browser_max_sessions:
                raise BrowserCapacityError("Maximum concurrent browser sessions reached; try again shortly.")
            browser = await self._get_browser(cfg.headless)
            session = await BrowserSession.create(browser, cfg, on_close=self._unregister)
            self._sessions[session.session_id] = session
            return session

    def _unregister(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    @asynccontextmanager
    async def session(
        self, *, headless: bool | None = None, trace: bool | None = None, config: BrowserSessionConfig | None = None
    ) -> AsyncIterator[BrowserSession]:
        """Always closes the session, even on error/cancellation."""
        session = await self.create_session(headless=headless, trace=trace, config=config)
        try:
            yield session
        finally:
            await asyncio.shield(session.close())

    async def close_session(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if session:
            await session.close()

    async def shutdown(self) -> None:
        for session in list(self._sessions.values()):
            await session.close()
        for browser in list(self._browsers.values()):
            try:
                await browser.close()
            except Exception:  # noqa: BLE001
                pass
        self._browsers.clear()
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:  # noqa: BLE001
                pass
            self._playwright = None
        logger.info("browser_manager_shutdown")


_manager: BrowserManager | None = None


def get_browser_manager() -> BrowserManager:
    global _manager
    if _manager is None:
        _manager = BrowserManager()
    return _manager
