from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool
from app.db import get_pool
from app.security import is_production
import os
import io
from email.utils import parsedate_to_datetime, formatdate
from datetime import timezone

def _build_test_art_bytes():
    """Generate a 600x600 JPEG test image; Pillow is required for the larger size."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (600, 600), (200, 50, 50)).save(buf, format="JPEG", quality=85)
    return buf.getvalue()


router = APIRouter()
CACHE_DIR = os.path.realpath("cache/art")
_TEST_ART_BYTES = _build_test_art_bytes()


def _safe_join(base: str, *parts: str) -> str:
    """Join path components under *base*, raising on traversal escape."""
    resolved = os.path.realpath(os.path.join(base, *parts))
    if not resolved.startswith(base + os.sep) and resolved != base:
        raise HTTPException(status_code=400, detail="Invalid path")
    return resolved


def _get_art_path(sha1: str, path_on_disk: str | None = None) -> str:
    """Compute unified path for artwork file, migrating legacy locations if found."""
    if path_on_disk and os.path.isfile(path_on_disk):
        return path_on_disk

    subdir = sha1[:2]
    unified = _safe_join(CACHE_DIR, subdir, sha1)
    if os.path.isfile(unified):
        return unified

    for legacy_dir in ("artistthumb", "artist", "album"):
        legacy = _safe_join(CACHE_DIR, legacy_dir, subdir, sha1)
        if os.path.isfile(legacy):
            os.makedirs(os.path.dirname(unified), exist_ok=True)
            try:
                os.rename(legacy, unified)
                return unified
            except OSError:
                return legacy

    return unified


if not is_production():

    @router.get("/art/test")
    async def get_test_artwork():
        """Serve a JPEG for UPnP album art testing."""
        response = Response(content=_TEST_ART_BYTES, media_type="image/jpeg")
        response.headers["Cache-Control"] = "no-cache"
        return response


ALLOWED_SIZES = [100, 200, 300, 400, 600]


def _snap_size(size: int) -> int:
    """Find the smallest allowed size >= requested size."""
    for s in ALLOWED_SIZES:
        if s >= size:
            return s
    return ALLOWED_SIZES[-1]

def _build_cache_headers(stat_result: os.stat_result, etag: str) -> dict:
    return {
        "Cache-Control": "public, max-age=31536000, immutable",
        "ETag": etag,
        "Last-Modified": formatdate(stat_result.st_mtime, usegmt=True),
    }


def _is_not_modified(request: Request, etag: str, stat_result: os.stat_result) -> bool:
    if_none_match = request.headers.get("if-none-match")
    if if_none_match and if_none_match.strip() == etag:
        return True

    if_modified_since = request.headers.get("if-modified-since")
    if if_modified_since:
        try:
            parsed = parsedate_to_datetime(if_modified_since)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            if stat_result.st_mtime <= parsed.timestamp():
                return True
        except Exception:
            pass

    return False


def _create_resized(original_path: str, resized_path: str, target_size: int) -> None:
    """Resize *original_path* to fit target_size and save as JPEG. Blocking."""
    from PIL import Image

    os.makedirs(os.path.dirname(resized_path), exist_ok=True)
    with Image.open(original_path) as img:
        # Convert to RGB if needed (handles PNG with transparency)
        if img.mode in ("RGBA", "LA", "P"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            background.paste(
                img,
                mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None,
            )
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")

        width, height = img.size
        if width > target_size or height > target_size:
            if width > height:
                new_width = target_size
                new_height = int(height * (target_size / width))
            else:
                new_height = target_size
                new_width = int(width * (target_size / height))

            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

        img.save(resized_path, format="JPEG", quality=85, optimize=True)


def _sniff_mime(path: str) -> str | None:
    """Guess image mime from file magic bytes. Blocking."""
    try:
        with open(path, "rb") as f:
            header = f.read(12)
            if header.startswith(b"\xff\xd8\xff"):
                return "image/jpeg"
            elif header.startswith(b"\x89PNG\r\n\x1a\n"):
                return "image/png"
            elif header.startswith(b"GIF8"):
                return "image/gif"
            elif header.startswith(b"RIFF") and header[8:12] == b"WEBP":
                return "image/webp"
    except Exception:
        pass
    return None


def _cached_file_response(
    request: Request, path: str, sha1: str, media_type: str | None
) -> Response:
    stat_result = os.stat(path)
    etag = f'W/"{sha1}-{int(stat_result.st_mtime)}-{stat_result.st_size}"'
    if _is_not_modified(request, etag, stat_result):
        return Response(status_code=304, headers=_build_cache_headers(stat_result, etag))
    response = FileResponse(path, media_type=media_type)
    response.headers.update(_build_cache_headers(stat_result, etag))
    return response


@router.api_route("/art/file/{sha1}", methods=["GET", "HEAD"])
async def get_artwork_by_sha1(sha1: str, request: Request, max_size: int = 0):
    if len(sha1) != 40 or any(c not in '0123456789abcdefABCDEF' for c in sha1):
        raise HTTPException(status_code=400, detail="Invalid SHA1 format")

    # Acquire briefly: the connection must not stay checked out while we do
    # file IO, image resizing, or send the response.
    async with get_pool().acquire() as db:
        row = await db.fetchrow(
            "SELECT path_on_disk, mime FROM artwork WHERE sha1 = $1", sha1
        )
    if not row:
        raise HTTPException(status_code=404, detail="Artwork not found")

    original_path = _get_art_path(sha1, row["path_on_disk"])
    mime = row["mime"]

    if not os.path.isfile(original_path):
        raise HTTPException(status_code=404, detail="Artwork file missing")

    # If resizing requested
    if max_size > 0:
        target_size = _snap_size(max_size)
        subdir = sha1[:2]
        resized_dir = _safe_join(CACHE_DIR, "resized", str(target_size), subdir)
        resized_path = os.path.join(resized_dir, sha1)

        # Serve from cache if exists
        if os.path.isfile(resized_path):  # lgtm[py/path-injection]
            return _cached_file_response(request, resized_path, sha1, "image/jpeg")

        # Create if missing; Pillow decode/resize is CPU-bound, keep it off
        # the event loop.
        try:
            await run_in_threadpool(
                _create_resized, original_path, resized_path, target_size
            )
            return _cached_file_response(request, resized_path, sha1, "image/jpeg")
        except Exception:
            # Fallback to original file on error
            pass

    # Fallback
    if not mime:
        mime = await run_in_threadpool(_sniff_mime, original_path)

    return _cached_file_response(request, original_path, sha1, mime)


@router.get("/art/renderer/{udn}")
async def get_renderer_icon(udn: str, request: Request, max_size: int = 0):
    async with get_pool().acquire() as db:
        row = await db.fetchrow(
            """
            SELECT a.sha1
            FROM image_map im
            JOIN artwork a ON im.artwork_id = a.id
            WHERE im.entity_type = 'renderer'
              AND im.entity_id = $1
              AND im.image_type = 'icon'
            """,
            udn,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Renderer icon not found")

    return await get_artwork_by_sha1(row["sha1"], max_size=max_size, request=request)
