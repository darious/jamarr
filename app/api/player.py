from fastapi import APIRouter, Depends, Request, HTTPException, Header, Response
import os
import asyncio
from app.db import get_db, DB_PATH
import aiosqlite
from app.upnp import UPnPManager
import mimetypes
import httpx
from typing import Dict, Any, List, Optional
from pydantic import BaseModel
import json
import logging
import time

router = APIRouter()
logger = logging.getLogger(__name__)
upnp = UPnPManager.get_instance()

# Global map to track Playback Monitor Tasks (UDN -> Task)
playback_monitors: Dict[str, asyncio.Task] = {}

async def play_next_track_internal(udn: str):
    """Internal helper to advance queue and play next track."""
    async with aiosqlite.connect(DB_PATH) as db:
        state = await get_renderer_state_db(db, udn)
        queue = state['queue']
        current_index = state['current_index']
        
        next_index = current_index + 1
        if 0 <= next_index < len(queue):
            track = queue[next_index]
            logger.info(f"[Player] Auto-advancing to track {next_index}: {track['title']}")
            
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
            if 'mime' not in track or not track['mime']:
                 mime, _ = mimetypes.guess_type(track.get('path', ''))
                 if not mime:
                     ext = os.path.splitext(track.get('path', ''))[1].lower()
                     if ext == '.flac': mime = "audio/flac"
                     elif ext == '.mp3': mime = "audio/mpeg"
                     elif ext == '.m4a': mime = "audio/mp4"
                     elif ext == '.wav': mime = "audio/wav"
                     elif ext == '.ogg': mime = "audio/ogg"
                     else: mime = "audio/flac"
                 track['mime'] = mime

            await upnp.play_track(track['id'], track['path'], track)
            
            # Update DB
            state['current_index'] = next_index
            state['is_playing'] = True
            state['position_seconds'] = 0
            # state['transport_state'] = "PLAYING" # Optimistic
            await update_renderer_state_db(db, udn, state)
            
            # Remove immediate history logging. 
            # We rely on the client (PlayerBar) to log history after 30s threshold to ensure:
            # 1. Correct Client IP/ID is logged.
            # 2. Track is actually listened to (not skipped immediately).
            # await log_history(db, track['id'], "127.0.0.1", "System Auto-Advance")
            
        else:
            logger.info("[Player] End of queue reached.")
            state['is_playing'] = False
            state['position_seconds'] = 0
            # state['transport_state'] = "STOPPED" # Already stopped
            await update_renderer_state_db(db, udn, state)

