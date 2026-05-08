from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static


_HELP_ROWS: list[tuple[str, str]] = [
    ("?", "Toggle help"),
    ("ctrl+q", "Quit from anywhere"),
    ("escape", "Back / close overlay"),
    ("", ""),
    ("/", "Search (from home)"),
    ("h", "Home"),
    ("p", "Playlists"),
    ("q", "Queue"),
    ("n", "Now playing"),
    ("ctrl+r", "Renderer picker"),
    ("", ""),
    ("space", "Play / pause"),
    (",  /  .", "Previous / next track"),
    ("[  /  ]", "Seek -10s / +10s"),
    ("-  /  +", "Volume down / up"),
    ("", ""),
    ("Enter", "Open / play (in lists)"),
    ("d / Delete", "Remove (queue / playlist)"),
    ("J / K", "Move down / up (queue / playlist)"),
    ("c", "Clear queue"),
    ("Q", "Quit (also ctrl+q)"),
]


class HelpScreen(ModalScreen):
    BINDINGS = [
        Binding("escape", "app.pop_screen", "Close"),
        Binding("question_mark", "app.pop_screen", "Close"),
    ]

    DEFAULT_CSS = """
    HelpScreen {
        align: center middle;
    }
    HelpScreen #help-box {
        background: $panel;
        border: tall $accent;
        padding: 1 2;
        width: 60;
        height: auto;
        max-height: 80%;
    }
    HelpScreen #help-title {
        text-style: bold;
        color: $accent;
        padding-bottom: 1;
    }
    HelpScreen #help-body {
        height: auto;
    }
    HelpScreen #help-footer {
        color: $text-muted;
        padding-top: 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="help-box"):
            yield Static("Jamarr TUI — Key bindings", id="help-title")
            yield Static(self._render_body(), id="help-body")
            yield Static("Press ? or Esc to close.", id="help-footer")

    @staticmethod
    def _render_body() -> str:
        lines: list[str] = []
        for key, label in _HELP_ROWS:
            if not key and not label:
                lines.append("")
                continue
            lines.append(f"  {key:<14}  {label}")
        return "\n".join(lines)
