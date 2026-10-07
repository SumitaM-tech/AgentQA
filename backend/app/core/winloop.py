"""Windows asyncio guard.

Playwright starts its driver with `asyncio.create_subprocess_exec`, which raises NotImplementedError on Windows when
the running loop is a SelectorEventLoop. `uvicorn --reload` (and `--workers`) force that loop on Windows. Starting the
server with `python run.py` (or `--loop none`) keeps the default ProactorEventLoop, which supports subprocesses.
"""
from __future__ import annotations

import asyncio
import sys

FIX_MESSAGE = (
    "The server's event loop cannot start the browser on Windows (uvicorn --reload forces a SelectorEventLoop). "
    "Stop the server and start it with:  python run.py   (or: python -m uvicorn app.main:app --reload --loop none)."
)


def windows_loop_problem(platform: str | None = None, loop: asyncio.AbstractEventLoop | None = None) -> str | None:
    """Return an actionable message if browser subprocesses cannot work with the current loop, else None."""
    if (platform or sys.platform) != "win32":
        return None
    try:
        loop = loop or asyncio.get_running_loop()
    except RuntimeError:
        return None
    return FIX_MESSAGE if "Selector" in type(loop).__name__ else None
