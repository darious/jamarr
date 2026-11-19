"""Send local plays to ListenBrainz.

The queue is derived, not enqueued: a play is due when its user has
ListenBrainz connected and enabled, it happened at or after
``user.listenbrainz_since``, and ``listenbrainz_submission`` has no row for it
(or a ``retry`` row whose ``next_attempt_at`` has passed). So a play logged by
any path (live, renderer monitor, offline upload) is picked up, plays made
while ListenBrainz is unreachable go out later, and plays made before this
code was deployed are caught up from ``listenbrainz_since``.

``ListenBrainzSubmitter`` runs one background loop per process. Recording a
play calls ``kick()``; a periodic sweep covers anything a kick missed.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app import listenbrainz as lb
from app.db import db_conn

logger = logging.getLogger(__name__)

SWEEP_INTERVAL_SECONDS = 300
# Rows fetched per drain round, across users.
DRAIN_BATCH_ROWS = 500
# Listens per submit request. ListenBrainz allows 1000; smaller batches make a
# rejected batch cheaper to bisect.
LISTENS_PER_REQUEST = 100
RETRY_BASE_SECONDS = 60
RETRY_MAX_SECONDS = 6 * 3600

_TRACK_COLUMNS = """
    t.title, t.artist, t.album, t.track_no, t.duration_seconds,
    t.artist_mbid, t.track_mbid, t.release_mbid, t.release_group_mbid,
    t.release_track_mbid
"""

_DUE_SQL = f"""
    SELECT ph.id AS history_id, ph.user_id, ph."timestamp" AS played_at,
           COALESCE(s.attempts, 0) AS attempts,
           u.listenbrainz_token AS token,
           {_TRACK_COLUMNS}
    FROM playback_history ph
    JOIN "user" u ON u.id = ph.user_id
    JOIN track t ON t.id = ph.track_id
    LEFT JOIN listenbrainz_submission s ON s.playback_history_id = ph.id
    WHERE u.listenbrainz_token IS NOT NULL
      AND u.listenbrainz_enabled
      AND u.listenbrainz_auth_error IS NULL
      AND u.listenbrainz_since IS NOT NULL
      AND ph."timestamp" >= u.listenbrainz_since
      AND (s.playback_history_id IS NULL
           OR (s.status = 'retry' AND s.next_attempt_at <= NOW()))
    ORDER BY ph.user_id, ph."timestamp", ph.id
    LIMIT $1
