from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from jamarr_tui.api.client import JamarrClient
from jamarr_tui.playback.controller import PlaybackController
from jamarr_tui.widgets.art_panel import ArtPanel
from jamarr_tui.widgets.player_bar import PlayerBar


def _fmt_duration(seconds: float | None) -> str:
    if not seconds:
        return ""
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    return f"{m:d}:{s:02d}"


class AlbumScreen(Screen):
    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("space", "toggle_pause", "Play/Pause"),
        Binding("comma", "prev_track", "Prev"),
        Binding("full_stop", "next_track", "Next"),
        Binding("left_square_bracket", "seek_back", "-10s"),
        Binding("right_square_bracket", "seek_fwd", "+10s"),
        Binding("q", "queue", "Queue"),
        Binding("n", "now_playing", "Now playing"),
    ]

    DEFAULT_CSS = """
    AlbumScreen #title {
        padding: 1 2 0 2;
        text-style: bold;
    }
    AlbumScreen #body {
        height: 1fr;
    }
    AlbumScreen ArtPanel {
        width: 50;
        height: 1fr;
        margin: 0 2;
    }
    AlbumScreen DataTable {
        height: 1fr;
        width: 1fr;
    }
    """

    def __init__(
        self,
        client: JamarrClient,
        controller: PlaybackController,
        album: dict[str, Any],
    ) -> None:
        super().__init__()
        self._client = client
        self._controller = controller
        self._album = album
        self._tracks: list[dict[str, Any]] = []

    def compose(self) -> ComposeResult:
        yield Header()
        title = self._album.get("album") or self._album.get("title") or "Album"
        artist = self._album.get("artist_name") or self._album.get("artist") or ""
        yield Static(f"{title} — {artist}", id="title")
        with Horizontal(id="body"):
            yield ArtPanel(self._client, self._album.get("art_sha1"))
            yield DataTable(id="tracks", cursor_type="row", zebra_stripes=True)
        yield PlayerBar(self._controller)
        yield Footer()

    async def on_mount(self) -> None:
        table = self.query_one("#tracks", DataTable)
        table.add_columns("#", "Title", "Duration")
        try:
            tracks = await self._client.album_tracks(
                album_mbid=self._album.get("album_mbid") or self._album.get("mb_release_id"),
                album=self._album.get("album"),
                artist=self._album.get("artist_name") or self._album.get("artist"),
            )
        except Exception as exc:  # noqa: BLE001
            table.add_row("?", f"Error: {exc}", "")
            return
        self._tracks = tracks or []
        for t in self._tracks:
            table.add_row(
                str(t.get("track_no") or ""),
                t.get("title") or "?",
                _fmt_duration(t.get("duration_seconds")),
            )
        # Track records carry art_sha1 even when the album dict doesn't, so
        # back-fill the panel from the first track if needed.
        if not self._album.get("art_sha1") and self._tracks:
            sha1 = self._tracks[0].get("art_sha1")
            if sha1:
                self.query_one(ArtPanel).set_sha1(sha1)

    def on_screen_suspend(self) -> None:
        for panel in self.query(ArtPanel):
            panel.suspend_graphics()

    def on_screen_resume(self) -> None:
        for panel in self.query(ArtPanel):
            panel.resume_graphics()

    async def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        idx = event.cursor_row
        if idx is None or idx < 0 or idx >= len(self._tracks):
            return
        queue = [t for t in self._tracks if t.get("id") is not None]
        await self._controller.set_queue(queue, start_index=idx)

    async def action_toggle_pause(self) -> None:
        await self._controller.toggle_pause()

    async def action_next_track(self) -> None:
        await self._controller.next()

    async def action_prev_track(self) -> None:
        await self._controller.prev()

    async def action_seek_back(self) -> None:
        await self._controller.seek_relative(-10.0)

    async def action_seek_fwd(self) -> None:
        await self._controller.seek_relative(10.0)

    def action_queue(self) -> None:
        from jamarr_tui.screens.queue import QueueScreen

        self.app.push_screen(QueueScreen(self._client, self._controller))

    def action_now_playing(self) -> None:
        from jamarr_tui.screens.now_playing import NowPlayingScreen

        self.app.push_screen(NowPlayingScreen(self._client, self._controller))
