"""AgentQA DEMO shop — a tiny app with INTENTIONAL bugs for demonstrating/evaluating AgentQA Cloud.

Run:  python server.py [port]      (default 8080, binds 127.0.0.1)
NOT a real product. Known bugs are listed in known_bugs.json (ground truth for the evaluation script).
"""
from __future__ import annotations

import functools
import http.server
import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).parent / "public"
PRODUCTS = [
    {"id": 1, "name": "Demo Apple", "price": 1.5}, {"id": 2, "name": "Demo Banana", "price": 0.8},
    {"id": 3, "name": "Demo Cherry", "price": 4.2}, {"id": 4, "name": "Demo Date", "price": 3.1},
]


class Handler(http.server.SimpleHTTPRequestHandler):
    def _json(self, code: int, body: object) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        parts = urlsplit(self.path)
        if parts.path == "/api/products":
            return self._json(200, PRODUCTS)
        if parts.path == "/api/search":
            q = parse_qs(parts.query).get("q", [""])[0].lower()
            return self._json(200, [p for p in PRODUCTS if q in p["name"].lower()])
        if parts.path == "/api/recommendations":  # BUG: always fails with a server error
            return self._json(500, {"error": "recommendation service crashed"})
        if parts.path == "/":
            self.path = "/index.html"
        return super().do_GET()

    def log_message(self, *_a) -> None:  # quiet
        pass


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    handler = functools.partial(Handler, directory=str(ROOT))
    with http.server.ThreadingHTTPServer((__import__("os").environ.get("DEMO_BIND", "127.0.0.1"), port), handler) as srv:
        print(f"AgentQA demo shop on http://127.0.0.1:{port}  (intentional bugs: see known_bugs.json)")
        srv.serve_forever()


if __name__ == "__main__":
    main()
