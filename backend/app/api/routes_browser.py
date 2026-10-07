"""POST /api/browser/test — open a URL in Chromium and return URL, title,
screenshot and interactive elements. The browser is always closed, even on error.

SECURITY: this makes the server fetch arbitrary URLs. Put auth in front of it
and set BROWSER_ALLOW_PRIVATE_NETWORKS=false on any shared/public deployment.
"""
from __future__ import annotations

import base64
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, status

from app.browser.manager import BrowserCapacityError, BrowserLaunchError, get_browser_manager
from app.browser.models import ErrorCode
from app.browser.session import BrowserSessionError
from app.core.logging import get_logger
from app.schemas.browser import BrowserTestRequest, BrowserTestResponse

logger = get_logger(__name__)
router = APIRouter(prefix="/api/browser", tags=["browser"])

_STATUS_FOR_ERROR = {
    ErrorCode.NAVIGATION_BLOCKED: status.HTTP_400_BAD_REQUEST,
    ErrorCode.INVALID_ARGUMENTS: 422,
    ErrorCode.TIMEOUT: status.HTTP_504_GATEWAY_TIMEOUT,
}


@router.post("/test", response_model=BrowserTestResponse)
async def browser_test(payload: BrowserTestRequest) -> BrowserTestResponse:
    started = time.monotonic()
    manager = get_browser_manager()
    try:
        async with manager.session(headless=payload.headless, trace=payload.trace) as session:
            opened = await session.open_url(str(payload.url))
            if not opened.ok:
                raise HTTPException(
                    _STATUS_FOR_ERROR.get(opened.error_code, status.HTTP_502_BAD_GATEWAY),
                    detail={"error_code": opened.error_code.value if opened.error_code else None, "error": opened.error},
                )
            state = await session.observe()
            session_id = session.session_id
            actions = [r.model_dump(mode="json") for r in session.action_log]
            http_status = opened.details.get("http_status")
        trace_path = session.trace_path  # set once the session has closed
    except BrowserCapacityError as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc)) from exc
    except BrowserLaunchError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except BrowserSessionError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    shot_b64 = None
    if payload.include_screenshot_base64 and state.screenshot_path and Path(state.screenshot_path).exists():
        shot_b64 = base64.b64encode(Path(state.screenshot_path).read_bytes()).decode()

    compact = state.to_prompt_text()
    return BrowserTestResponse(
        session_id=session_id, url=state.url, title=state.title, http_status=http_status,
        screenshot_path=state.screenshot_path, screenshot_base64=shot_b64,
        element_count=len(state.interactive_elements), observation=state,
        compact_prompt=compact, compact_prompt_chars=len(compact),
        trace_path=trace_path, duration_ms=int((time.monotonic() - started) * 1000), actions=actions,
    )
