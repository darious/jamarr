from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Center, Middle, Vertical
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Static


class LoginRequested(Message):
    """Posted when the login form is submitted; the App opens the client."""

    def __init__(self, server: str, username: str, password: str) -> None:
        super().__init__()
        self.server = server
        self.username = username
        self.password = password


class LoginSucceeded(Message):
    """Posted when login + client setup succeed."""


class LoginScreen(Screen):
    BINDINGS = [("escape", "app.quit", "Quit")]

    DEFAULT_CSS = """
    LoginScreen Vertical {
        width: 60;
        height: auto;
        border: solid $accent;
        padding: 1 2;
    }
    LoginScreen .title {
        content-align: center middle;
        padding-bottom: 1;
        text-style: bold;
    }
    LoginScreen #status {
        color: $error;
        padding-top: 1;
    }
    """

    _FIELD_ORDER = ("server", "username", "password")

    def __init__(
        self,
        *,
        default_server: str | None = None,
        default_username: str | None = None,
    ) -> None:
        super().__init__()
        self._default_server = default_server or ""
        self._default_username = default_username or ""

    def compose(self) -> ComposeResult:
        yield Header()
        with Middle():
            with Center():
                with Vertical():
                    yield Static("Jamarr TUI", classes="title")
                    yield Input(
                        placeholder="Server URL (e.g. https://jamarr.example.com)",
                        id="server",
                        value=self._default_server,
                    )
                    yield Input(
                        placeholder="Username",
                        id="username",
                        value=self._default_username,
                    )
                    yield Input(
                        placeholder="Password", password=True, id="password"
                    )
                    yield Button("Sign in", id="submit", variant="primary")
                    yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        if not self._default_server:
            target = "server"
        elif not self._default_username:
            target = "username"
        else:
            target = "password"
        self.query_one(f"#{target}", Input).focus()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id not in self._FIELD_ORDER:
            return
        idx = self._FIELD_ORDER.index(event.input.id)
        if idx + 1 < len(self._FIELD_ORDER):
            self.query_one(f"#{self._FIELD_ORDER[idx + 1]}", Input).focus()
        else:
            self._submit()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "submit":
            self._submit()

    def show_error(self, message: str) -> None:
        self.query_one("#status", Static).update(message)

    def _submit(self) -> None:
        server = self.query_one("#server", Input).value.strip().rstrip("/")
        username = self.query_one("#username", Input).value.strip()
        password = self.query_one("#password", Input).value
        status = self.query_one("#status", Static)
        if not server:
            status.update("Enter server URL.")
            return
        if not (server.startswith("http://") or server.startswith("https://")):
            server = "https://" + server
        if not username or not password:
            status.update("Enter username and password.")
            return
        status.update("Signing in…")
        self.post_message(LoginRequested(server, username, password))
