"""E2E on the real demo shop (intentional bugs) with real Chromium. No LLM: exercises the deterministic explorer
plus the rule-based critic, so only `rules`-detectable bugs are expected (LLM-only bugs need GEMINI_API_KEY)."""
import functools
import http.server
import importlib.util
import json
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.evaluation.run_eval import score
from app.main import app
from app.services.run_manager import RunManager, set_run_manager

DEMO = Path(__file__).resolve().parents[2] / "demo-app"


class _NoLLM:
    async def generate(self, prompt, *, system_instruction, schema, image_bytes=None):  # noqa: ANN001
        raise RuntimeError("LLM unavailable in tests")


@pytest.fixture(scope="module")
def shop():
    spec = importlib.util.spec_from_file_location("demo_server", DEMO / "server.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(mod.Handler, directory=str(DEMO / "public")))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_demo_shop_acceptance(shop):
    set_run_manager(RunManager(decision_model_factory=lambda: _NoLLM()))
    try:
        with TestClient(app) as c:
            pid = c.post("/api/projects", json={"name": "Demo shop", "base_url": shop, "default_goals": ["Thoroughly test the checkout flow."]}).json()["id"]
            rid = c.post("/api/runs", json={"url": shop + "/index.html", "goal": "Thoroughly test the checkout flow.", "project_id": pid,
                                            "max_steps": 45, "max_runtime_seconds": 150}).json()["run_id"]
            with c.websocket_connect(f"/ws/runs/{rid}") as ws:
                c.post(f"/api/runs/{rid}/start")
                types = []
                while True:
                    ev = ws.receive_json()
                    if ev["type"] != "ping":
                        types.append(ev["type"])
                    if ev["type"] == "run_completed":
                        break
            run = c.get(f"/api/runs/{rid}").json()
            assert run["status"] == "completed" and run["project_id"] == pid, run
            assert {"state_discovered", "agent_action", "bug_verified"} <= set(types), set(types)
            graph = c.get(f"/api/runs/{rid}/graph").json()
            assert len(graph["states"]) >= 5 and graph["edges"]
            bugs = c.get(f"/api/runs/{rid}/bugs").json()
            truth = json.loads((DEMO / "known_bugs.json").read_text())["bugs"]
            result = score(truth, bugs)
            print("GROUND TRUTH:", json.dumps({k: result[k] for k in ("detected", "known_bugs", "detection_rate_rule_detectable", "false_positive_rate", "unmatched_reports")}))
            assert result["detected"] >= 3, result                       # real findings, no fakes
            assert result["false_positive_rate"] in (0, 0.0), result     # correct validation messages are not bugs
            assert any(b["status"] == "verified" and b["screenshot_url"] for b in bugs)
            ev = c.get(f"/api/runs/{rid}/evaluation").json()
            assert ev["states_explored"] == len(graph["states"]) and ev["time_to_first_bug_seconds"] is not None
            assert c.get(f"/api/projects/{pid}").json()["run_count"] == 1
    finally:
        set_run_manager(None)
