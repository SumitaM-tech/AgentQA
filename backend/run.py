"""Development launcher:  python run.py [--no-reload] [--port 8000] [--host 127.0.0.1]

Why not plain `uvicorn --reload` on Windows? It forces a SelectorEventLoop, which cannot spawn Playwright's
driver process (NotImplementedError). This launcher keeps the default ProactorEventLoop on Windows, and only watches
the `app/` folder for changes (not venv/ or data/), so screenshots and dependencies never trigger a reload.
"""
from __future__ import annotations

import argparse
import sys

import uvicorn


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-reload", action="store_true")
    a = ap.parse_args()
    uvicorn.run(
        "app.main:app", host=a.host, port=a.port, reload=not a.no_reload, reload_dirs=["app"],
        loop="none" if sys.platform == "win32" else "auto",
    )


if __name__ == "__main__":
    main()
