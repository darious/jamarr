from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import FileResponse
from app.db import get_db
import os
import base64
import io

def _build_test_art_bytes():
    """Generate a 600x600 JPEG test image; Pillow is required for the larger size."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (600, 600), (200, 50, 50)).save(buf, format="JPEG", quality=85)
    return buf.getvalue()

router = APIRouter()
CACHE_DIR = "cache/art"
_TEST_ART_BYTES = _build_test_art_bytes()

def _get_art_path(sha1: str, path_on_disk: str | None = None) -> str:
    """
    Compute unified path for artwork file, migrating legacy locations if found.
    """
    if path_on_disk and os.path.exists(path_on_disk):
        return path_on_disk

    subdir = sha1[:2]
    unified = os.path.join(CACHE_DIR, subdir, sha1)
    if os.path.exists(unified):
        return unified

    legacy_candidates = [
        os.path.join(CACHE_DIR, "artistthumb", subdir, sha1),
        os.path.join(CACHE_DIR, "artist", subdir, sha1),
        os.path.join(CACHE_DIR, "album", subdir, sha1),
    ]
    for legacy in legacy_candidates:
        if os.path.exists(legacy):
            os.makedirs(os.path.dirname(unified), exist_ok=True)
            try:
                os.rename(legacy, unified)
                return unified
            except OSError:
                return legacy

    return unified

@router.get("/art/{art_id}")
async def get_artwork(art_id: int, max_size: int = 1000):
    """
    Serve artwork by ID, always converting to JPEG and resizing if needed.
    
    Args:
        art_id: Artwork database ID
        max_size: Maximum dimension (width or height) in pixels. Default 1000 for UPnP compatibility.
    """
    async for db in get_db():
        async with db.execute("SELECT sha1, path_on_disk FROM artwork WHERE id = ?", (art_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Artwork not found")
            
            sha1 = row["sha1"]
            path = _get_art_path(sha1, row["path_on_disk"])
            
            if not os.path.exists(path):
                raise HTTPException(status_code=404, detail="Artwork file missing")
            
            # Always re-encode as JPEG
            from PIL import Image
            with Image.open(path) as img:
                # Convert to RGB if needed (handles PNG with transparency)
                if img.mode in ('RGBA', 'LA', 'P'):
                    # Create white background for transparency
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'P':
                        img = img.convert('RGBA')
                    background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                    img = background
                elif img.mode != 'RGB':
                    img = img.convert('RGB')
                
                width, height = img.size
                
                # Resize if larger than max_size
                if width > max_size or height > max_size:
                    # Calculate new size maintaining aspect ratio
                    if width > height:
                        new_width = max_size
                        new_height = int(height * (max_size / width))
                    else:
                        new_height = max_size
                        new_width = int(width * (max_size / height))
                    
                    img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                
                # Save as JPEG to buffer
                buf = io.BytesIO()
                img.save(buf, format='JPEG', quality=90, optimize=True)
                buf.seek(0)
                
                # Return JPEG
                response = Response(content=buf.getvalue(), media_type="image/jpeg")
                response.headers["Cache-Control"] = "public, max-age=86400"  # Cache for 24 hours
                return response
    
    raise HTTPException(status_code=500, detail="Database error")

@router.get("/art/file/{sha1}")
async def get_artwork_by_sha1(sha1: str):
    # Lookup type to build path
    async for db in get_db():
        async with db.execute("SELECT path_on_disk FROM artwork WHERE sha1 = ?", (sha1,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Artwork not found")
            
            path = _get_art_path(sha1, row["path_on_disk"])
            
            if not os.path.exists(path):
                raise HTTPException(status_code=404, detail="Artwork file missing")
            
            # Since this is SHA1-based, we CAN cache it safely forever!
            # The URL uniquely identifies the content.
            response = FileResponse(path)
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            return response
    
    raise HTTPException(status_code=500, detail="Database error")

@router.get("/art/test")
async def get_test_artwork():
    """Serve a JPEG for UPnP album art testing (generated if Pillow is available)."""
    response = Response(content=_TEST_ART_BYTES, media_type="image/jpeg")
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response
