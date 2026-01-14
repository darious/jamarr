from fastapi import APIRouter, Depends, Request, HTTPException, Header
import os
import asyncio
import mimetypes
import logging
import time
from typing import Optional
import asyncpg
from app.db import get_db
from app.upnp import UPnPManager
from app.api.deps import get_optional_user_jwt

from app.models.player import (
    PlayerState,
    QueueUpdate,
    AppendQueue,
    IndexUpdate,
    ProgressUpdate,
    LogPlayRequest,
)
from app.services.player.globals import (
    playback_monitors,
    monitor_start_times,
    last_track_start_time,
)
from app.services.player.state import (
    track_path_exists,
    enrich_track_metadata,
    get_active_renderer,
    get_renderer_state_db,
    update_renderer_state_db,
)
from app.services.player.history import (
    log_history,
    reset_history_tracker,
    update_now_playing_lastfm,
)
from app.services.player.monitor import (
    monitor_upnp_playback,
    start_monitor_task,
    _mark_monitor_starting,
    _clear_monitor_starting,
    _is_monitor_starting,
)

router = APIRouter()
logger = logging.getLogger(__name__)
upnp = UPnPManager.get_instance()


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


@router.get("/api/client-ip")
async def get_client_ip_endpoint(request: Request):
    return {"ip": get_client_ip(request)}


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
                    now = time.time()
                    last_start = monitor_start_times.get(udn, 0)
                    if now - last_start > 5 and not _is_monitor_starting(udn):
                        logger.info(f"[Player] Auto-restarting monitor for {udn}")
                        start_monitor_task(udn)

        queue = state["queue"]
        track_ids = [
            t.get("id") for t in queue if isinstance(t, dict) and t.get("id")
        ]
        if track_ids:
            # 1. Fetch Plays
            plays_rows = await db.fetch(
                """
                SELECT h.track_id, COUNT(*) as plays
                FROM combined_playback_history_mat h
                WHERE h.track_id = ANY($1::bigint[])
                GROUP BY h.track_id
                """,
                track_ids,
            )
            plays_map = {row["track_id"]: row["plays"] for row in plays_rows}

            # 2. Fetch missing Art/Path/Mime
            needs_enrich = False
            for t in queue:
                if isinstance(t, dict):
                     if not t.get("art_sha1") or not t.get("path"):
                         needs_enrich = True
                         break
            
            meta_map = {}
            if needs_enrich:
                meta_rows = await db.fetch(
                    """
                    SELECT t.id, t.path, t.codec, a.sha1 as art_sha1
                    FROM track t
                    LEFT JOIN artwork a ON t.artwork_id = a.id
                    WHERE t.id = ANY($1::bigint[])
                    """,
                    track_ids
                )
                meta_map = {
                    r["id"]: {
                        "path": r["path"], 
                        "art_sha1": r["art_sha1"], 
                        "codec": r["codec"]
                    } 
                    for r in meta_rows
                }

            # 3. Apply updates
            for t in queue:
                if isinstance(t, dict) and t.get("id"):
                    tid = t["id"]
                    
                    # Apply plays
                    if "plays" not in t:
                        t["plays"] = plays_map.get(tid, 0)
                    
                    # Apply Meta
                    if needs_enrich and tid in meta_map:
                        meta = meta_map[tid]
                        if not t.get("art_sha1"):
                            t["art_sha1"] = meta["art_sha1"]
                        if not t.get("path"):
                            t["path"] = meta["path"]
                        if not t.get("codec"):
                            t["codec"] = meta["codec"]
                        
                        # Guess mime if missing and path exists
                        if not t.get("mime") and t.get("path"):
                            mime, _ = mimetypes.guess_type(t["path"])
                            if not mime:
                                ext = os.path.splitext(t["path"])[1].lower()
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
                            t["mime"] = mime

        return {
            "queue": queue,
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
    update: QueueUpdate,
    request: Request,
    client_id: str = Depends(get_client_id),
    user: asyncpg.Record | None = Depends(get_optional_user_jwt),
):
    async for db in get_db():
        udn = await get_active_renderer(db, client_id)
        state = await get_renderer_state_db(db, udn)
        user_id = user["id"] if user else None

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
        reset_history_tracker(udn if not udn.startswith("local") else client_id)
        
        # Trigger Now Playing update for Last.fm
        if user_id and enriched_queue and state["current_index"] >= 0:
            current_track = enriched_queue[state["current_index"]]
            asyncio.create_task(
                update_now_playing_lastfm(user_id, current_track["id"])
            )

        # For UPnP, immediately play the selected track and restart monitor
        if not udn.startswith("local:") and state["queue"]:
            # pick first playable track from start_index onward
            playable_idx = None
            for idx in range(state["current_index"], len(state["queue"])):
                candidate = await enrich_track_metadata(state["queue"][idx], db)
                if track_path_exists(candidate):
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
                try:
                    await upnp.set_renderer(udn)
                    env_port = os.environ.get("HOST_PORT")
                    port = env_port if env_port else (request.url.port or 8111)
                    upnp.base_url = f"http://{upnp.local_ip}:{port}"
                    track = state["queue"][state["current_index"]]
                    await upnp.play_track(track["id"], track.get("path"), track)
                    start_monitor_task(udn)
                    last_track_start_time[udn] = time.time()
                finally:
                    _clear_monitor_starting(udn)

            # Start playback in background
            _mark_monitor_starting(udn)
            asyncio.create_task(start_playback())

    return {"status": "ok"}


