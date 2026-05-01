from fastapi import APIRouter, Depends, Request, HTTPException, Header
import os
import asyncio
import mimetypes
import logging
import time
from typing import Optional
import asyncpg
from app.db import get_db
from app.api.deps import (
    get_current_admin_user_jwt,
    get_current_user_jwt,
    require_admin_user,
)
from app.security import get_client_ip, is_production

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
)
from app.services.player.state import (
    get_renderer_state_db,
    update_renderer_state_db,
)
from app.services.player.history import (
    log_history,
    reset_history_tracker,
    update_now_playing_lastfm,
)
from app.services.player.monitor import (
    start_monitor_task,
    _is_monitor_starting,
)
from app.services.renderer import get_renderer_orchestrator

router = APIRouter(dependencies=[Depends(get_current_user_jwt)])
logger = logging.getLogger(__name__)
renderer_orchestrator = get_renderer_orchestrator()


async def get_client_id(x_jamarr_client_id: Optional[str] = Header(None)) -> str:
    if not x_jamarr_client_id:
        # Fallback for old clients or direct API calls?
        return "unknown_client"
    return x_jamarr_client_id


@router.get("/api/client-ip")
async def get_client_ip_endpoint(request: Request):
    return {"ip": get_client_ip(request)}


@router.get("/api/player/state", response_model=PlayerState)
async def get_player_state(client_id: str = Depends(get_client_id)):
    async for db in get_db():
        renderer_id, udn = await renderer_orchestrator.get_active(db, client_id)
        state = await get_renderer_state_db(db, udn)

        # UPnP uses the legacy polling monitor. Event-capable backends like Cast
        # update state through the renderer orchestrator callback path.
        if renderer_id.startswith("upnp:"):
            # For UPnP devices, we might want to check if monitor is running
            if state["is_playing"]:
                if udn not in playback_monitors or playback_monitors[udn].done():
                    # Only restart if it's been at least 5 seconds since last start
                    now = time.time()
                    last_start = monitor_start_times.get(udn, 0)
                    if now - last_start > 5 and not _is_monitor_starting(udn):
                        logger.info(f"[Player] Auto-restarting monitor for {udn}")
                        start_monitor_task(udn)
        elif not renderer_id.startswith("local:"):
            state = await renderer_orchestrator.sync_status(db, renderer_id, udn, state)

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
            "renderer_id": renderer_id,
            "renderer_kind": renderer_id.split(":", 1)[0] if ":" in renderer_id else "upnp",
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


@router.post(
    "/api/player/queue",
    dependencies=[Depends(get_current_admin_user_jwt)],
)
async def set_queue(
    update: QueueUpdate,
    request: Request,
    client_id: str = Depends(get_client_id),
    user: asyncpg.Record = Depends(get_current_user_jwt),
):
    async for db in get_db():
        user_id = user["id"]

        enriched_queue = []
        for t in update.queue:
            track_dict = t.model_dump()
            if user_id is not None:
                track_dict["user_id"] = user_id
            enriched_queue.append(track_dict)
        
        # Trigger Now Playing update for Last.fm
        if enriched_queue:
            current_index = max(
                0, min(update.start_index, len(enriched_queue) - 1)
            )
            current_track = enriched_queue[current_index]
            asyncio.create_task(
                update_now_playing_lastfm(user_id, current_track["id"])
            )
        await renderer_orchestrator.set_queue(
            db,
            client_id,
            enriched_queue,
            update.start_index,
            user_id,
            request,
        )

    return {"status": "ok"}


