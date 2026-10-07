"""Redis pub/sub publisher for WebSocket session events.

Kept separate from `app/api/routes_ws.py` so the orchestrator — which may
run in a background task, not necessarily sharing a process with a
connected WebSocket — never needs a direct reference to a WebSocket
connection. It only publishes to Redis; any connected client's route
handler subscribes to the same channel and forwards messages verbatim.
"""
from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID

import redis.asyncio as redis

from app.core.config import get_settings

_settings = get_settings()
_redis_client: redis.Redis | None = None


def get_redis_client() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(_settings.redis_url, decode_responses=True)
    return _redis_client


def channel_name(session_id: UUID) -> str:
    return f"session:{session_id}:events"


async def publish_event(session_id: UUID, event_type: str, data: dict) -> None:
    """Publish one event envelope — see routes_ws.py for the full contract
    of `type` values and their `data` payloads."""
    envelope = {
        "type": event_type,
        "session_id": str(session_id),
        "data": data,
        "ts": datetime.utcnow().isoformat() + "Z",
    }
    client = get_redis_client()
    await client.publish(channel_name(session_id), json.dumps(envelope))
