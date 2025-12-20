from fastapi import APIRouter, Depends, Request, HTTPException
from app.db import get_db
import aiosqlite
from app.upnp import UPnPManager
import mimetypes
import httpx
from typing import Dict, Any, List, Optional
from pydantic import BaseModel
import json
import logging

router = APIRouter()
logger = logging.getLogger(__name__)
upnp = UPnPManager.get_instance()

# --- Pydantic Models ---

class Track(BaseModel):
    id: int
    title: str
    artist: str
    album: str
    duration_seconds: float
    art_id: Optional[int] = None  # Changed from str to int to match frontend
    codec: Optional[str] = None
    bit_depth: Optional[int] = None
    sample_rate_hz: Optional[int] = None
    path: Optional[str] = None
    # Add other optional fields from frontend
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

class QueueUpdate(BaseModel):
    queue: List[Track]
    start_index: int = 0
    hostname: Optional[str] = None
    client_ip: Optional[str] = None  # Frontend can send its own IP

class AppendQueue(BaseModel):
    tracks: List[Track]

class IndexUpdate(BaseModel):
    index: int
    hostname: Optional[str] = None
    client_ip: Optional[str] = None  # Frontend can send its own IP

class ProgressUpdate(BaseModel):
    position_seconds: float
    is_playing: bool

# --- Helper Functions ---

# --- Helper Functions ---

def get_client_ip(request: Request) -> str:
    """Get the real client IP, accounting for proxies."""
    # Debug: log all headers
    logger.warning(f"[IP Debug] Request headers: {dict(request.headers)}")
    logger.warning(f"[IP Debug] Request client: {request.client}")
    
    # Check X-Forwarded-For header first (for reverse proxies)
    forwarded_for = request.headers.get("X-Forwarded-For") or request.headers.get("x-forwarded-for")
    if forwarded_for:
        # X-Forwarded-For can be a comma-separated list, take the first (original client)
        client_ip = forwarded_for.split(",")[0].strip()
        logger.warning(f"[IP Debug] Using X-Forwarded-For: {client_ip}")
        return client_ip
    
    # Check X-Real-IP header (alternative proxy header)
    real_ip = request.headers.get("X-Real-IP") or request.headers.get("x-real-ip")
    if real_ip:
        logger.warning(f"[IP Debug] Using X-Real-IP: {real_ip}")
        return real_ip.strip()
    
    # Fallback to direct connection IP
    fallback = request.client.host if request.client else "unknown"
    logger.warning(f"[IP Debug] Using fallback client.host: {fallback}")
    return fallback

async def log_history(db: aiosqlite.Connection, track_id: int, client_ip: str, hostname: str = None):
    if track_id and track_id > 0:
        try:
            await db.execute(
                "INSERT INTO playback_history (track_id, client_ip, hostname) VALUES (?, ?, ?)",
                (track_id, client_ip, hostname)
            )
            await db.commit()
        except Exception as e:
            logger.error(f"Failed to log history: {e}")

# --- Endpoints ---

@router.get("/api/client-ip")
async def get_client_ip_endpoint(request: Request):
    """Return the client's IP address."""
    client_ip = get_client_ip(request)
    return {"ip": client_ip}