@router.post(
    "/api/player/queue/append",
    dependencies=[Depends(get_current_admin_user_jwt)],
)
async def append_queue(
    update: AppendQueue,
    request: Request,
    client_id: str = Depends(get_client_id),
    user: asyncpg.Record = Depends(get_current_user_jwt),
):
    async for db in get_db():
        _, udn = await renderer_orchestrator.get_active(db, client_id)
        state = await get_renderer_state_db(db, udn)
        user_id = user["id"]

        new_tracks = []
        for t in update.tracks:
            track_dict = t.model_dump()
            track_dict["user_id"] = user_id
            new_tracks.append(track_dict)
        state["queue"] = state["queue"] + new_tracks

        await update_renderer_state_db(db, udn, state)
        reset_history_tracker(client_id if udn.startswith("local") else udn)
    return {"status": "ok"}


@router.post(
    "/api/player/queue/reorder",
    dependencies=[Depends(get_current_admin_user_jwt)],
)
async def reorder_queue(
    update: QueueUpdate, client_id: str = Depends(get_client_id)
):
    """
    Reorder the queue without changing playback state.
    Expects the same queue items in a new order.
    """
    async for db in get_db():
        _, udn = await renderer_orchestrator.get_active(db, client_id)
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


@router.post(
    "/api/player/queue/clear",
    dependencies=[Depends(get_current_admin_user_jwt)],
)
async def clear_queue(client_id: str = Depends(get_client_id)):
    """
    Empty the active renderer queue and stop playback.
    """
    async for db in get_db():
        state, udn = await renderer_orchestrator.stop_or_clear(db, client_id)

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


@router.post(
    "/api/player/index",
    dependencies=[Depends(get_current_admin_user_jwt)],
)
async def set_index(update: IndexUpdate, client_id: str = Depends(get_client_id)):
    async for db in get_db():
        state, udn = await renderer_orchestrator.skip_to_index(db, client_id, update.index)
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
    user: asyncpg.Record = Depends(get_current_user_jwt),
):
    async for db in get_db():
        _, udn = await renderer_orchestrator.get_active(db, client_id)
        client_ip = get_client_ip(request)
        user_id = user["id"]
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
                            effective_user_id = user_id or track.get("user_id")
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


@router.get("/api/scan-status", dependencies=[Depends(get_current_admin_user_jwt)])
async def get_scan_status(client_id: str = Depends(get_client_id)):
    upnp_backend = renderer_orchestrator.registry.backends.get("upnp")
    manager = getattr(upnp_backend, "manager", None)
    return {
        "is_scanning": getattr(manager, "is_scanning_subnet", False),
        "message": getattr(manager, "scan_msg", ""),
        "progress": getattr(manager, "scan_progress", 0),
        "logs": getattr(manager, "debug_log", [])[-20:],
    }


@router.get("/api/renderers")
async def get_renderers(
    refresh: bool = False,
    client_id: str = Depends(get_client_id),
    user: asyncpg.Record = Depends(get_current_user_jwt),
):
    if refresh:
        require_admin_user(user)
    
    async for db in get_db():
        renderers = await renderer_orchestrator.list_renderers(
            db,
            client_id,
            refresh=refresh,
        )
    if refresh:
        upnp_backend = renderer_orchestrator.registry.backends.get("upnp")
        manager = getattr(upnp_backend, "manager", None)
        if manager:
            asyncio.create_task(manager.scan_subnet())
    return renderers


@router.post(
    "/api/player/renderer",
    dependencies=[Depends(get_current_admin_user_jwt)],
)
async def set_renderer(data: dict, client_id: str = Depends(get_client_id)):
    requested = data.get("renderer_id") or data.get("udn")
    if not requested:
        raise HTTPException(status_code=400, detail="Missing renderer_id")

    async for db in get_db():
        renderer_id, state_key = await renderer_orchestrator.set_active(db, client_id, requested)
    return {"active": state_key, "renderer_id": renderer_id}


@router.post(
    "/api/player/play",
    dependencies=[Depends(get_current_admin_user_jwt)],
)
async def play_track(
    data: dict,
    request: Request,
    client_id: str = Depends(get_client_id),
    db: asyncpg.Connection = Depends(get_db),
    user: asyncpg.Record = Depends(get_current_user_jwt),
):
    track_id = data.get("track_id")
    if not track_id:
        raise HTTPException(status_code=400, detail="Missing track_id")

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
    track["user_id"] = user_row["id"]

    return await renderer_orchestrator.play_track(
        db,
        client_id,
        track,
        user_row["id"],
        request,
    )


