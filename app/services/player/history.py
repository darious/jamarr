import time
import asyncio
import logging
import asyncpg

from app import lastfm
from app.db import get_pool

logger = logging.getLogger(__name__)

# In-memory tracker to avoid duplicate history inserts within a play session.
# Keyed by renderer UDN (for remote) or client_id (for local).
_history_tracker = {}


def reset_history_tracker(key: str):
    if key in _history_tracker:
        del _history_tracker[key]


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

    # Threshold: 30s or 20% of track, whichever is smaller
    if duration and duration > 0:
        threshold = min(30, duration * 0.2)
    else:
        threshold = 30

    if position >= threshold:
        _history_tracker[key] = {"track_id": track_id, "logged_at": time.time()}
        return True
    return False


async def update_now_playing_lastfm(user_id: int, track_id: int):
    """Background task to update Now Playing on Last.fm"""
    try:
        # Get our own database connection from the pool
        pool = get_pool()
        async with pool.acquire() as db:
            # Check if user has Last.fm enabled
            user_row = await db.fetchrow(
                'SELECT lastfm_session_key, lastfm_enabled FROM "user" WHERE id = $1',
                user_id
            )
            
            if not user_row or not user_row['lastfm_enabled'] or not user_row['lastfm_session_key']:
                return
            
            # Fetch track metadata
            track_row = await db.fetchrow(
                """
                SELECT title, artist, album, duration_seconds, artist_mbid
                FROM track
                WHERE id = $1
                """,
                track_id
            )
            
            if not track_row:
                return
            
            # Update Now Playing on Last.fm
            await lastfm.update_now_playing(
                session_key=user_row['lastfm_session_key'],
                track_info={
                    'track': track_row['title'],
                    'artist': track_row['artist'],
                    'album': track_row['album'],
                    'duration': int(track_row['duration_seconds']) if track_row['duration_seconds'] else None,
                    'mbid': track_row['artist_mbid'],
                }
            )
            
            logger.info(f"Updated Now Playing on Last.fm for user {user_id}: {track_row['artist']} - {track_row['title']}")
        
    except Exception as e:
        logger.error(f"Failed to update Now Playing on Last.fm: {e}")


async def scrobble_to_lastfm(user_id: int, track_id: int):
    """Background task to scrobble a track to Last.fm"""
    try:
        # Get our own database connection from the pool
        pool = get_pool()
        async with pool.acquire() as db:
            # Check if user has Last.fm enabled
            user_row = await db.fetchrow(
                'SELECT lastfm_session_key, lastfm_enabled FROM "user" WHERE id = $1',
                user_id
            )
            
            if not user_row or not user_row['lastfm_enabled'] or not user_row['lastfm_session_key']:
                return
            
            # Fetch track metadata
            track_row = await db.fetchrow(
                """
                SELECT title, artist, album, duration_seconds, artist_mbid
                FROM track
                WHERE id = $1
                """,
                track_id
            )
            
            if not track_row:
                return
            
            # Scrobble to Last.fm
            await lastfm.scrobble_track(
                session_key=user_row['lastfm_session_key'],
                track_info={
                    'track': track_row['title'],
                    'artist': track_row['artist'],
                    'album': track_row['album'],
                    'duration': int(track_row['duration_seconds']) if track_row['duration_seconds'] else None,
                    'mbid': track_row['artist_mbid'],
                },
                timestamp=int(time.time())
            )
            
            logger.info(f"Scrobbled track {track_id} to Last.fm for user {user_id}")
        
    except Exception as e:
        logger.error(f"Failed to scrobble to Last.fm: {e}")


async def log_history(
    db: asyncpg.Connection,
    track_id: int,
    client_ip: str,
    client_id: str = None,
    user_id: int = None,
):
    if track_id and track_id > 0:
        try:
            # Guard against immediate duplicate inserts (e.g., dual reporters) within a short window.
            existing = await db.fetchrow(
                """
                SELECT id, client_ip, user_id, client_id, timestamp 
                FROM playback_history 
                WHERE track_id = $1 
                  AND timestamp > NOW() - INTERVAL '5 seconds'
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
                    return
                logger.info(
                    f"Skipping duplicate history log for track {track_id} (recent entry exists)"
                )
                return

            await db.execute(
                "INSERT INTO playback_history (track_id, client_ip, client_id, user_id) VALUES ($1, $2, $3, $4)",
                track_id,
                client_ip,
                client_id,
                user_id,
            )
            
            # Trigger Last.fm scrobble if user has it enabled
            if user_id:
                asyncio.create_task(
                    scrobble_to_lastfm(user_id, track_id)
                )

            # Refresh materialized view to update stats immediately
            await db.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY combined_playback_history_mat")
                
        except Exception as e:
            logger.error(f"Failed to log history: {e}")
