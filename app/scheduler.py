import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

import asyncpg
from croniter import croniter

from app.db import get_pool
from app.scanner.scan_manager import ScanManager
from app.charts import refresh_chart_task
from app.lastfm_jobs import sync_all_lastfm_scrobbles


logger = logging.getLogger(__name__)

LOCK_KEY = 912337
POLL_INTERVAL_SECONDS = 30


JobRunner = Callable[[], Awaitable[None]]


@dataclass(frozen=True)
class JobDefinition:
    key: str
    name: str
    description: str
    runner: JobRunner


async def _run_full_scan() -> None:
    manager = ScanManager.get_instance()
    task = await manager.start_full(
        force=False,
        missing_only=True,
        fetch_metadata=True,
        fetch_bio=True,
        fetch_artwork=True,
        fetch_spotify_artwork=True,
        fetch_links=True,
        refresh_top_tracks=True,
        refresh_singles=True,
        fetch_similar_artists=True,
        fetch_album_metadata=True,
        prune=True,
    )
    await task


async def _run_missing_albums() -> None:
    manager = ScanManager.get_instance()
    task = await manager.start_missing_albums_scan()
    await task


async def _run_refresh_artists() -> None:
    manager = ScanManager.get_instance()
    task = await manager.start_metadata_update(
        path=None,
        artist_filter=None,
        mbid_filter=None,
        missing_only=False,
        bio_only=True,
        refresh_top_tracks=True,
        refresh_singles=True,
        fetch_metadata=False,
        fetch_bio=True,
        fetch_artwork=False,
        fetch_spotify_artwork=False,
        fetch_links=False,
        fetch_similar_artists=True,
        fetch_album_metadata=False,
    )
    await task


async def _run_refresh_chart() -> None:
    await refresh_chart_task()


async def _run_lastfm_sync() -> None:
    await sync_all_lastfm_scrobbles()


JOB_DEFINITIONS: Dict[str, JobDefinition] = {
    "library_full_scan": JobDefinition(
        key="library_full_scan",
        name="Library Scan (Full)",
        description="Run a full library scan with metadata refresh.",
        runner=_run_full_scan,
    ),
    "library_missing_albums": JobDefinition(
        key="library_missing_albums",
        name="Missing Albums Scan",
        description="Find missing albums for artists in your library.",
        runner=_run_missing_albums,
    ),
    "library_refresh_artists": JobDefinition(
        key="library_refresh_artists",
        name="Refresh Artists",
        description="Refresh bios, top tracks, singles, and similar artists.",
        runner=_run_refresh_artists,
    ),
    "charts_refresh": JobDefinition(
        key="charts_refresh",
        name="Refresh Chart",
        description="Refresh the charts list from the Charts page.",
        runner=_run_refresh_chart,
    ),
    "lastfm_sync": JobDefinition(
        key="lastfm_sync",
        name="Update Scrobbles + Match",
        description="Fetch new Last.fm scrobbles and match them to your library.",
        runner=_run_lastfm_sync,
    ),
}


def get_job_definitions() -> List[Dict[str, str]]:
    return [
        {"key": job.key, "name": job.name, "description": job.description}
        for job in JOB_DEFINITIONS.values()
    ]


def _compute_next_run(cron: str, base_time: datetime) -> datetime:
    return croniter(cron, base_time).get_next(datetime)


