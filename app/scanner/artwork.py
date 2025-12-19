import hashlib
import os
import aiofiles
import httpx
from mutagen import File
from mutagen.flac import FLAC, Picture
from mutagen.id3 import ID3, APIC

CACHE_DIR = "cache/art"

def _get_art_path(sha1: str, art_type: str) -> str:
    """
    Compute path for artwork file using subdirectory distribution.
    Uses first 2 characters of SHA1 hash for subdirectory (00-ff).
    
    Args:
        sha1: SHA1 hash of the artwork
        art_type: 'album' or 'artist'
    
    Returns:
        Full path to artwork file
    """
    subdir = sha1[:2]
    return os.path.join(CACHE_DIR, art_type, subdir, sha1)

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
    
    return await _save_artwork_to_disk(data, art_type='album')

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

async def _save_artwork_to_disk(data: bytes, art_type: str = 'album') -> str:
    """
    Save artwork to disk with subdirectory distribution.
    
    Args:
        data: Image data bytes
        art_type: 'album' or 'artist'
    
    Returns:
        SHA1 hash of the artwork
    """
    sha1 = hashlib.sha1(data).hexdigest()
    path = _get_art_path(sha1, art_type)
    
    if not os.path.exists(path):
        # Create subdirectory if needed
        os.makedirs(os.path.dirname(path), exist_ok=True)
        async with aiofiles.open(path, "wb") as f:
            await f.write(data)
            
    return sha1

async def download_and_save_artwork(url: str, art_type: str = 'artist') -> str:
    """
    Download artwork from URL and save to cache.
    
    Args:
        url: URL of the image to download
        art_type: 'album' or 'artist'
    
    Returns:
        SHA1 hash of the downloaded artwork, or None if download failed
    """
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, follow_redirects=True, timeout=30.0)
            if resp.status_code == 200:
                data = resp.content
                return await _save_artwork_to_disk(data, art_type)
    except Exception as e:
        print(f"Failed to download artwork from {url}: {e}")
        return None
