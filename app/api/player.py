from fastapi import APIRouter, Depends, Request, HTTPException, Header, Response
import os
import asyncio
from app.db import get_db
import asyncpg
from app.upnp import UPnPManager
import mimetypes
from typing import Dict, Any, List, Optional
from pydantic import BaseModel
import json
import logging
import time
from app.auth import get_session_user

router = APIRouter()
logger = logging.getLogger(__name__)
upnp = UPnPManager.get_instance()

# Global map to track Playback Monitor Tasks (UDN -> Task)
playback_monitors: Dict[str, asyncio.Task] = {}
monitor_start_times: Dict[str, float] = {}  # Track when monitors were last started
# Track when we last started a new track to prevent false "track finished" detection during transitions
last_track_start_time: Dict[str, float] = {}


async def play_next_track_internal(udn: str):
    """Internal helper to advance queue and play next track."""
    async for db in get_db():
        state = await get_renderer_state_db(db, udn)
        queue = state["queue"]
        current_index = state["current_index"]

        next_index = current_index + 1
        if 0 <= next_index < len(queue):
            track = queue[next_index]
            logger.info(
                f"[Player] Auto-advancing to track {next_index}: {track['title']}"
            )

            # Setup UPnP
            # Note: We assume UPnPManager needs active renderer set.
            # This follows the pattern in play_track endpoint.
            await upnp.set_renderer(udn)

            # Use stored IP/Port if possible, or attempt to reconstruct
            # Since this is a background task, accessing request.url is hard.
            # We rely on UPnPManager's existing base_url or reconstruct it.
            # If base_url is missing, art might break.
            upnp.base_url = f"http://{upnp.local_ip}:8111"

            # Check if mime is present, else guess
            if "mime" not in track or not track["mime"]:
                mime, _ = mimetypes.guess_type(track.get("path", ""))
                if not mime:
                    ext = os.path.splitext(track.get("path", ""))[1].lower()
                    if ext == ".flac":
                        mime = "audio/flac"
                    elif ext == ".mp3":
                        mime = "audio/mpeg"
                    elif ext == ".m4a":
                        mime = "audio/mp4"
                    elif ext == ".wav":
                        mime = "audio/wav"
                    elif ext == ".ogg":
                        mime = "audio/ogg"
                    else:
                        mime = "audio/flac"
                track["mime"] = mime

            await upnp.play_track(track["id"], track["path"], track)
            # Record track start time to prevent false "track finished" detection
            last_track_start_time[udn] = time.time()

            # Update DB
            state["current_index"] = next_index
            state["is_playing"] = True
            state["position_seconds"] = 0
            # state['transport_state'] = "PLAYING" # Optimistic
            await update_renderer_state_db(db, udn, state)

            # Remove immediate history logging.
            # We rely on the client (PlayerBar) to log history after 30s threshold to ensure:
            # 1. Correct Client IP/ID is logged.
            # 2. Track is actually listened to (not skipped immediately).
            # await log_history(db, track['id'], "127.0.0.1", "System Auto-Advance")

        else:
            logger.info("[Player] End of queue reached.")
            state["is_playing"] = False
            state["position_seconds"] = 0
            # state['transport_state'] = "STOPPED" # Already stopped
            await update_renderer_state_db(db, udn, state)