class Scheduler:
    _instance: Optional["Scheduler"] = None

    @classmethod
    def get_instance(cls) -> "Scheduler":
        if cls._instance is None:
            cls._instance = Scheduler()
        return cls._instance

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._running_ids: set[int] = set()
        self._running_tasks: dict[int, asyncio.Task] = {}
        self._lock_conn = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        pool = get_pool()
        self._lock_conn = await pool.acquire()
        locked = await self._lock_conn.fetchval(
            "SELECT pg_try_advisory_lock($1)", LOCK_KEY
        )
        if not locked:
            await pool.release(self._lock_conn)
            self._lock_conn = None
            logger.warning("Scheduler lock already held; skipping start.")
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Scheduler started.")

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._stop_event.set()
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._lock_conn:
            try:
                await self._lock_conn.execute(
                    "SELECT pg_advisory_unlock($1)", LOCK_KEY
                )
            except asyncpg.InterfaceError:
                logger.warning(
                    "Scheduler lock connection was already released before unlock."
                )
            finally:
                try:
                    await get_pool().release(self._lock_conn)
                except asyncpg.InterfaceError:
                    pass
                self._lock_conn = None
        logger.info("Scheduler stopped.")

    def is_running(self, task_id: int) -> bool:
        return task_id in self._running_ids

    async def run_task_now(self, task_id: int) -> bool:
        pool = get_pool()
        async with pool.acquire() as conn:
            task = await conn.fetchrow(
                "SELECT * FROM scheduled_task WHERE id = $1", task_id
            )
        if not task:
            return False
        if task_id in self._running_ids:
            return False
        self._running_ids.add(task_id)
        task_handle = asyncio.create_task(self._run_task(task))
        self._running_tasks[task_id] = task_handle
        task_handle.add_done_callback(lambda _: self._running_tasks.pop(task_id, None))
        return True

    async def stop_task(self, task_id: int) -> bool:
        task_handle = self._running_tasks.get(task_id)
        if not task_handle:
            return False
        try:
            pool = get_pool()
            async with pool.acquire() as conn:
                job_key = await conn.fetchval(
                    "SELECT job_key FROM scheduled_task WHERE id = $1", task_id
                )
            if job_key in {"library_full_scan", "library_missing_albums", "library_refresh_artists"}:
                await ScanManager.get_instance().stop_scan()
        finally:
            task_handle.cancel()
        return True

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self._ensure_next_runs()
                await self._run_due_tasks()
            except Exception:
                logger.exception("Scheduler loop error")
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def _ensure_next_runs(self) -> None:
        now = datetime.now(timezone.utc)
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, cron
                FROM scheduled_task
                WHERE enabled = TRUE AND next_run_at IS NULL
                """
            )
            for row in rows:
                next_run = _compute_next_run(row["cron"], now)
                await conn.execute(
                    """
                    UPDATE scheduled_task
                    SET next_run_at = $1, updated_at = NOW()
                    WHERE id = $2
                    """,
                    next_run,
                    row["id"],
                )

    async def _run_due_tasks(self) -> None:
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT *
                FROM scheduled_task
                WHERE enabled = TRUE
                  AND next_run_at IS NOT NULL
                  AND next_run_at <= NOW()
                ORDER BY next_run_at ASC, id ASC
                """
            )
        for row in rows:
            task_id = row["id"]
            if task_id in self._running_ids:
                continue
            self._running_ids.add(task_id)
            task_handle = asyncio.create_task(self._run_task(row))
            self._running_tasks[task_id] = task_handle
            task_handle.add_done_callback(lambda _: self._running_tasks.pop(task_id, None))

    async def _run_task(self, task: Any) -> None:
        task_id = task["id"]
        job_key = task["job_key"]
        job = JOB_DEFINITIONS.get(job_key)
        if not job:
            await self._finalize_task(
                task_id, "error", f"Unknown job key: {job_key}"
            )
            return
        start_time = datetime.now(timezone.utc)
        pool = get_pool()
        run_id = None
        try:
            async with pool.acquire() as conn:
                run_id = await conn.fetchval(
                    """
                    INSERT INTO scheduled_task_run (task_id, started_at, status)
                    VALUES ($1, $2, $3)
                    RETURNING id
                    """,
                    task_id,
                    start_time,
                    "running",
                )
                await conn.execute(
                    """
                    UPDATE scheduled_task
                    SET last_run_at = $1,
                        last_status = $2,
                        last_error = NULL,
                        updated_at = NOW()
                    WHERE id = $3
                    """,
                    start_time,
                    "running",
                    task_id,
                )
            await job.runner()
            await self._finalize_task(task_id, "success", None, run_id, start_time)
        except asyncio.CancelledError:
            await self._finalize_task(
                task_id, "cancelled", "Cancelled", run_id, start_time
            )
            return
        except RuntimeError as exc:
            status = "skipped" if "Busy" in str(exc) or "Scan already" in str(exc) else "error"
            await self._finalize_task(
                task_id, status, str(exc), run_id, start_time
            )
        except Exception as exc:
            await self._finalize_task(
                task_id, "error", str(exc), run_id, start_time
            )
        finally:
            self._running_ids.discard(task_id)

    async def _finalize_task(
        self,
        task_id: int,
        status: str,
        error: Optional[str],
        run_id: Optional[int] = None,
        start_time: Optional[datetime] = None,
    ) -> None:
        finish_time = datetime.now(timezone.utc)
        duration_ms = None
        if start_time:
            duration_ms = int((finish_time - start_time).total_seconds() * 1000)
        next_run = None
        pool = get_pool()
        async with pool.acquire() as conn:
            cron = await conn.fetchval(
                "SELECT cron FROM scheduled_task WHERE id = $1", task_id
            )
            if cron:
                next_run = _compute_next_run(cron, finish_time)
            await conn.execute(
                """
                UPDATE scheduled_task
                SET last_status = $1,
                    last_error = $2,
                    next_run_at = $3,
                    updated_at = NOW()
                WHERE id = $4
                """,
                status,
                error,
                next_run,
                task_id,
            )
            if run_id:
                await conn.execute(
                    """
                    UPDATE scheduled_task_run
                    SET finished_at = $1,
                        status = $2,
                        error = $3,
                        duration_ms = $4
                    WHERE id = $5
                    """,
                    finish_time,
                    status,
                    error,
                    duration_ms,
                    run_id,
                )
