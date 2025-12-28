import hashlib
import os
import shutil
from io import BytesIO
from typing import Any, Dict, Optional
from datetime import datetime, timezone

import aiofiles
import httpx
import asyncpg
from PIL import Image
from mutagen import File
from mutagen.flac import FLAC, Picture
from mutagen.id3 import ID3, APIC
from mutagen.mp4 import MP4
from mutagen.oggvorbis import OggVorbis
import base64

CACHE_DIR = "cache/art"

def _get_art_path(sha1: str) -> str:
    """
    Compute unified path for artwork file using subdirectory distribution.
    Uses first 2 characters of SHA1 hash for subdirectory (00-ff).
    """
    subdir = sha1[:2]
    return os.path.join(CACHE_DIR, subdir, sha1)

def _resolve_or_migrate_art_path(sha1: str, path_on_disk: Optional[str] = None) -> str:
    """
    Return the best-known path for an artwork file, migrating legacy locations
    into the unified cache layout when found.
    """
    if path_on_disk and os.path.exists(path_on_disk):
        return path_on_disk

    # Check unified path with possible extensions
    # Order matters: check precise matches first then generic
    unified_base = _get_art_path(sha1)
    
    # 1. Check strict legacy (no ext)
    if os.path.exists(unified_base):
        return unified_base
        
    # 2. Check known extensions
    for ext in [".jpg", ".png", ".gif", ".webp", ".bmp", ".tiff"]:
        p = unified_base + ext
        if os.path.exists(p):
            return p

    # 3. Check legacy locations (and migrate)
    legacy_candidates = [
        os.path.join(CACHE_DIR, "artistthumb", sha1[:2], sha1),
        os.path.join(CACHE_DIR, "artist", sha1[:2], sha1),
        os.path.join(CACHE_DIR, "album", sha1[:2], sha1),
    ]

    for legacy in legacy_candidates:
        if os.path.exists(legacy):
            # Migrate to unified (no extension, as we don't know it yet easily without probing)
            # Or should we probe? For now, keep as legacy (no ext) in new location.
            os.makedirs(os.path.dirname(unified_base), exist_ok=True)
            try:
                shutil.move(legacy, unified_base)
            except Exception:
                try:
                    shutil.copyfile(legacy, unified_base)
                except Exception:
                    return legacy
            return unified_base

    # Default to base (caller might handle missing)
    return unified_base

def _extract_image_metadata(data: bytes) -> Dict[str, Any]:
    """Inspect image bytes to capture dimensions, mime, and format."""
    meta: Dict[str, Any] = {
        "width": None,
        "height": None,
        "mime": None,
        "image_format": None,
        "filesize_bytes": len(data) if data else None,
    }
    try:
        with Image.open(BytesIO(data)) as img:
            meta["width"], meta["height"] = img.size
            meta["image_format"] = img.format
            meta["mime"] = Image.MIME.get(img.format, None)
    except Exception:
        # Leave metadata empty if the image cannot be parsed
        pass
    return meta

async def extract_and_save_artwork(path: str) -> Optional[Dict[str, Any]]:
    """
    Extracts artwork from file at path, saves to cache, and returns details.
    """
    data = _extract_artwork_data(path)
    if not data:
        return None
    
    sha1, meta = await _save_artwork_to_disk(data)
    return {"sha1": sha1, "meta": meta}

def _extract_artwork_data(path: str) -> bytes:
    try:
        f = File(path)
        if not f:
            return None

        # FLAC
        if isinstance(f, FLAC):
            if f.pictures:
                return f.pictures[0].data

        # MP3 (ID3)
        if f.tags and isinstance(f.tags, ID3):
            for tag in f.tags.values():
                if isinstance(tag, APIC):
                    return tag.data

        # MP4 (M4A/ALAC)
        if isinstance(f, MP4):
            # covr is a list of MP4Cover objects (subclass of bytes)
            covers = f.tags.get("covr") if f.tags else None
            if covers:
                return bytes(covers[0])

        # Ogg Vorbis
        if isinstance(f, OggVorbis):
             # METADATA_BLOCK_PICTURE is base64 encoded FLAC Picture structure
             if f.tags:
                 pics = f.tags.get("metadata_block_picture", [])
                 if pics:
                     try:
                         p = Picture(base64.b64decode(pics[0]))
                         return p.data
                     except Exception:
                         pass
        
        # TODO: Add other formats (Vorbis, etc)
        
        return None
    except Exception:
        return None

async def _save_artwork_to_disk(data: bytes) -> str:
    """
    Save artwork to disk with subdirectory distribution and file extension.
    
    Args:
        data: Image data bytes
    
    Returns:
        Tuple of SHA1 hash and extracted metadata
    """
    sha1 = hashlib.sha1(data).hexdigest()
    
    # Extract metadata early to get format
    meta = _extract_image_metadata(data)
    
    # Determine extension
    ext = ""
    fmt = meta.get("image_format")
    if fmt == "JPEG": ext = ".jpg"
    elif fmt == "PNG": ext = ".png"
    elif fmt == "GIF": ext = ".gif"
    elif fmt == "WEBP": ext = ".webp"
    elif fmt == "BMP": ext = ".bmp"
    elif fmt == "TIFF": ext = ".tiff"
    
    # Build path with extension
    subdir = sha1[:2]
    filename = sha1 + ext
    path = os.path.join(CACHE_DIR, subdir, filename)
    
    # If extensionless file exists (legacy), we might want to rename it?
    # Or just check if 'path' exists.
    
    if not os.path.exists(path):
        # Create subdirectory if needed
        os.makedirs(os.path.dirname(path), exist_ok=True)
        async with aiofiles.open(path, "wb") as f:
            await f.write(data)
            
    meta["path_on_disk"] = path
    return sha1, meta

