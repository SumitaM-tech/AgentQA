"""Live run events over WebSocket.

    WS /ws/runs/{run_id}?after=<seq>

Every message is one JSON event:
    {"seq": 12, "type": "agent_action", "run_id": "...", "message": "Clicking 'Login'",
     "data": {...}, "timestamp": "2026-09-30T10:31:12Z"}

Types: run_started, page_loaded, observation, agent_thinking, agent_action, action_completed,
state_discovered, state_revisited, bug_detected, bug_verified, screenshot_created, error, run_completed.
On connect the server replays persisted events with seq > `after`, then streams live ones, so a
reconnecting client (pass its last seen seq) never misses or duplicates anything. `{"type":"ping"}`
heartbeats are sent while idle. `agent_thinking` never contains private reasoning.
"""
from __future__ import annotations

import asyncio
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.core.event_bus import get_event_bus
from app.core.logging import get_logger
from app.database.session import get_sessionmaker
from app.models.run_event import RunEvent
from app.models.test_run import TestRun

logger = get_logger(__name__)
router = APIRouter(tags=["websocket"])
_HEARTBEAT_S = 20


def _row(e: RunEvent) -> dict:
    return {"seq": e.seq, "type": e.type, "run_id": str(e.test_run_id), "message": e.message, "data": e.data,
            "timestamp": e.timestamp.isoformat() + "Z"}


@router.websocket("/ws/runs/{run_id}")
@router.websocket("/api/sessions/{run_id}/stream")  # legacy path kept for older clients
async def run_stream(websocket: WebSocket, run_id: UUID, after: int = 0) -> None:
    await websocket.accept()
    sm = get_sessionmaker()
    async with sm() as db:
        exists = (await db.execute(select(TestRun.id).where(TestRun.id == run_id))).scalar_one_or_none()
    if exists is None:
        await websocket.close(code=4404, reason="run not found")
        return
    bus = get_event_bus()
    queue = bus.subscribe(run_id)  # subscribe BEFORE replaying so nothing is missed in between
    last = after
    try:
        async with sm() as db:
            rows = (await db.execute(select(RunEvent).where(RunEvent.test_run_id == run_id, RunEvent.seq > after)
                                     .order_by(RunEvent.seq))).scalars().all()
        for e in rows:
            await websocket.send_json(_row(e))
            last = e.seq
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=_HEARTBEAT_S)
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping"})
                continue
            if event["seq"] <= last:
                continue
            await websocket.send_json(event)
            last = event["seq"]
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        bus.unsubscribe(run_id, queue)
        logger.info("ws_disconnected", run_id=str(run_id))