async def monitor_upnp_playback(udn: str):
    """Background task to poll UPnP device for position and update DB."""
    logger.info(f"[Player] Starting UPnP monitor for {udn}")

    # Grace period: Wait for device to react to Play command before polling
    # This prevents detecting "STOPPED" immediately after a manual Play/Skip.
    await asyncio.sleep(3)

    was_playing = False  # Initialize to prevent UnboundLocalError
    consecutive_errors = 0
    try:
        while True:
            # 1. Fetch position & transport from UPnP
            try:
                rel_time, _ = await upnp.get_position(udn)
                transport_state = await upnp.get_transport_info(udn)
                consecutive_errors = 0  # Reset on success
            except Exception as e:
                consecutive_errors += 1
                logger.error(
                    f"[Player] Monitor {udn}: Error fetching state (attempt {consecutive_errors}/10): {e}",
                    exc_info=True,
                )
                if consecutive_errors > 10:
                    logger.error(
                        f"[Player] Monitor {udn}: Too many consecutive errors, stopping"
                    )
                    break
                # Use last known values and continue
                await asyncio.sleep(1)
                continue

            # print(f"[Player] Monitor {udn}: {transport_state} @ {rel_time}s")

            # 2. Update DB
            async for db in get_db():
                # What the DB currently thinks (may differ from the device)
                state = await get_renderer_state_db(db, udn)
                was_playing = state["is_playing"]

                # Update live stats from the device
                if transport_state == "PLAYING" and (rel_time is None or rel_time == 0):
                    # Some renderers report 0 at start; keep moving forward based on last known position.
                    rel_time = max(0, state.get("position_seconds", 0) + 1)
                state["position_seconds"] = rel_time
                state["transport_state"] = transport_state
                state["is_playing"] = transport_state not in [
                    "PAUSED_PLAYBACK",
                    "STOPPED",
                    "NO_MEDIA_PRESENT",
                ]

                # Auto-advance logic:
                # If we think we are playing but the device reports STOPPED/NO_MEDIA_PRESENT and position ~0,
                # assume the track finished. Keep this separate from the normal play/pause flow so we do not
                # overwrite queue/volume fields while a user action is in flight.
                if was_playing:
                    if transport_state in ["STOPPED", "NO_MEDIA_PRESENT"]:
                        # Ignore STOPPED if it arrives immediately after a Play/Skip (renderer churn).
                        time_since_start = time.time() - last_track_start_time.get(
                            udn, 0
                        )
                        if time_since_start < 5.0:
                            logger.info(
                                f"[Player] Ignoring STOPPED state during transition (started {time_since_start:.1f}s ago)"
                            )
                            continue
                        logger.info(
                            f"[Player] Track finished detection: State={transport_state}, Expected=Playing"
                        )
                        # Trigger next track outside DB loop; helper opens its own connection.
                    else:
                        # Still playing or paused/buffering. If user paused via remote, sync is_playing to False.
                        if "PAUSE" in transport_state:
                            state["is_playing"] = False

                        # Race Condition Fix: status-only UPDATE so we do not overwrite queue/volume changes
                        # that might have happened via API while this UPnP poll was in flight.
                        await db.execute(
                            """
                            UPDATE renderer_state
                            SET position_seconds = $1, transport_state = $2, is_playing = $3, updated_at = NOW()
                            WHERE renderer_udn = $4
                            """,
                            state["position_seconds"],
                            state["transport_state"],
                            bool(state["is_playing"]),
                            udn,
                        )
                else:
                    # Not previously playing; just persist snapshot of state.
                    await db.execute(
                        """
                        UPDATE renderer_state
                        SET position_seconds = $1, transport_state = $2, is_playing = $3, updated_at = NOW()
                        WHERE renderer_udn = $4
                        """,
                        state["position_seconds"],
                        state["transport_state"],
                        bool(state["is_playing"]),
                        udn,
                    )

                # History logging for remote playback (based on renderer state queue)
                if (
                    state["is_playing"]
                    and state["current_index"] is not None
                    and state["current_index"] >= 0
                ):
                    queue = state.get("queue") or []
                    if 0 <= state["current_index"] < len(queue):
                        track = queue[state["current_index"]]
                        
                        # Only check if not already logged
                        if not track.get("logged", False):
                            track_id = track.get("id")
                            duration = track.get("duration_seconds") or 0
                            
                            # Threshold check
                            threshold = min(30, duration * 0.2) if duration > 0 else 30
                            
                            if rel_time >= threshold:
                                renderer_ip = (
                                    upnp.renderers.get(udn, {}).get("ip")
                                    if upnp.renderers
                                    else None
                                )
                                await log_history(
                                    db,
                                    track_id,
                                    client_ip=renderer_ip or "unknown",
                                    client_id=udn,
                                    user_id=track.get("user_id"),
                                )
                                
                                # Mark logged and persist
                                track["logged"] = True
                                await db.execute(
                                    "UPDATE renderer_state SET queue = $1 WHERE renderer_udn = $2",
                                    json.dumps(queue),
                                    udn,
                                )

            # Execute side effects outside DB context (avoids holding a transaction open)
            if was_playing and transport_state in ["STOPPED", "NO_MEDIA_PRESENT"]:
                await play_next_track_internal(udn)
                await asyncio.sleep(4)  # Give the new track a moment to start

            await asyncio.sleep(1)

    except asyncio.CancelledError:
        logger.info(f"UPnP monitor for {udn} cancelled")
    except Exception as e:
        logger.error(f"UPnP monitor error for {udn}: {e}")
        import traceback

        traceback.print_exc()


# --- Pydantic Models ---


class Track(BaseModel):
    id: int
    title: str
    artist: str
    album: str
    duration_seconds: float
    artwork_id: Optional[int] = None
    art_id: Optional[int] = None
    art_sha1: Optional[str] = None
    codec: Optional[str] = None
    bit_depth: Optional[int] = None
    sample_rate_hz: Optional[int] = None
    path: Optional[str] = None
    album_artist: Optional[str] = None
    track_no: Optional[int] = None
    disc_no: Optional[int] = None
    release_date: Optional[str] = None
    bitrate: Optional[int] = None
    logged: bool = False


class PlayerState(BaseModel):
    queue: List[Track]
    current_index: int
    position_seconds: float
    is_playing: bool
    renderer: str  # UDN
    transport_state: Optional[str] = "STOPPED"
    volume: Optional[int] = None


class QueueUpdate(BaseModel):
    queue: List[Track]
    start_index: int = 0


class AppendQueue(BaseModel):
    tracks: List[Track]


class IndexUpdate(BaseModel):
    index: int


class ProgressUpdate(BaseModel):
    position_seconds: float
    is_playing: bool


class LogPlayRequest(BaseModel):
    track_id: int


# --- Dependencies & Helpers ---


async def get_client_id(x_jamarr_client_id: Optional[str] = Header(None)) -> str:
    if not x_jamarr_client_id:
        # Fallback for old clients or direct API calls?
        return "unknown_client"
    return x_jamarr_client_id


def get_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("X-Forwarded-For") or request.headers.get(
        "x-forwarded-for"
    )
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP") or request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "unknown"


def _track_path_exists(track: Dict[str, Any]) -> bool:
    from app.config import get_music_path

    path = track.get("path")
    if not path:
        return False
    abs_path = path
    if not os.path.isabs(abs_path):
        abs_path = os.path.join(get_music_path(), abs_path)
    return os.path.exists(abs_path)


# ... (skip to enrich function)


