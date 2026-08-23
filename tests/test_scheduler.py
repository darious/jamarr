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


@pytest.mark.asyncio
async def test_audio_analysis_job_runs_every_phase(monkeypatch):
    from app import scheduler as scheduler_module

    job = scheduler_module.JOB_DEFINITIONS["audio_analysis"]
    calls = []
    captured_kwargs = {}

    class _FakeRunner:
        def __init__(self, **kwargs):
            captured_kwargs.update(kwargs)

        def _phase(self, phase):
            async def run():
                calls.append(phase)
                kwargs["progress_cb"] = captured_kwargs.get("progress_cb")
                return {"selected": 0}

            return run

        def __getattr__(self, name):
            if name.startswith("run_phase"):
                return self._phase(name.removeprefix("run_phase"))
            raise AttributeError(name)

    kwargs = {}
    monkeypatch.setattr(scheduler_module, "AudioAnalysisRunner", _FakeRunner)
    monkeypatch.setattr(
        scheduler_module, "get_audio_analysis_settings", lambda: {"concurrency": 4}
    )

    await job.runner()

    assert calls == ["1", "2", "3", "4"]
    assert captured_kwargs["concurrency"] == 4
    assert callable(captured_kwargs["progress_cb"])
