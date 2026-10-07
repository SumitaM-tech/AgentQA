"""Abstract interface the orchestrator programs against.

The orchestrator never imports Playwright directly — it depends only on
this interface. Keeps Playwright fully isolated to `browser/` and makes the
agent loop testable with a fake/mock implementation.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from app.agent.legacy_state import Action, Observation


class BrowserTool(ABC):
    """One instance = one browser session/tab for a single AgentQA run."""

    @abstractmethod
    async def launch(self, headless: bool = True) -> None:
        """Start the browser and open a new page."""
        raise NotImplementedError

    @abstractmethod
    async def navigate(self, url: str) -> None:
        """Navigate the current page to `url`."""
        raise NotImplementedError

    @abstractmethod
    async def execute(self, action: Action) -> None:
        """Execute a single Action (click/fill/select/etc.) against the
        element referenced by `action.target_element_id`."""
        raise NotImplementedError

    @abstractmethod
    async def observe(self) -> Observation:
        """Capture the current page as a full Observation: screenshot,
        DOM/accessibility metadata, URL, title, console + network log
        since the last observation, and computed state fingerprint."""
        raise NotImplementedError

    @abstractmethod
    async def set_credentials(self, username: Optional[str], password: Optional[str]) -> None:
        """Store optional test credentials for the agent to use when it
        encounters a login form (never sent to Gemini directly)."""
        raise NotImplementedError

    @abstractmethod
    async def close(self) -> None:
        """Tear down the browser/page and release resources."""
        raise NotImplementedError
