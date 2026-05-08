"""mpv subprocess controller using the JSON IPC protocol."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import uuid
from dataclasses import dataclass
from typing import Any

log = logging.getLogger("jamarr_tui.mpv")


@dataclass
class PlaybackState:
    loaded: bool = False
    paused: bool = True
    position_s: float = 0.0
    duration_s: float = 0.0


class MpvController:
    """Drives a single long-lived mpv process over a unix-domain JSON IPC socket.

    The controller is intentionally minimal for v1: load a URL, play/pause,
    seek, set volume, observe time-pos and duration. Queue handling lives one
    layer up; we just react to track-end events via a callback.
    """

    def __init__(self) -> None:
        self._socket_path = os.path.join(
            tempfile.gettempdir(), f"jamarr-tui-{uuid.uuid4().hex[:8]}.sock"
        )
        self._proc: asyncio.subprocess.Process | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._req_id = 0
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._reader_task: asyncio.Task[None] | None = None
        self._state = PlaybackState()
        self._on_end: callable | None = None
        self._stderr_log_path = os.path.join(
            tempfile.gettempdir(), f"jamarr-tui-{uuid.uuid4().hex[:8]}.mpv.log"
        )
        self.last_end_reason: str | None = None

    @property
    def stderr_log_path(self) -> str:
        return self._stderr_log_path

    @property
    def state(self) -> PlaybackState:
        return self._state

    def on_track_end(self, callback) -> None:
        self._on_end = callback

    async def start(self) -> None:
        if self._proc is not None:
            return
        stderr_f = open(self._stderr_log_path, "wb")
        self._proc = await asyncio.create_subprocess_exec(
            "mpv",
            "--idle=yes",
            "--no-video",
            "--no-config",
            "--no-terminal",
            "--audio-display=no",
            "--msg-level=all=info",
            f"--input-ipc-server={self._socket_path}",
            stdin=asyncio.subprocess.DEVNULL,
            stdout=stderr_f,
            stderr=stderr_f,
        )
        log.info("mpv started, pid=%s, log=%s", self._proc.pid, self._stderr_log_path)
        # Wait for the IPC socket to appear.
        for _ in range(100):
            if os.path.exists(self._socket_path):
                break
            await asyncio.sleep(0.05)
        else:
            raise RuntimeError("mpv IPC socket never appeared")

        self._reader, self._writer = await asyncio.open_unix_connection(
            self._socket_path
        )
        self._reader_task = asyncio.create_task(self._read_loop())

        await self._command("observe_property", 1, "time-pos")
        await self._command("observe_property", 2, "duration")
        await self._command("observe_property", 3, "pause")
        await self._command("observe_property", 4, "eof-reached")

    async def stop(self) -> None:
        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
        if self._reader_task is not None:
            self._reader_task.cancel()
        if self._proc is not None:
            try:
                self._proc.terminate()
                await self._proc.wait()
            except ProcessLookupError:
                pass
        try:
            os.unlink(self._socket_path)
        except FileNotFoundError:
            pass

    async def load(self, url: str) -> None:
        log.info("mpv loadfile %s", url)
        self._state.loaded = True
        self._state.paused = False
        self._state.position_s = 0.0
        self.last_end_reason = None
        await self._command("loadfile", url, "replace")
        await self._set_property("pause", False)

    async def play(self) -> None:
        if self._state.loaded:
            await self._set_property("pause", False)
            self._state.paused = False

    async def pause(self) -> None:
        if self._state.loaded:
            await self._set_property("pause", True)
            self._state.paused = True

    async def toggle_pause(self) -> None:
        if self._state.paused:
            await self.play()
        else:
            await self.pause()

    async def seek(self, position_s: float) -> None:
        await self._command("seek", position_s, "absolute")

    async def stop_playback(self) -> None:
        """Stop the current file but leave mpv running idle."""
        if self._state.loaded:
            await self._command("stop")
        self._state.loaded = False
        self._state.paused = True
        self._state.position_s = 0.0
        self._state.duration_s = 0.0

    async def set_volume(self, level: float) -> None:
        # level in [0, 1]
        await self._set_property("volume", max(0.0, min(100.0, level * 100.0)))

    # -- internals ------------------------------------------------------------

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    async def _command(self, *args: Any) -> Any:
        return await self._send({"command": list(args)})

    async def _set_property(self, name: str, value: Any) -> Any:
        return await self._command("set_property", name, value)

    async def _send(self, payload: dict[str, Any]) -> Any:
        if self._writer is None:
            raise RuntimeError("mpv not started")
        req_id = self._next_id()
        payload = dict(payload, request_id=req_id)
        fut: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._pending[req_id] = fut
        self._writer.write((json.dumps(payload) + "\n").encode("utf-8"))
        await self._writer.drain()
        try:
            return await asyncio.wait_for(fut, timeout=5.0)
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            return None

    async def _read_loop(self) -> None:
        assert self._reader is not None
        try:
            while True:
                line = await self._reader.readline()
                if not line:
                    return
                try:
                    msg = json.loads(line.decode("utf-8"))
                except json.JSONDecodeError:
                    continue
                if "request_id" in msg and msg["request_id"] in self._pending:
                    self._pending.pop(msg["request_id"]).set_result(msg)
                    continue
                event = msg.get("event")
                if event == "property-change":
                    self._handle_property(msg.get("name"), msg.get("data"))
                elif event == "end-file":
                    reason = msg.get("reason")
                    error = msg.get("file_error") or msg.get("error")
                    self.last_end_reason = (
                        f"{reason}: {error}" if error else str(reason)
                    )
                    log.warning("mpv end-file: %s", self.last_end_reason)
                    self._state.loaded = False
                    self._state.paused = True
                    if self._on_end is not None:
                        try:
                            self._on_end()
                        except Exception:
                            pass
        except asyncio.CancelledError:
            return
        except Exception:
            return

    def _handle_property(self, name: str | None, data: Any) -> None:
        if name == "time-pos":
            self._state.position_s = float(data) if data is not None else 0.0
        elif name == "duration":
            self._state.duration_s = float(data) if data is not None else 0.0
        elif name == "pause":
            self._state.paused = bool(data) if data is not None else True