async def _enrich_track_metadata(
    track: Dict[str, Any], db: asyncpg.Connection
) -> Dict[str, Any]:
    """Ensure track dict has path, mime, and artwork; fallback to DB lookup."""
    enriched = dict(track)
    # Always try to fetch missing critical fields
    if (
        not enriched.get("path")
        or not enriched.get("mime")
        or not enriched.get("art_sha1")
    ):
        row = await db.fetchrow(
            """
            SELECT t.path, t.codec, t.artwork_id, a.sha1 as art_sha1 
            FROM track t
            LEFT JOIN artwork a ON t.artwork_id = a.id
            WHERE t.id = $1 LIMIT 1
            """,
            enriched.get("id"),
        )
        if row:
            if not enriched.get("path"):
                enriched["path"] = row[0]
            if not enriched.get("artwork_id"):
                enriched["artwork_id"] = row[2]
            if not enriched.get("art_sha1"):
                enriched["art_sha1"] = row[3]
                if not enriched.get("mime"):
                    mime, _ = mimetypes.guess_type(row[0])
                    if not mime:
                        ext = os.path.splitext(row[0])[1].lower()
                        if ext == ".flac":
                            mime = "audio/flac"
                        elif ext == ".mp3":
                            mime = "audio/mpeg"
                        elif ext == ".m4a":
                            mime = "audio/mp4"
                        elif ext == ".wav":
                            mime = "audio/wav"
                        elif ext == ".ogg":
                            mime = "audio/ogg"
                        else:
                            mime = "audio/flac"
                    enriched["mime"] = mime

    # Frontend compat
    if enriched.get("artwork_id") and not enriched.get("art_id"):
        enriched["art_id"] = enriched["artwork_id"]

    return enriched


async def get_active_renderer(db: asyncpg.Connection, client_id: str) -> str:
    """Get active renderer UDN for client. Defaults to local:<client_id>."""
    row = await db.fetchrow(
        "SELECT active_renderer_udn FROM client_session WHERE client_id = $1", client_id
    )
    if row and row[0]:
        return row[0]

    # If no session found, implicitly create one for observability
    default_udn = f"local:{client_id}"
    await db.execute(
        """
        INSERT INTO client_session (client_id, active_renderer_udn, last_seen_at)
        VALUES ($1, $2, NOW())
        ON CONFLICT (client_id) DO NOTHING
    """,
        client_id,
        default_udn,
    )

    return default_udn


async def get_renderer_state_db(db: asyncpg.Connection, udn: str) -> Dict[str, Any]:
    """Get state from DB for a renderer. Returns default if not found."""
    row = await db.fetchrow(
        "SELECT queue, current_index, position_seconds, is_playing, transport_state, volume FROM renderer_state WHERE renderer_udn = $1",
        udn,
    )
    if row:
        try:
            queue = json.loads(row[0])
        except Exception:
            queue = []

        # Backfill missing art_sha1 for legacy queues
        missing_sha1_ids = set()
        for t in queue:
            if t.get("artwork_id") and not t.get("art_sha1"):
                # Use integer conversion for safety
                try:
                    missing_sha1_ids.add(int(t["artwork_id"]))
                except Exception:
                    pass

            if missing_sha1_ids:
                try:
                    placeholders = ",".join("?" for _ in missing_sha1_ids)
                    query = f"SELECT id, sha1 FROM artwork WHERE id IN ({placeholders})"
                    art_rows = await db.fetch(query, list(missing_sha1_ids))
                    art_map = {r[0]: r[1] for r in art_rows}

                    updated = False
                    for t in queue:
                        aid = t.get("artwork_id")
                        if aid and not t.get("art_sha1"):
                            try:
                                aid_int = int(aid)
                                if aid_int in art_map:
                                    t["art_sha1"] = art_map[aid_int]
                                    updated = True
                            except Exception:
                                pass

                    if updated:
                        new_queue_json = json.dumps(queue)
                        await db.execute(
                            "UPDATE renderer_state SET queue = $1 WHERE renderer_udn = $2",
                            new_queue_json,
                            udn,
                        )
                except Exception as e:
                    import logging

                    logging.getLogger(__name__).error(
                        f"[Player] Failed to backfill art_sha1: {e}"
                    )

            # Ensure art_id is present for frontend
            for t in queue:
                if t.get("artwork_id") and not t.get("art_id"):
                    t["art_id"] = t["artwork_id"]

            return {
                "queue": queue,
                "current_index": row[1],
                "position_seconds": row[2],
                "is_playing": bool(row[3]),
                "transport_state": row[4] if len(row) > 4 else "STOPPED",
                "volume": row[5] if len(row) > 5 else None,
            }
    return {
        "queue": [],
        "current_index": -1,
        "position_seconds": 0,
        "is_playing": False,
        "transport_state": "STOPPED",
        "volume": None,
    }


async def update_renderer_state_db(
    db: asyncpg.Connection, udn: str, state: Dict[str, Any]
):
    """Upsert renderer state."""
    queue_json = json.dumps(state.get("queue", []))
    volume = state.get("volume")
    await db.execute(
        """
        INSERT INTO renderer_state (renderer_udn, queue, current_index, position_seconds, is_playing, transport_state, volume, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
        ON CONFLICT(renderer_udn) DO UPDATE SET
            queue = excluded.queue,
            current_index = excluded.current_index,
            position_seconds = excluded.position_seconds,
            is_playing = excluded.is_playing,
            transport_state = excluded.transport_state,
            volume = excluded.volume,
            updated_at = NOW()
    """,
        udn,
        queue_json,
        state.get("current_index", -1),
        state.get("position_seconds", 0),
        bool(state.get("is_playing")),
        state.get("transport_state", "STOPPED"),
        volume,
    )


def _reset_history_tracker(key: str):
    if key in _history_tracker:
        del _history_tracker[key]


