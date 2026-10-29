from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool
from app.config import get_art_resize_workers
from app.db import db_conn
from app.security import is_production
import asyncio
import os
import io
import logging
import tempfile
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime, formatdate
from datetime import timezone

log = logging.getLogger(__name__)

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


def _fit_within(width: int, height: int, target_size: int) -> tuple[int, int]:
    """Largest size with the same aspect ratio that fits in a target square.

    Never upscales, and never returns a zero dimension: a 10000x1 banner at
    600 comes back as 600x1, not 600x0.
    """
    if width <= target_size and height <= target_size:
        return width, height
    scale = target_size / max(width, height)
    return max(1, round(width * scale)), max(1, round(height * scale))


def _has_alpha(img) -> bool:
    if img.mode in ("RGBA", "LA", "PA", "RGBa", "La"):
        return True
    return img.mode == "P" and "transparency" in img.info


def _encode_resized(original_path: str, out, target_size: int) -> None:
    """Decode *original_path*, fit it in *target_size* and write a JPEG to *out*.

    Memory is kept proportional to the output, not the source, wherever the
    format allows: JPEGs are decoded at reduced scale (``draft``), everything is
    resized before it is converted, and transparency is flattened onto white
    only after the resize, so a transparent cover never allocates a
    full-resolution RGB background. Pillow resizes RGBA/LA through
    premultiplied alpha, so edges stay clean. Blocking.
    """
    from PIL import Image

    with Image.open(original_path) as img:
        width, height = img.size
        new_size = _fit_within(width, height, target_size)
        # JPEG only (no-op elsewhere): decode at 1/2, 1/4 or 1/8 scale while
        # staying at least as large as the output we need.
        img.draft(img.mode, new_size)

        if _has_alpha(img):
            if img.mode not in ("RGBA", "LA"):
                img = img.convert("RGBA")
            if img.size != new_size:
                img = img.resize(new_size, Image.Resampling.LANCZOS, reducing_gap=2.0)
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img, mask=img.getchannel("A"))
            img = background
        else:
            if img.mode not in ("RGB", "L", "CMYK"):
                # Modes the resampler cannot handle well (P, 1, I;16, ...).
                try:
                    img = img.convert("RGB")
                except ValueError:
                    img = img.convert("L")
            if img.size != new_size:
                img = img.resize(new_size, Image.Resampling.LANCZOS, reducing_gap=2.0)
            if img.mode != "RGB":
                img = img.convert("RGB")

        img.save(out, format="JPEG", quality=85, optimize=True)


def _create_resized(original_path: str, resized_path: str, target_size: int) -> None:
    """Resize *original_path* to fit target_size and publish it at *resized_path*.

    The JPEG is encoded into a uniquely named staging file in the same
    directory and renamed into place, so a reader (this process or another one
    sharing the cache) only ever sees a missing file or a complete one. A
    failure leaves nothing behind for the next request to trip over. Blocking.
    """
    resized_dir = os.path.dirname(resized_path)
    os.makedirs(resized_dir, exist_ok=True)
    if os.path.isfile(resized_path):
        return  # Published by another worker while we waited.
    fd, staging_path = tempfile.mkstemp(
        dir=resized_dir, prefix=f".{os.path.basename(resized_path)}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "wb") as out:
            _encode_resized(original_path, out, target_size)
            out.flush()
            os.fsync(out.fileno())
        os.chmod(staging_path, 0o644)  # mkstemp made it 0600
        os.replace(staging_path, resized_path)
    except BaseException:
        try:
            os.unlink(staging_path)
        except OSError:
            pass
        raise


# One resize per (artwork, size) per process. Waiters share the task and are
# shielded from each other: a cancelled request does not cancel the resize the
# others are waiting on. Coalescing is per process; across processes the atomic
# rename above keeps the cache correct, each process just resizes once itself.
_inflight: dict[tuple[str, int], asyncio.Task] = {}
_resize_pool: ThreadPoolExecutor | None = None


def _resize_executor() -> ThreadPoolExecutor:
    """A small pool of its own, so a grid of cold covers cannot flood the shared
    threadpool or decode more images at once than configured."""
    global _resize_pool
    if _resize_pool is None:
        _resize_pool = ThreadPoolExecutor(
            max_workers=get_art_resize_workers(), thread_name_prefix="art-resize"
        )
    return _resize_pool


def _forget_inflight(key: tuple[str, int], task: asyncio.Task) -> None:
    if _inflight.get(key) is task:
        del _inflight[key]
    if not task.cancelled():
        task.exception()  # Retrieved: every waiter may have gone away.


async def ensure_resized(original_path: str, resized_path: str, target_size: int) -> None:
    """Make sure *resized_path* exists, sharing in-flight work for the same key."""
    key = (resized_path, target_size)
    task = _inflight.get(key)
    if task is None or task.done():
        loop = asyncio.get_running_loop()

        async def _run() -> None:
            await loop.run_in_executor(
                _resize_executor(), _create_resized, original_path, resized_path, target_size
            )

        task = loop.create_task(_run())
        _inflight[key] = task
        task.add_done_callback(lambda t, key=key: _forget_inflight(key, t))
    await asyncio.shield(task)


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
    async with db_conn() as db:
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

        # Create if missing: one shared, bounded resize per key, published
        # atomically, so no request ever serves a half-written file.
        try:
            await ensure_resized(original_path, resized_path, target_size)
            return _cached_file_response(request, resized_path, sha1, "image/jpeg")
        except Exception as exc:
            # Fallback to original file on error
            log.warning("artwork %s: resize to %d failed (%s); serving original",
                        sha1, target_size, exc)

    # Fallback
    if not mime:
        mime = await run_in_threadpool(_sniff_mime, original_path)

    return _cached_file_response(request, original_path, sha1, mime)


@router.get("/art/renderer/{udn}")
async def get_renderer_icon(udn: str, request: Request, max_size: int = 0):
    async with db_conn() as db:
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