@router.post("/api/player/queue/append")
async def append_queue(
    update: AppendQueue,
    request: Request,
    client_id: str = Depends(get_client_id),
    user: asyncpg.Record | None = Depends(get_optional_user_jwt),
):
    async for db in get_db():
        udn = await get_active_renderer(db, client_id)
        state = await get_renderer_state_db(db, udn)
        user_id = user["id"] if user else None

        new_tracks = []
        for t in update.tracks:
            track_dict = t.model_dump()
            if user_id is not None:
                track_dict["user_id"] = user_id
            new_tracks.append(track_dict)
        state["queue"] = state["queue"] + new_tracks

        await update_renderer_state_db(db, udn, state)
        reset_history_tracker(client_id if udn.startswith("local") else udn)
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
        reset_history_tracker(client_id if udn.startswith("local") else udn)

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
        reset_history_tracker(client_id if udn.startswith("local") else udn)

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
        reset_history_tracker(client_id if udn.startswith("local") else udn)

        if not udn.startswith("local:"):
            queue = state.get("queue") or []
            if queue and 0 <= state["current_index"] < len(queue):
                # find next playable track from requested index forward
                playable_idx = None
                for idx in range(state["current_index"], len(queue)):
                    candidate = await enrich_track_metadata(queue[idx], db)
                    if track_path_exists(candidate):
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
                _mark_monitor_starting(udn)
                try:
                    await upnp.play_track(track["id"], track.get("path"), track)
                    start_monitor_task(udn)
                    last_track_start_time[udn] = time.time()
                finally:
                    _clear_monitor_starting(udn)
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
    update: ProgressUpdate,
    request: Request,
    client_id: str = Depends(get_client_id),
    user: asyncpg.Record | None = Depends(get_optional_user_jwt),
):
    async for db in get_db():
        udn = await get_active_renderer(db, client_id)
        client_ip = get_client_ip(request)
        user_id = user["id"] if user else None
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
    user: asyncpg.Record | None = Depends(get_optional_user_jwt),
):
    track_id = data.get("track_id")
    if not track_id:
        raise HTTPException(status_code=400, detail="Missing track_id")

    udn = await get_active_renderer(db, client_id)

    # Fetch track metadata
    # Fetch track metadata
    row = await db.fetchrow(
        """
        WITH track_artists AS (
            SELECT 
                ta.track_id, 
                jsonb_agg(
                    jsonb_build_object(
                        'name', a.name, 
                        'mbid', a.mbid
                    )
                ) as artists
            FROM track_artist ta
            JOIN artist a ON ta.artist_mbid = a.mbid
            WHERE ta.track_id = $1
            GROUP BY ta.track_id
        )
        SELECT 
            t.id, t.title, t.artist, t.album, t.artwork_id, t.path, t.duration_seconds,
            COALESCE(ta.artists, '[]'::jsonb) as artists
        FROM track t
        LEFT JOIN track_artists ta ON t.id = ta.track_id
        WHERE t.id = $1
        """,
        track_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Track not found")
    track = dict(row)
    # Parse jsonb string if needed (asyncpg usually returns python objects for jsonb)
    if isinstance(track.get("artists"), str):
        import json
        track["artists"] = json.loads(track["artists"])
    user_row = user

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

        if (
            current_track
            and current_track.get("id") == track["id"]
            and state.get("is_playing")
        ):
            logger.info(f"play_track: Track {track_id} already playing. checking monitor...")
            # Ensure monitor is running if it died
            if udn not in playback_monitors or playback_monitors[udn].done():
                logger.info(f"Restarting monitor for active track {track_id}")
                start_monitor_task(udn)
                last_track_start_time[udn] = time.time()
            else:
                 logger.info(f"play_track: Monitor already running for {udn}")
            
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
            
            # Start monitor
            start_monitor_task(udn)
            last_track_start_time[udn] = time.time()
            
            return {"status": "resumed", "renderer": udn}

        # Different track or no track playing - start new playback
        # Try to keep the existing queue if this track is in it; otherwise replace with single track
        existing_queue = state.get("queue") or []
        try:
            current_index = next(
                i for i, t in enumerate(existing_queue) if t.get("id") == track["id"]
            )
            existing_queue[current_index] = track
        except StopIteration:
            existing_queue = [track]
            current_index = 0

        state["queue"] = existing_queue
        state["current_index"] = current_index
        state["position_seconds"] = 0
        state["is_playing"] = True
        state["transport_state"] = "PLAYING"
        await update_renderer_state_db(db, udn, state)
        reset_history_tracker(udn)

        # Stop existing monitor cleanly
        if udn in playback_monitors:
            playback_monitors[udn].cancel()
            try:
                await asyncio.wait([playback_monitors[udn]], timeout=1)
            except Exception:
                pass

        _mark_monitor_starting(udn)
        try:
            await upnp.play_track(track["id"], track["path"], track)
            # Start fresh monitor (only for UPnP)
            start_monitor_task(udn)
            last_track_start_time[udn] = time.time()
        finally:
            _clear_monitor_starting(udn)

        return {"status": "streaming_started", "renderer": udn}
    else:
        state = await get_renderer_state_db(db, udn)
        existing_queue = state.get("queue") or []
        try:
            current_index = next(
                i for i, t in enumerate(existing_queue) if t.get("id") == track["id"]
            )
            existing_queue[current_index] = track
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
    monitors_status = {}
    for udn, task in playback_monitors.items():
        monitors_status[udn] = {
            "done": task.done(),
            "cancelled": task.cancelled(),
        }
        if task.done() and not task.cancelled():
            try:
                task.result() # check for exception
                monitors_status[udn]["result"] = "success"
            except Exception as e:
                monitors_status[udn]["error"] = str(e)

    return {
        "log": upnp.debug_log,
        "renderers": upnp.renderers,
        "dmr_devices_keys": list(upnp.dmr_devices.keys()),
        "local_ip": upnp.local_ip,
        "monitors": monitors_status,
        "monitor_start_times": monitor_start_times,
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
