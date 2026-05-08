from __future__ import annotations

import asyncio
import itertools
import logging

from rich.text import Text
from textual.events import Hide, Resize, Show
from textual.widget import Widget

from jamarr_tui.api.client import JamarrClient
from jamarr_tui.art.cells import terminal_cell_aspect
from jamarr_tui.art import kitty
from jamarr_tui.art.ascii import best_max_size, fetch_art_bytes, render_ascii

log = logging.getLogger("jamarr_tui.art_panel")

_image_id_seq = itertools.count(start=1000)


class ArtPanel(Widget):
    """Display artwork for a SHA1.

    Prefers the Kitty graphics protocol (Ghostty / Kitty) and falls back to
    half-block ANSI rendering elsewhere. The panel re-places / re-renders
    on resize and on track change.
    """

    DEFAULT_CSS = """
    ArtPanel {
        width: auto;
        height: auto;
        content-align: center middle;
    }
    """

    def __init__(
        self,
        client: JamarrClient,
        sha1: str | None = None,
        *,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self._client = client
        self._sha1 = sha1
        self._bytes: bytes | None = None
        self._content: Text | None = None
        self._rendered_for: tuple[int, int, float] | None = None
        self._fetch_task: asyncio.Task[None] | None = None
        self._kitty = kitty.supported()
        self._image_id = next(_image_id_seq)
        self._kitty_uploaded = False
        self._kitty_dims: tuple[int, int] | None = None  # (w_px, h_px)
        self._loaded_max_size: int = 0  # last fetched server size
        self._needs_load = False
        self._cell_aspect = terminal_cell_aspect()
        self._visible = True

    def render(self) -> Text:
        if not self._visible:
            return Text(" ")
        if self._kitty and self._kitty_uploaded and self._kitty_dims:
            box_cols = max(1, self.size.width)
            box_rows = max(1, self.size.height)
            cols, rows = kitty.fit_cells(
                self._kitty_dims[0],
                self._kitty_dims[1],
                box_cols,
                box_rows,
                cell_aspect=self._cell_aspect,
            )
            # Centre inside the panel so leftover cells stay symmetric.
            offset_x = (box_cols - cols) // 2
            offset_y = (box_rows - rows) // 2
            try:
                kitty.place(
                    self._image_id,
                    self.region.x + offset_x,
                    self.region.y + offset_y,
                    cols,
                    rows,
                )
            except Exception:
                log.exception("kitty.place failed")
            return Text("\n".join(" " * box_cols for _ in range(box_rows)))
        if self._content is None:
            return Text(" ")
        return self._content

    def set_sha1(self, sha1: str | None) -> None:
        if sha1 == self._sha1:
            return
        self._sha1 = sha1
        self._bytes = None
        self._content = None
        self._rendered_for = None
        self._loaded_max_size = 0
        if self._kitty and self._kitty_uploaded:
            kitty.delete(self._image_id)
            self._kitty_uploaded = False
            self._kitty_dims = None
        if sha1:
            self._spawn_fetch()
        self.refresh()

    async def on_mount(self) -> None:
        if self._sha1:
            self._needs_load = True

    def on_resize(self, _: Resize) -> None:
        # Defer the first fetch until we have a real size, so we can pick
        # the smallest server snap that still covers the box. Re-fetch when
        # the box grows past what we last loaded.
        self._cell_aspect = terminal_cell_aspect(self._cell_aspect)
        if self._sha1 and self.size.width > 0 and self.size.height > 0:
            target = best_max_size(
                self.size.width,
                self.size.height,
                cell_aspect=self._cell_aspect,
            )
            if self._needs_load or target > self._loaded_max_size:
                self._needs_load = False
                self._spawn_fetch()
        if self._kitty:
            self.refresh()
            return
        self._rerender()

    def on_hide(self, _: Hide) -> None:
        self.suspend_graphics()

    def on_show(self, _: Show) -> None:
        self.resume_graphics()

    def suspend_graphics(self) -> None:
        self._visible = False
        self._delete_kitty_placement()

    def resume_graphics(self) -> None:
        self._visible = True
        self.refresh()

    async def on_unmount(self) -> None:
        if self._kitty and self._kitty_uploaded:
            try:
                kitty.delete(self._image_id)
            except Exception:
                log.exception("kitty.delete failed")
            self._kitty_uploaded = False

    def _delete_kitty_placement(self) -> None:
        if not (self._kitty and self._kitty_uploaded):
            return
        try:
            kitty.delete_placement(self._image_id)
        except Exception:
            log.exception("kitty.delete_placement failed")

    def _spawn_fetch(self) -> None:
        if self._fetch_task and not self._fetch_task.done():
            self._fetch_task.cancel()
        self._fetch_task = asyncio.create_task(self._load())

    async def _load(self) -> None:
        sha1 = self._sha1
        if not sha1:
            return
        if self.size.width <= 0 or self.size.height <= 0:
            self._needs_load = True
            return
        self._cell_aspect = terminal_cell_aspect(self._cell_aspect)
        target = best_max_size(
            self.size.width,
            self.size.height,
            cell_aspect=self._cell_aspect,
        )
        data = await fetch_art_bytes(self._client, sha1, max_size=target)
        if sha1 != self._sha1:
            return
        self._bytes = data
        if not data:
            return
        self._loaded_max_size = target
        if self._kitty:
            try:
                png, w_px, h_px = kitty.make_png(data)
                kitty.transmit(self._image_id, png)
                self._kitty_uploaded = True
                self._kitty_dims = (w_px, h_px)
                self.refresh()
                return
            except Exception:
                log.exception("kitty transmit failed; falling back to ASCII")
                self._kitty = False
        self._rerender()

    def _rerender(self) -> None:
        if not self._bytes:
            return
        cols = self.size.width
        rows = self.size.height
        if cols < 4 or rows < 2:
            return
        rendered_for = (cols, rows, round(self._cell_aspect, 3))
        if self._rendered_for == rendered_for:
            return
        try:
            self._content = render_ascii(
                self._bytes,
                cols,
                rows,
                cell_aspect=self._cell_aspect,
            )
        except Exception:
            log.exception("render_ascii failed")
            return
        self._rendered_for = rendered_for
        self.refresh()
