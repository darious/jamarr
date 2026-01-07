from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
import json

from app.scanner.scan_manager import ScanManager

router = APIRouter()


class ScanRequest(BaseModel):
    type: str  # 'filesystem', 'metadata', 'prune'
    path: Optional[str] = None
    force: bool = False
    artist_filter: Optional[str] = None
    mbid_filter: Optional[str] = None
    missing_only: bool = False
    bio_only: bool = False  # deprecated; use fetch_bio
    links_only: bool = False  # deprecated; use fetch_links
    refresh_top_tracks: bool = False
    refresh_singles: bool = False
    fetch_metadata: bool = False
    fetch_bio: bool = False
    fetch_artwork: bool = False
    fetch_spotify_artwork: bool = False
    fetch_links: bool = False
    fetch_similar_artists: bool = False
    fetch_album_metadata: bool = False
    prune: bool = True


@router.post("/api/library/scan")
async def trigger_scan(request: ScanRequest):
    manager = ScanManager.get_instance()

    try:
        manager_path = manager.get_music_path()
        target_path = request.path or manager_path
        if not target_path:
            raise HTTPException(status_code=400, detail="path is required for all scan types")

        if request.type == "filesystem":
            await manager.start_scan(path=target_path, force=request.force)
            return {"message": "Filesystem scan started"}

        elif request.type == "metadata":
            await manager.start_metadata_update(
                path=target_path,
                artist_filter=request.artist_filter,
                mbid_filter=request.mbid_filter,
                missing_only=request.missing_only,
                bio_only=request.bio_only or request.fetch_bio,
                refresh_top_tracks=request.refresh_top_tracks,
                refresh_singles=request.refresh_singles,
                fetch_metadata=request.fetch_metadata,
                fetch_bio=request.fetch_bio,
                fetch_artwork=request.fetch_artwork,
                fetch_spotify_artwork=request.fetch_spotify_artwork,
                fetch_links=request.fetch_links,
                fetch_similar_artists=request.fetch_similar_artists,
                fetch_album_metadata=request.fetch_album_metadata,
            )
            return {"message": "Metadata update started"}

        elif request.type == "full":
            await manager.start_full(
                path=target_path,
                force=request.force,
                artist_filter=request.artist_filter,
                mbid_filter=request.mbid_filter,
                missing_only=request.missing_only,
                bio_only=request.bio_only or request.fetch_bio,
                refresh_top_tracks=request.refresh_top_tracks,
                refresh_singles=request.refresh_singles,
                fetch_metadata=request.fetch_metadata,
                fetch_bio=request.fetch_bio,
                fetch_artwork=request.fetch_artwork,
                fetch_spotify_artwork=request.fetch_spotify_artwork,
                fetch_links=request.fetch_links,
                prune=request.prune,
                fetch_similar_artists=request.fetch_similar_artists,
                fetch_album_metadata=request.fetch_album_metadata,
            )
            return {"message": "Full library refresh started"}

        elif request.type == "prune":
            await manager.start_prune()
            return {"message": "Library prune started"}

        elif request.type == "missing_albums":
            await manager.start_missing_albums_scan(
                artist_filter=request.artist_filter, 
                mbid_filter=request.mbid_filter,
                path=request.path
            )
            return {"message": "Missing albums scan started"}

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
    from app.scanner.stats import get_api_tracker
    
    manager = ScanManager.get_instance()
    tracker = get_api_tracker()
    
    # Get stage metrics
    stage_metrics = tracker.get_stage_metrics()
    categories = []
    for stage_name, metrics in stage_metrics.items():
        missing = metrics.get("missing", 0)
        searched = metrics.get("searched", 0)
        hits = metrics.get("hits", 0)
        misses = metrics.get("misses", 0)
        success_rate = f"{int(hits / missing * 100)}%" if missing > 0 else "N/A"
        
        categories.append({
            "name": stage_name,
            "missing": missing,
            "searched": searched,
            "hits": hits,
            "misses": misses,
            "success_rate": success_rate
        })
    
    # Get API request counts
    api_stats = tracker.get_stats()
    api_requests = {
        "musicbrainz": api_stats.get("musicbrainz", 0),
        "lastfm": api_stats.get("lastfm", 0),
        "wikidata": api_stats.get("wikidata", 0),
        "fanart": api_stats.get("fanart", 0),
        "spotify": api_stats.get("spotify", 0),
        "qobuz": api_stats.get("qobuz", 0),
    }
    
    # Get processed counts
    processed = tracker.get_processed_stats()
    
    return {
        "status": manager._status,
        "stats": manager._stats,
        "processed": processed,
        "categories": categories,
        "api_requests": api_requests,
        "stage_metrics": stage_metrics,  # Also return raw stage_metrics
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
