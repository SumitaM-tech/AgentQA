"""Low-level async wrapper over the `google-genai` SDK (`genai.Client`,
`client.aio.models.generate_content`). Handles retry (429 + 5xx with
exponential backoff), request timeout, and logging that never includes
the API key. Prompt/schema logic lives in `service.py`.
"""
from __future__ import annotations

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class GeminiClientError(RuntimeError):
    """Misconfiguration (e.g. missing API key)."""


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, genai_errors.APIError):
        code = exc.code
        return code == 429 or (code is not None and 500 <= int(code) < 600)
    return isinstance(exc, (TimeoutError, ConnectionError))


class GeminiClient:
    def __init__(self) -> None:
        settings = get_settings()
        self._model_name = settings.gemini_model
        self._api_key = settings.gemini_api_key
        self._timeout_seconds = settings.gemini_request_timeout_seconds
        self._client: genai.Client | None = None

    @property
    def model_name(self) -> str:
        return self._model_name

    def _ensure_client(self) -> genai.Client:
        if self._client is None:
            if not self._api_key:
                raise GeminiClientError(
                    "GEMINI_API_KEY is not set. Create backend/.env from .env.example and set it."
                )
            self._client = genai.Client(
                api_key=self._api_key,
                http_options=types.HttpOptions(timeout=self._timeout_seconds * 1000),  # ms
            )
            logger.info("gemini_client_initialized", model=self._model_name, api_key_configured=True)
        return self._client

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=2, max=20),
        reraise=True,
    )
    async def generate(
        self, contents: list, config: types.GenerateContentConfig
    ) -> types.GenerateContentResponse:
        client = self._ensure_client()
        if config.temperature is None:
            config.temperature = get_settings().gemini_temperature
        logger.info(
            "gemini_request_started",
            model=self._model_name,
            parts=len(contents),
            tools=bool(config.tools),
            structured=bool(config.response_schema),
        )
        try:
            response = await client.aio.models.generate_content(
                model=self._model_name, contents=contents, config=config
            )
        except genai_errors.APIError as exc:
            if exc.code == 429:
                logger.warning("gemini_rate_limited", model=self._model_name)
            else:
                logger.error("gemini_request_failed", model=self._model_name, code=exc.code)
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("gemini_request_failed", model=self._model_name, error_type=type(exc).__name__)
            raise

        usage = response.usage_metadata
        logger.info(
            "gemini_request_succeeded",
            model=self._model_name,
            input_tokens=getattr(usage, "prompt_token_count", None),
            output_tokens=getattr(usage, "candidates_token_count", None),
        )
        return response
