"""Shared fixtures: a tiny local web app served over HTTP (with a few API routes)."""
from __future__ import annotations

import os
import tempfile

# Isolate the test run BEFORE any `app` import: throwaway SQLite DB + screenshot dir, local targets allowed.
_TMP = tempfile.mkdtemp(prefix="agentqa-tests-")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP}/test.db"
os.environ["SCREENSHOT_DIR"] = f"{_TMP}/shots"
os.environ["TRACE_DIR"] = f"{_TMP}/traces"
os.environ["BROWSER_ALLOW_PRIVATE_NETWORKS"] = "true"
os.environ["GEMINI_API_KEY"] = ""
os.environ["ENABLE_DEBUG_ENDPOINTS"] = "true"
os.environ["ALLOWED_DOMAINS"] = ""
os.environ["FIX_AGENT_ENABLED"] = "false"

import functools
import http.server
import json
import threading
from pathlib import Path

import pytest

APP_DIR = Path(__file__).parent / "fixtures" / "app"


class _Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args, **kwargs) -> None:  # silence
        pass

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/api/boom"):
            body = json.dumps({"error": "boom"}).encode()
            self.send_response(500)
        elif self.path.startswith("/api/ok"):
            body = json.dumps({"ok": True}).encode()
            self.send_response(200)
        else:
            return super().do_GET()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="module")
def app_server():
    handler = functools.partial(_Handler, directory=str(APP_DIR))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


DEMO_DIR = Path(__file__).parent / "fixtures" / "demo"


@pytest.fixture(scope="module")
def demo_server():
    """Small multi-page demo shop (one page deliberately logs a console error on load)."""
    handler = functools.partial(_Handler, directory=str(DEMO_DIR))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
