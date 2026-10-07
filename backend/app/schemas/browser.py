from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, HttpUrl

from app.perception.models import PageObservation


class BrowserTestRequest(BaseModel):
    url: HttpUrl
    headless: bool = Field(default=True, description="false opens a visible window (local runs only, not Docker).")
    trace: bool = Field(default=False, description="Record a Playwright trace (zip) for this run.")
    include_screenshot_base64: bool = True


class BrowserTestResponse(BaseModel):
    session_id: str
    url: str
    title: str
    http_status: int | None = None
    screenshot_path: str | None = None
    screenshot_base64: str | None = None
    element_count: int
    observation: PageObservation  # full structured perception result
    compact_prompt: str  # exactly the compact text that would be sent to Gemini
    compact_prompt_chars: int
    trace_path: str | None = None
    duration_ms: int
    actions: list[dict[str, Any]]
