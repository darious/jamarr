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
from jamarr_tui.widgets.art_panel import ArtPanel
from jamarr_tui.widgets.player_bar import PlayerBar


def _fmt_duration(seconds: float | None) -> str:
    if not seconds:
        return ""
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    return f"{m:d}:{s:02d}"


def _normalize(item: dict[str, Any], artist_name: str) -> dict[str, Any]:
    local_id = item.get("local_track_id")
    title = item.get("name") or item.get("title") or "?"
    duration = item.get("duration_seconds")
    if not duration and item.get("duration_ms"):
        duration = item["duration_ms"] / 1000.0
    return {
        "id": local_id,
        "title": title,
        "artist": artist_name,
        "album": item.get("album") or "",
        "duration_seconds": duration or 0,
        "art_sha1": item.get("art_sha1"),
        "mb_release_id": item.get("mb_release_id"),
        "codec": item.get("codec"),
        "bit_depth": item.get("bit_depth"),
        "sample_rate_hz": item.get("sample_rate_hz"),
        "plays": item.get("plays"),
        "date": item.get("date"),
    }


class TrackListScreen(Screen):
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
    TrackListScreen #title {
        padding: 1 2 0 2;
        text-style: bold;
    }
    TrackListScreen #body {
        height: 1fr;
    }
    TrackListScreen ArtPanel {
        width: 50;
        height: 1fr;
        margin: 0 2;
    }
    TrackListScreen DataTable {
        height: 1fr;
        width: 1fr;
    }
    """

    def __init__(
        self,
        client: JamarrClient,
        controller: PlaybackController,
        *,
        title: str,
        kind: str,
        items: list[dict[str, Any]],
        artist_name: str = "",
        artist_art_sha1: str | None = None,
    ) -> None:
        super().__init__()
        self._client = client
        self._controller = controller
        self._screen_title = title
        self._kind = kind
        self._artist_name = artist_name
        self._artist_art_sha1 = artist_art_sha1
        self._tracks: list[dict[str, Any]] = [
            _normalize(i, artist_name) for i in items
        ]

    def compose(self) -> ComposeResult:
        yield Header()
        label = f"{self._screen_title} — {self._artist_name}" if self._artist_name else self._screen_title
        yield Static(label, id="title")
        with Horizontal(id="body"):
            sha1 = self._artist_art_sha1
            if not sha1:
                for t in self._tracks:
                    if t.get("art_sha1"):
                        sha1 = t["art_sha1"]
                        break
            yield ArtPanel(self._client, sha1)
            yield DataTable(id="tracks", cursor_type="row", zebra_stripes=True)
        yield PlayerBar(self._controller)
        yield Footer()

    async def on_mount(self) -> None:
        table = self.query_one("#tracks", DataTable)
        if self._kind == "most_listened":
            table.add_columns("Title", "Album", "Plays", "Duration")
        elif self._kind == "singles":
            table.add_columns("Title", "Date", "Duration")
        else:  # top_tracks
            table.add_columns("Title", "Album", "Duration")

        for t in self._tracks:
            in_lib = t.get("id") is not None
            style = "" if in_lib else "dim italic"
            title = Text(t.get("title") or "?", style=style)
            album = Text(t.get("album") or "", style=style)
            dur = Text(_fmt_duration(t.get("duration_seconds")), style=style)
            if self._kind == "most_listened":
                plays = Text(str(t.get("plays") or ""), style=style)
                table.add_row(title, album, plays, dur)
            elif self._kind == "singles":
                date = (t.get("date") or "")
                if isinstance(date, str) and len(date) >= 10:
                    date = date[:10]
                table.add_row(title, Text(str(date), style=style), dur)
            else:
                table.add_row(title, album, dur)

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
        selected = self._tracks[idx]
        if selected.get("id") is None:
            return
        # Queue only in-library tracks, find new start index relative to that queue.
        queue: list[dict[str, Any]] = []
        start = 0
        for i, t in enumerate(self._tracks):
            if t.get("id") is None:
                continue
            if i == idx:
                start = len(queue)
            queue.append(t)
        if not queue:
            return
        await self._controller.set_queue(queue, start_index=start)

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
