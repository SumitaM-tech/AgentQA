"""Structured logging configuration (structlog), used across the backend.

All modules should `from app.core.logging import get_logger` and log with
key-value fields (session_id=..., step=..., etc.) rather than f-strings,
so agent runs are greppable/queryable in production.
"""
import logging
import sys

import structlog

from app.core.config import get_settings


def configure_logging() -> None:
    settings = get_settings()
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _redact_processor,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer()
            if settings.environment != "development"
            else structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


_SENSITIVE_KEYS = ("password", "passwd", "secret", "token", "cookie", "authorization", "api_key", "apikey", "credential")


def _redact_processor(_logger, _method, event_dict):  # noqa: ANN001, ANN202
    """Last line of defence: scrub secrets from every structured log record."""
    from app.perception.sanitize import redact_secrets

    for key, value in list(event_dict.items()):
        if key in ("event", "level", "timestamp"):
            if isinstance(value, str) and key == "event":
                event_dict[key] = redact_secrets(value)
            continue
        if any(k in key.lower() for k in _SENSITIVE_KEYS):
            event_dict[key] = "[redacted]"
        elif isinstance(value, str):
            event_dict[key] = redact_secrets(value)
    return event_dict


def get_logger(name: str) -> structlog.BoundLogger:
    return structlog.get_logger(name)
