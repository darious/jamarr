"""Tells open history pages that the play history changed.

Every write to ``playback_history`` (live plays, offline uploads, Last.fm
syncs) ends with a refresh of ``combined_playback_history_mat``, which is what
the history endpoints read. :func:`refresh_history` does that refresh and then
publishes, so a subscriber that re-reads on an event always sees the new rows.
"""

import asyncio
from typing import Any, AsyncGenerator

import asyncpg

from app.sse import HEARTBEAT, SSE_HEARTBEAT_SECONDS


class HistoryEvents:
    _instance: "HistoryEvents | None" = None

    @classmethod
    def get_instance(cls) -> "HistoryEvents":
        if cls._instance is None:
            cls._instance = HistoryEvents()
        return cls._instance

    def __init__(self) -> None:
        self._queues: set[asyncio.Queue] = set()

    async def subscribe(self) -> AsyncGenerator[Any, None]:
        """Yield ``{"user_id": ...}`` per change, or HEARTBEAT when idle."""
        queue: asyncio.Queue = asyncio.Queue()
        self._queues.add(queue)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(
                        queue.get(), timeout=SSE_HEARTBEAT_SECONDS
                    )
                except asyncio.TimeoutError:
                    yield HEARTBEAT
                    continue
                if event is None:
                    break
                yield event
        finally:
            self._queues.discard(queue)

    def publish(self, user_id: int | None) -> None:
        """Announce that ``user_id``'s history changed (None: no owning user)."""
        for queue in self._queues:
            queue.put_nowait({"user_id": user_id})


async def refresh_history(db: asyncpg.Connection, user_id: int | None) -> None:
    """Refresh the history view, then tell subscribers it changed."""
    await db.execute(
        "REFRESH MATERIALIZED VIEW CONCURRENTLY combined_playback_history_mat"
    )
    HistoryEvents.get_instance().publish(user_id)
