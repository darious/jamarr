"""Artwork → ANSI text.

Renders an album/artist artwork SHA1 into a Rich `Text` block of half-block
characters (`▀`). Each character cell carries the colour of the upper pixel
in its foreground and the lower pixel in its background, doubling the
vertical resolution we get out of a terminal cell.
"""

from __future__ import annotations

import logging
import os
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image
from rich.color import Color
from rich.style import Style
from rich.text import Text

from jamarr_tui.art.cells import DEFAULT_CELL_ASPECT, clamp_cell_aspect

if TYPE_CHECKING:
    from jamarr_tui.api.client import JamarrClient

log = logging.getLogger("jamarr_tui.art")

CACHE_DIR = Path(os.path.expanduser("~/.cache/jamarr-tui/art"))

# Server snaps requested max_size to one of these (see app/media/art.py).
_ALLOWED_SIZES = (100, 200, 300, 400, 600)
# Approximate terminal cell width for sizing the source image. Height is
# derived from the measured terminal cell aspect when available.
_CELL_W_PX = 10


def best_max_size(
    box_cols: int,
    box_rows: int,
    *,
    cell_aspect: float = DEFAULT_CELL_ASPECT,
) -> int:
    """Pick the smallest server snap that comfortably covers the box."""
    aspect = clamp_cell_aspect(cell_aspect)
    target = max(box_cols * _CELL_W_PX, int(box_rows * _CELL_W_PX * aspect))
    for s in _ALLOWED_SIZES:
        if s >= target:
            return s
    return _ALLOWED_SIZES[-1]


def _cache_path(sha1: str, max_size: int) -> Path:
    return CACHE_DIR / f"{sha1}-{max_size}"


async def fetch_art_bytes(
    client: "JamarrClient", sha1: str, *, max_size: int = 600
) -> bytes | None:
    """Fetch (and cache) the raw artwork bytes for a sha1."""
    if not sha1:
        return None
    path = _cache_path(sha1, max_size)
    if path.is_file():
        try:
            return path.read_bytes()
        except OSError:
            pass
    try:
        data = await client.fetch_art(sha1, max_size=max_size)
    except Exception:
        log.exception("fetch_art_bytes failed for %s", sha1)
        return None
    if not data:
        return None
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    except OSError:
        log.exception("art cache write failed for %s", sha1)
    return data


def render_ascii(
    image_bytes: bytes,
    cols: int,
    rows: int,
    *,
    cell_aspect: float = DEFAULT_CELL_ASPECT,
) -> Text:
    """Render *image_bytes* into a Rich `Text` block sized to (cols, rows)."""
    cols = max(2, int(cols))
    rows = max(1, int(rows))
    cell_aspect = clamp_cell_aspect(cell_aspect)
    img = Image.open(BytesIO(image_bytes)).convert("RGB")
    # Each terminal cell shows two vertical pixels, so we sample twice as many
    # rows of pixels. Preserve physical aspect by fitting inside the box after
    # correcting for the terminal's cell height-to-width ratio.
    src_w, src_h = img.size
    target_w, target_h = cols, rows * 2
    source_ratio_in_half_block_grid = (src_w / src_h) * (cell_aspect / 2.0)
    box_ratio = target_w / target_h
    if source_ratio_in_half_block_grid > box_ratio:
        # Wider than the box → match width, shrink height.
        new_w = target_w
        new_h = max(2, int(round(target_w / source_ratio_in_half_block_grid)))
        new_h -= new_h % 2
    else:
        new_h = target_h
        new_w = max(1, int(round(target_h * source_ratio_in_half_block_grid)))
    img = img.resize((new_w, new_h), Image.LANCZOS)
    px = img.load()
    actual_rows = new_h // 2
    text = Text(no_wrap=True, overflow="crop")
    for y in range(actual_rows):
        for x in range(new_w):
            top = px[x, y * 2]
            bot = px[x, y * 2 + 1]
            style = Style(
                color=Color.from_rgb(*top),
                bgcolor=Color.from_rgb(*bot),
            )
            text.append("▀", style=style)
        if y < actual_rows - 1:
            text.append("\n")
    return text
