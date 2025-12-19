import hashlib
import os
import aiofiles
from mutagen import File
from mutagen.flac import FLAC, Picture
from mutagen.id3 import ID3, APIC

CACHE_DIR = "cache/art"

async def extract_and_save_artwork(path: str) -> int:
    """
    Extracts artwork from file at path, saves to cache, returns art_id (DB ID).
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
    
    return await _save_artwork_to_disk(data)

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
    sha1 = hashlib.sha1(data).hexdigest()
    path = os.path.join(CACHE_DIR, sha1)
    
    if not os.path.exists(path):
        async with aiofiles.open(path, "wb") as f:
            await f.write(data)
            
    return sha1
