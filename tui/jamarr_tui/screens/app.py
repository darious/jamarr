from __future__ import annotations

import logging
import os
import tempfile

from textual.app import App
from textual.binding import Binding

from jamarr_tui.api.client import AuthError, JamarrClient
from jamarr_tui.playback.controller import PlaybackController
from jamarr_tui.playback.probe import NoBackendError, detect_backend
from jamarr_tui.screens.help import HelpScreen
from jamarr_tui.screens.home import HomeScreen
from jamarr_tui.screens.login import (
    LoginRequested,
    LoginScreen,
    LoginSucceeded,
)
from jamarr_tui.screens.renderers import RendererPickerScreen


def _setup_file_logging() -> str:
    log_path = os.path.join(tempfile.gettempdir(), "jamarr-tui.log")
    handler = logging.FileHandler(log_path, mode="w")
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root = logging.getLogger("jamarr_tui")
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    return log_path


class JamarrTuiApp(App):
    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", priority=True, show=False),
        Binding("question_mark", "help", "Help", priority=True, show=False),
        Binding("minus", "vol_down", "Vol -", priority=True, show=False),
        Binding("plus", "vol_up", "Vol +", priority=True, show=False),
        Binding("equals_sign", "vol_up", "Vol +", priority=True, show=False),
        Binding("ctrl+r", "renderer_picker", "Renderers", priority=True, show=False),
    ]

    CSS = """
    Screen {
        background: $surface;
    }
    """

    def __init__(
        self, *, server: str | None = None, username: str | None = None
    ) -> None:
        super().__init__()
        self._default_server = server
        self._default_username = username
        self._log_path = _setup_file_logging()
        log = logging.getLogger("jamarr_tui.app")
        log.info(
            "Jamarr TUI starting; server=%s log=%s",
            server or "(prompt)",
            self._log_path,
        )
        self._client: JamarrClient | None = None
        self._controller: PlaybackController | None = None

    async def on_mount(self) -> None:
        # Probe audio backend up-front so we fail loudly before the login.
        try:
            detect_backend()
        except NoBackendError as exc:
            self.exit(message=str(exc))
            return
        await self.push_screen(
            LoginScreen(
                default_server=self._default_server,
                default_username=self._default_username,
            )
        )

    async def on_unmount(self) -> None:
        if self._controller is not None:
            await self._controller.stop()
        if self._client is not None:
            await self._client.aclose()

    async def on_login_requested(self, msg: LoginRequested) -> None:
        log = logging.getLogger("jamarr_tui.app")
        # Tear down any previous attempt (e.g. user re-tries after wrong URL).
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        client = JamarrClient(msg.server)
        try:
            await client.login(msg.username, msg.password)
        except AuthError:
            log.warning("login failed: invalid credentials")
            await client.aclose()
            self._show_login_error("Invalid credentials.")
            return
        except Exception as exc:  # noqa: BLE001
            log.exception("login failed")
            await client.aclose()
            self._show_login_error(f"Could not reach server: {exc}")
            return
        log.info("login ok; server=%s user=%s", msg.server, msg.username)
        self._client = client
        self._controller = PlaybackController(client=client)
        try:
            await self._controller.start()
        except Exception as exc:  # noqa: BLE001
            log.exception("controller start failed")
            self._show_login_error(f"Audio backend failed: {exc}")
            return
        await self.switch_screen(HomeScreen(client, self._controller))

    def _show_login_error(self, message: str) -> None:
        screen = self.screen
        if isinstance(screen, LoginScreen):
            screen.show_error(message)

    async def on_login_succeeded(self, _: LoginSucceeded) -> None:
        # Retained for backwards compatibility with the old flow; current flow
        # uses LoginRequested → switch_screen above.
        if self._client is None or self._controller is None:
            return
        await self.switch_screen(HomeScreen(self._client, self._controller))

    async def action_help(self) -> None:
        if isinstance(self.screen, HelpScreen):
            self.pop_screen()
        else:
            await self.push_screen(HelpScreen())

    async def action_vol_up(self) -> None:
        if self._controller is not None:
            await self._controller.vol_up()

    async def action_vol_down(self) -> None:
        if self._controller is not None:
            await self._controller.vol_down()

    async def action_renderer_picker(self) -> None:
        if self._controller is None or self._client is None:
            return
        if isinstance(self.screen, RendererPickerScreen):
            return
        await self.push_screen(
            RendererPickerScreen(self._client, self._controller)
        )
