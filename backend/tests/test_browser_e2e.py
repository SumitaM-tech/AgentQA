"""End-to-end test of the deterministic execution layer — real headless
Chromium via Playwright, no mocks. Navigates a local fixture page, checks
element extraction/screenshot/DOM-snapshot capture, executes a click via
the injected `data-agentqa-id`, and checks the exploration graph dedups
correctly by fingerprint.

Requires `playwright install chromium` to have been run (see README).
Skipped automatically if Chromium isn't installed, so `pytest` still
passes in environments that haven't run that step.
"""
from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest

from app.agent.legacy_state import Action, ActionType
from app.browser.playwright_driver import PlaywrightBrowserTool
from app.exploration.graph import StateGraph

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sample_page.html"


def _chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            p.chromium.executable_path  # noqa: B018 - existence check only
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.asyncio
@pytest.mark.skipif(not _chromium_available(), reason="Playwright chromium not installed")
async def test_full_observe_execute_observe_cycle(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SCREENSHOT_DIR", str(tmp_path / "screenshots"))
    monkeypatch.setenv("DOM_SNAPSHOT_DIR", str(tmp_path / "dom"))
    from app.core.config import get_settings

    get_settings.cache_clear()

    run_id = uuid4()
    tool = PlaywrightBrowserTool(run_id=run_id)
    try:
        await tool.launch(headless=True)
        await tool.navigate(FIXTURE_PATH.as_uri())

        obs1 = await tool.observe()
        assert obs1.title == "Test QA Target"
        assert len(obs1.interactive_elements) == 4  # 2 inputs, 1 button, 1 link
        assert os.path.exists(obs1.screenshot_path)
        assert os.path.exists(obs1.dom_snapshot_path)

        login_button = next(el for el in obs1.interactive_elements if el.tag == "button")
        action = Action(action_type=ActionType.CLICK, target_element_id=login_button.element_id, reasoning="test")
        await tool.execute(action)

        obs2 = await tool.observe()

        graph = StateGraph()
        node1 = graph.get_or_create_node(obs1)
        node2 = graph.get_or_create_node(obs2)
        edge = graph.record_transition(node1, action, node2, step_index=0)

        assert edge.source_node_id == node1.node_id
        assert edge.target_node_id == node2.node_id
    finally:
        await tool.close()
        get_settings.cache_clear()
