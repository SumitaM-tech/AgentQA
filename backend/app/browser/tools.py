"""Browser tool layer — the ONLY surface the Gemini agent may use.

The model picks a tool name + JSON arguments. Arguments are validated against
strict Pydantic models (unknown fields rejected) before anything runs. There
is deliberately no tool that evaluates JavaScript, runs Python, or shells out;
unknown tool names are refused. Failures come back as structured results so the
model can recover instead of crashing the loop.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, ValidationError

from app.browser import actions as A
from app.browser.models import ActionResult, ErrorCode
from app.browser.session import BrowserSession, BrowserSessionError
from app.core.logging import get_logger

logger = get_logger(__name__)


class ToolResult(BaseModel):
    ok: bool
    tool: str
    error: str | None = None
    error_code: ErrorCode | None = None
    result: dict[str, Any] = {}
    screenshot_path: str | None = None


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_model: type[BaseModel]
    handler: Callable[[BrowserSession, Any], Awaitable[ActionResult | dict[str, Any]]]


def _tools() -> dict[str, ToolSpec]:
    specs = [
        ToolSpec("browser_open", "Open an http(s) URL in the browser.", A.OpenArgs,
                 lambda s, a: s.open_url(a.url)),
        ToolSpec("browser_click", "Click an element by element_id (from browser_get_page_state).", A.ClickArgs,
                 lambda s, a: s.click(a.element_id)),
        ToolSpec("browser_type", "Type text into an input/textarea by element_id.", A.TypeArgs,
                 lambda s, a: s.type(a.element_id, a.text, a.clear_first, a.press_enter)),
        ToolSpec("browser_select", "Choose an option in a <select> by value, label, or index (exactly one).", A.SelectArgs,
                 lambda s, a: s.select_option(a.element_id, value=a.value, label=a.label, index=a.index)),
        ToolSpec("browser_check", "Check a checkbox/radio by element_id.", A.CheckArgs,
                 lambda s, a: s.check(a.element_id)),
        ToolSpec("browser_uncheck", "Uncheck a checkbox by element_id.", A.CheckArgs,
                 lambda s, a: s.uncheck(a.element_id)),
        ToolSpec("browser_scroll", "Scroll the page up/down/top/bottom, or an element into view.", A.ScrollArgs,
                 lambda s, a: s.scroll(a.direction, a.amount, a.element_id)),
        ToolSpec("browser_press", "Press an allow-listed key (Enter, Tab, Escape, arrows, Control+A, ...).", A.PressArgs,
                 lambda s, a: s.press_key(a.key, a.element_id)),
        ToolSpec("browser_back", "Go back in history.", A.NoArgs, lambda s, a: s.go_back()),
        ToolSpec("browser_forward", "Go forward in history.", A.NoArgs, lambda s, a: s.go_forward()),
        ToolSpec("browser_reload", "Reload the current page.", A.NoArgs, lambda s, a: s.reload()),
        ToolSpec("browser_wait", "Wait a fixed time (ms) or for a load state.", A.WaitArgs,
                 lambda s, a: s.wait(a.milliseconds, a.load_state)),
        ToolSpec("browser_screenshot", "Capture a screenshot of the current page.", A.ScreenshotArgs,
                 lambda s, a: s.screenshot(a.full_page)),
        ToolSpec("browser_get_page_state",
                 "Observe the page: URL, title, interactive elements with element_ids, visible text, "
                 "accessibility snapshot, console errors, failed requests, screenshot. Call before acting "
                 "and after page changes; element_ids are only valid for the last observed state.",
                 A.NoArgs, lambda s, a: _page_state(s)),
    ]
    return {t.name: t for t in specs}


async def _page_state(session: BrowserSession) -> dict[str, Any]:
    """Compact, sanitized, size-bounded view (never raw HTML)."""
    return (await session.observe()).to_compact_dict()


TOOLS: dict[str, ToolSpec] = _tools()


def _simplify_schema(node: Any) -> Any:
    """Pydantic JSON schema -> plain, Gemini-friendly schema (no titles,
    additionalProperties, or nullable anyOf)."""
    if isinstance(node, list):
        return [_simplify_schema(n) for n in node]
    if not isinstance(node, dict):
        return node
    if "anyOf" in node:
        non_null = [b for b in node["anyOf"] if b.get("type") != "null"]
        if len(non_null) == 1:
            merged = {**{k: v for k, v in node.items() if k != "anyOf"}, **non_null[0]}
            return _simplify_schema(merged)
    return {k: _simplify_schema(v) for k, v in node.items()
            if k not in ("title", "additionalProperties", "default")}


def tool_schemas() -> list[dict[str, Any]]:
    """[{name, description, parameters(JSON schema)}] for all tools."""
    return [
        {"name": t.name, "description": t.description,
         "parameters": _simplify_schema(t.args_model.model_json_schema())}
        for t in TOOLS.values()
    ]


def gemini_function_declarations():
    """google-genai FunctionDeclarations for the tool set (lazy import)."""
    from google.genai import types

    return [
        types.FunctionDeclaration(name=s["name"], description=s["description"], parameters_json_schema=s["parameters"])
        for s in tool_schemas()
    ]


class BrowserToolbox:
    """Executes model tool calls against one BrowserSession."""

    def __init__(self, session: BrowserSession) -> None:
        self._session = session

    async def execute(self, name: str, arguments: Any = None) -> ToolResult:
        spec = TOOLS.get(name) if isinstance(name, str) else None
        if spec is None:
            logger.warning("browser_tool_unknown", tool=str(name)[:60])
            return ToolResult(ok=False, tool=str(name)[:60], error_code=ErrorCode.UNKNOWN_TOOL,
                              error=f"Unknown tool. Available: {sorted(TOOLS)}")
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            return ToolResult(ok=False, tool=name, error_code=ErrorCode.INVALID_ARGUMENTS,
                              error="arguments must be a JSON object")
        try:
            args = spec.args_model(**arguments)
        except ValidationError as exc:
            msg = "; ".join(f"{'.'.join(map(str, e['loc'])) or 'args'}: {e['msg']}" for e in exc.errors())[:500]
            return ToolResult(ok=False, tool=name, error_code=ErrorCode.INVALID_ARGUMENTS, error=msg)

        try:
            out = await spec.handler(self._session, args)
        except BrowserSessionError as exc:
            return ToolResult(ok=False, tool=name, error_code=ErrorCode.SESSION_CLOSED, error=str(exc))

        if isinstance(out, ActionResult):
            return ToolResult(ok=out.ok, tool=name, error=out.error, error_code=out.error_code,
                              result=out.model_dump(mode="json"), screenshot_path=out.screenshot_path)
        return ToolResult(ok=True, tool=name, result=out, screenshot_path=out.get("screenshot_path"))