@router.post(
    "/api/player/pause",
    dependencies=[Depends(get_current_admin_user_jwt)],
)
async def pause_playback(client_id: str = Depends(get_client_id)):
    async for db in get_db():
        await renderer_orchestrator.pause(db, client_id)
        return {"status": "ok"}


@router.post(
    "/api/player/resume",
    dependencies=[Depends(get_current_admin_user_jwt)],
)
async def resume_playback(client_id: str = Depends(get_client_id)):
    async for db in get_db():
        await renderer_orchestrator.resume(db, client_id)

    return {"status": "ok"}


@router.post(
    "/api/player/volume",
    dependencies=[Depends(get_current_admin_user_jwt)],
)
async def set_volume(data: dict, client_id: str = Depends(get_client_id)):
    percent = data.get("percent")
    if percent is None:
        raise HTTPException(status_code=400, detail="Missing percent")
    percent = max(0, min(100, int(percent)))

    async for db in get_db():
        await renderer_orchestrator.set_volume(db, client_id, percent)

    return {"status": "ok", "percent": percent}


@router.post(
    "/api/player/seek",
    dependencies=[Depends(get_current_admin_user_jwt)],
)
async def seek_track(data: dict, client_id: str = Depends(get_client_id)):
    seconds = data.get("seconds")
    if seconds is None:
        raise HTTPException(status_code=400, detail="Missing seconds")

    async for db in get_db():
        target = await renderer_orchestrator.seek(db, client_id, float(seconds))
        if target == "remote":
            return {"status": "ok", "target": seconds}
        return {"status": "local", "message": "Handle seek in browser"}


@router.post(
    "/api/player/add_manual",
    dependencies=[Depends(get_current_admin_user_jwt)],
)
async def add_manual_renderer(data: dict):
    ip = data.get("ip")
    if not ip:
        raise HTTPException(status_code=400, detail="Missing ip")
    found = await renderer_orchestrator.add_manual(ip)
    if found:
        return {"status": "found"}
    else:
        raise HTTPException(status_code=404, detail="Device not found at IP")


if not is_production():

    @router.get(
        "/api/player/debug",
        dependencies=[Depends(get_current_admin_user_jwt)],
    )
    async def debug_info():
        upnp_backend = renderer_orchestrator.registry.backends.get("upnp")
        upnp_manager = getattr(upnp_backend, "manager", None)
        monitors_status = {}
        for udn, task in playback_monitors.items():
            monitors_status[udn] = {
                "done": task.done(),
                "cancelled": task.cancelled(),
            }
            if task.done() and not task.cancelled():
                try:
                    task.result()  # check for exception
                    monitors_status[udn]["result"] = "success"
                except Exception as e:
                    monitors_status[udn]["error"] = str(e)

        return {
            "log": getattr(upnp_manager, "debug_log", []),
            "renderers": getattr(upnp_manager, "renderers", {}),
            "dmr_devices_keys": list(getattr(upnp_manager, "dmr_devices", {}).keys()),
            "local_ip": getattr(upnp_manager, "local_ip", None),
            "monitors": monitors_status,
            "monitor_start_times": monitor_start_times,
        }

    @router.get(
        "/api/player/test_upnp",
        dependencies=[Depends(get_current_admin_user_jwt)],
    )
    async def test_upnp():
        upnp_backend = renderer_orchestrator.registry.backends.get("upnp")
        upnp_manager = getattr(upnp_backend, "manager", None)
        if not getattr(upnp_manager, "active_renderer", None):
            return {"error": "No active renderer"}
        return {"status": "ok", "message": "Check debug logs"}
