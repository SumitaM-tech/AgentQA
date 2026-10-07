"""Smoke tests: app boots and core contracts import cleanly. Deeper tests
(orchestrator loop, browser tool, Gemini client) land alongside their
implementations."""
from fastapi.testclient import TestClient

from app.main import app


def test_health_check() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok" and body["database"] == "ok"


def test_agent_state_models_importable() -> None:
    from app.agent.legacy_state import Action, AgentState, Observation  # noqa: F401