"""


def retry_delay_seconds(attempts: int) -> float:
    """Backoff after ``attempts`` failed tries: 1 min doubling, capped at 6 h."""
    return float(min(RETRY_MAX_SECONDS, RETRY_BASE_SECONDS * 2 ** max(attempts - 1, 0)))


async def _mark(
    rows: list[dict],
    status: str,
    *,
    error: Optional[str] = None,
    retry_after: Optional[float] = None,
) -> None:
    if not rows:
        return
    now = datetime.now(timezone.utc)
    values = []
    for row in rows:
        attempts = row["attempts"] + 1
        next_attempt = None
        if status == "retry":
            delay = retry_after if retry_after is not None else retry_delay_seconds(attempts)
            next_attempt = now + timedelta(seconds=delay)
        values.append(
            (
                row["history_id"],
                row["user_id"],
                status,
                attempts,
                error,
                next_attempt,
                now if status == "submitted" else None,
            )
        )
    async with db_conn() as db:
        # INSERT ... SELECT so a play deleted mid-send (track removed by a scan)
        # is skipped instead of failing the whole chunk on the foreign key.
        await db.executemany(
            """
            INSERT INTO listenbrainz_submission
                (playback_history_id, user_id, status, attempts, last_error,
                 next_attempt_at, submitted_at, updated_at)
            SELECT $1::bigint, $2::bigint, $3::text, $4::int, $5::text,
                   $6::timestamptz, $7::timestamptz, NOW()
            WHERE EXISTS (SELECT 1 FROM playback_history WHERE id = $1::bigint)
            ON CONFLICT (playback_history_id) DO UPDATE SET
                status = EXCLUDED.status,
                attempts = EXCLUDED.attempts,
                last_error = EXCLUDED.last_error,
                next_attempt_at = EXCLUDED.next_attempt_at,
                submitted_at = EXCLUDED.submitted_at,
                updated_at = NOW()
            """,
            values,
        )


async def _mark_auth_error(user_id: int, token: str, message: str) -> None:
    # Only flag the token that failed: a reconnect may have replaced it already.
    async with db_conn() as db:
        await db.execute(
            """
            UPDATE "user" SET listenbrainz_auth_error = $1
            WHERE id = $2 AND listenbrainz_token = $3
            """,
            message[:500],
            user_id,
            token,
        )


class _StopRound(Exception):
    """Abort the current drain round (rate limited or ListenBrainz down)."""


class ListenBrainzSubmitter:
    _instance: Optional["ListenBrainzSubmitter"] = None

    @classmethod
    def get_instance(cls) -> "ListenBrainzSubmitter":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self, sweep_interval: float = SWEEP_INTERVAL_SECONDS):
        self.sweep_interval = sweep_interval
        self._wake: Optional[asyncio.Event] = None
        self._task: Optional[asyncio.Task] = None
        self._drain_lock = asyncio.Lock()

    def kick(self) -> None:
        """Ask the loop to drain soon. Safe to call from any request handler."""
        if self._wake is not None:
            self._wake.set()

    async def start(self) -> None:
        if self._task is None or self._task.done():
            # Created here, on the loop that runs them, not at import time.
            self._wake = asyncio.Event()
            self._drain_lock = asyncio.Lock()
            self._task = asyncio.create_task(self._run(), name="listenbrainz-submitter")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _next_wait(self) -> float:
        """Sleep until the earliest retry is due, or the sweep, whichever is sooner."""
        try:
            async with db_conn() as db:
                due = await db.fetchval(
                    """
                    SELECT EXTRACT(EPOCH FROM (MIN(next_attempt_at) - NOW()))
                    FROM listenbrainz_submission WHERE status = 'retry'
                    """
                )
        except Exception:
            return self.sweep_interval
        if due is None:
            return self.sweep_interval
        return min(self.sweep_interval, max(float(due), 1.0))

    async def _run(self) -> None:
        assert self._wake is not None
        while True:
            try:
                await self.drain()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("ListenBrainz submission round failed")
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=await self._next_wait())
            except asyncio.TimeoutError:
                pass
            self._wake.clear()

    async def drain(self) -> int:
        """Submit every due play. Returns how many were accepted."""
        async with self._drain_lock:
            accepted = 0
            while True:
                async with db_conn() as db:
                    rows = [dict(r) for r in await db.fetch(_DUE_SQL, DRAIN_BATCH_ROWS)]
                if not rows:
                    return accepted
                try:
                    accepted += await self._submit_rows(rows)
                except _StopRound:
                    return accepted

    async def _submit_rows(self, rows: list[dict]) -> int:
        accepted = 0
        by_user: dict[int, list[dict]] = {}
        for row in rows:
            by_user.setdefault(row["user_id"], []).append(row)
        for user_rows in by_user.values():
            for i in range(0, len(user_rows), LISTENS_PER_REQUEST):
                accepted += await self._submit_chunk(user_rows[i : i + LISTENS_PER_REQUEST])
        return accepted

    async def _submit_chunk(self, rows: list[dict]) -> int:
        listens: list[dict] = []
        sendable: list[dict] = []
        unsendable: list[dict] = []
        for row in rows:
            metadata = lb.build_track_metadata(row)
            if metadata is None:
                unsendable.append(row)
                continue
            listens.append(
                {"listened_at": int(row["played_at"].timestamp()), "track_metadata": metadata}
            )
            sendable.append(row)
        await _mark(unsendable, "rejected", error="track has no artist or title")
        if not sendable:
            return 0

        token = sendable[0]["token"]
        listen_type = "single" if len(listens) == 1 else "import"
        try:
            await lb.get_client().submit_listens(token, listen_type, listens)
        except lb.ListenBrainzAuthError as exc:
            # Leave the rows due; they go out after the user reconnects.
            logger.warning("ListenBrainz rejected the token for user %s", sendable[0]["user_id"])
            await _mark_auth_error(sendable[0]["user_id"], token, str(exc) or "token rejected")
            # End the round so a flag that did not stick cannot loop; other
            # users go on the next kick or sweep.
            raise _StopRound() from exc
        except lb.ListenBrainzRejectedError as exc:
            if len(sendable) == 1:
                logger.warning(
                    "ListenBrainz refused play %s: %s", sendable[0]["history_id"], exc
                )
                await _mark(sendable, "rejected", error=str(exc)[:500])
                return 0
            # One bad listen fails the whole request; split to find it.
            mid = len(sendable) // 2
            return await self._submit_chunk(sendable[:mid]) + await self._submit_chunk(
                sendable[mid:]
            )
        except lb.ListenBrainzRateLimitedError as exc:
            await _mark(sendable, "retry", error=str(exc), retry_after=exc.retry_after)
            raise _StopRound() from exc
        except lb.ListenBrainzError as exc:
            logger.info("ListenBrainz unavailable, will retry: %s", exc)
            await _mark(sendable, "retry", error=str(exc)[:500])
            raise _StopRound() from exc

        await _mark(sendable, "submitted")
        return len(sendable)


async def skip_paused_plays(db, user_id: int) -> int:
    """End a pause: mark plays made while paused as ``skipped`` so they are never sent.

    Plays queued before the pause keep their state and still go out.
    """
    result = await db.execute(
        """
        INSERT INTO listenbrainz_submission (playback_history_id, user_id, status, updated_at)
        SELECT ph.id, ph.user_id, 'skipped', NOW()
        FROM playback_history ph
        JOIN "user" u ON u.id = ph.user_id
        WHERE ph.user_id = $1
          AND u.listenbrainz_paused_at IS NOT NULL
          AND ph."timestamp" >= u.listenbrainz_paused_at
        ON CONFLICT (playback_history_id) DO NOTHING
        """,
        user_id,
    )
    await db.execute(
        'UPDATE "user" SET listenbrainz_paused_at = NULL WHERE id = $1', user_id
    )
    return int(result.split()[-1]) if result else 0


def kick_submissions() -> None:
    ListenBrainzSubmitter.get_instance().kick()


async def update_now_playing_listenbrainz(user_id: Optional[int], track_id: Any) -> None:
    """Best-effort ``playing_now``. Never retried: it is stale within minutes."""
    if not user_id or not track_id:
        return
    try:
        async with db_conn() as db:
            row = await db.fetchrow(
                f"""
                SELECT u.listenbrainz_token AS token, {_TRACK_COLUMNS}
                FROM "user" u, track t
                WHERE u.id = $1 AND t.id = $2
                  AND u.listenbrainz_token IS NOT NULL
                  AND u.listenbrainz_enabled
                  AND u.listenbrainz_auth_error IS NULL
                """,
                user_id,
                int(track_id),
            )
        if row is None:
            return
        metadata = lb.build_track_metadata(dict(row))
        if metadata is None:
            return
        await lb.get_client().submit_listens(
            row["token"], "playing_now", [{"track_metadata": metadata}]
        )
    except Exception as exc:
        logger.debug("ListenBrainz playing_now failed: %s", exc)


async def submission_summary(db, user_id: int) -> dict:
    """Counts for the settings page."""
    row = await db.fetchrow(
        """
        SELECT
            (SELECT COUNT(*) FROM playback_history ph
               LEFT JOIN listenbrainz_submission s ON s.playback_history_id = ph.id
              WHERE ph.user_id = u.id
                AND u.listenbrainz_since IS NOT NULL
                AND ph."timestamp" >= u.listenbrainz_since
                AND (u.listenbrainz_paused_at IS NULL
                     OR ph."timestamp" < u.listenbrainz_paused_at)
                AND (s.playback_history_id IS NULL OR s.status = 'retry')) AS pending,
            (SELECT COUNT(*) FROM listenbrainz_submission s
              WHERE s.user_id = u.id AND s.status = 'submitted') AS submitted,
            (SELECT COUNT(*) FROM listenbrainz_submission s
              WHERE s.user_id = u.id AND s.status = 'rejected') AS rejected,
            (SELECT MAX(submitted_at) FROM listenbrainz_submission s
              WHERE s.user_id = u.id) AS last_submitted_at,
            (SELECT s.last_error FROM listenbrainz_submission s
              WHERE s.user_id = u.id AND s.status = 'retry'
              ORDER BY s.updated_at DESC LIMIT 1) AS last_error
        FROM "user" u WHERE u.id = $1
        """,
        user_id,
    )
    if row is None:
        return {"pending": 0, "submitted": 0, "rejected": 0, "last_submitted_at": None, "last_error": None}
    return {
        "pending": row["pending"],
        "submitted": row["submitted"],
        "rejected": row["rejected"],
        "last_submitted_at": row["last_submitted_at"].isoformat() if row["last_submitted_at"] else None,
        "last_error": row["last_error"],
    }
