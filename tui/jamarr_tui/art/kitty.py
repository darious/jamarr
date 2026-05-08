"""Kitty graphics protocol support.

Used by Ghostty (Linux + macOS) and Kitty itself. We send the artwork as a
PNG via the protocol's transmission action, then re-place it at the panel's
screen coordinates on every render. Image scaling to the terminal cell box
is handled by the terminal via the `c`/`r` placement params.
"""

from __future__ import annotations

import base64
import logging
import os
import sys
from io import BytesIO

from PIL import Image

from jamarr_tui.art.cells import DEFAULT_CELL_ASPECT, clamp_cell_aspect

log = logging.getLogger("jamarr_tui.kitty")

# Cap the source PNG so the APC payload stays modest. Ghostty handles much
# larger, but anything above this is wasted: the terminal scales down to the
# cell box at draw time.
_MAX_PIXEL_DIM = 800
_CHUNK_BASE64 = 4096


def supported() -> bool:
    """Best-effort detect of Kitty / Ghostty terminals from env."""
    if os.environ.get("KITTY_WINDOW_ID"):
        return True
    if os.environ.get("GHOSTTY_RESOURCES_DIR") or os.environ.get("GHOSTTY_BIN_DIR"):
        return True
    term = os.environ.get("TERM", "")
    if "kitty" in term or "ghostty" in term:
        return True
    term_program = os.environ.get("TERM_PROGRAM", "")
    return term_program in ("ghostty", "Ghostty", "kitty")


def make_png(image_bytes: bytes) -> tuple[bytes, int, int]:
    """Decode the source image and re-encode as PNG, capped at _MAX_PIXEL_DIM.

    Returns (png_bytes, width_px, height_px) so callers can preserve aspect
    ratio when picking a cell box for placement.
    """
    img = Image.open(BytesIO(image_bytes)).convert("RGB")
    if max(img.size) > _MAX_PIXEL_DIM:
        scale = _MAX_PIXEL_DIM / float(max(img.size))
        img = img.resize(
            (int(img.size[0] * scale), int(img.size[1] * scale)),
            Image.LANCZOS,
        )
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue(), img.size[0], img.size[1]


def fit_cells(
    img_w_px: int,
    img_h_px: int,
    box_cols: int,
    box_rows: int,
    *,
    cell_aspect: float = DEFAULT_CELL_ASPECT,
) -> tuple[int, int]:
    """Pick (cols, rows) inside the box that preserves image aspect.

    *cell_aspect* is the terminal cell height-to-width ratio (typical
    monospace fonts are ~2:1). Square art renders into a cell box twice as
    wide as it is tall, hence the default.
    """
    if img_w_px <= 0 or img_h_px <= 0 or box_cols <= 0 or box_rows <= 0:
        return max(1, box_cols), max(1, box_rows)
    cell_aspect = clamp_cell_aspect(cell_aspect)
    img_aspect = img_w_px / img_h_px
    target_w_over_h = img_aspect * cell_aspect  # cols / rows
    box_w_over_h = box_cols / box_rows
    if target_w_over_h > box_w_over_h:
        # Image wider than box → match width.
        cols = box_cols
        rows = max(1, int(round(cols / target_w_over_h)))
    else:
        rows = box_rows
        cols = max(1, int(round(rows * target_w_over_h)))
    return cols, rows


def transmit(image_id: int, png_bytes: bytes) -> None:
    """Transmit (action 't') a PNG to the terminal under *image_id*."""
    encoded = base64.standard_b64encode(png_bytes).decode("ascii")
    out: list[str] = []
    i = 0
    n = len(encoded)
    first = True
    while i < n:
        chunk = encoded[i : i + _CHUNK_BASE64]
        i += _CHUNK_BASE64
        last = i >= n
        m = "0" if last else "1"
        if first:
            out.append(
                f"\x1b_Gf=100,a=t,i={image_id},q=2,m={m};{chunk}\x1b\\"
            )
            first = False
        else:
            out.append(f"\x1b_Gm={m};{chunk}\x1b\\")
    _write("".join(out))


def place(
    image_id: int,
    x: int,
    y: int,
    cols: int,
    rows: int,
    *,
    placement_id: int = 1,
) -> None:
    """Place a previously-transmitted image at terminal cell (x, y).

    A stable *placement_id* is required: without it Kitty/Ghostty create
    a brand new placement on every call, so refreshing the panel stacks
    placements on top of each other and the wrong one wins the draw order.
    """
    if cols <= 0 or rows <= 0:
        return
    # Save cursor → move → place (C=1 keeps cursor put after) → restore.
    seq = (
        "\x1b[s"
        f"\x1b[{y + 1};{x + 1}H"
        f"\x1b_Ga=p,i={image_id},p={placement_id},c={cols},r={rows},C=1,q=2"
        "\x1b\\"
        "\x1b[u"
    )
    _write(seq)


def delete_placement(image_id: int, placement_id: int = 1) -> None:
    """Remove a single placement, leaving the underlying image transmitted."""
    _write(
        f"\x1b_Ga=d,d=i,i={image_id},p={placement_id},q=2\x1b\\"
    )


def delete(image_id: int) -> None:
    _write(f"\x1b_Ga=d,d=i,i={image_id},q=2\x1b\\")


def _write(s: str) -> None:
    """Write straight to the controlling TTY, bypassing Textual's buffer."""
    try:
        sys.__stdout__.write(s)
        sys.__stdout__.flush()
    except Exception:
        log.exception("kitty write failed")
