"""Validated action arguments + the only code that touches Playwright to act.

Security model: the model never supplies code. It supplies typed, validated
arguments (element ids like `el-12`, bounded strings/ints, allow-listed keys,
http(s) URLs). Any JavaScript executed here is a fixed constant in this file
that receives validated primitives as parameters.
"""
from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from typing import Any, Awaitable, Callable, Iterable, Literal
from urllib.parse import urlsplit

from playwright.async_api import Locator, Page
from playwright.async_api import TimeoutError as PlaywrightTimeout
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ELEMENT_ID_RE = re.compile(r"^e[0-9a-f]{6}(\.[0-9a-z]{1,4})?$")
MAX_URL_LENGTH = 2048
MAX_TYPE_LENGTH = 5000
MAX_WAIT_MS = 30_000

_NAMED_KEYS = frozenset(
    {"Enter", "Tab", "Escape", "Backspace", "Delete", "Space", "ArrowUp", "ArrowDown",
     "ArrowLeft", "ArrowRight", "Home", "End", "PageUp", "PageDown"}
)
_MODIFIERS = frozenset({"Control", "Shift", "Alt", "Meta"})


class ActionError(Exception):
    """Expected, model-recoverable failure with a stable error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# URL safety
# ---------------------------------------------------------------------------

def validate_url_syntax(url: str) -> str:
    """http/https only, no embedded credentials, bounded length."""
    if not isinstance(url, str) or not url.strip():
        raise ValueError("url must be a non-empty string")
    url = url.strip()
    if len(url) > MAX_URL_LENGTH:
        raise ValueError(f"url exceeds {MAX_URL_LENGTH} characters")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise ValueError("only http and https URLs are allowed")
    if not parts.hostname:
        raise ValueError("url has no host")
    if parts.username or parts.password:
        raise ValueError("credentials in URLs are not allowed")
    return url


def _ip_blocked(ip: ipaddress._BaseAddress, allow_private: bool) -> bool:
    # Always blocked: link-local (cloud metadata 169.254.169.254), multicast, unspecified.
    if ip.is_link_local or ip.is_multicast or ip.is_unspecified:
        return True
    if not allow_private and (ip.is_private or ip.is_loopback or ip.is_reserved):
        return True
    return False


def host_allowed(host: str, allowed_domains: "Iterable[str] | None", allow_subdomains: bool = True) -> bool:
    """True if `host` is in the allow-list (None/empty list => no domain restriction)."""
    if not allowed_domains:
        return True
    host = host.lower().rstrip(".")
    for d in allowed_domains:
        d = d.lower().lstrip(".").rstrip(".")
        if host == d or (allow_subdomains and host.endswith("." + d)):
            return True
    return False


async def assert_url_allowed(
    url: str, allow_private: bool, allowed_domains: "Iterable[str] | None" = None, allow_subdomains: bool = True
) -> None:
    """Syntax check + resolve the host and reject blocked addresses (SSRF guard).
    Note: cannot fully prevent DNS rebinding between check and connect."""
    try:
        validate_url_syntax(url)
    except ValueError as exc:
        raise ActionError("navigation_blocked", str(exc)) from exc
    host = urlsplit(url).hostname or ""
    if not host_allowed(host, allowed_domains, allow_subdomains):
        raise ActionError("navigation_blocked", f"Domain '{host}' is outside the allowed domains")
    try:
        addrs = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise ActionError("navigation_failed", f"Could not resolve host '{host}'") from exc
        addrs = [ipaddress.ip_address(i[4][0].split("%")[0]) for i in infos]
    for ip in addrs:
        if _ip_blocked(ip, allow_private):
            raise ActionError("navigation_blocked", f"Navigation to {ip} is not allowed")


# ---------------------------------------------------------------------------
# Argument models (extra fields forbidden; these ARE the tool schemas)
# ---------------------------------------------------------------------------

class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class _ElementArgs(_Args):
    element_id: str = Field(description="Element id from browser_get_page_state, e.g. 'e3fa91c'.")

    @field_validator("element_id")
    @classmethod
    def _valid_id(cls, v: str) -> str:
        if not ELEMENT_ID_RE.match(v):
            raise ValueError("element_id must look like 'e3fa91c' (optionally with a '.suffix')")
        return v


class OpenArgs(_Args):
    url: str = Field(description="Absolute http(s) URL to open.")

    @field_validator("url")
    @classmethod
    def _valid_url(cls, v: str) -> str:
        return validate_url_syntax(v)


class ClickArgs(_ElementArgs):
    pass


class CheckArgs(_ElementArgs):
    pass


class TypeArgs(_ElementArgs):
    text: str = Field(max_length=MAX_TYPE_LENGTH, description="Text to enter.")
    clear_first: bool = Field(default=True, description="Replace existing content (true) or append (false).")
    press_enter: bool = Field(default=False, description="Press Enter after typing.")


class SelectArgs(_ElementArgs):
    value: str | None = Field(default=None, max_length=500, description="Option value attribute.")
    label: str | None = Field(default=None, max_length=500, description="Visible option label.")
    index: int | None = Field(default=None, ge=0, le=10_000, description="Zero-based option index.")

    @model_validator(mode="after")
    def _exactly_one(self) -> "SelectArgs":
        if sum(x is not None for x in (self.value, self.label, self.index)) != 1:
            raise ValueError("provide exactly one of value, label, index")
        return self


class ScrollArgs(_Args):
    direction: Literal["up", "down", "top", "bottom"] = Field(default="down")
    amount: int = Field(default=600, ge=1, le=5000, description="Pixels for up/down.")
    element_id: str | None = Field(default=None, description="If set, scroll this element into view instead.")

    @field_validator("element_id")
    @classmethod
    def _valid_id(cls, v: str | None) -> str | None:
        if v is not None and not ELEMENT_ID_RE.match(v):
            raise ValueError("element_id must look like 'e3fa91c' (optionally with a '.suffix')")
        return v


class PressArgs(_Args):
    key: str = Field(max_length=40, description="e.g. 'Enter', 'Tab', 'Escape', 'ArrowDown', 'Control+A'.")
    element_id: str | None = Field(default=None, description="Element to focus first; omit to use the page.")

    @field_validator("key")
    @classmethod
    def _valid_key(cls, v: str) -> str:
        parts = v.split("+")
        *mods, key = parts
        if len(set(mods)) != len(mods) or any(m not in _MODIFIERS for m in mods):
            raise ValueError(f"modifiers must be from {sorted(_MODIFIERS)}")
        if key not in _NAMED_KEYS and not re.fullmatch(r"[A-Za-z0-9]", key):
            raise ValueError(f"key must be a single letter/digit or one of {sorted(_NAMED_KEYS)}")
        return v

    @field_validator("element_id")
    @classmethod
    def _valid_id(cls, v: str | None) -> str | None:
        if v is not None and not ELEMENT_ID_RE.match(v):
            raise ValueError("element_id must look like 'e3fa91c' (optionally with a '.suffix')")
        return v


class WaitArgs(_Args):
    milliseconds: int = Field(default=1000, ge=0, le=MAX_WAIT_MS)
    load_state: Literal["load", "domcontentloaded", "networkidle"] | None = Field(
        default=None, description="If set, wait for this load state instead of a fixed delay."
    )


class ScreenshotArgs(_Args):
    full_page: bool = False


class NoArgs(_Args):
    pass


# ---------------------------------------------------------------------------
# Fixed internal scripts (constants; never model-supplied)
# ---------------------------------------------------------------------------

_JS_SCROLL_BY = "(dy) => { window.scrollBy(0, dy); }"
_JS_SCROLL_TOP = "() => { window.scrollTo(0, 0); }"
_JS_SCROLL_BOTTOM = "() => { window.scrollTo(0, document.documentElement.scrollHeight); }"
_JS_SCROLL_POS = (
    "() => ({ scrollY: Math.round(window.scrollY), viewportHeight: window.innerHeight,"
    " scrollHeight: document.documentElement.scrollHeight })"
)


# ---------------------------------------------------------------------------
# Executors (operate on a Playwright Page; return small `details` dicts)
# ---------------------------------------------------------------------------

async def _settle(page: Page, timeout_ms: int = 3000) -> None:
    try:
        await page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except PlaywrightTimeout:
        pass


Resolver = Callable[[str], Awaitable[Locator]]  # element id -> live Locator (raises ActionError)


async def do_open(
    page: Page, a: OpenArgs, *, nav_timeout_ms: int, allow_private: bool,
    allowed_domains: Iterable[str] | None = None, allow_subdomains: bool = True,
) -> dict[str, Any]:
    await assert_url_allowed(a.url, allow_private, allowed_domains, allow_subdomains)
    response = await page.goto(a.url, wait_until="domcontentloaded", timeout=nav_timeout_ms)
    await _settle(page)
    return {"http_status": response.status if response else None}


async def do_click(page: Page, a: ClickArgs, *, timeout_ms: int, resolve: Resolver) -> dict[str, Any]:
    await (await resolve(a.element_id)).click(timeout=timeout_ms)
    await _settle(page, 2000)
    return {}


async def do_type(page: Page, a: TypeArgs, *, timeout_ms: int, resolve: Resolver) -> dict[str, Any]:
    loc = await resolve(a.element_id)
    if a.clear_first:
        await loc.fill(a.text, timeout=timeout_ms)
    else:
        await loc.click(timeout=timeout_ms)
        await loc.press_sequentially(a.text, timeout=timeout_ms)
    if a.press_enter:
        await loc.press("Enter", timeout=timeout_ms)
        await _settle(page, 2000)
    return {"text_length": len(a.text)}


async def do_select(page: Page, a: SelectArgs, *, timeout_ms: int, resolve: Resolver) -> dict[str, Any]:
    loc = await resolve(a.element_id)
    if a.value is not None:
        chosen = await loc.select_option(value=a.value, timeout=timeout_ms)
    elif a.label is not None:
        chosen = await loc.select_option(label=a.label, timeout=timeout_ms)
    else:
        chosen = await loc.select_option(index=a.index, timeout=timeout_ms)
    return {"selected": chosen}


async def do_check(page: Page, a: CheckArgs, *, timeout_ms: int, resolve: Resolver, checked: bool) -> dict[str, Any]:
    loc = await resolve(a.element_id)
    if checked:
        await loc.check(timeout=timeout_ms)
    else:
        await loc.uncheck(timeout=timeout_ms)
    return {"checked": await loc.is_checked()}


async def do_scroll(page: Page, a: ScrollArgs, *, timeout_ms: int, resolve: Resolver) -> dict[str, Any]:
    if a.element_id:
        await (await resolve(a.element_id)).scroll_into_view_if_needed(timeout=timeout_ms)
    elif a.direction == "down":
        await page.evaluate(_JS_SCROLL_BY, a.amount)
    elif a.direction == "up":
        await page.evaluate(_JS_SCROLL_BY, -a.amount)
    elif a.direction == "top":
        await page.evaluate(_JS_SCROLL_TOP)
    else:
        await page.evaluate(_JS_SCROLL_BOTTOM)
    return await page.evaluate(_JS_SCROLL_POS)


async def do_press(page: Page, a: PressArgs, *, timeout_ms: int, resolve: Resolver) -> dict[str, Any]:
    if a.element_id:
        await (await resolve(a.element_id)).press(a.key, timeout=timeout_ms)
    else:
        await page.keyboard.press(a.key)
    await _settle(page, 2000)
    return {}


async def do_history(page: Page, *, direction: str, nav_timeout_ms: int) -> dict[str, Any]:
    fn = page.go_back if direction == "back" else page.go_forward
    response = await fn(wait_until="domcontentloaded", timeout=nav_timeout_ms)
    if response is None:
        # Playwright returns None both for "no history" and same-document navigations.
        return {"note": "No navigation occurred (no history entry, or same-document navigation)."}
    await _settle(page)
    return {"http_status": response.status if response else None}


async def do_reload(page: Page, *, nav_timeout_ms: int) -> dict[str, Any]:
    response = await page.reload(wait_until="domcontentloaded", timeout=nav_timeout_ms)
    await _settle(page)
    return {"http_status": response.status if response else None}


async def do_wait(page: Page, a: WaitArgs, *, timeout_ms: int) -> dict[str, Any]:
    if a.load_state:
        await page.wait_for_load_state(a.load_state, timeout=timeout_ms)
    else:
        await page.wait_for_timeout(a.milliseconds)
    return {}
