from __future__ import annotations

import asyncio
import logging
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Input, Static

from jamarr_tui.api.client import JamarrClient
from jamarr_tui.playback.controller import PlaybackController
from jamarr_tui.screens.album import AlbumScreen
from jamarr_tui.screens.artist import ArtistScreen
from jamarr_tui.widgets.player_bar import PlayerBar

log = logging.getLogger("jamarr_tui.search")


def _fmt_duration(seconds: float | None) -> str:
    if not seconds:
        return ""
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    return f"{m:d}:{s:02d}"


class SearchScreen(Screen):
    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("space", "toggle_pause", "Play/Pause"),
    ]

    DEFAULT_CSS = """
    SearchScreen Input {
        margin: 1 2 0 2;
    }
    SearchScreen .section-title {
        padding: 1 2 0 2;
        text-style: bold;
        color: $accent;
    }
    SearchScreen #status {
        padding: 0 2;
        color: $text-muted;
    }
    SearchScreen DataTable {
        height: auto;
        max-height: 12;
    }
    SearchScreen VerticalScroll {
        height: 1fr;
    }
    """

    DEBOUNCE_S = 0.3

    def __init__(self, client: JamarrClient, controller: PlaybackController) -> None:
        super().__init__()
        self._client = client
        self._controller = controller
        self._artists: list[dict[str, Any]] = []
        self._albums: list[dict[str, Any]] = []
        self._tracks: list[dict[str, Any]] = []
        self._debounce_task: asyncio.Task[None] | None = None
        self._inflight: asyncio.Task[None] | None = None
        self._last_query: str = ""

    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(placeholder="Search artists, albums, tracks…", id="q")
        yield Static("", id="status")
        with VerticalScroll():
            yield Static("Artists", classes="section-title", id="t-artists")
            yield DataTable(id="artists", cursor_type="row", zebra_stripes=True)
            yield Static("Albums", classes="section-title", id="t-albums")
            yield DataTable(id="albums", cursor_type="row", zebra_stripes=True)
            yield Static("Tracks", classes="section-title", id="t-tracks")
            yield DataTable(id="tracks", cursor_type="row", zebra_stripes=True)
        yield PlayerBar(self._controller)
        yield Footer()

    async def on_mount(self) -> None:
        self.query_one("#artists", DataTable).add_columns("Artist")
        self.query_one("#albums", DataTable).add_columns("Album", "Artist")
        self.query_one("#tracks", DataTable).add_columns(
            "Title", "Artist", "Album", "Duration"
        )
        self.query_one("#q", Input).focus()

    # -- query handling --------------------------------------------------------

    async def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "q":
            return
        q = event.value.strip()
        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()
        if len(q) < 2:
            self._clear_results()
            self._set_status("")
            return
        self._debounce_task = asyncio.create_task(self._debounced_run(q))

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "q":
            return
        q = event.value.strip()
        if len(q) >= 2:
            await self._run(q)

    async def _debounced_run(self, q: str) -> None:
        try:
            await asyncio.sleep(self.DEBOUNCE_S)
        except asyncio.CancelledError:
            return
        await self._run(q)

    async def _run(self, q: str) -> None:
        if self._inflight and not self._inflight.done():
            self._inflight.cancel()
        self._last_query = q
        self._set_status("Searching…")
        self._inflight = asyncio.create_task(self._do_search(q))

    async def _do_search(self, q: str) -> None:
        try:
            data = await self._client.search(q)
        except asyncio.CancelledError:
            return
        except Exception as exc:  # noqa: BLE001
            log.exception("search failed")
            self._set_status(f"Search failed: {exc}")
            return
        # If the query has moved on, ignore stale response.
        if q != self._last_query:
            return
        self._artists = data.get("artists") or []
        self._albums = data.get("albums") or []
        self._tracks = data.get("tracks") or []
        self._render_results()
        total = len(self._artists) + len(self._albums) + len(self._tracks)
        if total == 0:
            self._set_status("No results")
        else:
            self._set_status(
                f"{len(self._artists)} artists · {len(self._albums)} albums · "
                f"{len(self._tracks)} tracks"
            )

    # -- rendering -------------------------------------------------------------

    def _clear_results(self) -> None:
        self._artists = []
        self._albums = []
        self._tracks = []
        self._render_results()

    def _render_results(self) -> None:
        artists = self.query_one("#artists", DataTable)
        albums = self.query_one("#albums", DataTable)
        tracks = self.query_one("#tracks", DataTable)
        artists.clear()
        albums.clear()
        tracks.clear()
        for a in self._artists:
            artists.add_row(a.get("name") or "?")
        for a in self._albums:
            albums.add_row(
                a.get("title") or a.get("album") or "?",
                a.get("artist") or "",
            )
        for t in self._tracks:
            tracks.add_row(
                t.get("title") or "?",
                t.get("artist") or "",
                t.get("album") or "",
                _fmt_duration(t.get("duration_seconds")),
            )

    def _set_status(self, msg: str) -> None:
        self.query_one("#status", Static).update(msg)

    # -- selection -------------------------------------------------------------

    async def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        table_id = event.data_table.id
        idx = event.cursor_row
        if idx is None or idx < 0:
            return
        if table_id == "artists" and idx < len(self._artists):
            await self._open_artist(self._artists[idx])
        elif table_id == "albums" and idx < len(self._albums):
            await self._open_album(self._albums[idx])
        elif table_id == "tracks" and idx < len(self._tracks):
            await self._play_track(self._tracks[idx])

    async def _open_artist(self, artist: dict[str, Any]) -> None:
        self.app.push_screen(ArtistScreen(self._client, self._controller, artist))

    async def _open_album(self, album: dict[str, Any]) -> None:
        # Search returns {title, artist, mbid}; AlbumScreen reads
        # album_mbid/mb_release_id and falls back to album+artist.
        norm = {
            "album": album.get("title") or album.get("album"),
            "artist_name": album.get("artist"),
            "album_mbid": album.get("mbid") or album.get("album_mbid"),
            "mb_release_id": album.get("mbid") or album.get("mb_release_id"),
            "art_sha1": album.get("art_sha1"),
        }
        self.app.push_screen(AlbumScreen(self._client, self._controller, norm))

    async def _play_track(self, track: dict[str, Any]) -> None:
        # Single-track queue. Server still records history via the same
        # progress threshold path AlbumScreen relies on.
        await self._controller.set_queue([track], start_index=0)

    # -- actions ---------------------------------------------------------------

    def action_back(self) -> None:
        self.app.pop_screen()

    async def action_toggle_pause(self) -> None:
        await self._controller.toggle_pause()
