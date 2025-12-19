from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from app.db import get_db
import aiosqlite
import os

router = APIRouter()

import mimetypes

@router.get("/api/stream/{track_id}")
async def stream_track(track_id: int, db: aiosqlite.Connection = Depends(get_db)):
    async with db.execute("SELECT path FROM tracks WHERE id = ?", (track_id,)) as cursor:
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Track not found")
        
        path = row[0]
        
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail="File not found on disk")
        
        # Guess mime type or default to octet-stream
        media_type, _ = mimetypes.guess_type(path)
        if media_type is None:
            media_type = "application/octet-stream"
            
        return FileResponse(path, media_type=media_type)
