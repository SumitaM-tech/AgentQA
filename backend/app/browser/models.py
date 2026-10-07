"""Typed data models for the browser engine: config, page state, results."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from app.core.config import get_settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ErrorCode(str, Enum):
    INVALID_ARGUMENTS = "invalid_arguments"
    UNKNOWN_TOOL = "unknown_tool"
    ELEMENT_NOT_FOUND = "element_not_found"
    ELEMENT_NOT_ACTIONABLE = "element_not_actionable"
    NAVIGATION_BLOCKED = "navigation_blocked"
    NAVIGATION_FAILED = "navigation_failed"
    NO_HISTORY = "no_history"
    TIMEOUT = "timeout"
    SESSION_CLOSED = "session_closed"
    LIMIT_EXCEEDED = "limit_exceeded"
    INTERNAL = "internal_error"


class ViewportSize(BaseModel):
    width: int = Field(default=1440, ge=320, le=3840)
    height: int = Field(default=900, ge=240, le=2160)


# Actions after which a screenshot is captured (failures always capture one).
DEFAULT_SCREENSHOT_ACTIONS = frozenset(
    {"open_url", "click", "select_option", "check", "uncheck", "press_key", "go_back", "go_forward", "reload"}
)


class BrowserSessionConfig(BaseModel):
    headless: bool = True
    viewport: ViewportSize = Field(default_factory=ViewportSize)
    action_timeout_ms: int = Field(default=15000, ge=500, le=120000)
    navigation_timeout_ms: int = Field(default=30000, ge=1000, le=180000)
    trace_enabled: bool = False
    screenshot_actions: frozenset[str] = DEFAULT_SCREENSHOT_ACTIONS
    max_actions: int = Field(default=200, ge=1)
    allow_private_networks: bool = True
    # Top-level navigations outside these domains are blocked (None = unrestricted).
    allowed_domains: list[str] | None = None
    allow_subdomains: bool = True
    ttl_seconds: int = Field(default=900, ge=30)

    @classmethod
    def from_settings(cls, headless: bool | None = None, trace: bool | None = None) -> "BrowserSessionConfig":
        s = get_settings()
        return cls(
            headless=s.browser_headless if headless is None else headless,
            viewport=ViewportSize(width=s.browser_viewport_width, height=s.browser_viewport_height),
            action_timeout_ms=s.action_timeout_ms,
            navigation_timeout_ms=s.navigation_timeout_ms,
            trace_enabled=s.browser_trace_enabled if trace is None else trace,
            max_actions=s.browser_max_actions,
            allow_private_networks=s.browser_allow_private_networks,
            ttl_seconds=s.browser_session_ttl_seconds,
        )


class ActionResult(BaseModel):
    ok: bool
    action: str
    args: dict[str, Any] = Field(default_factory=dict)  # redacted summary
    error: str | None = None
    error_code: ErrorCode | None = None
    duration_ms: int = 0
    url: str | None = None
    title: str | None = None
    screenshot_path: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=utcnow)