@router.get("/api/player/history")
async def get_playback_history():
    """Get playback history with track details."""
    async for db in get_db():
        query = """
            SELECT 
                h.id,
                h.timestamp,
                h.client_ip,
                h.hostname,
                t.id as track_id,
                t.title,
                t.artist,
                t.album,
                t.art_id,
                t.duration_seconds,
                t.codec,
                t.bit_depth,
                t.sample_rate_hz,
                t.date
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
                    "hostname": row[3],
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
async def get_player_state():
    async for db in get_db():
        async with db.execute("SELECT queue, current_index, position_seconds, is_playing FROM playback_state WHERE id = 1") as cursor:
            row = await cursor.fetchone()
            if row:
                queue_json, idx, pos, playing = row
                try:
                    queue = json.loads(queue_json)
                except:
                    queue = []
                return {
                    "queue": queue,
                    "current_index": idx,
                    "position_seconds": pos,
                    "is_playing": bool(playing)
                }
    return {"queue": [], "current_index": 0, "position_seconds": 0, "is_playing": False}

@router.post("/api/player/queue")
async def set_queue(update: QueueUpdate, request: Request):
    # Prefer client_ip from request body (sent by frontend), fallback to headers
    client_ip = update.client_ip or get_client_ip(request)
    async for db in get_db():
        queue_json = json.dumps([t.dict() for t in update.queue])
        await db.execute(
            "UPDATE playback_state SET queue = ?, current_index = ?, position_seconds = 0, is_playing = 1 WHERE id = 1",
            (queue_json, update.start_index)
        )
        await db.commit()
        # Note: History logging moved to /api/player/log-play endpoint
            
    return {"status": "ok"}

@router.post("/api/player/queue/append")
async def append_queue(update: AppendQueue):
    async for db in get_db():
        # Get current queue
        async with db.execute("SELECT queue FROM playback_state WHERE id = 1") as cursor:
            row = await cursor.fetchone()
            current_queue = json.loads(row[0]) if row else []
            
        new_tracks = [t.dict() for t in update.tracks]
        updated_queue = current_queue + new_tracks
        
        await db.execute(
            "UPDATE playback_state SET queue = ? WHERE id = 1",
            (json.dumps(updated_queue),)
        )
        await db.commit()
    return {"status": "ok"}

@router.post("/api/player/index")
async def set_index(update: IndexUpdate, request: Request):
    # Prefer client_ip from request body (sent by frontend), fallback to headers
    client_ip = update.client_ip or get_client_ip(request)
    async for db in get_db():
        # Note: History logging moved to /api/player/log-play endpoint
        await db.execute(
            "UPDATE playback_state SET current_index = ?, position_seconds = 0 WHERE id = 1",
            (update.index,)
        )
        await db.commit()
    return {"status": "ok"}

class LogPlayRequest(BaseModel):
    track_id: int
    client_ip: Optional[str] = None
    hostname: Optional[str] = None

@router.post("/api/player/log-play")
async def log_play(update: LogPlayRequest, request: Request):
    """Log a track play to history after threshold is met."""
    client_ip = update.client_ip or get_client_ip(request)
    async for db in get_db():
        await log_history(db, update.track_id, client_ip, update.hostname)
    return {"status": "ok"}

@router.post("/api/player/progress")
async def update_progress(update: ProgressUpdate):
    async for db in get_db():
        await db.execute(
            "UPDATE playback_state SET position_seconds = ?, is_playing = ? WHERE id = 1",
            (update.position_seconds, update.is_playing)
        )
        await db.commit()
    return {"status": "ok"}

# --- UPnP & Debug Endpoints (Preserved) ---

@router.get("/api/player/debug")
async def debug_info():
    return {
        "log": upnp.debug_log,
        "renderers": upnp.renderers,
        "local_ip": upnp.local_ip
    }

@router.get("/api/player/test_upnp")
async def test_upnp():
    if not upnp.active_renderer:
        return {"error": "No active renderer"}
    
    r = upnp.renderers[upnp.active_renderer]
    url = r['control_url']
    
    try:
        # GetTransportInfo
        action = "GetTransportInfo"
        body = f"""<?xml version="1.0"?>
        <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
            <s:Body>
                <u:{action} xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">
                    <InstanceID>0</InstanceID>
                </u:{action}>
            </s:Body>
        </s:Envelope>
        """
        headers = {
            'Content-Type': 'text/xml; charset="utf-8"',
            'SOAPAction': f'"urn:schemas-upnp-org:service:AVTransport:1#{action}"'
        }
        
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, content=body, headers=headers, timeout=5.0)
            return {"status": resp.status_code, "text": resp.text}
            
    except Exception as e:
        return {"error": str(e)}

@router.get("/api/renderers")
async def get_renderers(refresh: bool = False):
    if refresh:
        await upnp.discover()
    renderers = await upnp.get_renderers()
    # Add 'Local' option
    return [
        {"udn": "local", "name": "This Device (Web Browser)", "type": "local"},
        *renderers
    ]

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

@router.post("/api/player/renderer")
async def set_renderer(data: dict):
    udn = data.get("udn")
    if not udn:
        raise HTTPException(status_code=400, detail="Missing udn")
    try:
        await upnp.set_renderer(udn)
        return {"active": udn}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/api/player/play")
async def play_track(data: dict, request: Request, db: aiosqlite.Connection = Depends(get_db)):
    track_id = data.get("track_id")
    if not track_id:
        raise HTTPException(status_code=400, detail="Missing track_id")

    # Fetch track metadata
    async with db.execute("SELECT id, title, artist, album, art_id, path, duration_seconds FROM tracks WHERE id = ?", (track_id,)) as cursor:
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Track not found")
            
        track = dict(row)
        
        # Mime
        mime, _ = mimetypes.guess_type(track['path'])
        track['mime'] = mime or "audio/flac"

        # Update UPnP manager's base URL knowledge from this request
        base_url = str(request.base_url).rstrip('/')
        port = request.url.port or 80
        upnp.base_url = f"http://{upnp.local_ip}:{port}" 
        
        if upnp.active_renderer:
            await upnp.play_track(track['id'], track['path'], track)
            return {"status": "streaming_started", "renderer": upnp.active_renderer}
        else:
            return {"status": "local_playback", "message": "Handle playback in browser"}

@router.post("/api/player/pause")
async def pause_playback():
    if upnp.active_renderer:
        await upnp.pause()
    return {"status": "ok"}

@router.post("/api/player/resume")
async def resume_playback():
    if upnp.active_renderer:
        await upnp.resume()
    return {"status": "ok"}
