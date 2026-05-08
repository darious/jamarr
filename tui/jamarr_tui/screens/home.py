from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from jamarr_tui.api.client import JamarrClient
from jamarr_tui.playback.controller import PlaybackController
from jamarr_tui.screens.album import AlbumScreen
from jamarr_tui.screens.artist import ArtistScreen
from jamarr_tui.screens.now_playing import NowPlayingScreen
from jamarr_tui.screens.queue import QueueScreen
from jamarr_tui.screens.search import SearchScreen
from jamarr_tui.widgets.player_bar import PlayerBar


# Each section: (table_id, heading, fetcher attr name, kind, column titles).
_AlbumSection = ("album", ("Album", "Artist", "Year"))
_ArtistSection = ("artist", ("Artist",))


class HomeScreen(Screen):
    BINDINGS = [
        Binding("space", "toggle_pause", "Play/Pause"),
        Binding("Q", "app.quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("slash", "search", "Search"),
        Binding("q", "queue", "Queue"),
        Binding("n", "now_playing", "Now playing"),
        Binding("p", "playlists", "Playlists"),
    ]

    DEFAULT_CSS = """
    HomeScreen VerticalScroll {
        height: 1fr;
    }
    HomeScreen .section-title {
        padding: 1 2 0 2;
        text-style: bold;
        color: $accent;
    }
    HomeScreen DataTable {
        height: auto;
        max-height: 12;
    }
    """

    SECTIONS: list[tuple[str, str, str, str, tuple[str, ...]]] = [
        ("new-releases", "New releases", "new_releases", "album", ("Album", "Artist", "Year")),
        ("recent-albums", "Recently added albums", "recently_added_albums", "album", ("Album", "Artist", "Year")),
        ("played-albums", "Recently played albums", "recently_played_albums", "album", ("Album", "Artist", "Year")),
        ("discover-artists", "Discover (newly added) artists", "discover_artists", "artist", ("Artist",)),
        ("played-artists", "Recently played artists", "recently_played_artists", "artist", ("Artist",)),
    ]

    def __init__(self, client: JamarrClient, controller: PlaybackController) -> None:
        super().__init__()
        self._client = client
        self._controller = controller
        self._data: dict[str, list[dict[str, Any]]] = {}

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll():
            for table_id, heading, _, _, _ in self.SECTIONS:
                yield Static(heading, classes="section-title", id=f"t-{table_id}")
                yield DataTable(id=table_id, cursor_type="row", zebra_stripes=True)
        yield PlayerBar(self._controller)
        yield Footer()

    async def on_mount(self) -> None:
        for table_id, _, _, _, columns in self.SECTIONS:
            table = self.query_one(f"#{table_id}", DataTable)
            table.add_columns(*columns)
        await self._load()

    async def _load(self) -> None:
        # Fire all fetches in parallel; render each as it lands.
        async def fetch(section: tuple[str, str, str, str, tuple[str, ...]]) -> None:
            table_id, _, attr, kind, columns = section
            table = self.query_one(f"#{table_id}", DataTable)
            ncols = len(columns)
            table.clear()
            try:
                fetcher: Callable[..., Awaitable[list[dict[str, Any]]]] = getattr(
                    self._client, attr
                )
                rows = await fetcher(limit=20)
            except Exception as exc:  # noqa: BLE001
                cells = [f"Error: {exc}"] + [""] * (ncols - 1)
                table.add_row(*cells)
                return
            self._data[table_id] = rows or []
            for r in self._data[table_id]:
                if kind == "album":
                    title = r.get("album") or r.get("title") or "?"
                    artist = r.get("artist_name") or r.get("artist") or ""
                    year = ""
                    date = r.get("release_date") or r.get("year")
                    if isinstance(date, str) and len(date) >= 4:
                        year = date[:4]
                    elif date is not None:
                        year = str(date)[:4]
                    table.add_row(title, artist, year)
                else:
                    table.add_row(r.get("name") or "?")
            if not self._data[table_id]:
                table.add_row(*["—"] * ncols)

        await asyncio.gather(*(fetch(s) for s in self.SECTIONS))

    async def action_refresh(self) -> None:
        await self._load()

    async def action_toggle_pause(self) -> None:
        await self._controller.toggle_pause()

    def action_search(self) -> None:
        self.app.push_screen(SearchScreen(self._client, self._controller))

    def action_queue(self) -> None:
        self.app.push_screen(QueueScreen(self._client, self._controller))

    def action_now_playing(self) -> None:
        self.app.push_screen(NowPlayingScreen(self._client, self._controller))

    def action_playlists(self) -> None:
        from jamarr_tui.screens.playlists import PlaylistsScreen

        self.app.push_screen(PlaylistsScreen(self._client, self._controller))

    async def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        table_id = event.data_table.id
        if table_id is None:
            return
        rows = self._data.get(table_id, [])
        idx = event.cursor_row
        if idx is None or idx < 0 or idx >= len(rows):
            return
        section = next((s for s in self.SECTIONS if s[0] == table_id), None)
        if section is None:
            return
        kind = section[3]
        item = rows[idx]
        if kind == "album":
            self.app.push_screen(AlbumScreen(self._client, self._controller, item))
        else:
            self.app.push_screen(ArtistScreen(self._client, self._controller, item))
