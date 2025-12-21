from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
import json
import asyncio

from app.scanner.scan_manager import ScanManager

router = APIRouter()

class ScanRequest(BaseModel):
    type: str # 'filesystem', 'metadata', 'prune'
    path: Optional[str] = None
    force: bool = False
    artist_filter: Optional[str] = None
    mbid_filter: Optional[str] = None
    missing_only: bool = False
    bio_only: bool = False
    links_only: bool = False

@router.post("/api/library/scan")
async def trigger_scan(request: ScanRequest):
    manager = ScanManager.get_instance()
    
    try:
        if request.type == 'filesystem':
            await manager.start_scan(path=request.path, force=request.force)
            return {"message": "Filesystem scan started"}
        
        elif request.type == 'metadata':
            await manager.start_metadata_update(
                artist_filter=request.artist_filter, 
                mbid_filter=request.mbid_filter,
                missing_only=request.missing_only,
                bio_only=request.bio_only,
                links_only=request.links_only,
            )
            return {"message": "Metadata update started"}

        elif request.type == 'full':
            await manager.start_full(
                path=request.path,
                force=request.force,
                artist_filter=request.artist_filter,
                mbid_filter=request.mbid_filter,
                missing_only=request.missing_only,
                bio_only=request.bio_only,
                links_only=request.links_only,
            )
            return {"message": "Full library refresh started"}
            
        elif request.type == 'prune':
            await manager.start_prune()
            return {"message": "Library prune started"}
            
        else:
            raise HTTPException(status_code=400, detail="Invalid scan type")
            
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))

@router.post("/api/library/cancel")
async def cancel_scan():
    manager = ScanManager.get_instance()
    await manager.stop_scan()
    return {"message": "Stop signal sent"}

@router.get("/api/library/status")
async def get_scan_status():
    manager = ScanManager.get_instance()
    return {
        "status": manager._status,
        "stats": manager._stats,
        "is_running": manager._current_task is not None and not manager._current_task.done(),
        "music_path": manager.get_music_path(),
    }

@router.get("/api/library/events")
async def sse_events():
    manager = ScanManager.get_instance()
    
    async def event_generator():
        # First check connection by yielding a comment
        yield ": connected\n\n"
        
        async for event in manager.subscribe():
            # SSE format: "data: <json>\n\n"
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
