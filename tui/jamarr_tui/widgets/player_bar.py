from __future__ import annotations

from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from jamarr_tui.playback.controller import PlaybackController


def _fmt_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    m, s = divmod(seconds, 60)
    return f"{m:d}:{s:02d}"


class PlayerBar(Widget):
    DEFAULT_CSS = """
    PlayerBar {
        dock: bottom;
        height: 3;
        background: $boost;
        border-top: solid $accent;
    }
    PlayerBar Horizontal {
        height: 3;
        padding: 0 1;
    }
    PlayerBar #pb-track {
        width: 1fr;
        content-align: left middle;
    }
    PlayerBar #pb-state {
        width: 12;
        content-align: center middle;
    }
    PlayerBar #pb-time {
        width: 16;
        content-align: right middle;
    }
    PlayerBar #pb-vol {
        width: 12;
        content-align: right middle;
        color: $text-muted;
    }
    """

    track_label: reactive[str] = reactive("Nothing playing")
    state_label: reactive[str] = reactive("--")
    time_label: reactive[str] = reactive("0:00 / 0:00")
    vol_label: reactive[str] = reactive("vol 100%")

    def __init__(self, controller: PlaybackController) -> None:
        super().__init__()
        self._controller = controller

    def compose(self):
        with Horizontal():
            yield Static(self.track_label, id="pb-track")
            yield Static(self.state_label, id="pb-state")
            yield Static(self.time_label, id="pb-time")
            yield Static(self.vol_label, id="pb-vol")

    def on_mount(self) -> None:
        self.set_interval(0.5, self._tick)
        self.set_interval(5.0, self._report_progress)

    async def _report_progress(self) -> None:
        await self._controller.report_progress()

    async def _tick(self) -> None:
        await self._controller.advance_if_pending()
        cur = self._controller.current
        st = self._controller.state
        if cur is not None:
            label = (cur.title or "?") + (f" — {cur.artist}" if cur.artist else "")
            self.track_label = label
        else:
            self.track_label = "Nothing playing"
        if not st.loaded:
            self.state_label = "stopped"
        elif st.paused:
            self.state_label = "paused"
        else:
            self.state_label = "playing"
        self.time_label = f"{_fmt_time(st.position_s)} / {_fmt_time(st.duration_s)}"
        self.vol_label = f"vol {int(self._controller.volume * 100)}%"

        # Push reactive updates into the child Statics.
        self.query_one("#pb-track", Static).update(self.track_label)
        self.query_one("#pb-state", Static).update(self.state_label)
        self.query_one("#pb-time", Static).update(self.time_label)
        self.query_one("#pb-vol", Static).update(self.vol_label)
