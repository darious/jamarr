import time
import logging
from datetime import datetime, timedelta, timezone

import asyncpg

from app.history_events import refresh_history
from app.listenbrainz_submissions import kick_submissions

logger = logging.getLogger(__name__)

# In-memory tracker to avoid duplicate history inserts within a play session.
# Keyed by renderer UDN (for remote) or client_id (for local).
_history_tracker = {}


def reset_history_tracker(key: str):
    if key in _history_tracker:
        del _history_tracker[key]


def play_threshold_seconds(duration: float | None) -> float:
    """How long a track must play to count: 30s or 20% of it, whichever is smaller."""
    if duration and duration > 0:
        return min(30, duration * 0.2)
    return 30


def should_log_history(
    key: str, track_id: int, position: float, duration: float
) -> bool:
    """
    Decide if we should log history for this renderer/client and track at given position.
    Uses a simple memory guard per key to avoid duplicate logs per track.
    """
    if not track_id:
        return False
    prev = _history_tracker.get(key)
    if prev and prev.get("track_id") == track_id:
        # Already logged this track for this key
        return False

    if position >= play_threshold_seconds(duration):
        _history_tracker[key] = {"track_id": track_id, "logged_at": time.time()}
        return True
    return False


# A duplicate report of the same play lands within this many seconds of the
# first one's start time (two reporters, or one reporting twice).
DUPLICATE_WINDOW_SECONDS = 5


def play_started_at(position_seconds: float | None, now: datetime | None = None) -> datetime:
    """When the play started: the moment it is logged, minus how far into the track it is.

    History, Last.fm and ListenBrainz all record a play at its start time;
    logging only happens once the play threshold (30 s / 20 %) is reached.
    """
    now = now or datetime.now(timezone.utc)
    if not position_seconds or position_seconds < 0:
        return now
    return now - timedelta(seconds=float(position_seconds))


async def log_history(
    db: asyncpg.Connection,
    track_id: int,
    client_ip: str,
    client_id: str = None,
    user_id: int = None,
    position_seconds: float | None = None,
):
    if track_id and track_id > 0:
        try:
            started_at = play_started_at(position_seconds)
            # Guard against duplicate inserts of the same play (e.g. dual reporters).
            existing = await db.fetchrow(
                """
                SELECT id, client_ip, user_id, client_id, timestamp
                FROM playback_history
                WHERE track_id = $1
                  AND timestamp BETWEEN $6::timestamptz - make_interval(secs => $7)
                                    AND $6::timestamptz + make_interval(secs => $7)
                  AND (client_id = $2 OR ($3::text IS NULL AND client_id IS NULL))
                  AND (user_id = $4 OR ($5::integer IS NULL AND user_id IS NULL))
                ORDER BY timestamp DESC
                LIMIT 1
                """,
                track_id,
                client_id,
                client_id,
                user_id,
                user_id,
                started_at,
                float(DUPLICATE_WINDOW_SECONDS),
            )
            if existing:
                (
                    existing_id,
                    existing_ip,
                    existing_user_id,
                    existing_client_id,
                    existing_ts,
                ) = existing
                if (
                    existing_ip == "127.0.0.1"
                    and client_ip
                    and client_ip != "127.0.0.1"
                    and client_ip != "unknown"
                ):
                    logger.info(
                        f"Refining history log {existing_id}: Updating IP to {client_ip}"
                    )
                    await db.execute(
                        "UPDATE playback_history SET client_ip = $1, client_id = $2, user_id = COALESCE(user_id, $3) WHERE id = $4",
                        client_ip,
                        client_id,
                        user_id,
                        existing_id,
                    )
                    if user_id:
                        kick_submissions()
                    return
                logger.info(
                    f"Skipping duplicate history log for track {track_id} (recent entry exists)"
                )
                return

            await db.execute(
                "INSERT INTO playback_history (track_id, timestamp, client_ip, client_id, user_id) VALUES ($1, $2, $3, $4, $5)",
                track_id,
                started_at,
                client_ip,
                client_id,
                user_id,
            )

            # Send it to ListenBrainz if the user has it connected.
            if user_id:
                kick_submissions()

            # Refresh materialized view to update stats immediately
            await refresh_history(db, user_id)
                
        except Exception as e:
            logger.error(f"Failed to log history: {e}")
