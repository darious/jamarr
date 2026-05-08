from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Footer, Header, Static

from jamarr_tui.api.client import JamarrClient
from jamarr_tui.playback.controller import PlaybackController
from jamarr_tui.widgets.art_panel import ArtPanel
from jamarr_tui.widgets.player_bar import PlayerBar


def _fmt_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    m, s = divmod(seconds, 60)
    return f"{m:d}:{s:02d}"


class _SeekBar(Widget):
    """Theme-coloured progress bar with explicit start/end caps.

    Uses two child `Static`s laid out horizontally; the left child carries
    the `$accent` background and is sized to the played-fraction of the
    container, the right child fills the remainder with `$boost`. That
    gives a solid filled rectangle that matches the rest of the UI rather
    than the default `ProgressBar` glyph treatment.
    """

    DEFAULT_CSS = """
    _SeekBar {
        layout: horizontal;
        height: 1;
        width: 1fr;
    }
    _SeekBar #seek-fill {
        background: $accent;
        height: 1;
        width: 0;
    }
    _SeekBar #seek-empty {
        background: $boost;
        height: 1;
        width: 1fr;
    }
    """

    progress: reactive[float] = reactive(0.0)

    def compose(self) -> ComposeResult:
        yield Static(" ", id="seek-fill")
        yield Static(" ", id="seek-empty")

    def watch_progress(self, value: float) -> None:
        self._apply()

    def on_resize(self, _) -> None:
        self._apply()

    def set_progress(self, value: float) -> None:
        clamped = max(0.0, min(1.0, value))
        if abs(clamped - self.progress) > 0.001:
            self.progress = clamped

    def _apply(self) -> None:
        total = self.size.width
        if total <= 0:
            return
        fill_w = max(0, min(total, int(round(self.progress * total))))
        try:
            self.query_one("#seek-fill", Static).styles.width = fill_w
            self.query_one("#seek-empty", Static).styles.width = max(
                0, total - fill_w
            )
        except Exception:
            pass


class NowPlayingScreen(Screen):
    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("space", "toggle_pause", "Play/Pause"),
        Binding("comma", "prev_track", "Prev"),
        Binding("full_stop", "next_track", "Next"),
        Binding("left_square_bracket", "seek_back", "-10s"),
        Binding("right_square_bracket", "seek_fwd", "+10s"),
    ]

    DEFAULT_CSS = """
    NowPlayingScreen #np-body {
        padding: 1 4;
        height: 1fr;
    }
    NowPlayingScreen #np-art {
        width: 80;
        height: 30;
    }
    NowPlayingScreen #np-title {
        text-style: bold;
        color: $accent;
        padding-top: 1;
    }
    NowPlayingScreen #np-artist {
        color: $text;
    }
    NowPlayingScreen #np-album {
        color: $text-muted;
        padding-bottom: 1;
    }
    NowPlayingScreen #np-bar-row {
        height: 1;
        width: 80%;
        margin: 1 0;
    }
    NowPlayingScreen #np-time-left, NowPlayingScreen #np-time-right {
        width: 6;
        color: $text-muted;
        content-align: center middle;
    }
    NowPlayingScreen #np-state {
        color: $text-muted;
    }
    NowPlayingScreen #np-empty {
        padding: 4;
        color: $text-muted;
    }
    """

    def __init__(
        self, client: JamarrClient, controller: PlaybackController
    ) -> None:
        super().__init__()
        self._client = client
        self._controller = controller
        self._current_sha1: str | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="np-body"):
            with Center():
                yield ArtPanel(self._client, id="np-art")
            with Center():
                yield Static("", id="np-title")
            with Center():
                yield Static("", id="np-artist")
            with Center():
                yield Static("", id="np-album")
            with Center():
                with Horizontal(id="np-bar-row"):
                    yield Static("0:00", id="np-time-left")
                    yield _SeekBar(id="np-bar")
                    yield Static("0:00", id="np-time-right")
            with Center():
                yield Static("", id="np-state")
            yield Static("", id="np-empty")
        yield PlayerBar(self._controller)
        yield Footer()

    def on_mount(self) -> None:
        self._tick()
        self.set_interval(0.5, self._tick)

    def on_screen_suspend(self) -> None:
        for panel in self.query(ArtPanel):
            panel.suspend_graphics()

    def on_screen_resume(self) -> None:
        for panel in self.query(ArtPanel):
            panel.resume_graphics()

    def _tick(self) -> None:
        cur = self._controller.current
        st = self._controller.state
        title = self.query_one("#np-title", Static)
        artist = self.query_one("#np-artist", Static)
        album = self.query_one("#np-album", Static)
        time_l = self.query_one("#np-time-left", Static)
        time_r = self.query_one("#np-time-right", Static)
        state_lbl = self.query_one("#np-state", Static)
        empty_lbl = self.query_one("#np-empty", Static)
        bar = self.query_one("#np-bar", _SeekBar)
        art = self.query_one("#np-art", ArtPanel)
        if cur is None:
            title.update("")
            artist.update("")
            album.update("")
            time_l.update("0:00")
            time_r.update("0:00")
            state_lbl.update("")
            empty_lbl.update("Nothing playing.")
            bar.set_progress(0.0)
            if self._current_sha1 is not None:
                art.set_sha1(None)
                self._current_sha1 = None
            return
        empty_lbl.update("")
        title.update(cur.title or "?")
        artist.update(cur.artist or "")
        album.update(cur.album or "")
        if cur.art_sha1 != self._current_sha1:
            art.set_sha1(cur.art_sha1)
            self._current_sha1 = cur.art_sha1
        if not st.loaded:
            state = "stopped"
        elif st.paused:
            state = "paused"
        else:
            state = "playing"
        state_lbl.update(
            f"[{state}]   vol {int(self._controller.volume * 100)}%"
        )
        time_l.update(_fmt_time(st.position_s))
        time_r.update(_fmt_time(st.duration_s))
        if st.duration_s > 0:
            bar.set_progress(st.position_s / st.duration_s)
        else:
            bar.set_progress(0.0)

    async def action_toggle_pause(self) -> None:
        await self._controller.toggle_pause()

    async def action_prev_track(self) -> None:
        await self._controller.prev()

    async def action_next_track(self) -> None:
        await self._controller.next()

    async def action_seek_back(self) -> None:
        await self._controller.seek_relative(-10.0)

    async def action_seek_fwd(self) -> None:
        await self._controller.seek_relative(10.0)
