from __future__ import annotations

import logging
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Static

from jamarr_tui.api.client import JamarrClient
from jamarr_tui.playback.controller import PlaybackController

log = logging.getLogger("jamarr_tui.renderers")


class RendererPickerScreen(ModalScreen):
    BINDINGS = [
        Binding("escape", "app.pop_screen", "Close"),
        Binding("r", "refresh", "Rescan"),
    ]

    DEFAULT_CSS = """
    RendererPickerScreen {
        align: center middle;
    }
    RendererPickerScreen #picker {
        background: $panel;
        border: tall $accent;
        padding: 1 2;
        width: 80;
        height: auto;
        max-height: 80%;
    }
    RendererPickerScreen #picker-title {
        text-style: bold;
        color: $accent;
        padding-bottom: 1;
    }
    RendererPickerScreen DataTable {
        height: auto;
        max-height: 20;
    }
    RendererPickerScreen #picker-status {
        color: $text-muted;
        padding-top: 1;
    }
    """

    def __init__(
        self, client: JamarrClient, controller: PlaybackController
    ) -> None:
        super().__init__()
        self._client = client
        self._controller = controller
        self._renderers: list[dict[str, Any]] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="picker"):
            yield Static("Select a renderer", id="picker-title")
            yield DataTable(id="renderers", cursor_type="row", zebra_stripes=True)
            yield Static("Loading…", id="picker-status")
        yield Footer()

    async def on_mount(self) -> None:
        table = self.query_one("#renderers", DataTable)
        table.add_columns("", "Name", "Type", "Notes")
        await self._load(refresh=False)

    async def _load(self, *, refresh: bool) -> None:
        status = self.query_one("#picker-status", Static)
        table = self.query_one("#renderers", DataTable)
        status.update("Scanning…" if refresh else "Loading…")
        try:
            data = await self._client.list_renderers(refresh=refresh)
            state = await self._client.player_state()
        except Exception as exc:  # noqa: BLE001
            status.update(f"Failed: {exc}")
            log.exception("list_renderers failed")
            return
        self._renderers = data or []
        active_id = state.get("renderer_id") or state.get("renderer") or ""
        # Adopt the server's view so the controller doesn't drive local mpv in
        # parallel with a server-managed remote renderer.
        if active_id:
            await self._controller.activate_renderer(active_id)
        table.clear()
        for r in self._renderers:
            kind = r.get("kind") or r.get("type") or ""
            name = r.get("name") or r.get("native_id") or "?"
            notes = r.get("manufacturer") or r.get("model_name") or ""
            rid = r.get("renderer_id") or r.get("udn") or ""
            marker = "▶" if rid == active_id else " "
            table.add_row(marker, name, kind, notes)
        status.update(
            f"{len(self._renderers)} renderer(s). Press r to rescan, "
            "Enter to activate."
        )

    async def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        idx = event.cursor_row
        if idx is None or idx < 0 or idx >= len(self._renderers):
            return
        r = self._renderers[idx]
        rid = r.get("renderer_id") or r.get("udn")
        if not rid:
            return
        status = self.query_one("#picker-status", Static)
        status.update(f"Switching to {r.get('name')}…")
        try:
            data = await self._client.set_renderer(rid)
            await self._controller.activate_renderer(data.get("renderer_id") or rid)
        except Exception as exc:  # noqa: BLE001
            status.update(f"Switch failed: {exc}")
            log.exception("set_renderer failed")
            return
        status.update(f"Active: {r.get('name')}")
        self.app.pop_screen()

    async def action_refresh(self) -> None:
        await self._load(refresh=True)
