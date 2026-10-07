"""GeminiService / client / /api/ai/test tests. No network: the low-level
GeminiClient.generate is replaced with a fake returning SDK-shaped objects."""
from __future__ import annotations

import io
import json

import pytest
from fastapi.testclient import TestClient
from google.genai import errors as genai_errors
from google.genai import types

from app.llm.client import GeminiClient, GeminiClientError, _is_retryable
from app.llm.schemas import AgentDecision
from app.llm.service import GeminiService
from app.llm.tool_definitions import RECORD_AGENT_DECISION

DECISION = {
    "action_type": "fill",
    "target": "el-3",
    "arguments": {"value": "-1"},
    "reason": "Testing invalid checkout input.",
    "expected_outcome": {"summary": "A validation error appears."},
    "confidence": 0.8,
    "exploration_priority": 0.4,
}


class FakeClient:
    model_name = "fake-model"

    def __init__(self, response):
        self.response = response
        self.calls: list[tuple[list, types.GenerateContentConfig]] = []

    async def generate(self, contents, config):
        self.calls.append((contents, config))
        return self.response


def _text_response(text, parsed=None):
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=[types.Part(text=text)]))],
        parsed=parsed,
    )


async def test_structured_uses_response_schema_and_parses() -> None:
    fake = FakeClient(_text_response(json.dumps(DECISION)))
    result = await GeminiService(fake).generate_structured("p", AgentDecision, image_bytes=b"png")
    assert isinstance(result, AgentDecision) and result.target == "el-3"
    contents, config = fake.calls[0]
    assert config.response_schema is AgentDecision
    assert config.response_mime_type == "application/json"
    assert len(contents) == 2  # prompt + image part


async def test_tool_calling_returns_args() -> None:
    resp = types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=[
            types.Part(function_call=types.FunctionCall(name="record_agent_decision", args=DECISION))
        ]))]
    )
    fake = FakeClient(resp)
    args = await GeminiService(fake).generate_with_tool("p", RECORD_AGENT_DECISION)
    assert AgentDecision.model_validate(args).action_type.value == "fill"
    assert fake.calls[0][1].tool_config.function_calling_config.allowed_function_names == ["record_agent_decision"]


async def test_text_request() -> None:
    fake = FakeClient(_text_response("hello"))
    assert await GeminiService(fake).generate_text("hi") == "hello"


def test_reason_length_enforced() -> None:
    bad = {**DECISION, "reason": "x" * 500}
    with pytest.raises(Exception):
        AgentDecision.model_validate(bad)


def test_retry_classification() -> None:
    assert _is_retryable(genai_errors.APIError(429, {"error": {"message": "quota"}}))
    assert _is_retryable(genai_errors.APIError(503, {"error": {"message": "down"}}))
    assert not _is_retryable(genai_errors.APIError(400, {"error": {"message": "bad"}}))
    assert not _is_retryable(genai_errors.APIError(401, {"error": {"message": "auth"}}))
    assert _is_retryable(TimeoutError())


async def test_missing_api_key_raises(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "")
    from app.core.config import get_settings

    get_settings.cache_clear()
    try:
        with pytest.raises(GeminiClientError):
            await GeminiClient().generate(["x"], types.GenerateContentConfig())
    finally:
        get_settings.cache_clear()


async def test_retry_on_429_then_success(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    from app.core.config import get_settings

    get_settings.cache_clear()
    client = GeminiClient()
    attempts = {"n": 0}

    class FakeModels:
        async def generate_content(self, **kw):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise genai_errors.APIError(429, {"error": {"message": "rate"}})
            return _text_response("ok")

    class FakeAio:
        models = FakeModels()

    class FakeSDK:
        aio = FakeAio()

    client._client = FakeSDK()
    # avoid real backoff sleeps
    client.generate.retry.wait = lambda *_a, **_k: 0
    resp = await client.generate(["x"], types.GenerateContentConfig())
    assert resp.text == "ok" and attempts["n"] == 3
    get_settings.cache_clear()


def test_ai_test_endpoint(monkeypatch) -> None:
    from app.api import routes_ai
    from app.main import app

    fake = FakeClient(_text_response(json.dumps(DECISION)))
    monkeypatch.setattr(routes_ai, "_service", GeminiService(fake))
    client = TestClient(app)

    r = client.post("/api/ai/test", data={"prompt": "test checkout"},
                    files={"screenshot": ("s.png", io.BytesIO(b"\x89PNG"), "image/png")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["used_image"] is True and body["result"]["reason"] == "Testing invalid checkout input."

    r = client.post("/api/ai/test", data={"prompt": "x"},
                    files={"screenshot": ("s.txt", io.BytesIO(b"hi"), "text/plain")})
    assert r.status_code == 415
