"""Browser-side perception helpers. The perception pipeline itself lives in
`app.perception`; this module re-exports it and owns raw screenshot capture."""
from __future__ import annotations

from pathlib import Path

from playwright.async_api import Page

from app.perception import observe_page  # noqa: F401  (re-export)


async def capture_screenshot(page: Page, path: Path, *, full_page: bool = False, timeout_ms: int = 15000) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    await page.screenshot(
        path=str(path), full_page=full_page, timeout=timeout_ms, animations="disabled", caret="hide"
    )
    return str(path)
