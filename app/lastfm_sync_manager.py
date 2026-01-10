import asyncio
import time
from typing import Any, Dict


class LastfmSyncManager:
    _instance = None

    @classmethod
    def get_instance(cls) -> "LastfmSyncManager":
        if cls._instance is None:
            cls._instance = LastfmSyncManager()
        return cls._instance

    def __init__(self) -> None:
        self._event_queues: set[asyncio.Queue] = set()
        self._status = "Idle"

    async def subscribe(self):
        queue: asyncio.Queue = asyncio.Queue()
        self._event_queues.add(queue)
        try:
            yield {"type": "status", "status": self._status}
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield event
        finally:
            self._event_queues.remove(queue)

    def _broadcast(self, event: Dict[str, Any]) -> None:
        for queue in self._event_queues:
            queue.put_nowait(event)

    def start_sync(self) -> None:
        self._status = "Running"
        self._broadcast({"type": "start"})

    def complete_sync(self, status: str, error: str | None = None) -> None:
        self._status = "Idle"
        payload: Dict[str, Any] = {"type": "complete", "status": status}
        if error:
            payload["error"] = error
        self._broadcast(payload)

    def log_message(self, message: str) -> None:
        self._broadcast({"type": "log", "message": message, "timestamp": time.time()})
