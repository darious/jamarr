from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from app.db import get_db
import os

router = APIRouter()
CACHE_DIR = "cache/art"

def _get_art_path(sha1: str, art_type: str) -> str:
    """Compute path for artwork file using subdirectory distribution."""
    subdir = sha1[:2]
    return os.path.join(CACHE_DIR, art_type, subdir, sha1)

@router.get("/art/{art_id}")
async def get_artwork(art_id: int):
    # We need to look up the SHA1 and type from the ID
    # For simplicity, we'll do a quick DB lookup
    # In a real app, we might want to cache this mapping or pass the SHA1 directly if possible
    # But the outline says /art/{art_id}
    
    async for db in get_db():
        async with db.execute("SELECT sha1, type FROM artwork WHERE id = ?", (art_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Artwork not found")
            
            sha1 = row["sha1"]
            art_type = row["type"] or "album"  # Default to album for legacy records
            path = _get_art_path(sha1, art_type)
            
            if not os.path.exists(path):
                raise HTTPException(status_code=404, detail="Artwork file missing")
            
            return FileResponse(path)
    
    raise HTTPException(status_code=500, detail="Database error")
