from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from jamarr_tui.api.client import JamarrClient
from jamarr_tui.playback.controller import PlaybackController
from jamarr_tui.screens.album import AlbumScreen
from jamarr_tui.screens.track_list import TrackListScreen
from jamarr_tui.widgets.art_panel import ArtPanel
from jamarr_tui.widgets.player_bar import PlayerBar


_RELEASE_GROUPS: list[tuple[str, str]] = [
    ("album", "Albums"),
    ("ep", "EPs"),
    ("single", "Singles"),
    ("compilation", "Compilations"),
    ("live", "Live"),
    ("appears_on", "Appears On"),
]


class ArtistScreen(Screen):
    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("space", "toggle_pause", "Play/Pause"),
    ]

    DEFAULT_CSS = """
    ArtistScreen #title {
        padding: 1 2 0 2;
        text-style: bold;
    }
    ArtistScreen #body {
        height: 1fr;
    }
    ArtistScreen ArtPanel {
        width: 50;
        height: 1fr;
        margin: 0 2;
    }
    ArtistScreen DataTable {
        height: 1fr;
        width: 1fr;
    }
    """

    def __init__(
        self,
        client: JamarrClient,
        controller: PlaybackController,
        artist: dict[str, Any],
    ) -> None:
        super().__init__()
        self._client = client
        self._controller = controller
        self._artist = artist
        # Entries: (kind, payload). kind in {"header", "album", "tracks"}.
        self._entries: list[tuple[str, Any]] = []

    def compose(self) -> ComposeResult:
        yield Header()
        name = self._artist.get("name") or self._artist.get("artist") or "Artist"
        yield Static(name, id="title")
        with Horizontal(id="body"):
            yield ArtPanel(self._client, self._artist.get("art_sha1"))
            yield DataTable(id="albums", cursor_type="row", zebra_stripes=True)
        yield PlayerBar(self._controller)
        yield Footer()

    async def on_mount(self) -> None:
        table = self.query_one("#albums", DataTable)
        table.add_columns("Name", "Year", "Tracks")
        mbid = self._artist.get("mbid") or self._artist.get("artist_mbid")
        if not mbid:
            table.add_row("No artist mbid; cannot load albums.", "", "")
            return

        try:
            albums = await self._client.artist_albums(mbid)
        except Exception as exc:  # noqa: BLE001
            table.add_row(f"Error loading albums: {exc}", "", "")
            albums = []

        detail: dict[str, Any] = {}
        try:
            detail = await self._client.artist_detail(mbid) or {}
        except Exception:  # noqa: BLE001
            detail = {}

        # Group albums by release type, appears_on takes priority.
        groups: dict[str, list[dict[str, Any]]] = {k: [] for k, _ in _RELEASE_GROUPS}
        for a in albums or []:
            if (a.get("type") or "main") == "appears_on":
                groups["appears_on"].append(a)
                continue
            rt = (a.get("release_type") or "album").lower()
            if rt not in groups:
                rt = "album"
            groups[rt].append(a)

        for items in groups.values():
            items.sort(key=lambda a: (a.get("release_date") or ""), reverse=True)

        for key, label in _RELEASE_GROUPS:
            items = groups[key]
            if not items:
                continue
            self._entries.append(("header", f"── {label} ({len(items)}) ──"))
            for a in items:
                self._entries.append(("album", a))

        top_tracks = detail.get("top_tracks") or []
        most_listened = detail.get("most_listened") or []
        singles_tracks = detail.get("singles") or []
        artist_name = self._artist.get("name") or detail.get("name") or ""
        artist_art = self._artist.get("art_sha1") or detail.get("art_sha1")

        if top_tracks:
            self._entries.append((
                "tracks",
                {
                    "kind": "top_tracks",
                    "title": "Most Scrobbled",
                    "items": top_tracks,
                    "artist_name": artist_name,
                    "artist_art_sha1": artist_art,
                },
            ))
        if most_listened:
            self._entries.append((
                "tracks",
                {
                    "kind": "most_listened",
                    "title": "Most Listened",
                    "items": most_listened,
                    "artist_name": artist_name,
                    "artist_art_sha1": artist_art,
                },
            ))
        if singles_tracks:
            self._entries.append((
                "tracks",
                {
                    "kind": "singles",
                    "title": "Singles",
                    "items": singles_tracks,
                    "artist_name": artist_name,
                    "artist_art_sha1": artist_art,
                },
            ))

        if not self._entries:
            table.add_row("No releases or tracks for this artist.", "", "")
            return

        for kind, payload in self._entries:
            if kind == "header":
                table.add_row(Text(payload, style="bold cyan"), "", "")
            elif kind == "album":
                a = payload
                year = ""
                date = a.get("release_date") or a.get("year")
                if isinstance(date, str) and len(date) >= 4:
                    year = date[:4]
                title = a.get("album") or a.get("title") or "?"
                table.add_row(title, year, str(a.get("track_count") or ""))
            elif kind == "tracks":
                p = payload
                table.add_row(
                    Text(f"▶ {p['title']} ({len(p['items'])})", style="bold magenta"),
                    "",
                    "",
                )

    def on_screen_suspend(self) -> None:
        for panel in self.query(ArtPanel):
            panel.suspend_graphics()

    def on_screen_resume(self) -> None:
        for panel in self.query(ArtPanel):
            panel.resume_graphics()

    async def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        idx = event.cursor_row
        if idx is None or idx < 0 or idx >= len(self._entries):
            return
        kind, payload = self._entries[idx]
        if kind == "album":
            self.app.push_screen(
                AlbumScreen(self._client, self._controller, payload)
            )
        elif kind == "tracks":
            self.app.push_screen(
                TrackListScreen(
                    self._client,
                    self._controller,
                    title=payload["title"],
                    kind=payload["kind"],
                    items=payload["items"],
                    artist_name=payload.get("artist_name", ""),
                    artist_art_sha1=payload.get("artist_art_sha1"),
                )
            )
        # header rows: no action

    async def action_toggle_pause(self) -> None:
        await self._controller.toggle_pause()
