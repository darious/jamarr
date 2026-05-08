from __future__ import annotations

import fcntl
import struct
import sys
import termios
from typing import TextIO

DEFAULT_CELL_ASPECT = 2.0
_MIN_CELL_ASPECT = 1.0
_MAX_CELL_ASPECT = 4.0


def clamp_cell_aspect(value: float | int | None) -> float:
    if value is None:
        return DEFAULT_CELL_ASPECT
    try:
        aspect = float(value)
    except (TypeError, ValueError):
        return DEFAULT_CELL_ASPECT
    if aspect <= 0:
        return DEFAULT_CELL_ASPECT
    return max(_MIN_CELL_ASPECT, min(_MAX_CELL_ASPECT, aspect))


def terminal_cell_aspect(default: float = DEFAULT_CELL_ASPECT) -> float:
    """Return terminal cell height / width from TIOCGWINSZ when available."""
    for stream in (sys.__stdout__, sys.stdout):
        aspect = _stream_cell_aspect(stream)
        if aspect is not None:
            return aspect
    return clamp_cell_aspect(default)


def _stream_cell_aspect(stream: TextIO) -> float | None:
    try:
        fd = stream.fileno()
    except (AttributeError, OSError):
        return None
    return _fd_cell_aspect(fd)


def _fd_cell_aspect(fd: int) -> float | None:
    try:
        rows, cols, width_px, height_px = struct.unpack(
            "HHHH",
            fcntl.ioctl(fd, termios.TIOCGWINSZ, struct.pack("HHHH", 0, 0, 0, 0)),
        )
    except OSError:
        return None
    if rows <= 0 or cols <= 0 or width_px <= 0 or height_px <= 0:
        return None
    cell_w = width_px / cols
    cell_h = height_px / rows
    return clamp_cell_aspect(cell_h / cell_w)
