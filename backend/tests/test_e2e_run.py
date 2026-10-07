"""End-to-end: API -> RunManager -> Playwright (real Chromium) -> local demo shop -> DB + live WebSocket events.

The LLM is replaced by a model that always fails, which exercises the agent's deterministic fallback
explorer, so this test needs no network and no API key.
"""
import time

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.run_manager import RunManager, set_run_manager


class _NoLLM:
    async def generate(self, prompt, *, system_instruction, schema, image_bytes=None):  # noqa: ANN001
        raise RuntimeError("LLM unavailable in tests")


@pytest.fixture
def client():
    set_run_manager(RunManager(decision_model_factory=lambda: _NoLLM()))
    with TestClient(app) as c:
        yield c
    set_run_manager(None)


def _wait_done(client, rid, timeout=120):
    end = time.time() + timeout
    while time.time() < end:
        run = client.get(f"/api/runs/{rid}").json()
        if run["status"] in ("completed", "failed", "stopped"):
            return run
        time.sleep(0.5)
    raise AssertionError("run did not finish")


def test_full_autonomous_run(client, demo_server):
    rid = client.post("/api/runs", json={"url": f"{demo_server}/index.html", "goal": "Explore the shop",
                                         "max_steps": 8, "max_runtime_seconds": 90}).json()["run_id"]
    with client.websocket_connect(f"/ws/runs/{rid}") as ws:
        assert client.post(f"/api/runs/{rid}/start").status_code == 200
        seen = []
        while True:
            ev = ws.receive_json()
            if ev.get("type") == "ping":
                continue
            seen.append(ev)
            if ev["type"] == "run_completed":
                break
    types = [e["type"] for e in seen]
    for expected in ("run_started", "page_loaded", "observation", "agent_thinking", "agent_action",
                     "action_completed", "state_discovered", "run_completed"):
        assert expected in types, f"missing {expected}: {sorted(set(types))}"
    seqs = [e["seq"] for e in seen]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)

    run = _wait_done(client, rid)
    assert run["status"] == "completed", run
    assert run["states_count"] >= 2 and run["actions_count"] >= 2 and run["steps_taken"] >= 2

    graph = client.get(f"/api/runs/{rid}/graph").json()
    assert len(graph["states"]) >= 2 and len(graph["edges"]) >= 1
    ids = {s["id"] for s in graph["states"]}
    assert all(e["source_state_id"] in ids and e["target_state_id"] in ids for e in graph["edges"])
    assert all(len(s["fingerprint"]) <= 64 for s in graph["states"])

    bugs = client.get(f"/api/runs/{rid}/bugs").json()
    assert bugs, "the demo page logs a console error on every load and should be reported"
    bug = bugs[0]
    assert bug["status"] in ("verified", "unverified") and 0 < bug["confidence"] <= 1
    assert bug["steps_to_reproduce"] and bug["severity_reason"] and bug["verification"]
    assert len({b["fingerprint"] for b in bugs}) == len(bugs)  # no duplicates

    # Persisted event log matches what was streamed, and replay works after a reconnect.
    stored = client.get(f"/api/runs/{rid}/events").json()
    assert [e["seq"] for e in stored] == sorted(e["seq"] for e in stored)
    tail = client.get(f"/api/runs/{rid}/events", params={"after": stored[-3]["seq"]}).json()
    assert len(tail) == 2
    with client.websocket_connect(f"/ws/runs/{rid}?after={stored[-2]['seq']}") as ws:
        assert ws.receive_json()["type"] == "run_completed"

    shot = next((s["screenshot_url"] for s in graph["states"] if s["screenshot_url"]), None)
    assert shot and client.get(shot).headers["content-type"].startswith("image/")


def test_unreachable_site_fails_gracefully(client):
    rid = client.post("/api/runs", json={"url": "http://127.0.0.1:9/", "goal": "x", "max_steps": 3}).json()["run_id"]
    client.post(f"/api/runs/{rid}/start")
    run = _wait_done(client, rid, timeout=90)
    assert run["status"] == "failed" and run["termination_reason"] in ("site_unreachable", "fatal_error")
    assert run["error_message"]


def test_stop_a_running_run(client, demo_server):
    rid = client.post("/api/runs", json={"url": f"{demo_server}/index.html", "goal": "x", "max_steps": 200,
                                         "max_runtime_seconds": 120}).json()["run_id"]
    client.post(f"/api/runs/{rid}/start")
    end = time.time() + 60
    while time.time() < end and client.get(f"/api/runs/{rid}").json()["status"] != "running":
        time.sleep(0.2)
    assert client.post(f"/api/runs/{rid}/pause").json()["status"] == "paused"
    assert client.post(f"/api/runs/{rid}/resume").json()["status"] == "running"
    client.post(f"/api/runs/{rid}/stop")
    assert _wait_done(client, rid)["status"] in ("stopped", "completed")
