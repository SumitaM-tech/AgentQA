"""Test doubles for the reasoning engine: synthetic observations, a fake website,
a scripted decision model and a fake executor. No browser, no network, no LLM."""
from __future__ import annotations

import hashlib
from collections import deque
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from app.agent.state import ActionType, AgentAction, ExecutionResult
from app.perception.models import (
    BoundingBox, BrowserException, ConsoleError, NetworkError, PageElement, PageObservation, SelectorStrategy, Viewport,
)

BASE = "http://app.test"


def eid(n: int) -> str:
    """A valid element id, e.g. eid(1) -> 'e000001'."""
    return f"e{n:06x}"


def make_element(
    n: int, role: str = "button", name: str = "", *, tag: str | None = None, href: str | None = None,
    enabled: bool = True, input_type: str | None = None, readonly: bool = False, in_viewport: bool = True,
) -> PageElement:
    tag = tag or {"link": "a", "textbox": "input", "combobox": "select", "checkbox": "input"}.get(role, "button")
    return PageElement(
        id=eid(n), role=role, tag=tag, name=name, text=name, href=href, enabled=enabled, input_type=input_type,
        readonly=readonly, in_viewport=in_viewport, bounding_box=BoundingBox(x=0, y=0, width=80, height=20),
        selector_strategy=SelectorStrategy(kind="css", value="body", fragile=True), fingerprint=f"fp{n}",
    )


def make_obs(
    url: str = f"{BASE}/", title: str = "Home", elements: list[PageElement] | None = None, *, text: str = "",
    console: list[str] | None = None, exceptions: list[str] | None = None,
    network: list[tuple[int, str, str]] | None = None, fingerprint: str | None = None, tree: str | None = None,
) -> PageObservation:
    elements = elements or []
    fp = fingerprint or hashlib.sha1((url + "|" + ",".join(e.id for e in elements)).encode()).hexdigest()[:32]
    return PageObservation(
        url=url, title=title, visible_text=text, accessibility_tree=tree, interactive_elements=elements,
        console_errors=[ConsoleError(text=c) for c in (console or [])],
        browser_exceptions=[BrowserException(message=m) for m in (exceptions or [])],
        network_errors=[NetworkError(url=u, method="GET", status=s, resource_type=rt) for s, u, rt in (network or [])],
        viewport=Viewport(width=1440, height=900), page_load_state="load", state_fingerprint=fp,
    )


class ScriptedModel:
    """DecisionModel returning queued responses per schema. Items may be AgentAction / CriticAssessment
    instances, dicts, or Exceptions (raised). `factory` supplies unlimited responses when the queue is empty."""

    def __init__(self, planner: list[Any] | None = None, critic: list[Any] | None = None, factory=None) -> None:
        self.planner: deque[Any] = deque(planner or [])
        self.critic: deque[Any] = deque(critic or [])
        self.factory = factory
        self.prompts: list[str] = []
        self.critic_prompts: list[str] = []

    async def generate(self, prompt: str, *, system_instruction: str, schema, image_bytes=None):  # noqa: ANN001
        is_planner = schema is AgentAction
        (self.prompts if is_planner else self.critic_prompts).append(prompt)
        queue = self.planner if is_planner else self.critic
        if queue:
            item = queue.popleft()
        elif self.factory is not None:
            item = self.factory(prompt, schema)
        else:
            raise RuntimeError("no scripted response left")
        if isinstance(item, BaseException):
            raise item
        return item


@dataclass
class Page:
    title: str
    elements: list[PageElement]
    text: str = ""
    goto: dict[str, str] = field(default_factory=dict)  # element id -> absolute url


class FakeSite:
    """Tiny website + executor. State changes only via `goto` links and OPEN/BACK."""

    def __init__(self, pages: dict[str, Page], start: str = "/") -> None:
        self.pages = pages
        self.url = f"{BASE}{start}"
        self.history: list[str] = []
        self.executed: list[AgentAction] = []
        self.fail_with: str | None = None            # make every execute() fail with this error code
        self.extra_after: dict[str, dict] = {}       # url -> extra telemetry for observe(): console/exceptions/network
        self.text_after_click: str | None = None

    def _page(self) -> Page:
        path = urlsplit(self.url).path or "/"
        host = urlsplit(self.url).hostname
        if host != "app.test":
            return Page("External", [], "external site")
        return self.pages.get(path, Page("Not found", [], "404"))

    async def execute(self, action: AgentAction) -> ExecutionResult:
        self.executed.append(action)
        if self.fail_with and action.action_type != ActionType.OPEN:  # let the bootstrap OPEN succeed
            return ExecutionResult(ok=False, error="boom", error_code=self.fail_with)
        t = action.action_type
        if t == ActionType.OPEN:
            self.history.append(self.url)
            self.url = action.arguments.url or self.url
        elif t == ActionType.BACK:
            if self.history:
                self.url = self.history.pop()
        elif t == ActionType.CLICK:
            page = self._page()
            dest = page.goto.get(action.target or "")
            if dest:
                self.history.append(self.url)
                self.url = dest
        return ExecutionResult(ok=True, url=self.url)

    async def observe(self) -> PageObservation:
        page = self._page()
        extra = self.extra_after.pop(self.url, {})
        return make_obs(self.url, page.title, list(page.elements), text=page.text, **extra)


def shop_site() -> FakeSite:
    """Home -> Products / About (links) plus a Logout and an external link."""
    home = Page("Home", [
        make_element(1, "link", "Products", href="/products"),
        make_element(2, "link", "About", href="/about"),
        make_element(3, "link", "Log out", href="/logout"),
        make_element(4, "link", "Docs", href="http://evil.test/docs"),
        make_element(5, "textbox", "Search", input_type="search"),
        make_element(6, "button", "Help"),
    ], "Welcome", goto={eid(1): f"{BASE}/products", eid(2): f"{BASE}/about", eid(4): "http://evil.test/docs"})
    products = Page("Products", [
        make_element(10, "link", "Home", href="/"), make_element(11, "button", "Add to cart"),
    ], "Products", goto={eid(10): f"{BASE}/"})
    about = Page("About", [make_element(20, "link", "Home", href="/")], "About us", goto={eid(20): f"{BASE}/"})
    return FakeSite({"/": home, "/products": products, "/about": about})
