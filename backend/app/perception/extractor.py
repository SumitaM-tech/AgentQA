"""Builds a `PageObservation` from a live Playwright page.

Signals: screenshot, accessibility tree, DOM metadata, interactive elements,
URL, title, visible text, console errors, network failures, browser exceptions.
Everything page-derived is sanitized and size-bounded here.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

from playwright.async_api import Page

from app.core.logging import get_logger
from app.perception.models import (
    BoundingBox,
    BrowserException,
    ConsoleError,
    DomMetadata,
    FormInfo,
    Heading,
    NetworkError,
    ObservationLimits,
    PageElement,
    PageLoadState,
    PageObservation,
    SelectorStrategy,
    TruncationReport,
    Viewport,
)
from app.perception.sanitize import clean_block, clean_inline, sanitize_aria_snapshot
from app.perception.scripts import AGENTQA_JS, VISIBLE_TEXT_JS

logger = get_logger(__name__)

_READY_TO_LOAD_STATE: dict[str, PageLoadState] = {
    "loading": "loading", "interactive": "domcontentloaded", "complete": "load",
}


class TelemetrySource(Protocol):
    """What the extractor needs from a telemetry collector (browser/telemetry.py)."""

    def drain_console_errors(self) -> list[ConsoleError]: ...
    def drain_network_errors(self) -> list[NetworkError]: ...
    def drain_exceptions(self) -> list[BrowserException]: ...
    def drain_dialogs(self) -> list[str]: ...


async def ensure_injected(page: Page) -> None:
    """Idempotently install window.__agentqa (lost on every navigation)."""
    await page.evaluate(AGENTQA_JS)


def _strategy(raw: dict[str, Any]) -> SelectorStrategy:
    return SelectorStrategy(
        kind=raw["kind"], value=raw["value"][:200], role=raw.get("role"),
        nth=raw.get("nth"), fragile=bool(raw.get("fragile", False)),
    )


def _element(raw: dict[str, Any], lim: ObservationLimits) -> PageElement:
    def inline(v: str | None, n: int) -> str | None:
        return clean_inline(v, n, redact=lim.redact_secrets) if v else None

    b = raw["box"]
    return PageElement(
        id=raw["id"], role=raw["role"], tag=raw["tag"],
        name=clean_inline(raw["name"], lim.max_name_chars, redact=lim.redact_secrets),
        text=clean_inline(raw["text"], lim.max_name_chars, redact=lim.redact_secrets),
        aria_label=inline(raw.get("ariaLabel"), lim.max_name_chars),
        placeholder=inline(raw.get("placeholder"), lim.max_name_chars),
        value=(clean_inline(raw["value"], lim.max_value_chars, redact=lim.redact_secrets)
               if raw.get("value") is not None else None),
        input_type=raw.get("type"),
        href=inline(raw.get("href"), 200),
        visible=True, in_viewport=bool(raw["inViewport"]), enabled=bool(raw["enabled"]),
        checked=raw.get("checked"), required=bool(raw.get("required")),
        readonly=bool(raw.get("readonly")), focused=bool(raw.get("focused")),
        bounding_box=BoundingBox(x=b["x"], y=b["y"], width=b["width"], height=b["height"]),
        selector_strategy=_strategy(raw["strategy"]),
        fallback_strategies=[_strategy(f) for f in raw.get("fallbacks", [])],
        fingerprint=raw["fp"], landmark=inline(raw.get("landmark"), 80), context=raw.get("context"),
    )


def _prioritize(elements: list[PageElement], cap: int) -> tuple[list[PageElement], int]:
    """Keep DOM order but, when over the cap, drop the least useful first:
    off-screen and disabled elements before on-screen enabled ones."""
    if len(elements) <= cap:
        return elements, 0
    scored = sorted(
        range(len(elements)),
        key=lambda i: (-(2 * elements[i].in_viewport + elements[i].enabled), i),
    )
    keep = sorted(scored[:cap])
    return [elements[i] for i in keep], len(elements) - cap


def _state_fingerprint(url: str, title: str, elements: list[PageElement]) -> str:
    """Structure-based (URL path + title + sorted element fingerprints); ignores
    text values, scroll position and volatile digits."""
    path = urlsplit(url)
    key = "|".join([f"{path.scheme}://{path.netloc}{path.path}", title, *sorted(e.fingerprint for e in elements)])
    return hashlib.sha256(key.encode()).hexdigest()[:32]


def _rank_network(errors: list[NetworkError]) -> list[NetworkError]:
    def rank(e: NetworkError) -> tuple[int, int]:
        if e.kind == "request_failed":
            return (0, 0)
        if e.status and e.status >= 500:
            return (1, 0)
        return (2 if e.resource_type in ("document", "xhr", "fetch") else 3, 0)

    return sorted(errors, key=rank)


async def _load_state(page: Page, ready_state: str, probe_ms: int) -> PageLoadState:
    state = _READY_TO_LOAD_STATE.get(ready_state, "load")
    if state == "load" and probe_ms > 0:
        try:
            await page.wait_for_load_state("networkidle", timeout=probe_ms)
            return "networkidle"
        except Exception:  # noqa: BLE001 - still busy
            return "load"
    return state


async def observe_page(
    page: Page,
    telemetry: TelemetrySource | None = None,
    *,
    screenshot_path: Path | None = None,
    full_page_screenshot: bool = False,
    limits: ObservationLimits | None = None,
) -> PageObservation:
    lim = limits or ObservationLimits()
    warnings: list[str] = []
    trunc = TruncationReport()

    await ensure_injected(page)
    raw = await page.evaluate(
        "(o) => window.__agentqa.snapshot(o)",
        {"maxElements": lim.max_elements * 3, "maxValue": lim.max_value_chars,
         "maxName": lim.max_name_chars, "tag": lim.tag_dom},
    )

    elements, omitted = _prioritize([_element(e, lim) for e in raw["elements"]], lim.max_elements)
    trunc.elements_omitted = omitted + max(0, raw["total"] - raw["hidden"] - len(raw["elements"]))

    text_raw = await page.evaluate(VISIBLE_TEXT_JS, lim.max_visible_text_chars * 3)
    visible_text, trunc.visible_text_omitted_chars = clean_block(
        text_raw, lim.max_visible_text_chars, redact=lim.redact_secrets
    )

    a11y: str | None = None
    if lim.include_accessibility:
        try:
            snap = await page.locator("body").aria_snapshot(timeout=5000)
            a11y, trunc.accessibility_tree_omitted_chars = sanitize_aria_snapshot(snap, lim.max_accessibility_chars)
        except Exception as exc:  # noqa: BLE001 - best effort signal
            warnings.append(f"accessibility tree unavailable: {type(exc).__name__}")

    dom_raw = raw["dom"]
    dom = DomMetadata(
        lang=dom_raw.get("lang"),
        meta_description=clean_inline(dom_raw.get("meta_description"), 200) or None,
        headings=[Heading(level=h["level"], text=clean_inline(h["text"], 100, redact=lim.redact_secrets))
                  for h in dom_raw["headings"][: lim.max_headings]],
        landmarks=dom_raw["landmarks"],
        forms=[FormInfo(**f) for f in dom_raw["forms"]],
        form_count=dom_raw["form_count"], link_count=dom_raw["link_count"],
        image_count=dom_raw["image_count"], images_missing_alt=dom_raw["images_missing_alt"],
        iframe_count=dom_raw["iframe_count"], dom_node_count=dom_raw["dom_node_count"],
        interactive_total=raw["total"], interactive_hidden=raw["hidden"], open_dialog=dom_raw["open_dialog"],
    )

    console: list[ConsoleError] = []
    network: list[NetworkError] = []
    exceptions: list[BrowserException] = []
    dialogs: list[str] = []
    if telemetry is not None:
        def msg(s: str) -> str:
            return clean_inline(s, lim.max_message_chars, redact=lim.redact_secrets)

        console = [c.model_copy(update={"text": msg(c.text)}) for c in telemetry.drain_console_errors()]
        network = _rank_network(telemetry.drain_network_errors())
        exceptions = [e.model_copy(update={"message": msg(e.message),
                                           "stack": clean_block(e.stack, 600, redact=lim.redact_secrets)[0] or None})
                      for e in telemetry.drain_exceptions()]
        dialogs = [msg(d) for d in telemetry.drain_dialogs()]
        trunc.console_errors_omitted = max(0, len(console) - lim.max_console_errors)
        trunc.network_errors_omitted = max(0, len(network) - lim.max_network_errors)
        console, network = console[: lim.max_console_errors], network[: lim.max_network_errors]
        exceptions = exceptions[: lim.max_exceptions]

    shot: str | None = None
    if screenshot_path is not None:
        try:
            screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(screenshot_path), full_page=full_page_screenshot,
                                  timeout=15000, animations="disabled", caret="hide")
            shot = str(screenshot_path)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"screenshot failed: {type(exc).__name__}")

    url = page.url
    title = clean_inline(await page.title(), 200, redact=lim.redact_secrets)
    return PageObservation(
        url=url, title=title, screenshot_path=shot, accessibility_tree=a11y,
        visible_text=visible_text, interactive_elements=elements,
        console_errors=console, network_errors=network, browser_exceptions=exceptions, dialogs=dialogs,
        viewport=Viewport(**raw["viewport"]),
        page_load_state=await _load_state(page, raw["ready_state"], lim.network_idle_probe_ms),
        dom_metadata=dom, state_fingerprint=_state_fingerprint(url, title, elements),
        truncation=trunc, warnings=warnings,
    )