async def download_and_save_artwork(url: str, art_type: str = 'artistthumb') -> Optional[Dict[str, Any]]:
    """
    Download artwork from URL and save to cache.
    
    Args:
        url: URL of the image to download
        art_type: semantic role (kept for compatibility; not used for path)
    
    Returns:
        Dict with SHA1 hash, metadata, and source URL, or None if download failed
    """
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, follow_redirects=True, timeout=30.0)
            if resp.status_code == 200:
                data = resp.content
                sha1, meta = await _save_artwork_to_disk(data)
                return {"sha1": sha1, "meta": meta, "source_url": str(resp.url)}
    except Exception as e:
        print(f"Failed to download artwork from {url}: {e}")
        return None
    return None

async def cleanup_orphaned_artwork(db):
    """
    Remove artwork from cache and DB that is not referenced by any tracks or artists.
    """
    try:
        sql = """
            SELECT id, sha1, path_on_disk FROM artwork 
            WHERE id NOT IN (
                SELECT DISTINCT artwork_id FROM image_map
                UNION
                SELECT DISTINCT artwork_id FROM track WHERE artwork_id IS NOT NULL
                UNION
                SELECT DISTINCT artwork_id FROM artist WHERE artwork_id IS NOT NULL
                UNION
                SELECT DISTINCT artwork_id FROM album WHERE artwork_id IS NOT NULL
            )
        """
        
        rows = await db.fetch(sql)
            
        if not rows:
            return 0
            
        count = 0
        for row in rows:
            artwork_id, sha1, stored_path = row["id"], row["sha1"], row["path_on_disk"]
            path = _resolve_or_migrate_art_path(sha1, stored_path)
            
            # Delete file
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError as e:
                    print(f"Error removing artwork file {path}: {e}")
            
            # Delete DB entry
            await db.execute("DELETE FROM artwork WHERE id = $1", artwork_id)
            count += 1
        
        return count
        
    except Exception as e:
        print(f"Error extracting orphaned artwork: {e}")
        return 0

async def upsert_artwork_record(db: asyncpg.Connection, sha1: str, meta: Optional[Dict[str, Any]] = None, source: Optional[str] = None, source_url: Optional[str] = None) -> Optional[int]:
    """
    Insert or update an artwork row with the provided metadata and return its ID.
    """
    if not sha1:
        return None

    meta = meta or {}
    if sha1 and not meta.get("path_on_disk"):
        meta["path_on_disk"] = _resolve_or_migrate_art_path(sha1, meta.get("path_on_disk"))
    
    row = await db.fetchrow("SELECT id FROM artwork WHERE sha1 = $1", sha1)

    params = (
        meta.get("mime"),
        meta.get("width"),
        meta.get("height"),
        meta.get("path_on_disk"),
        meta.get("filesize_bytes"),
        meta.get("image_format"),
        source,
        source_url,
    )

    if row:
        artwork_id = row["id"]
        await db.execute(
            """
            UPDATE artwork
            SET mime=COALESCE($1, mime),
                width=COALESCE($2, width),
                height=COALESCE($3, height),
                path_on_disk=COALESCE($4, path_on_disk),
                filesize_bytes=COALESCE($5, filesize_bytes),
                image_format=COALESCE($6, image_format),
                source=COALESCE($7, source),
                source_url=COALESCE($8, source_url)
            WHERE id=$9
            """,
            *params, artwork_id,
        )
    else:
        artwork_id = await db.fetchval(
            """
            INSERT INTO artwork (sha1, mime, width, height, path_on_disk, filesize_bytes, image_format, source, source_url)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING id
            """,
            sha1, *params,
        )

    return artwork_id

async def upsert_image_mapping(
    db: asyncpg.Connection,
    artwork_id: int,
    entity_type: str,
    entity_id: str,
    image_type: str,
    score: Optional[float] = None,
):
    """
    Link an artwork to an entity/role. Replaces existing mapping for that role.
    """
    if not artwork_id or not entity_id:
        return

    await db.execute(
        """
        INSERT INTO image_map (artwork_id, entity_type, entity_id, image_type, score, created_at)
        VALUES ($1, $2, $3, $4, $5, NOW())
        ON CONFLICT(entity_type, entity_id, image_type)
        DO UPDATE SET artwork_id=excluded.artwork_id,
                      score=COALESCE(excluded.score, image_map.score),
                      created_at=COALESCE(image_map.created_at, excluded.created_at)
        """,
        artwork_id, entity_type, str(entity_id), image_type, score,
    )
