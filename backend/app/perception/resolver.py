"""Turns a stable element id back into a live Playwright Locator.

Resolution order (each candidate is *verified* against the element's semantic
fingerprint, so a re-used DOM node that now shows different content is never
acted on):
  1. the `data-agentqa-id` attribute written at observation time (fast path)
  2. the element's selector strategies: testid -> id -> role+name -> label ->
     placeholder -> text -> structural css (last resort)
CSS classes are never the primary handle, so class-name churn in dynamic apps
does not break resolution.
"""
from __future__ import annotations

from collections import OrderedDict
from typing import Iterable

from playwright.async_api import Locator, Page

from app.perception.extractor import ensure_injected
from app.perception.models import PageElement, SelectorStrategy

_TESTID_ATTRS = frozenset({"data-testid", "data-test-id", "data-test", "data-cy", "data-qa"})
_MAX_PROBE = 8


class ElementResolutionError(Exception):
    """The id is unknown, gone, or no longer matches the same element."""


class ElementRegistry:
    """Remembers recently observed elements (id -> PageElement), bounded."""

    def __init__(self, capacity: int = 1500) -> None:
        self._items: OrderedDict[str, PageElement] = OrderedDict()
        self._capacity = capacity

    def update(self, elements: Iterable[PageElement]) -> None:
        for e in elements:
            self._items[e.id] = e
            self._items.move_to_end(e.id)
        while len(self._items) > self._capacity:
            self._items.popitem(last=False)

    def get(self, element_id: str) -> PageElement | None:
        return self._items.get(element_id)

    def clear(self) -> None:
        self._items.clear()

    def __len__(self) -> int:
        return len(self._items)


def _attr_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").replace("\r", " ")


def locator_for(page: Page, s: SelectorStrategy) -> Locator | None:
    """Build a locator from a strategy. Values are data, never evaluated as code."""
    try:
        exact = len(s.value) < 80  # values are truncated at 80 -> substring match then
        if s.kind == "testid":
            attr, _, val = s.value.partition("=")
            return page.locator(f'[{attr}="{_attr_escape(val)}"]') if attr in _TESTID_ATTRS else None
        if s.kind == "id":
            return page.locator(f'[id="{_attr_escape(s.value)}"]')
        if s.kind == "role" and s.role:
            return page.get_by_role(s.role, name=s.value, exact=exact)  # type: ignore[arg-type]
        if s.kind == "label":
            return page.get_by_label(s.value, exact=exact)
        if s.kind == "placeholder":
            return page.get_by_placeholder(s.value, exact=exact)
        if s.kind == "text":
            return page.get_by_text(s.value, exact=exact)
        if s.kind == "css":
            return page.locator(s.value)
    except Exception:  # noqa: BLE001 - malformed strategy => skip it
        return None
    return None


class ElementResolver:
    def __init__(self, registry: ElementRegistry) -> None:
        self.registry = registry

    async def _verify(self, loc: Locator, rec: PageElement) -> bool:
        try:
            fp = await loc.evaluate("(el) => window.__agentqa.fingerprint(el)", timeout=2000)
            if fp != rec.fingerprint:
                return False
            if rec.context:  # duplicate-disambiguating row context must match too
                return await loc.evaluate("(el) => window.__agentqa.context(el)", timeout=2000) == rec.context
            return True
        except Exception:  # noqa: BLE001
            return False

    async def locate(self, page: Page, element_id: str) -> Locator:
        rec = self.registry.get(element_id)
        if rec is None:
            raise ElementResolutionError(
                f"Unknown element id '{element_id}'. Observe the page (browser_get_page_state) to get current ids."
            )
        await ensure_injected(page)

        fast = page.locator(f'[data-agentqa-id="{_attr_escape(element_id)}"]')
        if await fast.count() == 1 and await self._verify(fast.first, rec):
            return fast.first

        for strat in [rec.selector_strategy, *rec.fallback_strategies]:
            cand = locator_for(page, strat)
            if cand is None:
                continue
            try:
                n = await cand.count()
            except Exception:  # noqa: BLE001
                continue
            if n == 0:
                continue
            order = ([strat.nth] if strat.nth is not None and strat.nth < n else []) + [
                i for i in range(min(n, _MAX_PROBE)) if i != strat.nth
            ]
            for i in order:
                item = cand.nth(i)
                if await self._verify(item, rec):
                    return item

        raise ElementResolutionError(
            f"Element '{element_id}' ({rec.role} \"{rec.name[:40]}\") is no longer on the page or has changed. "
            "Call browser_get_page_state to refresh element ids."
        )
