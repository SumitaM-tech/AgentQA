"""Turns raw Playwright page state into a structured `Observation`.

This is where all the "sensing" logic lives: screenshot capture, DOM /
accessibility-tree walking, interactive-element extraction, console and
network log draining, and state fingerprinting. Kept separate from
`browser/` so it can be unit-tested against saved HTML fixtures without a
live browser, and so `browser/playwright_driver.py` stays a thin adapter.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import UUID

from app.agent.legacy_state import ConsoleMessage, InteractiveElement, NetworkEvent, Observation
from app.core.config import get_settings

# Injected into the page once per navigation. Tags every interactive
# element with a stable `data-agentqa-id` (if it doesn't already have
# one) and returns a JSON-serializable list of element metadata. Kept as
# a single evaluate() call rather than N round trips for speed.
_EXTRACT_ELEMENTS_JS = """
() => {
  const SELECTOR = 'a, button, input, select, textarea, [role], [onclick], [contenteditable="true"]';
  if (!window.__agentqaCounter) window.__agentqaCounter = 0;

  const isVisible = (el) => {
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    return (
      rect.width > 0 &&
      rect.height > 0 &&
      style.visibility !== 'hidden' &&
      style.display !== 'none' &&
      style.opacity !== '0'
    );
  };

  const accessibleName = (el) => {
    return (
      el.getAttribute('aria-label') ||
      el.getAttribute('placeholder') ||
      el.getAttribute('alt') ||
      el.getAttribute('title') ||
      (el.innerText ? el.innerText.trim().slice(0, 120) : '') ||
      el.value ||
      ''
    );
  };

  const elements = [];
  document.querySelectorAll(SELECTOR).forEach((el) => {
    if (!el.hasAttribute('data-agentqa-id')) {
      el.setAttribute('data-agentqa-id', 'el-' + (window.__agentqaCounter++));
    }
    const rect = el.getBoundingClientRect();
    elements.push({
      element_id: el.getAttribute('data-agentqa-id'),
      role: el.getAttribute('role') || el.tagName.toLowerCase(),
      accessible_name: accessibleName(el),
      tag: el.tagName.toLowerCase(),
      is_visible: isVisible(el),
      is_enabled: !el.disabled,
      bounding_box: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
      attributes: {
        type: el.getAttribute('type') || '',
        name: el.getAttribute('name') || '',
        href: el.getAttribute('href') || '',
      },
    });
  });
  return elements;
}
"""


def compute_state_fingerprint(url: str, title: str, dom_structure_signature: str) -> str:
    """Hash used to de-duplicate UI states in the exploration graph.

    Deliberately based on structural signals (URL path, title, a
    normalized signature of interactive elements) rather than full DOM
    text, so that e.g. a timestamp changing on screen doesn't create a
    spurious new state node.
    """
    payload = f"{url}|{title}|{dom_structure_signature}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _structure_signature(elements: list[InteractiveElement]) -> str:
    """Order-independent signature: role+tag+name for every *visible*
    element, sorted. Invisible elements (e.g. off-screen menu items in a
    closed dropdown) are excluded so opening/closing UI chrome that
    doesn't add visible affordances doesn't fork the state graph."""
    parts = sorted(
        f"{el.role}:{el.tag}:{el.accessible_name}" for el in elements if el.is_visible
    )
    return "|".join(parts)


def extract_interactive_elements(raw_elements: list[dict]) -> list[InteractiveElement]:
    return [InteractiveElement(**el) for el in raw_elements]


def drain_console_messages(buffer: list[dict]) -> list[ConsoleMessage]:
    messages = [ConsoleMessage(level=m["level"], text=m["text"]) for m in buffer]
    buffer.clear()
    return messages


def drain_network_events(buffer: list[dict]) -> list[NetworkEvent]:
    events = [
        NetworkEvent(
            url=e["url"],
            method=e["method"],
            status=e.get("status"),
            ok=e.get("ok", False),
            resource_type=e.get("resource_type", "other"),
            duration_ms=e.get("duration_ms"),
        )
        for e in buffer
    ]
    buffer.clear()
    return events


async def build_observation(
    page,  # noqa: ANN001 - playwright.async_api.Page
    run_id: UUID,
    step_index: int,
    console_buffer: list[dict],
    network_buffer: list[dict],
) -> Observation:
    """Build a full Observation from a live Playwright `Page`.

    Artifacts (screenshot, DOM snapshot) are written under
    `settings.screenshot_dir` / `settings.dom_snapshot_dir`, namespaced by
    run_id/step so concurrent runs never collide.
    """
    settings = get_settings()

    screenshot_dir = Path(settings.screenshot_dir) / str(run_id)
    dom_dir = Path(settings.dom_snapshot_dir) / str(run_id)
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    dom_dir.mkdir(parents=True, exist_ok=True)

    screenshot_path = screenshot_dir / f"step_{step_index:04d}.png"
    await page.screenshot(path=str(screenshot_path), full_page=False)

    raw_elements = await page.evaluate(_EXTRACT_ELEMENTS_JS)
    interactive_elements = extract_interactive_elements(raw_elements)

    dom_snapshot_path = dom_dir / f"step_{step_index:04d}.json"
    dom_snapshot_path.write_text(
        json.dumps({"url": page.url, "title": await page.title(), "elements": raw_elements}, indent=2)
    )

    console_messages = drain_console_messages(console_buffer)
    network_events = drain_network_events(network_buffer)

    url = page.url
    title = await page.title()
    fingerprint = compute_state_fingerprint(url, title, _structure_signature(interactive_elements))

    return Observation(
        url=url,
        title=title,
        screenshot_path=str(screenshot_path),
        dom_snapshot_path=str(dom_snapshot_path),
        interactive_elements=interactive_elements,
        console_messages=console_messages,
        network_events=network_events,
        http_status=None,
        state_fingerprint=fingerprint,
    )
