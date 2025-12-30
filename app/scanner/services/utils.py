import asyncio
import time
import httpx
import logging

logger = logging.getLogger("scanner.services")

class SpotifyRateLimitError(Exception):
    pass


class RateLimiter:
    def __init__(self, rate_limit: float, burst_limit: int = 1):
        self.rate_limit = rate_limit
        self.burst_limit = burst_limit
        self._tokens = burst_limit
        self._last_update = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self):
        if self.rate_limit is None:
            return

        async with self._lock:
            now = time.monotonic()
            time_passed = now - self._last_update
            self._last_update = now
            self._tokens = min(
                self.burst_limit, self._tokens + time_passed * self.rate_limit
            )

            if self._tokens < 1:
                wait_time = (1 - self._tokens) / self.rate_limit
                logger.debug(f"RateLimit hit. Waiting {wait_time:.2f}s (tokens={self._tokens:.2f})")
                await asyncio.sleep(wait_time)
                self._tokens -= 1
                self._last_update = time.monotonic()
            else:
                self._tokens -= 1

def get_client(client: httpx.AsyncClient = None):
    """
    Small helper to reuse a provided client or create/close a new one.
    """
    if client:
        from contextlib import nullcontext
        return nullcontext(client)
    return httpx.AsyncClient(
        headers={"User-Agent": "Jamarr/0.1 ( jamarr@example.com )"},
        timeout=30.0
    )