async def monitor_upnp_playback(udn: str):
    """Background task to poll UPnP device for position and update DB."""
    logger.info(f"[Player] Starting UPnP monitor for {udn}")
    
    # Grace period: Wait for device to react to Play command before polling
    # This prevents detecting "STOPPED" immediately after a manual Play/Skip.
    await asyncio.sleep(3)
    
    was_playing = False # Initialize to prevent UnboundLocalError
    try:
        while True:
            # 1. Fetch position & transport from UPnP
            rel_time, _ = await upnp.get_position(udn)
            transport_state = await upnp.get_transport_info(udn)
            
            # print(f"[Player] Monitor {udn}: {transport_state} @ {rel_time}s")
            
            # 2. Update DB
            async with aiosqlite.connect(DB_PATH) as db:
                 # Check what we *think* we are doing
                 state = await get_renderer_state_db(db, udn)
                 was_playing = state['is_playing']
                 
                 # Update Live Stats
                 state['position_seconds'] = rel_time
                 state['transport_state'] = transport_state
                 # Don't overwrite is_playing yet, logic below decides
                 
                 # Save partial update (position/transport)
                 # await update_renderer_state_db(db, udn, state) 
                 # Optimization: Batch update at end? No, we need fresh state for logic.
                 
                 # --- Auto-Advance Logic ---
                 # If we think we are playing, but device says STOPPED (and position is near 0 or we don't care),
                 # it implies track finished.
                 # Note: "NO_MEDIA_PRESENT" or "TRANSITIONING" handling?
                 
                 if was_playing:
                     if transport_state in ["STOPPED", "NO_MEDIA_PRESENT"]:
                         logger.info(f"[Player] Track finished detection: State={transport_state}, Expected=Playing")
                         # Trigger Next Track
                         # We must run this OUTSIDE the current DB transaction if helper uses its own?
                         # Helper `play_next_track_internal` opens its own connection. 
                         # We should close this one or just run helper after.
                         pass
                     else:
                         # Still playing or paused or buffering
                         # If Paused, do we set is_playing=False? 
                         # If user paused via remote, transport is PAUSED_PLAYBACK.
                         # We should sync is_playing to False?
                         if "PAUSE" in transport_state:
                             state['is_playing'] = False
                         
                         # Race Condition Fix:
                         # Use a specific UPDATE for status fields to avoid overwriting volume/queue
                         # if they were changed by another request while we were waiting on UPnP.
                         # await update_renderer_state_db(db, udn, state)
                         await db.execute("""
                             UPDATE renderer_states 
                             SET position_seconds = ?, transport_state = ?, is_playing = ?, updated_at = CURRENT_TIMESTAMP
                             WHERE renderer_udn = ?
                         """, (state['position_seconds'], state['transport_state'], 1 if state['is_playing'] else 0, udn))
                         await db.commit()

                 # History logging for remote playback (based on renderer state queue)
                 if state['is_playing'] and state['current_index'] is not None and state['current_index'] >= 0:
                     queue = state.get("queue") or []
                     if 0 <= state['current_index'] < len(queue):
                         track = queue[state['current_index']]
                         track_id = track.get("id")
                         duration = track.get("duration_seconds") or 0
                         renderer_ip = upnp.renderers.get(udn, {}).get("ip") if upnp.renderers else None
                         if _should_log_history(udn, track_id, rel_time, duration):
                             await log_history(db, track_id, client_ip=renderer_ip or "unknown", client_id=udn)
            
            # Execute Side Effects outside DB context
            if was_playing and transport_state in ["STOPPED", "NO_MEDIA_PRESENT"]:
                 # Double check we didn't just start? 
                 # Ideally we'd validte track duration vs position, but STOPPED is strong signal.
                 # Debounce? UPnP might report STOPPED briefly between tracks if we are fast?
                 # If we just sent a Play command, we might see STOPPED for a split second.
                 # BUT `play_track` waits for `Play` SOAP action. 
                 # So it should be PLAYING or TRANSITIONING.
                 
                 await play_next_track_internal(udn)
                 await asyncio.sleep(4) # Wait a bit to let new track start
            
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
    art_id: Optional[int] = None
    codec: Optional[str] = None
    bit_depth: Optional[int] = None
    sample_rate_hz: Optional[int] = None
    path: Optional[str] = None
    album_artist: Optional[str] = None
    track_no: Optional[int] = None
    disc_no: Optional[int] = None
    date: Optional[str] = None
    bitrate: Optional[int] = None

class PlayerState(BaseModel):
    queue: List[Track]
    current_index: int
    position_seconds: float
    is_playing: bool
    renderer: str # UDN
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
    forwarded_for = request.headers.get("X-Forwarded-For") or request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP") or request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "unknown"

async def get_active_renderer(db: aiosqlite.Connection, client_id: str) -> str:
    """Get active renderer UDN for client. Defaults to local:<client_id>."""
    async with db.execute("SELECT active_renderer_udn FROM client_sessions WHERE client_id = ?", (client_id,)) as cursor:
        row = await cursor.fetchone()
        if row and row[0]:
            return row[0]
            
    # If no session found, implicitly create one for observability
    default_udn = f"local:{client_id}"
    await db.execute("""
        INSERT OR IGNORE INTO client_sessions (client_id, active_renderer_udn, last_seen)
        VALUES (?, ?, CURRENT_TIMESTAMP)
    """, (client_id, default_udn))
    await db.commit()
    
    return default_udn

async def get_renderer_state_db(db: aiosqlite.Connection, udn: str) -> Dict[str, Any]:
    """Get state from DB for a renderer. Returns default if not found."""
    async with db.execute("SELECT queue, current_index, position_seconds, is_playing, transport_state, volume FROM renderer_states WHERE renderer_udn = ?", (udn,)) as cursor:
        row = await cursor.fetchone()
        if row:
            try:
                queue = json.loads(row[0])
            except:
                queue = []
            return {
                "queue": queue,
                "current_index": row[1],
                "position_seconds": row[2],
                "is_playing": bool(row[3]),
                "transport_state": row[4] if len(row) > 4 else "STOPPED",
                "volume": row[5] if len(row) > 5 else None
            }
    return {
        "queue": [],
        "current_index": -1,
        "position_seconds": 0,
        "is_playing": False,
        "transport_state": "STOPPED",
        "volume": None
    }

