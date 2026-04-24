from types import SimpleNamespace

import asyncpg
import pytest

from app.scheduler import Scheduler


class _ReleasedLockConnection:
    async def execute(self, *_args, **_kwargs):
        raise asyncpg.InterfaceError(
            "cannot call Connection.execute(): connection has been released back to the pool"
        )


@pytest.mark.asyncio
async def test_scheduler_stop_tolerates_released_lock_connection(monkeypatch):
    scheduler = Scheduler()
    scheduler._lock_conn = _ReleasedLockConnection()

    pool = SimpleNamespace()

    async def release(_conn):
        raise asyncpg.InterfaceError(
            "cannot call Connection.release(): connection has been released back to the pool"
        )

    pool.release = release
    monkeypatch.setattr("app.scheduler.get_pool", lambda: pool)

    await scheduler.stop()

    assert scheduler._lock_conn is None
