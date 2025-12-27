from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import FileResponse
from app.db import get_db
import os
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

@router.get("/art/{artwork_id}")
@router.get("/art/{artwork_id}.jpg")
async def get_artwork(artwork_id: int, max_size: int = 1000):
    """
    Serve artwork by ID, always converting to JPEG and resizing if needed.
    """
    async for db in get_db():
        async with db.execute("SELECT sha1, path_on_disk FROM artwork WHERE id = ?", (artwork_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Artwork not found")
            
            sha1 = row["sha1"]
            path = _get_art_path(sha1, row["path_on_disk"])
            
            if not os.path.exists(path):
                raise HTTPException(status_code=404, detail="Artwork file missing")
            
            from PIL import Image
            try:
                with Image.open(path) as img:
                    # Convert to RGB if needed (handles PNG with transparency)
                    if img.mode in ('RGBA', 'LA', 'P'):
                        background = Image.new('RGB', img.size, (255, 255, 255))
                        if img.mode == 'P':
                            img = img.convert('RGBA')
                        background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                        img = background
                    elif img.mode != 'RGB':
                        img = img.convert('RGB')
                    
                    width, height = img.size
                    
                    # Resize logic
                    should_resize = width > max_size or height > max_size
                    if should_resize:
                        if width > height:
                            new_width = max_size
                            new_height = int(height * (max_size / width))
                        else:
                            new_height = max_size
                            new_width = int(width * (max_size / height))
                        
                        img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                    
                    # Save to buffer
                    buf = io.BytesIO()
                    quality = 95
                    img.save(buf, format='JPEG', quality=quality, optimize=True)
                    
                    # Enforce strict 1MB size limit for Naim/UPnP compatibility
                    # If too big, reduce quality loop
                    while buf.tell() > 1_000_000 and quality > 30:
                        buf.seek(0)
                        buf.truncate()
                        quality -= 15
                        img.save(buf, format='JPEG', quality=quality, optimize=True)

                    buf.seek(0)
                    
                    # Return JPEG
                    response = Response(content=buf.getvalue(), media_type="image/jpeg")
                    response.headers["Cache-Control"] = "public, max-age=86400"
                    return response
                    
            except Exception as e:
                pass
            
            # Fallback
            response = FileResponse(path)
            response.headers["Cache-Control"] = "no-cache"
            return response
    
    raise HTTPException(status_code=500, detail="Database error")

@router.get("/art/file/{sha1}")
async def get_artwork_by_sha1(sha1: str, max_size: int = 0):
    # Lookup type to build path
    async for db in get_db():
        async with db.execute("SELECT path_on_disk FROM artwork WHERE sha1 = ?", (sha1,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Artwork not found")
            
            path = _get_art_path(sha1, row["path_on_disk"])
            
            if not os.path.exists(path):
                raise HTTPException(status_code=404, detail="Artwork file missing")
            
            # If resizing requested
            if max_size > 0:
                from PIL import Image
                try:
                    with Image.open(path) as img:
                         # Convert to RGB if needed (handles PNG with transparency)
                        if img.mode in ('RGBA', 'LA', 'P'):
                            background = Image.new('RGB', img.size, (255, 255, 255))
                            if img.mode == 'P':
                                img = img.convert('RGBA')
                            background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                            img = background
                        elif img.mode != 'RGB':
                            img = img.convert('RGB')
                        
                        width, height = img.size
                        should_resize = width > max_size or height > max_size
                        
                        if should_resize:
                            if width > height:
                                new_width = max_size
                                new_height = int(height * (max_size / width))
                            else:
                                new_height = max_size
                                new_width = int(width * (max_size / height))
                            
                            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                        
                        buf = io.BytesIO()
                        # Use high quality for web, but reasonable size
                        img.save(buf, format='JPEG', quality=85, optimize=True)
                        buf.seek(0)
                        
                        response = Response(content=buf.getvalue(), media_type="image/jpeg")
                        # Immutable cache for resized artifacts too - they are derived from SHA1
                        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
                        return response
                except Exception as e:
                     # Fallback to original file on error
                     pass

            response = FileResponse(path)
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            return response
    
    raise HTTPException(status_code=500, detail="Database error")

@router.get("/art/test")
async def get_test_artwork():
    """Serve a JPEG for UPnP album art testing."""
    response = Response(content=_TEST_ART_BYTES, media_type="image/jpeg")
    response.headers["Cache-Control"] = "no-cache"
    return response