def _should_log_history(
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


# In-memory tracker to avoid duplicate history inserts within a play session.
# Keyed by renderer UDN (for remote) or client_id (for local).
_history_tracker = {}


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
        except Exception as e:
            logger.error(f"Failed to log history: {e}")


# --- Endpoints ---


@router.get("/api/client-ip")
async def get_client_ip_endpoint(request: Request):
    return {"ip": get_client_ip(request)}


@router.get("/api/player/history")
async def get_playback_history(
    response: Response,
    scope: str = "all",
    days: int = 7,
    page: int = 1,
    limit: int = 20,
    request: Request = None,
):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    async for db in get_db():
        user_row, _ = (
            await get_session_user(db, request.cookies.get("jamarr_session"))
            if request
            else (None, None)
        )
        # Date filter
        from datetime import timedelta

        # Ensure days is valid
        days = max(1, min(days, 365))
        
        where_clauses = ["DATE(h.timestamp) >= CURRENT_DATE + CAST($1 AS INTERVAL)"]
        params_list = [timedelta(days=-(days - 1))]
        
        if scope == "mine" and user_row:
            where_clauses.append("h.user_id = $2")
            params_list.append(user_row["id"])
            
        where_sql = "WHERE " + " AND ".join(where_clauses)
        
        # Pagination
        page = max(1, page)
        limit = max(1, min(limit, 100))
        offset = (page - 1) * limit
        
        # Add offset/limit to params (adjusting indices)
        # params_list currently has 1 or 2 items
        params_list.append(limit)
        params_list.append(offset)
        
        # Calculate indices for SQL placeholders
        # $1 is duration
        # $2 is user_id (optional)
        # Limit is next, Offset is last
        limit_idx = len(params_list) - 1
        offset_idx = len(params_list)

        query = f"""
            SELECT 
                h.id, h.timestamp, h.client_ip, h.client_id, h.user_id,
                t.id, t.title, t.artist, t.album, t.artwork_id, t.duration_seconds,
                t.codec, t.bit_depth, t.sample_rate_hz, t.release_date,
                u.username, u.display_name, u.email,
                a.sha1 as art_sha1
            FROM playback_history h
            JOIN track t ON h.track_id = t.id
            LEFT JOIN artwork a ON t.artwork_id = a.id
            LEFT JOIN "user" u ON u.id = h.user_id
            {where_sql}
            ORDER BY h.timestamp DESC
            LIMIT ${limit_idx} OFFSET ${offset_idx}
        """
        rows = await db.fetch(query, *params_list)
        history = []
        for row in rows:
            history.append(
                {
                    "id": row[0],
                    "timestamp": row[1],
                    "client_ip": row[2],
                    "client_id": row[3],
                    "user": {
                        "id": row[4],
                        "username": row[15],
                        "display_name": row[16],
                        "email": row[17],
                    }
                    if row[4]
                    else None,
                    "track": {
                        "id": row[5],
                        "title": row[6],
                        "artist": row[7],
                        "album": row[8],
                        "artwork_id": row[9],
                        "art_id": row[9],  # Compat
                        "art_sha1": row[18],  # New standard
                        "duration_seconds": row[10],
                        "codec": row[11],
                        "bit_depth": row[12],
                        "sample_rate_hz": row[13],
                        "release_date": row[14],
                    },
                }
            )
        return history
    return []


@router.get("/api/player/history/stats")
async def get_playback_history_stats(
    response: Response,
    request: Request,
    scope: str = "all",
    days: int = 7,
):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    days = max(1, min(days, 365))

    async for db in get_db():
        user_row, _ = await get_session_user(db, request.cookies.get("jamarr_session"))
        from datetime import timedelta

        where_clauses = ["DATE(timestamp) >= CURRENT_DATE + CAST($1 AS INTERVAL)"]
        params: List[Any] = [timedelta(days=-(days - 1))]
        if scope == "mine" and user_row:
            where_clauses.append("h.user_id = $2")
            params.append(user_row["id"])
        where_sql = " AND ".join(where_clauses)

        # Plays per day
        daily_query = f"""
            SELECT DATE(timestamp) as day, COUNT(*) as plays
            FROM playback_history h
            WHERE {where_sql}
            GROUP BY day
            ORDER BY day DESC
        """
        rows = await db.fetch(daily_query, *params)
        daily = [{"day": row[0], "plays": row[1]} for row in rows]

        # Top artists
        artists_query = f"""
            SELECT 
                COALESCE(NULLIF(t.album_artist, ''), t.artist) as artist_name, 
                MIN(t.artwork_id) as artwork_id, 
                MAX(a.sha1) as art_sha1, 
                COUNT(*) as plays
            FROM playback_history h
            JOIN track t ON t.id = h.track_id
            LEFT JOIN artwork a ON t.artwork_id = a.id
            WHERE {where_sql}
            GROUP BY COALESCE(NULLIF(t.album_artist, ''), t.artist)
            ORDER BY plays DESC
            LIMIT 10
        """
        rows = await db.fetch(artists_query, *params)
        artists = [
            {
                "artist": row[0],
                "artwork_id": row[1],
                "art_id": row[1],
                "art_sha1": row[2],
                "plays": row[3],
            }
            for row in rows
            if row[0]
        ]

        # Top albums
        albums_query = f"""
            SELECT 
                t.album, 
                COALESCE(NULLIF(t.album_artist, ''), t.artist) as artist_name, 
                MIN(t.artwork_id) as artwork_id, 
                MAX(a.sha1) as art_sha1, 
                COUNT(*) as plays
            FROM playback_history h
            JOIN track t ON t.id = h.track_id
            LEFT JOIN artwork a ON t.artwork_id = a.id
                WHERE {where_sql}
                GROUP BY t.album, COALESCE(NULLIF(t.album_artist, ''), t.artist)
                ORDER BY plays DESC
                LIMIT 10
            """
        rows = await db.fetch(albums_query, *params)
        albums = [
            {
                "album": row[0],
                "artist": row[1],
                "artwork_id": row[2],
                "art_id": row[2],
                "art_sha1": row[3],
                "plays": row[4],
            }
            for row in rows
            if row[0]
        ]

        # Top tracks
        tracks_query = f"""
        SELECT t.id, t.title, t.artist, t.album, t.artwork_id, MAX(a.sha1) as art_sha1, COUNT(*) as plays
        FROM playback_history h
        JOIN track t ON t.id = h.track_id
        LEFT JOIN artwork a ON t.artwork_id = a.id
        WHERE {where_sql}
            GROUP BY t.id, t.title, t.artist, t.album, t.artwork_id
            ORDER BY plays DESC
            LIMIT 10
        """
        rows = await db.fetch(tracks_query, *params)
        tracks = [
            {
                "id": row[0],
                "title": row[1],
                "artist": row[2],
                "album": row[3],
                "artwork_id": row[4],
                "art_id": row[4],
                "art_sha1": row[5],
                "plays": row[6],
            }
            for row in rows
        ]

        return {
            "daily": daily,
            "artists": artists,
            "albums": albums,
            "tracks": tracks,
        }
    return {"daily": [], "artists": [], "albums": [], "tracks": []}


@router.get("/api/player/state", response_model=PlayerState)
async def get_player_state(client_id: str = Depends(get_client_id)):
    async for db in get_db():
        udn = await get_active_renderer(db, client_id)
        state = await get_renderer_state_db(db, udn)

        # If UPnP, sync live state
        if udn != f"local:{client_id}" and not udn.startswith("local:"):
            # For UPnP devices, we might want to check if monitor is running
            if state["is_playing"]:
                if udn not in playback_monitors or playback_monitors[udn].done():
                    # Only restart if it's been at least 5 seconds since last start
                    import time

                    now = time.time()
                    last_start = monitor_start_times.get(udn, 0)
                    if now - last_start > 5:
                        logger.info(f"[Player] Auto-restarting monitor for {udn}")
                        playback_monitors[udn] = asyncio.create_task(
                            monitor_upnp_playback(udn)
                        )
                        monitor_start_times[udn] = now

        return {
            "queue": state["queue"],
            "current_index": state["current_index"],
            "position_seconds": state["position_seconds"],
            "is_playing": state["is_playing"],
            "renderer": udn,
            "transport_state": state.get("transport_state", "STOPPED"),
            "volume": state.get("volume"),
        }
    return PlayerState(
        queue=[],
        current_index=-1,
        position_seconds=0,
        is_playing=False,
        renderer=f"local:{client_id}",
    )


@router.post("/api/player/queue")
async def set_queue(
    update: QueueUpdate, request: Request, client_id: str = Depends(get_client_id)
):
    async for db in get_db():
        udn = await get_active_renderer(db, client_id)
        state = await get_renderer_state_db(db, udn)
        user_row, _ = await get_session_user(db, request.cookies.get("jamarr_session"))
        user_id = user_row["id"] if user_row else None

        enriched_queue = []
        for t in update.queue:
            track_dict = t.model_dump()
            if user_id is not None:
                track_dict["user_id"] = user_id
            enriched_queue.append(track_dict)

        state["queue"] = enriched_queue
        state["current_index"] = max(
            0, min(update.start_index, len(enriched_queue) - 1 if enriched_queue else 0)
        )
        state["position_seconds"] = 0
        state["is_playing"] = True
        state["transport_state"] = "PLAYING"

        await update_renderer_state_db(db, udn, state)
        _reset_history_tracker(udn if not udn.startswith("local") else client_id)

        # For UPnP, immediately play the selected track and restart monitor
        if not udn.startswith("local:") and state["queue"]:
            # pick first playable track from start_index onward
            playable_idx = None
            for idx in range(state["current_index"], len(state["queue"])):
                candidate = await _enrich_track_metadata(state["queue"][idx], db)
                if _track_path_exists(candidate):
                    state["queue"][idx] = candidate
                    playable_idx = idx
                    break
            if playable_idx is None:
                raise HTTPException(
                    status_code=404,
                    detail="No playable tracks found on disk for this queue.",
                )
            state["current_index"] = playable_idx
            await update_renderer_state_db(db, udn, state)

            # Cancel existing monitor
            if udn in playback_monitors:
                playback_monitors[udn].cancel()
                try:
                    await asyncio.wait([playback_monitors[udn]], timeout=1)
                except Exception:
                    pass

            # Start playback in background to avoid blocking HTTP response
            async def start_playback():
                await upnp.set_renderer(udn)
                env_port = os.environ.get("HOST_PORT")
                port = env_port if env_port else (request.url.port or 8111)
                upnp.base_url = f"http://{upnp.local_ip}:{port}"
                track = state["queue"][state["current_index"]]
                await upnp.play_track(track["id"], track.get("path"), track)
                playback_monitors[udn] = asyncio.create_task(monitor_upnp_playback(udn))
                import time

                monitor_start_times[udn] = time.time()

            # Start playback in background
            asyncio.create_task(start_playback())

    return {"status": "ok"}


@router.post("/api/player/queue/append")
async def append_queue(
    update: AppendQueue, request: Request, client_id: str = Depends(get_client_id)
):
    async for db in get_db():
        udn = await get_active_renderer(db, client_id)
        state = await get_renderer_state_db(db, udn)
        user_row, _ = await get_session_user(db, request.cookies.get("jamarr_session"))
        user_id = user_row["id"] if user_row else None

        new_tracks = []
        for t in update.tracks:
            track_dict = t.model_dump()
            if user_id is not None:
                track_dict["user_id"] = user_id
            new_tracks.append(track_dict)
        state["queue"] = state["queue"] + new_tracks

        await update_renderer_state_db(db, udn, state)
        _reset_history_tracker(client_id if udn.startswith("local") else udn)
    return {"status": "ok"}


@router.post("/api/player/queue/reorder")
async def reorder_queue(
    update: QueueUpdate, client_id: str = Depends(get_client_id)
):
    """
    Reorder the queue without changing playback state.
    Expects the same queue items in a new order.
    """
    async for db in get_db():
        udn = await get_active_renderer(db, client_id)
        state = await get_renderer_state_db(db, udn)
        existing_queue = state.get("queue") or []

        # Preserve currently playing track (by id) to restore index
        current_idx = state.get("current_index", -1)
        current_track = (
            existing_queue[current_idx] if 0 <= current_idx < len(existing_queue) else None
        )

        # Normalize incoming queue (pydantic models -> dict)
        incoming_queue = [
            t.model_dump() if hasattr(t, "model_dump") else dict(t)
            if hasattr(t, "keys")
            else t
            for t in update.queue
        ]

        # Rebuild queue based on ids, fallback to incoming order if mismatch
        id_to_tracks = {}
        for i, t in enumerate(existing_queue):
            id_to_tracks.setdefault(t.get("id"), []).append((i, t))

        reordered = []
        used = set()
        for incoming in incoming_queue:
            tid = incoming.get("id") if isinstance(incoming, dict) else None
            if tid in id_to_tracks:
                # pop first unused occurrence
                candidates = id_to_tracks[tid]
                chosen = None
                for pos, track in candidates:
                    if pos in used:
                        continue
                    chosen = (pos, track)
                    break
                if chosen:
                    used.add(chosen[0])
                    reordered.append(chosen[1])
                    continue
            # fallback to provided object
            reordered.append(incoming)

        state["queue"] = reordered

        if current_track and current_track.get("id") is not None:
            try:
                new_idx = next(
                    i for i, t in enumerate(reordered) if t.get("id") == current_track["id"]
                )
                state["current_index"] = new_idx
            except StopIteration:
                state["current_index"] = -1
                state["is_playing"] = False
                state["transport_state"] = "STOPPED"

        await update_renderer_state_db(db, udn, state)
        _reset_history_tracker(client_id if udn.startswith("local") else udn)

        return {
            "status": "ok",
            "state": {
                "queue": state["queue"],
                "current_index": state.get("current_index", -1),
                "position_seconds": state.get("position_seconds", 0),
                "is_playing": state.get("is_playing", False),
                "transport_state": state.get("transport_state", "STOPPED"),
                "renderer": udn,
                "volume": state.get("volume"),
            },
        }


@router.post("/api/player/queue/clear")
async def clear_queue(client_id: str = Depends(get_client_id)):
    """
    Empty the active renderer queue and stop playback.
    """
    async for db in get_db():
        udn = await get_active_renderer(db, client_id)
        state = await get_renderer_state_db(db, udn)

        state["queue"] = []
        state["current_index"] = -1
        state["position_seconds"] = 0
        state["is_playing"] = False
        state["transport_state"] = "STOPPED"
        await update_renderer_state_db(db, udn, state)
        _reset_history_tracker(client_id if udn.startswith("local") else udn)

        if not udn.startswith("local:"):
            try:
                await upnp.set_renderer(udn)
                await upnp.pause()
            except Exception as e:
                logger.warning(f"[Player] Failed to pause renderer {udn} on clear: {e}")

            if udn in playback_monitors:
                playback_monitors[udn].cancel()
                try:
                    await asyncio.wait([playback_monitors[udn]], timeout=1)
                except Exception:
                    pass
                del playback_monitors[udn]

        return {
            "status": "ok",
            "state": {
                "queue": state["queue"],
                "current_index": state["current_index"],
                "position_seconds": state["position_seconds"],
                "is_playing": state["is_playing"],
                "transport_state": state.get("transport_state", "STOPPED"),
                "renderer": udn,
                "volume": state.get("volume"),
            },
        }


@router.post("/api/player/index")
async def set_index(update: IndexUpdate, client_id: str = Depends(get_client_id)):
    async for db in get_db():
        udn = await get_active_renderer(db, client_id)
        state = await get_renderer_state_db(db, udn)

        state["current_index"] = update.index
        state["position_seconds"] = 0
        state["is_playing"] = True  # Assume play on skip
        state["transport_state"] = "PLAYING"

        await update_renderer_state_db(db, udn, state)
        _reset_history_tracker(client_id if udn.startswith("local") else udn)

        if not udn.startswith("local:"):
            queue = state.get("queue") or []
            if queue and 0 <= state["current_index"] < len(queue):
                # find next playable track from requested index forward
                playable_idx = None
                for idx in range(state["current_index"], len(queue)):
                    candidate = await _enrich_track_metadata(queue[idx], db)
                    if _track_path_exists(candidate):
                        state["queue"][idx] = candidate
                        playable_idx = idx
                        break
                if playable_idx is None:
                    raise HTTPException(
                        status_code=404, detail="Selected track is missing on disk."
                    )
                state["current_index"] = playable_idx
                await update_renderer_state_db(db, udn, state)

                if udn in playback_monitors:
                    playback_monitors[udn].cancel()
                    try:
                        await asyncio.wait([playback_monitors[udn]], timeout=1)
                    except Exception:
                        pass

                await upnp.set_renderer(udn)
                env_port = os.environ.get("HOST_PORT")
                port = env_port if env_port else 8111
                upnp.base_url = f"http://{upnp.local_ip}:{port}"
                track = state["queue"][state["current_index"]]
                await upnp.play_track(track["id"], track.get("path"), track)
                playback_monitors[udn] = asyncio.create_task(monitor_upnp_playback(udn))
                import time

                monitor_start_times[udn] = time.time()
    # Return the state so the client can sync immediately
    return {
        "status": "ok",
        "state": {
            "queue": state.get("queue", []),
            "current_index": state.get("current_index", -1),
            "position_seconds": state.get("position_seconds", 0),
            "is_playing": state.get("is_playing", False),
            "transport_state": state.get("transport_state", "STOPPED"),
            "renderer": udn,
            "volume": state.get("volume"),
        },
    }


@router.post("/api/player/log-play")
async def log_play(
    update: LogPlayRequest, request: Request, client_id: str = Depends(get_client_id)
):
    """
    Client-initiated logging is now a no-op; history is recorded server-side from
    playback state to avoid double entries. We still return success for backward
    compatibility with older clients.
    """
    return {"status": "ok"}


@router.post("/api/player/progress")
async def update_progress(
    update: ProgressUpdate, request: Request, client_id: str = Depends(get_client_id)
):
    async for db in get_db():
        udn = await get_active_renderer(db, client_id)
        client_ip = get_client_ip(request)
        user_row, _ = await get_session_user(db, request.cookies.get("jamarr_session"))
        user_id = user_row["id"] if user_row else None
        if udn.startswith("local:"):
            state = await get_renderer_state_db(db, udn)
            state["position_seconds"] = update.position_seconds
            state["is_playing"] = update.is_playing

            # Check for history logging
            if state["current_index"] is not None and state["current_index"] >= 0:
                queue = state.get("queue") or []
                if 0 <= state["current_index"] < len(queue):
                    track = queue[state["current_index"]]
                    
                    # Only log if not already logged
                    if not track.get("logged", False):
                        duration = track.get("duration_seconds") or 0
                        # Check threshold (30s or 20%)
                        threshold = min(30, duration * 0.2) if duration > 0 else 30
                        
                        if update.position_seconds >= threshold:
                            # Log it
                            effective_user_id = (
                                user_id if user_id is not None else track.get("user_id")
                            )
                            try:
                                await log_history(
                                    db,
                                    track.get("id"),
                                    client_ip=client_ip,
                                    client_id=client_id,
                                    user_id=effective_user_id,
                                )
                            except Exception as e:
                                logger.error(f"Failed to log history: {e}")
                            
                            # Mark as logged and persist
                            track["logged"] = True
                            # Queue is already ref in state, so just save state
                            await update_renderer_state_db(db, udn, state)
            
            # Save state (position/playing updates)
            await update_renderer_state_db(db, udn, state)
        else:
            # For remote renderers, skip logging here to avoid double-reporting with UPnP monitor
            state = await get_renderer_state_db(db, udn)
    return {"status": "ok"}


@router.get("/api/scan-status")
async def get_scan_status(client_id: str = Depends(get_client_id)):
    return {
        "is_scanning": upnp.is_scanning_subnet,
        "message": upnp.scan_msg,
        "progress": upnp.scan_progress,
        "logs": upnp.debug_log[-20:],
    }


@router.get("/api/renderers")
async def get_renderers(refresh: bool = False, client_id: str = Depends(get_client_id)):
    if refresh:
        await upnp.discover()
        asyncio.create_task(upnp.scan_subnet())
    renderers = await upnp.get_renderers()
    local_device = {
        "udn": f"local:{client_id}",
        "name": "This Device (Web Browser)",
        "type": "local",
    }
    return [local_device, *renderers]


@router.post("/api/player/renderer")
async def set_renderer(data: dict, client_id: str = Depends(get_client_id)):
    udn = data.get("udn")
    if not udn:
        raise HTTPException(status_code=400, detail="Missing udn")

    async for db in get_db():
        await db.execute(
            """
            INSERT INTO client_session (client_id, active_renderer_udn, last_seen_at)
            VALUES ($1, $2, NOW())
            ON CONFLICT(client_id) DO UPDATE SET
                active_renderer_udn = excluded.active_renderer_udn,
                last_seen_at = NOW()
        """,
            client_id,
            udn,
        )
    return {"active": udn}


@router.post("/api/player/play")
async def play_track(
    data: dict,
    request: Request,
    client_id: str = Depends(get_client_id),
    db: asyncpg.Connection = Depends(get_db),
):
    track_id = data.get("track_id")
    if not track_id:
        raise HTTPException(status_code=400, detail="Missing track_id")

    udn = await get_active_renderer(db, client_id)

    # Fetch track metadata
    row = await db.fetchrow(
        "SELECT id, title, artist, album, artwork_id, path, duration_seconds FROM track WHERE id = $1",
        track_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Track not found")
    track = dict(row)
    user_row, _ = await get_session_user(db, request.cookies.get("jamarr_session"))

    # Mime logic
    mime, _ = mimetypes.guess_type(track["path"])
    if not mime:
        ext = os.path.splitext(track["path"])[1].lower()
        if ext == ".flac":
            mime = "audio/flac"
        elif ext == ".mp3":
            mime = "audio/mpeg"
        elif ext == ".m4a":
            mime = "audio/mp4"
        elif ext == ".wav":
            mime = "audio/wav"
        elif ext == ".ogg":
            mime = "audio/ogg"
        else:
            mime = "audio/flac"
    track["mime"] = mime
    if user_row:
        track["user_id"] = user_row["id"]

    is_local = udn.startswith("local:") or udn == "local"

    if not is_local:
        # UPnP Playback
        await upnp.set_renderer(udn)

        env_port = os.environ.get("HOST_PORT")
        port = env_port if env_port else (request.url.port or 8111)
        upnp.base_url = f"http://{upnp.local_ip}:{port}"

        state = await get_renderer_state_db(db, udn)

        # Check if this track is already playing
        current_track = None
        if state.get("current_index") is not None and state.get("queue"):
            queue = state["queue"]
            if 0 <= state["current_index"] < len(queue):
                current_track = queue[state["current_index"]]

        # If the same track is already playing, just resume if paused
        if (
            current_track
            and current_track.get("id") == track["id"]
            and state.get("is_playing")
        ):
            logger.info(
                f"Track {track_id} is already playing, ignoring duplicate play request"
            )
            return {"status": "already_playing", "renderer": udn}

        # If paused, just resume
        if (
            current_track
            and current_track.get("id") == track["id"]
            and not state.get("is_playing")
        ):
            logger.info(f"Resuming track {track_id}")
            await upnp.play()
            state["is_playing"] = True
            state["transport_state"] = "PLAYING"
            await update_renderer_state_db(db, udn, state)
            return {"status": "resumed", "renderer": udn}

        # Different track or no track playing - start new playback
        # Try to keep the existing queue if this track is in it; otherwise replace with single track
        existing_queue = state.get("queue") or []
        try:
            current_index = next(
                i for i, t in enumerate(existing_queue) if t.get("id") == track["id"]
            )
        except StopIteration:
            existing_queue = [track]
            current_index = 0

        state["queue"] = existing_queue
        state["current_index"] = current_index
        state["position_seconds"] = 0
        state["is_playing"] = True
        state["transport_state"] = "PLAYING"
        await update_renderer_state_db(db, udn, state)
        _reset_history_tracker(udn)

        # Stop existing monitor cleanly
        if udn in playback_monitors:
            playback_monitors[udn].cancel()
            try:
                await asyncio.wait([playback_monitors[udn]], timeout=1)
            except Exception:
                pass

        await upnp.play_track(track["id"], track["path"], track)

        # Start fresh monitor (only for UPnP)
        playback_monitors[udn] = asyncio.create_task(monitor_upnp_playback(udn))
        import time

        monitor_start_times[udn] = time.time()

        return {"status": "streaming_started", "renderer": udn}
    else:
        state = await get_renderer_state_db(db, udn)
        existing_queue = state.get("queue") or []
        try:
            current_index = next(
                i for i, t in enumerate(existing_queue) if t.get("id") == track["id"]
            )
        except StopIteration:
            existing_queue = [track]
            current_index = 0

        state["queue"] = existing_queue
        state["current_index"] = current_index
        state["position_seconds"] = 0
        state["is_playing"] = True
        state["transport_state"] = "PLAYING"
        await update_renderer_state_db(db, udn, state)

        return {"status": "local_playback", "message": "Handle playback in browser"}


@router.post("/api/player/pause")
async def pause_playback(client_id: str = Depends(get_client_id)):
    async for db in get_db():
        udn = await get_active_renderer(db, client_id)

        state = await get_renderer_state_db(db, udn)
        state["is_playing"] = False
        await update_renderer_state_db(db, udn, state)

        if not udn.startswith("local:"):
            await upnp.set_renderer(udn)
            await upnp.pause()

            if udn in playback_monitors:
                playback_monitors[udn].cancel()
                del playback_monitors[udn]

        return {"status": "ok"}


@router.post("/api/player/resume")
async def resume_playback(client_id: str = Depends(get_client_id)):
    async for db in get_db():
        udn = await get_active_renderer(db, client_id)

        state = await get_renderer_state_db(db, udn)
        state["is_playing"] = True
        await update_renderer_state_db(db, udn, state)

        if not udn.startswith("local:"):
            await upnp.set_renderer(udn)
            await upnp.resume()

            if udn not in playback_monitors or playback_monitors[udn].done():
                playback_monitors[udn] = asyncio.create_task(monitor_upnp_playback(udn))
                import time

                monitor_start_times[udn] = time.time()

    return {"status": "ok"}


@router.post("/api/player/volume")
async def set_volume(data: dict, client_id: str = Depends(get_client_id)):
    percent = data.get("percent")
    if percent is None:
        raise HTTPException(status_code=400, detail="Missing percent")
    percent = max(0, min(100, int(percent)))

    async for db in get_db():
        udn = await get_active_renderer(db, client_id)

        # Persist volume
        state = await get_renderer_state_db(db, udn)
        state["volume"] = percent
        await update_renderer_state_db(db, udn, state)

        if not udn.startswith("local:"):
            await upnp.set_renderer(udn)
            await upnp.set_volume(percent)

    return {"status": "ok", "percent": percent}


@router.post("/api/player/seek")
async def seek_track(data: dict, client_id: str = Depends(get_client_id)):
    seconds = data.get("seconds")
    if seconds is None:
        raise HTTPException(status_code=400, detail="Missing seconds")

    async for db in get_db():
        udn = await get_active_renderer(db, client_id)

        state = await get_renderer_state_db(db, udn)
        state["position_seconds"] = float(seconds)
        await update_renderer_state_db(db, udn, state)

        if not udn.startswith("local:"):
            await upnp.set_renderer(udn)
            await upnp.seek(float(seconds))
            return {"status": "ok", "target": seconds}
        else:
            return {"status": "local", "message": "Handle seek in browser"}


# Re-expose Debug/Manual Added endpoints
@router.get("/api/player/debug")
async def debug_info():
    return {
        "log": upnp.debug_log,
        "renderers": upnp.renderers,
        "local_ip": upnp.local_ip,
    }


@router.post("/api/player/add_manual")
async def add_manual_renderer(data: dict):
    ip = data.get("ip")
    if not ip:
        raise HTTPException(status_code=400, detail="Missing ip")
    found = await upnp.add_device_by_ip(ip)
    if found:
        return {"status": "found"}
    else:
        raise HTTPException(status_code=404, detail="Device not found at IP")


@router.get("/api/player/test_upnp")
async def test_upnp():
    if not upnp.active_renderer:
        return {"error": "No active renderer"}
    return {"status": "ok", "message": "Check debug logs"}
