import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:  # runs lifespan -> creates tables
        yield c


def test_health(client):
    for path in ("/health", "/api/health"):
        body = client.get(path).json()
        assert body["status"] == "ok" and body["database"] == "ok"
        assert "gemini_configured" in body and "GEMINI_API_KEY" not in str(body)


def test_create_get_list_run(client):
    r = client.post("/api/runs", json={"url": "http://127.0.0.1:9/", "goal": "Test checkout", "max_steps": 5})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "queued" and uuid.UUID(body["run_id"])
    detail = client.get(f"/api/runs/{body['run_id']}").json()
    assert detail["goal"] == "Test checkout" and detail["max_steps"] == 5 and detail["steps_taken"] == 0
    assert body["run_id"] in [x["id"] for x in client.get("/api/runs").json()]
    assert client.get(f"/api/runs/{body['run_id']}/states").json() == []
    assert client.get(f"/api/runs/{body['run_id']}/bugs").json() == []
    assert client.get(f"/api/runs/{body['run_id']}/events").json() == []


def test_unknown_run_is_404(client):
    rid = uuid.uuid4()
    for path in ("", "/states", "/bugs", "/events", "/graph"):
        assert client.get(f"/api/runs/{rid}{path}").status_code == 404
    assert client.post(f"/api/runs/{rid}/start").status_code == 404


def test_run_validation_errors(client):
    assert client.post("/api/runs", json={"url": "x"}).status_code == 422
    assert client.post("/api/runs", json={"url": "https://example.com", "max_steps": 0}).status_code == 422
    assert client.post("/api/runs", json={"url": "https://example.com", "max_steps": 9999}).status_code == 422


def test_private_target_blocked_by_default(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "browser_allow_private_networks", False)
    r = client.post("/api/runs", json={"url": "http://127.0.0.1:8000/", "goal": "x"})
    assert r.status_code == 403
    r = client.post("/api/targets/validate", json={"url": "http://169.254.169.254/"})
    assert r.json()["ok"] is False


def test_validate_target_returns_warnings(client):
    body = client.post("/api/targets/validate", json={"url": "http://127.0.0.1:1234"}).json()
    assert body["ok"] and body["warnings"]


def test_stop_and_double_start_conflicts(client):
    rid = client.post("/api/runs", json={"url": "http://127.0.0.1:9/", "goal": "g"}).json()["run_id"]
    assert client.post(f"/api/runs/{rid}/pause").status_code == 409     # not running
    assert client.post(f"/api/runs/{rid}/stop").json()["status"] == "stopped"
    assert client.post(f"/api/runs/{rid}/start").status_code == 409     # no longer queued


def test_credentials_are_never_returned(client):
    r = client.post("/api/runs", json={"url": "http://127.0.0.1:9/", "goal": "g",
                                       "auth": {"username": "alice", "password": "s3cret-pw"}})
    rid = r.json()["run_id"]
    text = client.get(f"/api/runs/{rid}").text
    assert "s3cret-pw" not in text and "alice" not in text
    assert client.get(f"/api/runs/{rid}").json()["has_credentials"] is True


def test_bugs_endpoint_and_dashboard(client):
    assert client.get("/api/bugs").status_code == 200
    assert client.get(f"/api/bugs/{uuid.uuid4()}").status_code == 404
    s = client.get("/api/dashboard/summary").json()
    assert {"runs_total", "runs_active", "bugs_total", "recent_runs"} <= set(s)


def test_screenshot_endpoint_blocks_traversal(client):
    assert client.get("/api/artifacts/screenshots/../../etc/passwd").status_code in (404, 400)
    assert client.get("/api/artifacts/screenshots/nope.png").status_code == 404


def test_windows_selector_loop_is_detected_and_run_fails_with_actionable_message(client, monkeypatch):
    import asyncio
    import time

    from app.core import winloop
    from app.services import run_manager as rm

    class SelectorEventLoop(asyncio.AbstractEventLoop):
        pass

    class ProactorEventLoop(asyncio.AbstractEventLoop):
        pass

    assert winloop.windows_loop_problem("win32", SelectorEventLoop()) == winloop.FIX_MESSAGE
    assert winloop.windows_loop_problem("win32", ProactorEventLoop()) is None
    assert winloop.windows_loop_problem("linux", SelectorEventLoop()) is None

    monkeypatch.setattr(rm, "windows_loop_problem", lambda: winloop.FIX_MESSAGE)
    rid = client.post("/api/runs", json={"url": "https://example.com/", "goal": "g"}).json()["run_id"]
    client.post(f"/api/runs/{rid}/start")
    for _ in range(50):
        run = client.get(f"/api/runs/{rid}").json()
        if run["status"] == "failed":
            break
        time.sleep(0.2)
    assert run["status"] == "failed" and "python run.py" in run["error_message"]
