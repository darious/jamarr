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

        wait_time = 0.0
        async with self._lock:
            now = time.monotonic()
            time_passed = now - self._last_update
            self._last_update = now
            
            # Refill tokens
            self._tokens = min(
                self.burst_limit, 
                self._tokens + (time_passed * self.rate_limit)
            )

            # Consume token
            # If we go negative, that indicates debt (time we must wait)
            # We calculate wait required to get back to 0 (or really, to have 1 available before consumption)
            # Actually simplest Logic:
            # If tokens < 1, we need to wait until we would have 1.
            # Deficit = 1 - tokens
            # Wait = Deficit / Rate
            
            if self._tokens < 1:
                wait_time = (1 - self._tokens) / self.rate_limit
                logger.debug(f"RateLimit hit. Waiting {wait_time:.2f}s (tokens={self._tokens:.2f})")
                
            # Deduct the cost immediately (reserving the slot)
            self._tokens -= 1

        if wait_time > 0:
            await asyncio.sleep(wait_time)

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
