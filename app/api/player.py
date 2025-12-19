from fastapi import APIRouter, Depends, Request, HTTPException
from app.db import get_db
import aiosqlite
from app.upnp import UPnPManager
import mimetypes
import httpx
from typing import Dict, Any, List

router = APIRouter()
upnp = UPnPManager.get_instance()
queue_state: Dict[str, Any] = {"queue": [], "current_index": -1}


async def _fetch_track(db: aiosqlite.Connection, track_id: int) -> Dict[str, Any]:
    async with db.execute(
        """
        SELECT id, title, artist, album, art_id, duration_seconds, bitrate, sample_rate_hz, bit_depth, date, codec
        FROM tracks WHERE id = ?
        """,
        (track_id,),
    ) as cursor:
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Track not found: {track_id}")
        return dict(row)

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
        # (e.g. http://192.168.0.x:8000/)
        base_url = str(request.base_url).rstrip('/')
        # Override IP in base_url with local network IP if request came from localhost?
        # Naim needs an IP it can reach.
        # If user accessed via localhost:8000, base_url is localhost:8000. Naim can't reach localhost.
        # So we should rely on upnp.local_ip but use the port from request.
        port = request.url.port or 80
        upnp.base_url = f"http://{upnp.local_ip}:{port}" # Update logic in upnp.py to use this

        # If active renderer is local, we don't do anything here (Frontend handles it)
        # But frontend calls this ONLY if remote?
        # Actually frontend should probably call this regardless for consistent API?
        # NO. If local, frontend sets <audio src>.
        # If remote, frontend calls this.
        
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


@router.get("/api/player/queue")
async def get_queue():
    return queue_state


@router.post("/api/player/queue/set")
async def set_queue(data: dict, db: aiosqlite.Connection = Depends(get_db)):
    track_ids: List[int] = data.get("track_ids") or []
    current_index = data.get("current_index", 0)
    if not track_ids:
        queue_state["queue"] = []
        queue_state["current_index"] = -1
        return queue_state

    tracks = []
    for tid in track_ids:
        tracks.append(await _fetch_track(db, int(tid)))

    queue_state["queue"] = tracks
    queue_state["current_index"] = min(max(0, int(current_index)), len(tracks) - 1)
    return queue_state


@router.post("/api/player/queue/add")
async def add_to_queue(data: dict, db: aiosqlite.Connection = Depends(get_db)):
    track_id = data.get("track_id")
    if track_id is None:
        raise HTTPException(status_code=400, detail="Missing track_id")

    track = await _fetch_track(db, int(track_id))
    queue_state["queue"] = queue_state.get("queue", []) + [track]
    if queue_state.get("current_index", -1) == -1:
        queue_state["current_index"] = 0
    return queue_state
