from __future__ import annotations

import logging
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import DataTable, Footer, Header, Input, Static

from jamarr_tui.api.client import JamarrClient
from jamarr_tui.playback.controller import PlaybackController
from jamarr_tui.widgets.player_bar import PlayerBar

log = logging.getLogger("jamarr_tui.playlists")


def _fmt_duration(seconds: float | None) -> str:
    if not seconds:
        return ""
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:d}:{s:02d}"


class _NameInputModal(ModalScreen[str]):
    """Single-line text prompt. Returns the entered string or None on cancel."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    _NameInputModal {
        align: center middle;
    }
    _NameInputModal #box {
        background: $panel;
        border: tall $accent;
        padding: 1 2;
        width: 60;
        height: auto;
    }
    _NameInputModal #prompt {
        text-style: bold;
        padding-bottom: 1;
    }
    """

    def __init__(self, prompt: str, *, initial: str = "") -> None:
        super().__init__()
        self._prompt = prompt
        self._initial = initial

    def compose(self) -> ComposeResult:
        with Vertical(id="box"):
            yield Static(self._prompt, id="prompt")
            yield Input(value=self._initial, id="name")

    def on_mount(self) -> None:
        self.query_one("#name", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        self.dismiss(value or None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class PlaylistsScreen(Screen):
    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("space", "toggle_pause", "Play/Pause"),
        Binding("c", "create", "Create"),
        Binding("d", "delete", "Delete"),
        Binding("R", "rename", "Rename"),
        Binding("r", "refresh", "Refresh"),
    ]

    DEFAULT_CSS = """
    PlaylistsScreen #title {
        padding: 1 2 0 2;
        text-style: bold;
        color: $accent;
    }
    PlaylistsScreen DataTable {
        height: 1fr;
    }
    PlaylistsScreen #status {
        padding: 0 2;
        color: $text-muted;
    }
    """

    def __init__(
        self, client: JamarrClient, controller: PlaybackController
    ) -> None:
        super().__init__()
        self._client = client
        self._controller = controller
        self._playlists: list[dict[str, Any]] = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Playlists", id="title")
        yield Static("", id="status")
        yield DataTable(id="playlists", cursor_type="row", zebra_stripes=True)
        yield PlayerBar(self._controller)
        yield Footer()

    async def on_mount(self) -> None:
        table = self.query_one("#playlists", DataTable)
        table.add_columns("Name", "Tracks", "Duration", "Updated")
        await self._load()

    async def _load(self) -> None:
        table = self.query_one("#playlists", DataTable)
        status = self.query_one("#status", Static)
        table.clear()
        status.update("Loading…")
        try:
            self._playlists = await self._client.list_playlists() or []
        except Exception as exc:  # noqa: BLE001
            status.update(f"Failed: {exc}")
            log.exception("list_playlists failed")
            return
        for p in self._playlists:
            updated = (p.get("updated_at") or "")[:10]
            table.add_row(
                p.get("name") or "?",
                str(p.get("track_count") or 0),
                _fmt_duration(p.get("total_duration")),
                str(updated),
            )
        status.update(
            f"{len(self._playlists)} playlist(s).  c create  R rename  d delete  Enter open"
        )

    async def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        idx = event.cursor_row
        if idx is None or idx < 0 or idx >= len(self._playlists):
            return
        self.app.push_screen(
            PlaylistScreen(
                self._client, self._controller, self._playlists[idx]
            )
        )

    async def action_create(self) -> None:
        name = await self.app.push_screen_wait(
            _NameInputModal("Playlist name:")
        )
        if not name:
            return
        try:
            await self._client.create_playlist(name)
        except Exception as exc:  # noqa: BLE001
            self.query_one("#status", Static).update(f"Create failed: {exc}")
            return
        await self._load()

    async def action_rename(self) -> None:
        idx = self.query_one("#playlists", DataTable).cursor_row
        if idx is None or idx < 0 or idx >= len(self._playlists):
            return
        p = self._playlists[idx]
        name = await self.app.push_screen_wait(
            _NameInputModal("New name:", initial=p.get("name") or "")
        )
        if not name:
            return
        try:
            await self._client.update_playlist(p["id"], name=name)
        except Exception as exc:  # noqa: BLE001
            self.query_one("#status", Static).update(f"Rename failed: {exc}")
            return
        await self._load()

    async def action_delete(self) -> None:
        idx = self.query_one("#playlists", DataTable).cursor_row
        if idx is None or idx < 0 or idx >= len(self._playlists):
            return
        p = self._playlists[idx]
        try:
            await self._client.delete_playlist(p["id"])
        except Exception as exc:  # noqa: BLE001
            self.query_one("#status", Static).update(f"Delete failed: {exc}")
            return
        await self._load()

    async def action_refresh(self) -> None:
        await self._load()

    async def action_toggle_pause(self) -> None:
        await self._controller.toggle_pause()


class PlaylistScreen(Screen):
    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("space", "toggle_pause", "Play/Pause"),
        Binding("d", "remove", "Remove"),
        Binding("delete", "remove", "Remove"),
        Binding("J", "move_down", "Move down"),
        Binding("K", "move_up", "Move up"),
        Binding("n", "now_playing", "Now playing"),
        Binding("q", "queue", "Queue"),
    ]

    DEFAULT_CSS = """
    PlaylistScreen #title {
        padding: 1 2 0 2;
        text-style: bold;
        color: $accent;
    }
    PlaylistScreen DataTable {
        height: 1fr;
    }
    PlaylistScreen #status {
        padding: 0 2;
        color: $text-muted;
    }
    """

    def __init__(
        self,
        client: JamarrClient,
        controller: PlaybackController,
        playlist: dict[str, Any],
    ) -> None:
        super().__init__()
        self._client = client
        self._controller = controller
        self._playlist_id = int(playlist["id"])
        self._playlist_name = playlist.get("name") or ""
        self._tracks: list[dict[str, Any]] = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(self._playlist_name, id="title")
        yield Static("", id="status")
        yield DataTable(id="tracks", cursor_type="row", zebra_stripes=True)
        yield PlayerBar(self._controller)
        yield Footer()

    async def on_mount(self) -> None:
        table = self.query_one("#tracks", DataTable)
        table.add_columns("#", "Title", "Artist", "Album", "Duration")
        await self._load()

    async def _load(self) -> None:
        table = self.query_one("#tracks", DataTable)
        status = self.query_one("#status", Static)
        table.clear()
        try:
            data = await self._client.get_playlist(self._playlist_id)
        except Exception as exc:  # noqa: BLE001
            status.update(f"Failed: {exc}")
            log.exception("get_playlist failed")
            return
        # Playlist API returns the track key as `track_id` (since `id`
        # belongs to the playlist row). Controller / mpv flow keys off
        # `id`, so always copy `track_id` over even when an `id` field
        # happens to be present.
        self._tracks = []
        for t in data.get("tracks") or []:
            d = dict(t)
            tid = d.get("track_id")
            if tid is not None:
                d["id"] = tid
            if d.get("id") is None:
                log.warning("playlist track without id, skipping: %r", d)
                continue
            self._tracks.append(d)
        log.info(
            "playlist %s loaded: %d tracks (first id=%s, title=%r)",
            self._playlist_id,
            len(self._tracks),
            self._tracks[0].get("id") if self._tracks else None,
            self._tracks[0].get("title") if self._tracks else None,
        )
        for i, t in enumerate(self._tracks, start=1):
            table.add_row(
                str(i),
                t.get("title") or "?",
                t.get("artist") or "",
                t.get("album") or "",
                _fmt_duration(t.get("duration_seconds")),
            )
        total = sum(float(t.get("duration_seconds") or 0.0) for t in self._tracks)
        status.update(
            f"{len(self._tracks)} tracks · total {_fmt_duration(total)}  ·  "
            "Enter play  d remove  J/K reorder"
        )

    async def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        idx = event.cursor_row
        if idx is None or idx < 0 or idx >= len(self._tracks):
            return
        await self._controller.set_queue(self._tracks, start_index=idx)

    async def action_remove(self) -> None:
        idx = self.query_one("#tracks", DataTable).cursor_row
        if idx is None or idx < 0 or idx >= len(self._tracks):
            return
        track = self._tracks[idx]
        playlist_track_id = track.get("playlist_track_id")
        if not playlist_track_id:
            return
        try:
            await self._client.remove_track_from_playlist(
                self._playlist_id, int(playlist_track_id)
            )
        except Exception as exc:  # noqa: BLE001
            self.query_one("#status", Static).update(f"Remove failed: {exc}")
            return
        await self._load()

    async def action_move_down(self) -> None:
        await self._move(+1)

    async def action_move_up(self) -> None:
        await self._move(-1)

    async def _move(self, delta: int) -> None:
        table = self.query_one("#tracks", DataTable)
        idx = table.cursor_row
        if idx is None:
            return
        target = idx + delta
        if target < 0 or target >= len(self._tracks):
            return
        new_tracks = list(self._tracks)
        new_tracks[idx], new_tracks[target] = new_tracks[target], new_tracks[idx]
        ordering = [
            int(t["playlist_track_id"]) for t in new_tracks if t.get("playlist_track_id")
        ]
        try:
            await self._client.reorder_playlist(self._playlist_id, ordering)
        except Exception as exc:  # noqa: BLE001
            self.query_one("#status", Static).update(f"Reorder failed: {exc}")
            return
        await self._load()
        try:
            self.query_one("#tracks", DataTable).move_cursor(row=target)
        except Exception:
            pass

    def action_now_playing(self) -> None:
        from jamarr_tui.screens.now_playing import NowPlayingScreen

        self.app.push_screen(NowPlayingScreen(self._client, self._controller))

    def action_queue(self) -> None:
        from jamarr_tui.screens.queue import QueueScreen

        self.app.push_screen(QueueScreen(self._client, self._controller))

    async def action_toggle_pause(self) -> None:
        await self._controller.toggle_pause()
