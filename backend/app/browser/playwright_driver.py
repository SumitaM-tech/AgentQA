"""Concrete `BrowserTool` implementation backed by Playwright + Chromium."""
from __future__ import annotations

import asyncio
from typing import Optional
from uuid import UUID

from app.agent.legacy_state import Action, ActionType, Observation
from app.browser.interface import BrowserTool
from app.core.config import get_settings
from app.core.logging import get_logger
from app.perception.observation import build_observation

logger = get_logger(__name__)

_ELEMENT_SELECTOR = '[data-agentqa-id="{element_id}"]'


class PlaywrightBrowserTool(BrowserTool):
    def __init__(self, run_id: UUID) -> None:
        self._run_id = run_id
        self._settings = get_settings()
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._credentials: tuple[Optional[str], Optional[str]] = (None, None)
        self._console_buffer: list[dict] = []
        self._network_buffer: list[dict] = []
        self._observation_count = 0

    async def launch(self, headless: bool = True) -> None:
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        browser_type = getattr(self._playwright, self._settings.browser_type)
        self._browser = await browser_type.launch(headless=headless)
        self._context = await self._browser.new_context(
            viewport={
                "width": self._settings.browser_viewport_width,
                "height": self._settings.browser_viewport_height,
            }
        )
        self._page = await self._context.new_page()
        self._page.on("console", self._on_console)
        self._page.on("pageerror", self._on_page_error)
        self._page.on("response", self._on_response)
        self._page.on("requestfailed", self._on_request_failed)
        logger.info("browser_launched", run_id=str(self._run_id), headless=headless)

    def _on_console(self, msg) -> None:  # noqa: ANN001 - playwright ConsoleMessage
        self._console_buffer.append({"level": msg.type, "text": msg.text})

    def _on_page_error(self, error) -> None:  # noqa: ANN001
        self._console_buffer.append({"level": "error", "text": str(error)})

    def _on_response(self, response) -> None:  # noqa: ANN001 - playwright Response
        self._network_buffer.append(
            {
                "url": response.url,
                "method": response.request.method,
                "status": response.status,
                "ok": response.ok,
                "resource_type": response.request.resource_type,
                "duration_ms": None,
            }
        )

    def _on_request_failed(self, request) -> None:  # noqa: ANN001 - playwright Request
        self._network_buffer.append(
            {
                "url": request.url,
                "method": request.method,
                "status": None,
                "ok": False,
                "resource_type": request.resource_type,
                "duration_ms": None,
            }
        )

    async def navigate(self, url: str) -> None:
        await self._page.goto(url, timeout=self._settings.navigation_timeout_ms, wait_until="load")
        try:
            await self._page.wait_for_load_state("networkidle", timeout=self._settings.navigation_timeout_ms)
        except Exception:  # noqa: BLE001 - networkidle is best-effort, not required
            pass

    async def execute(self, action: Action) -> None:
        timeout = self._settings.action_timeout_ms
        locator = None
        if action.target_element_id:
            locator = self._page.locator(_ELEMENT_SELECTOR.format(element_id=action.target_element_id))

        if action.action_type == ActionType.CLICK:
            await locator.click(timeout=timeout)
        elif action.action_type == ActionType.FILL:
            await locator.fill(action.value or "", timeout=timeout)
        elif action.action_type == ActionType.SELECT:
            await locator.select_option(action.value, timeout=timeout)
        elif action.action_type == ActionType.HOVER:
            await locator.hover(timeout=timeout)
        elif action.action_type == ActionType.SCROLL:
            if locator is not None:
                await locator.scroll_into_view_if_needed(timeout=timeout)
            else:
                await self._page.mouse.wheel(0, float(action.value) if action.value else 800)
        elif action.action_type == ActionType.NAVIGATE:
            await self.navigate(action.value or self._page.url)
        elif action.action_type == ActionType.PRESS_KEY:
            if locator is not None:
                await locator.press(action.value or "Enter", timeout=timeout)
            else:
                await self._page.keyboard.press(action.value or "Enter")
        elif action.action_type == ActionType.WAIT:
            await asyncio.sleep((float(action.value) if action.value else 1000) / 1000)
        elif action.action_type == ActionType.GO_BACK:
            await self._page.go_back(timeout=self._settings.navigation_timeout_ms)
        elif action.action_type in (ActionType.ASSERT, ActionType.FINISH):
            # Pure verification / termination signals — no browser mutation.
            pass
        else:  # pragma: no cover - defensive
            raise ValueError(f"Unhandled action type: {action.action_type}")

    async def observe(self) -> Observation:
        observation = await build_observation(
            self._page,
            self._run_id,
            self._observation_count,
            self._console_buffer,
            self._network_buffer,
        )
        self._observation_count += 1
        return observation

    async def set_credentials(self, username: Optional[str], password: Optional[str]) -> None:
        self._credentials = (username, password)

    async def close(self) -> None:
        if self._context is not None:
            await self._context.close()
        if self._browser is not None:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()
        logger.info("browser_closed", run_id=str(self._run_id))