async def update_renderer_state_db(db: aiosqlite.Connection, udn: str, state: Dict[str, Any]):
    """Upsert renderer state."""
    queue_json = json.dumps(state.get("queue", []))
    volume = state.get("volume")
    await db.execute("""
        INSERT INTO renderer_states (renderer_udn, queue, current_index, position_seconds, is_playing, transport_state, volume, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(renderer_udn) DO UPDATE SET
            queue = excluded.queue,
            current_index = excluded.current_index,
            position_seconds = excluded.position_seconds,
            is_playing = excluded.is_playing,
            transport_state = excluded.transport_state,
            volume = excluded.volume,
            updated_at = CURRENT_TIMESTAMP
    """, (udn, queue_json, state.get("current_index", -1), state.get("position_seconds", 0), 1 if state.get("is_playing") else 0, state.get("transport_state", "STOPPED"), volume))
    await db.commit()

def _reset_history_tracker(key: str):
    if key in _history_tracker:
        del _history_tracker[key]

def _should_log_history(key: str, track_id: int, position: float, duration: float) -> bool:
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

async def log_history(db: aiosqlite.Connection, track_id: int, client_ip: str, client_id: str = None):
    if track_id and track_id > 0:
        try:
            # Check for duplicate within last 60 seconds
            async with db.execute(
                "SELECT id, client_ip FROM playback_history WHERE track_id = ? AND timestamp > datetime('now', '-60 seconds')",
                (track_id,)
            ) as cursor:
                existing = await cursor.fetchone()
                if existing:
                    existing_id, existing_ip = existing
                    if existing_ip == "127.0.0.1" and client_ip and client_ip != "127.0.0.1" and client_ip != "unknown":
                        logger.info(f"Refining history log {existing_id}: Updating IP to {client_ip}")
                        await db.execute(
                            "UPDATE playback_history SET client_ip = ?, client_id = ? WHERE id = ?",
                            (client_ip, client_id, existing_id)
                        )
                        await db.commit()
                        return
                    
                    logger.info(f"Skipping duplicate history log for track {track_id}")
                    return

            await db.execute(
                "INSERT INTO playback_history (track_id, client_ip, client_id) VALUES (?, ?, ?)",
                (track_id, client_ip, client_id)
            )
            await db.commit()
        except Exception as e:
            logger.error(f"Failed to log history: {e}")

# --- Endpoints ---

@router.get("/api/client-ip")
async def get_client_ip_endpoint(request: Request):
    return {"ip": get_client_ip(request)}

