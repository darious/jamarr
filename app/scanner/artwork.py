import hashlib
import os
import shutil
from io import BytesIO
from typing import Any, Dict, Optional

import aiofiles
import httpx
from PIL import Image
from mutagen import File
from mutagen.flac import FLAC, Picture
from mutagen.id3 import ID3, APIC

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

    unified_path = _get_art_path(sha1)
    if os.path.exists(unified_path):
        return unified_path

    legacy_candidates = [
        os.path.join(CACHE_DIR, "artistthumb", sha1[:2], sha1),
        os.path.join(CACHE_DIR, "artist", sha1[:2], sha1),
        os.path.join(CACHE_DIR, "album", sha1[:2], sha1),
    ]

    for legacy in legacy_candidates:
        if os.path.exists(legacy):
            os.makedirs(os.path.dirname(unified_path), exist_ok=True)
            try:
                shutil.move(legacy, unified_path)
            except Exception:
                try:
                    shutil.copyfile(legacy, unified_path)
                except Exception:
                    return legacy
            return unified_path

    return unified_path

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
    Note: This function assumes it's called within a context where we can write to DB,
    but for separation of concerns, maybe it just returns the hash and we link it later?
    
    Actually, the plan said:
    - extract_artwork -> bytes
    - save_artwork -> hash
    
    Let's stick to that.
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
        
        # TODO: Add other formats (Vorbis, etc)
        
        return None
    except Exception:
        return None

async def _save_artwork_to_disk(data: bytes) -> str:
    """
    Save artwork to disk with subdirectory distribution.
    
    Args:
        data: Image data bytes
    
    Returns:
        Tuple of SHA1 hash and extracted metadata
    """
    sha1 = hashlib.sha1(data).hexdigest()
    path = _get_art_path(sha1)
    
    if not os.path.exists(path):
        # Create subdirectory if needed
        os.makedirs(os.path.dirname(path), exist_ok=True)
        async with aiofiles.open(path, "wb") as f:
            await f.write(data)
            
    meta = _extract_image_metadata(data)
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
            SELECT id, sha1 FROM artwork 
            WHERE id NOT IN (
                SELECT DISTINCT artwork_id FROM image_mapping
                UNION
                SELECT DISTINCT art_id FROM tracks WHERE art_id IS NOT NULL
                UNION
                SELECT DISTINCT art_id FROM artists WHERE art_id IS NOT NULL
                UNION
                SELECT DISTINCT art_id FROM albums WHERE art_id IS NOT NULL
            )
        """
        
        async with db.execute(sql) as cursor:
            rows = await cursor.fetchall()
            
        if not rows:
            return 0
            
        count = 0
        for row in rows:
            art_id, sha1 = row
            path = _resolve_or_migrate_art_path(sha1)
            
            # Delete file
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError as e:
                    print(f"Error removing artwork file {path}: {e}")
            
            # Delete DB entry
            await db.execute("DELETE FROM artwork WHERE id = ?", (art_id,))
            count += 1
            
        await db.commit()
        return count
        
    except Exception as e:
        print(f"Error extracting orphaned artwork: {e}")
        return 0

async def upsert_artwork_record(db, sha1: str, meta: Optional[Dict[str, Any]] = None, source: Optional[str] = None, source_url: Optional[str] = None) -> Optional[int]:
    """
    Insert or update an artwork row with the provided metadata and return its ID.
    """
    if not sha1:
        return None

    meta = meta or {}
    if sha1 and not meta.get("path_on_disk"):
        meta["path_on_disk"] = _resolve_or_migrate_art_path(sha1, meta.get("path_on_disk"))
    async with db.execute("SELECT id FROM artwork WHERE sha1 = ?", (sha1,)) as cursor:
        row = await cursor.fetchone()

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
        art_id = row[0]
        await db.execute(
            """
            UPDATE artwork
            SET mime=COALESCE(?, mime),
                width=COALESCE(?, width),
                height=COALESCE(?, height),
                path_on_disk=COALESCE(?, path_on_disk),
                filesize_bytes=COALESCE(?, filesize_bytes),
                image_format=COALESCE(?, image_format),
                source=COALESCE(?, source),
                source_url=COALESCE(?, source_url)
            WHERE id=?
            """,
            (*params, art_id),
        )
    else:
        await db.execute(
            """
            INSERT INTO artwork (sha1, mime, width, height, path_on_disk, filesize_bytes, image_format, source, source_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (sha1, *params),
        )
        async with db.execute("SELECT last_insert_rowid()") as id_cursor:
            art_id = (await id_cursor.fetchone())[0]

    return art_id

async def upsert_image_mapping(
    db,
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
        INSERT INTO image_mapping (artwork_id, entity_type, entity_id, image_type, score, created_at)
        VALUES (?, ?, ?, ?, ?, strftime('%s','now'))
        ON CONFLICT(entity_type, entity_id, image_type)
        DO UPDATE SET artwork_id=excluded.artwork_id,
                      score=COALESCE(excluded.score, image_mapping.score),
                      created_at=COALESCE(image_mapping.created_at, excluded.created_at)
        """,
        (artwork_id, entity_type, str(entity_id), image_type, score),
    )
