"""Browser telemetry: console errors, uncaught exceptions, failed requests and
dialogs (deduplicated, bounded) plus a structured action log. URLs are logged
without query strings so tokens never reach logs or the model. Implements the
perception layer's `TelemetrySource`; draining returns what happened since the
previous observation."""
from __future__ import annotations

from collections import OrderedDict
from urllib.parse import urlsplit

from app.browser.models import ActionResult
from app.core.logging import get_logger
from app.perception.models import BrowserException, ConsoleError, NetworkError

logger = get_logger(__name__)

_MAX_TEXT = 500
_MAX_UNIQUE = 200


def redact_url(url: str) -> str:
    try:
        p = urlsplit(url)
        base = f"{p.scheme}://{p.netloc}{p.path}"
        return base[:300] + ("?…" if p.query else "")
    except ValueError:
        return url[:300]


def _bump(store: OrderedDict, key, make):
    if key in store:
        store[key].count += 1
        return
    store[key] = make()
    while len(store) > _MAX_UNIQUE:
        store.popitem(last=False)


class TelemetryCollector:
    """Attach to a BrowserContext so popups/new tabs are covered too."""

    def __init__(self) -> None:
        self._console: OrderedDict[tuple, ConsoleError] = OrderedDict()
        self._network: OrderedDict[tuple, NetworkError] = OrderedDict()
        self._exceptions: OrderedDict[str, BrowserException] = OrderedDict()
        self._dialogs: list[str] = []
        self.request_count = 0
        self.warning_count = 0

    def attach(self, context) -> None:  # noqa: ANN001 - playwright BrowserContext
        context.on("console", self._on_console)
        context.on("weberror", self._on_web_error)
        context.on("request", self._on_request)
        context.on("response", self._on_response)
        context.on("requestfailed", self._on_request_failed)
        context.on("dialog", self._on_dialog)

    def _on_console(self, msg) -> None:  # noqa: ANN001
        if msg.type == "warning":
            self.warning_count += 1
        elif msg.type == "error":
            if msg.text.startswith("Failed to load resource"):
                return  # duplicated, with more detail, by the network telemetry below
            text = msg.text[:_MAX_TEXT]
            _bump(self._console, ("error", text), lambda: ConsoleError(level="error", text=text))

    def _on_web_error(self, web_error) -> None:  # noqa: ANN001
        err = web_error.error
        message = (getattr(err, "message", None) or str(err))[:_MAX_TEXT]
        stack = (getattr(err, "stack", None) or "")[:1000] or None
        _bump(self._exceptions, message, lambda: BrowserException(message=message, stack=stack))

    def _on_request(self, _request) -> None:  # noqa: ANN001
        self.request_count += 1

    def _on_response(self, response) -> None:  # noqa: ANN001
        if response.status >= 400:
            req = response.request
            url = redact_url(response.url)
            _bump(self._network, ("http", req.method, url, response.status), lambda: NetworkError(
                url=url, method=req.method, status=response.status, resource_type=req.resource_type,
                kind="http_error"))

    def _on_request_failed(self, request) -> None:  # noqa: ANN001
        url = redact_url(request.url)
        failure = (request.failure or "failed")[:200]
        _bump(self._network, ("fail", request.method, url, failure), lambda: NetworkError(
            url=url, method=request.method, resource_type=request.resource_type,
            failure=failure, kind="request_failed"))

    async def _on_dialog(self, dialog) -> None:  # noqa: ANN001
        self._dialogs.append(f"{dialog.type}: {dialog.message[:_MAX_TEXT]}")
        try:
            await dialog.dismiss()  # never leave a dialog blocking the page
        except Exception:  # noqa: BLE001
            pass

    # --- TelemetrySource -------------------------------------------------
    def drain_console_errors(self) -> list[ConsoleError]:
        items = list(self._console.values())
        self._console.clear()
        return items

    def drain_network_errors(self) -> list[NetworkError]:
        items = list(self._network.values())
        self._network.clear()
        return items

    def drain_exceptions(self) -> list[BrowserException]:
        items = list(self._exceptions.values())
        self._exceptions.clear()
        return items

    def drain_dialogs(self) -> list[str]:
        items, self._dialogs = self._dialogs, []
        return items


class ActionLogger:
    """In-memory log of every action + structured log line (no typed text)."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.records: list[ActionResult] = []

    def record(self, result: ActionResult) -> None:
        self.records.append(result)
        logger.info(
            "browser_action",
            session_id=self.session_id,
            action=result.action,
            ok=result.ok,
            error_code=result.error_code.value if result.error_code else None,
            duration_ms=result.duration_ms,
            url=redact_url(result.url) if result.url else None,
            args=result.args,
            screenshot=result.screenshot_path,
        )
