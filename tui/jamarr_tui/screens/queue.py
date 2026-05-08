from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from jamarr_tui.api.client import JamarrClient
from jamarr_tui.playback.controller import PlaybackController
from jamarr_tui.widgets.player_bar import PlayerBar


def _fmt_duration(seconds: float | None) -> str:
    if not seconds:
        return ""
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    return f"{m:d}:{s:02d}"


class QueueScreen(Screen):
    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("space", "toggle_pause", "Play/Pause"),
        Binding("comma", "prev_track", "Prev"),
        Binding("full_stop", "next_track", "Next"),
        Binding("d", "remove", "Remove"),
        Binding("delete", "remove", "Remove"),
        Binding("J", "move_down", "Move down"),
        Binding("K", "move_up", "Move up"),
        Binding("c", "clear", "Clear"),
        Binding("n", "now_playing", "Now playing"),
    ]

    DEFAULT_CSS = """
    QueueScreen #title {
        padding: 1 2 0 2;
        text-style: bold;
    }
    QueueScreen DataTable {
        height: 1fr;
    }
    QueueScreen #status {
        padding: 0 2 1 2;
        color: $text-muted;
    }
    """

    def __init__(
        self, client: JamarrClient, controller: PlaybackController
    ) -> None:
        super().__init__()
        self._client = client
        self._controller = controller

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Queue", id="title")
        yield Static("", id="status")
        yield DataTable(id="queue", cursor_type="row", zebra_stripes=True)
        yield PlayerBar(self._controller)
        yield Footer()

    async def on_mount(self) -> None:
        table = self.query_one("#queue", DataTable)
        table.add_columns("#", "Title", "Artist", "Album", "Duration")
        self._refresh_view()
        # Refresh periodically so the row marker follows playback.
        self.set_interval(1.0, self._refresh_view)

    def _refresh_view(self) -> None:
        table = self.query_one("#queue", DataTable)
        # Preserve cursor across re-renders.
        cursor = table.cursor_row if table.row_count else 0
        table.clear()
        queue = self._controller.queue
        cur_idx = self._controller.index
        for i, t in enumerate(queue):
            marker = "▶" if i == cur_idx else str(i + 1)
            table.add_row(
                marker,
                t.get("title") or "?",
                t.get("artist") or "",
                t.get("album") or "",
                _fmt_duration(t.get("duration_seconds")),
            )
        if queue:
            target = max(0, min(cursor, len(queue) - 1))
            try:
                table.move_cursor(row=target)
            except Exception:
                pass
        total_dur = sum(float(t.get("duration_seconds") or 0.0) for t in queue)
        self.query_one("#status", Static).update(
            f"{len(queue)} tracks · total {_fmt_duration(total_dur)}"
            if queue
            else "Queue empty"
        )

    async def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        idx = event.cursor_row
        if idx is None:
            return
        await self._controller.play_index(idx)
        self._refresh_view()

    async def action_remove(self) -> None:
        idx = self.query_one("#queue", DataTable).cursor_row
        if idx is None:
            return
        await self._controller.remove_at(idx)
        self._refresh_view()

    async def action_move_down(self) -> None:
        table = self.query_one("#queue", DataTable)
        idx = table.cursor_row
        if idx is None or idx >= len(self._controller.queue) - 1:
            return
        await self._controller.move(idx, idx + 1)
        self._refresh_view()
        try:
            table.move_cursor(row=idx + 1)
        except Exception:
            pass

    async def action_move_up(self) -> None:
        table = self.query_one("#queue", DataTable)
        idx = table.cursor_row
        if idx is None or idx <= 0:
            return
        await self._controller.move(idx, idx - 1)
        self._refresh_view()
        try:
            table.move_cursor(row=idx - 1)
        except Exception:
            pass

    async def action_clear(self) -> None:
        await self._controller.clear()
        self._refresh_view()

    async def action_toggle_pause(self) -> None:
        await self._controller.toggle_pause()

    async def action_prev_track(self) -> None:
        await self._controller.prev()

    async def action_next_track(self) -> None:
        await self._controller.next()

    def action_now_playing(self) -> None:
        from jamarr_tui.screens.now_playing import NowPlayingScreen

        self.app.push_screen(NowPlayingScreen(self._client, self._controller))
