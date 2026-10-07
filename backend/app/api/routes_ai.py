"""POST /api/ai/test — exercises GeminiService (and, in `agent_decision` mode,
the reasoning engine's decision schema) without Playwright.

multipart/form-data: `prompt` (required), `mode` (text|structured|tool|agent_decision,
default structured), `screenshot` (optional image file).
"""
from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.agent.planner import GeminiDecisionModel
from app.agent.prompts import PLANNER_SYSTEM_PROMPT
from app.agent.state import AgentAction
from app.core.logging import get_logger
from app.llm.client import GeminiClientError
from app.llm.prompts import AGENT_DECISION_SYSTEM_PROMPT
from app.llm.schemas import AgentDecision
from app.llm.service import GeminiService
from app.llm.tool_definitions import RECORD_AGENT_DECISION
from app.schemas.ai import AITestMode, AITestResponse

logger = get_logger(__name__)
router = APIRouter(prefix="/api/ai", tags=["ai"])

_ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}
_MAX_IMAGE_BYTES = 5 * 1024 * 1024

_service: GeminiService | None = None


def get_service() -> GeminiService:
    global _service
    if _service is None:
        _service = GeminiService()
    return _service


@router.post("/test", response_model=AITestResponse)
async def ai_test(
    prompt: str = Form(..., min_length=1, max_length=8000),
    mode: AITestMode = Form(AITestMode.STRUCTURED),
    screenshot: UploadFile | None = File(default=None),
) -> AITestResponse:
    image_bytes: bytes | None = None
    mime = "image/png"
    if screenshot is not None:
        if screenshot.content_type not in _ALLOWED_IMAGE_TYPES:
            raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Use PNG, JPEG or WebP.")
        image_bytes = await screenshot.read()
        if len(image_bytes) > _MAX_IMAGE_BYTES:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Image exceeds 5 MB.")
        mime = screenshot.content_type

    service = get_service()
    try:
        if mode == AITestMode.TEXT:
            text = await service.generate_text(prompt, image_bytes=image_bytes, image_mime_type=mime)
            return AITestResponse(model=service.model_name, mode=mode, used_image=bool(image_bytes), text=text)

        if mode == AITestMode.AGENT_DECISION:
            # Exercises the reasoning engine's actual decision schema (app.agent.state.AgentAction)
            # and system prompt — the same path QAAgent's planner uses — WITHOUT the policy layer
            # or a browser. `prompt` should look like a planner prompt (see build_planner_prompt);
            # for a quick smoke test, a plain description of a page + goal also works.
            model = GeminiDecisionModel(service)
            try:
                decision = await model.generate(
                    prompt, system_instruction=PLANNER_SYSTEM_PROMPT, schema=AgentAction, image_bytes=image_bytes
                )
            except Exception as exc:  # noqa: BLE001 - includes schema validation failures
                raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Invalid AgentAction response: {exc}") from exc
            return AITestResponse(model=service.model_name, mode=mode, used_image=bool(image_bytes),
                                  result=decision.model_dump(mode="json"))

        if mode == AITestMode.STRUCTURED:
            decision_ai = await service.generate_structured(
                prompt, AgentDecision, system_instruction=AGENT_DECISION_SYSTEM_PROMPT,
                image_bytes=image_bytes, image_mime_type=mime,
            )
            result = decision_ai.model_dump(mode="json")
        else:
            args = await service.generate_with_tool(
                prompt, RECORD_AGENT_DECISION, system_instruction=AGENT_DECISION_SYSTEM_PROMPT,
                image_bytes=image_bytes, image_mime_type=mime,
            )
            result = AgentDecision.model_validate(args).model_dump(mode="json")
    except GeminiClientError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Invalid model response: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        logger.error("ai_test_failed", error_type=type(exc).__name__)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Gemini request failed. Check logs.") from exc

    return AITestResponse(model=service.model_name, mode=mode, used_image=bool(image_bytes), result=result)
