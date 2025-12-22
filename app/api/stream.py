from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from app.db import get_db
import aiosqlite
import os

router = APIRouter()

import mimetypes

@router.api_route("/api/stream/{track_id}", methods=["GET", "HEAD"])
async def stream_track(track_id: int, db: aiosqlite.Connection = Depends(get_db)):
    async with db.execute("SELECT path FROM tracks WHERE id = ?", (track_id,)) as cursor:
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Track not found")
        
        from app.config import get_music_path
        
        path = row[0]
        if not os.path.isabs(path):
            path = os.path.join(get_music_path(), path)
        
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail="File not found on disk")
        
        # Guess mime type or default to octet-stream
        media_type, _ = mimetypes.guess_type(path)
        if media_type is None:
            # Fallbacks for common types if system mime.types is missing
            ext = os.path.splitext(path)[1].lower()
            if ext == '.flac':
                media_type = "audio/flac"
            elif ext == '.mp3':
                media_type = "audio/mpeg"
            elif ext == '.m4a':
                media_type = "audio/mp4"
            elif ext == '.wav':
                media_type = "audio/wav"
            elif ext == '.ogg':
                media_type = "audio/ogg"
            else:
                media_type = "application/octet-stream"
            
        return FileResponse(path, media_type=media_type)
