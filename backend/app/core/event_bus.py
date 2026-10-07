"""In-process pub/sub for live run events.

Single-process by design (one uvicorn worker, MAX_CONCURRENT_BROWSERS=1) so a local Core i3
setup needs no Redis. Events are also persisted (RunEvent) so a WebSocket client that
reconnects can replay what it missed. Swap this class for a Redis-backed one to scale out.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any
from uuid import UUID

_QUEUE_SIZE = 500


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[UUID, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)

    def subscribe(self, run_id: UUID) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_QUEUE_SIZE)
        self._subs[run_id].add(q)
        return q

    def unsubscribe(self, run_id: UUID, q: asyncio.Queue) -> None:
        self._subs[run_id].discard(q)
        if not self._subs[run_id]:
            self._subs.pop(run_id, None)

    def publish(self, run_id: UUID, event: dict[str, Any]) -> None:
        for q in list(self._subs.get(run_id, ())):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:  # slow consumer: drop oldest, keep newest
                try:
                    q.get_nowait()
                    q.put_nowait(event)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass

    def subscriber_count(self, run_id: UUID) -> int:
        return len(self._subs.get(run_id, ()))


_bus = EventBus()


def get_event_bus() -> EventBus:
    return _bus
