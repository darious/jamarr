from __future__ import annotations

from io import BytesIO

from PIL import Image

from jamarr_tui.art.ascii import best_max_size, render_ascii
from jamarr_tui.art.cells import clamp_cell_aspect
from jamarr_tui.art.kitty import fit_cells


def _png(width: int, height: int) -> bytes:
    img = Image.new("RGB", (width, height), (255, 0, 0))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_kitty_square_art_uses_measured_cell_aspect() -> None:
    assert fit_cells(600, 600, 80, 40, cell_aspect=2.0) == (80, 40)
    assert fit_cells(600, 600, 80, 40, cell_aspect=2.4) == (80, 33)


def test_ascii_square_art_uses_measured_cell_aspect() -> None:
    text = render_ascii(_png(600, 600), 80, 40, cell_aspect=2.4)
    lines = text.plain.splitlines()

    assert len(lines) == 33
    assert {len(line) for line in lines} == {80}


def test_best_max_size_uses_measured_cell_height() -> None:
    assert best_max_size(10, 25, cell_aspect=2.0) == 600
    assert best_max_size(10, 25, cell_aspect=1.0) == 300


def test_cell_aspect_is_clamped_to_reasonable_bounds() -> None:
    assert clamp_cell_aspect(None) == 2.0
    assert clamp_cell_aspect(0) == 2.0
    assert clamp_cell_aspect(0.5) == 1.0
    assert clamp_cell_aspect(5) == 4.0