@router.get("/api/player/history")
async def get_playback_history(response: Response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    async for db in get_db():
        query = """
            SELECT 
                h.id, h.timestamp, h.client_ip, h.client_id,
                t.id, t.title, t.artist, t.album, t.art_id, t.duration_seconds,
                t.codec, t.bit_depth, t.sample_rate_hz, t.date
            FROM playback_history h
            JOIN tracks t ON h.track_id = t.id
            ORDER BY h.timestamp DESC
        """
        async with db.execute(query) as cursor:
            rows = await cursor.fetchall()
            history = []
            for row in rows:
                history.append({
                    "id": row[0],
                    "timestamp": row[1],
                    "client_ip": row[2],
                    "client_id": row[3],
                    "track": {
                        "id": row[4],
                        "title": row[5],
                        "artist": row[6],
                        "album": row[7],
                        "art_id": row[8],
                        "duration_seconds": row[9],
                        "codec": row[10],
                        "bit_depth": row[11],
                        "sample_rate_hz": row[12],
                        "date": row[13]
                    }
                })
            return history
    return []

@router.get("/api/player/state", response_model=PlayerState)
async def get_player_state(client_id: str = Depends(get_client_id)):
    async for db in get_db():
        udn = await get_active_renderer(db, client_id)
        state = await get_renderer_state_db(db, udn)
        
        # If UPnP, sync live state
        if udn != f"local:{client_id}" and not udn.startswith("local:"):
             # For UPnP devices, we might want to check if monitor is running
             if state['is_playing']:
                if udn not in playback_monitors or playback_monitors[udn].done():
                    logger.info(f"[Player] Auto-restarting monitor for {udn}")
                    playback_monitors[udn] = asyncio.create_task(monitor_upnp_playback(udn))

        return {
            "queue": state['queue'],
            "current_index": state['current_index'],
            "position_seconds": state['position_seconds'],
            "is_playing": state['is_playing'],
            "renderer": udn,
            "transport_state": state.get('transport_state', 'STOPPED'),
            "volume": state.get('volume')
        }
    return PlayerState(queue=[], current_index=-1, position_seconds=0, is_playing=False, renderer=f"local:{client_id}")

@router.post("/api/player/queue")
async def set_queue(update: QueueUpdate, client_id: str = Depends(get_client_id)):
    async for db in get_db():
        udn = await get_active_renderer(db, client_id)
        state = await get_renderer_state_db(db, udn)
        
        state['queue'] = [t.dict() for t in update.queue]
        state['current_index'] = update.start_index
        state['position_seconds'] = 0
        state['is_playing'] = True
        
        await update_renderer_state_db(db, udn, state)
    return {"status": "ok"}

@router.post("/api/player/queue/append")
async def append_queue(update: AppendQueue, client_id: str = Depends(get_client_id)):
    async for db in get_db():
        udn = await get_active_renderer(db, client_id)
        state = await get_renderer_state_db(db, udn)
        
        new_tracks = [t.dict() for t in update.tracks]
        state['queue'] = state['queue'] + new_tracks
        
        await update_renderer_state_db(db, udn, state)
        _reset_history_tracker(client_id if udn.startswith("local") else udn)
    return {"status": "ok"}

@router.post("/api/player/index")
async def set_index(update: IndexUpdate, client_id: str = Depends(get_client_id)):
    async for db in get_db():
        udn = await get_active_renderer(db, client_id)
        state = await get_renderer_state_db(db, udn)
        
        state['current_index'] = update.index
        state['position_seconds'] = 0
        state['is_playing'] = True # Assume play on skip
        
        await update_renderer_state_db(db, udn, state)
        _reset_history_tracker(client_id if udn.startswith("local") else udn)
    return {"status": "ok"}

@router.post("/api/player/log-play")
async def log_play(update: LogPlayRequest, request: Request, client_id: str = Depends(get_client_id)):
    """
    Client-initiated logging is now a no-op; history is recorded server-side from
    playback state to avoid double entries. We still return success for backward
    compatibility with older clients.
    """
    return {"status": "ok"}

@router.post("/api/player/progress")
async def update_progress(update: ProgressUpdate, request: Request, client_id: str = Depends(get_client_id)):
    async for db in get_db():
        udn = await get_active_renderer(db, client_id)
        client_ip = get_client_ip(request)
        if udn.startswith("local:"):
            state = await get_renderer_state_db(db, udn)
            state['position_seconds'] = update.position_seconds
            state['is_playing'] = update.is_playing
            await update_renderer_state_db(db, udn, state)

            # Server-side history logging for local playback
            if state['current_index'] is not None and state['current_index'] >= 0:
                queue = state.get("queue") or []
                if 0 <= state['current_index'] < len(queue):
                    track = queue[state['current_index']]
                    track_id = track.get("id")
                    duration = track.get("duration_seconds") or 0
                    if _should_log_history(client_id, track_id, update.position_seconds, duration):
                        await log_history(db, track_id, client_ip=client_ip, client_id=client_id)
        else:
            # For remote renderers, also evaluate logging on progress updates if ever sent
            state = await get_renderer_state_db(db, udn)
            if state['current_index'] is not None and state['current_index'] >= 0:
                queue = state.get("queue") or []
                if 0 <= state['current_index'] < len(queue):
                    track = queue[state['current_index']]
                    track_id = track.get("id")
                    duration = track.get("duration_seconds") or 0
                    if _should_log_history(udn, track_id, update.position_seconds, duration):
                        await log_history(db, track_id, client_ip=client_ip or "unknown", client_id=udn)
    return {"status": "ok"}

@router.get("/api/scan-status")
async def get_scan_status(client_id: str = Depends(get_client_id)):
    return {
        "is_scanning": upnp.is_scanning_subnet,
        "message": upnp.scan_msg,
        "progress": upnp.scan_progress,
        "logs": upnp.debug_log[-20:]
    }

@router.get("/api/renderers")
async def get_renderers(refresh: bool = False, client_id: str = Depends(get_client_id)):
    if refresh:
        await upnp.discover()
        asyncio.create_task(upnp.scan_subnet())
    renderers = await upnp.get_renderers()
    local_device = {"udn": f"local:{client_id}", "name": "This Device (Web Browser)", "type": "local"}
    return [local_device, *renderers]

@router.post("/api/player/renderer")
async def set_renderer(data: dict, client_id: str = Depends(get_client_id)):
    udn = data.get("udn")
    if not udn:
        raise HTTPException(status_code=400, detail="Missing udn")
    
    async for db in get_db():
        await db.execute("""
            INSERT INTO client_sessions (client_id, active_renderer_udn, last_seen)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(client_id) DO UPDATE SET
                active_renderer_udn = excluded.active_renderer_udn,
                last_seen = CURRENT_TIMESTAMP
        """, (client_id, udn))
        await db.commit()
    return {"active": udn}

@router.post("/api/player/play")
async def play_track(data: dict, request: Request, client_id: str = Depends(get_client_id), db: aiosqlite.Connection = Depends(get_db)):
    track_id = data.get("track_id")
    if not track_id:
        raise HTTPException(status_code=400, detail="Missing track_id")

    udn = await get_active_renderer(db, client_id)

    # Fetch track metadata
    async with db.execute("SELECT id, title, artist, album, art_id, path, duration_seconds FROM tracks WHERE id = ?", (track_id,)) as cursor:
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Track not found")
        track = dict(row)
        
        # Mime logic
        mime, _ = mimetypes.guess_type(track['path'])
        if not mime:
            ext = os.path.splitext(track['path'])[1].lower()
            if ext == '.flac': mime = "audio/flac"
            elif ext == '.mp3': mime = "audio/mpeg"
            elif ext == '.m4a': mime = "audio/mp4"
            elif ext == '.wav': mime = "audio/wav"
            elif ext == '.ogg': mime = "audio/ogg"
            else: mime = "audio/flac"
        track['mime'] = mime

        is_local = udn.startswith("local:")

        if not is_local:
            # UPnP Playback
            await upnp.set_renderer(udn) 
            
            env_port = os.environ.get('HOST_PORT')
            port = env_port if env_port else (request.url.port or 8111)
            upnp.base_url = f"http://{upnp.local_ip}:{port}"
            
            await upnp.play_track(track['id'], track['path'], track)
            
            # Start/Restart Monitor (only for UPnP)
            if udn in playback_monitors:
                playback_monitors[udn].cancel()
            playback_monitors[udn] = asyncio.create_task(monitor_upnp_playback(udn))
            
            state = await get_renderer_state_db(db, udn)
            state['is_playing'] = True
            await update_renderer_state_db(db, udn, state)
            
            return {"status": "streaming_started", "renderer": udn}
        else:
            state = await get_renderer_state_db(db, udn)
            state['is_playing'] = True
            await update_renderer_state_db(db, udn, state)
            
            return {"status": "local_playback", "message": "Handle playback in browser"}

@router.post("/api/player/pause")
async def pause_playback(client_id: str = Depends(get_client_id)):
    async for db in get_db():
        udn = await get_active_renderer(db, client_id)
        
        state = await get_renderer_state_db(db, udn)
        state['is_playing'] = False
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
        state['is_playing'] = True
        await update_renderer_state_db(db, udn, state)
        
        if not udn.startswith("local:"):
            await upnp.set_renderer(udn)
            await upnp.resume()
            
            if udn not in playback_monitors or playback_monitors[udn].done():
                playback_monitors[udn] = asyncio.create_task(monitor_upnp_playback(udn))
            
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
        state['volume'] = percent
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
        state['position_seconds'] = float(seconds)
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
        "local_ip": upnp.local_ip
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
