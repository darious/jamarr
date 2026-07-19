import asyncio
import time
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.services.renderer.cast_backend import CastRendererBackend
from app.services.renderer.contracts import PlaybackContext


class FakeHostBrowser:
    def __init__(self) -> None:
        self.added: list[str] = []

    def add_hosts(self, hosts) -> None:
        self.added.extend(hosts)


class FakeBrowser:
    """Stands in for pychromecast's CastBrowser: exposes a devices dict of
    CastInfo-shaped entries and start/stop hooks."""

    def __init__(self, devices=None) -> None:
        self.devices = dict(devices or {})
        self.started = False
        self.stopped = False
        self.host_browser = FakeHostBrowser()

    def start_discovery(self) -> None:
        self.started = True

    def stop_discovery(self) -> None:
        self.stopped = True


def make_backend(cast: "FakeCast") -> tuple[CastRendererBackend, FakeBrowser]:
    browser = FakeBrowser({cast.cast_info.uuid: cast.cast_info})
    backend = CastRendererBackend(
        browser_factory=lambda _backend: browser,
        cast_factory=lambda _cast_info: cast,
        discovery_timeout=0,
    )
    return backend, browser


class FakeMediaController:
    def __init__(self) -> None:
        self.calls = []
        self.listeners = []
        self.status = SimpleNamespace(
            player_state="PLAYING",
            adjusted_current_time=12,
            duration=120,
            volume_level=0.4,
            volume_muted=False,
            content_id="http://media",
        )

    def play_media(self, *args, **kwargs) -> None:
        self.calls.append(("play_media", args, kwargs))

    def pause(self) -> None:
        self.calls.append(("pause", (), {}))

    def play(self) -> None:
        self.calls.append(("play", (), {}))

    def stop(self) -> None:
        self.calls.append(("stop", (), {}))

    def seek(self, seconds) -> None:
        self.calls.append(("seek", (seconds,), {}))

    def register_status_listener(self, listener) -> None:
        self.listeners.append(listener)

    def update_status(self, callback_function=None) -> None:
        self.calls.append(("update_status", (), {}))
        if callback_function:
            callback_function(True, {})


class FakeCast:
    def __init__(self, uuid: str = "11111111-1111-1111-1111-111111111111") -> None:
        self.uuid = UUID(uuid)
        self.name = "Kitchen Cast"
        self.model_name = "Nest Audio"
        self.cast_type = "audio"
        self.cast_info = SimpleNamespace(
            uuid=self.uuid,
            friendly_name=self.name,
            host="192.0.2.55",
            manufacturer="Google",
            model_name=self.model_name,
            cast_type=self.cast_type,
        )
        self.media_controller = FakeMediaController()
        self.status = SimpleNamespace(
            volume_level=0.4,
            volume_muted=False,
        )
        self.calls = []

    def wait(self, timeout=None) -> None:
        self.calls.append(("wait", timeout))

    def start_app(self, app_id, force_launch=False, timeout=10) -> None:
        self.calls.append(("start_app", app_id, force_launch, timeout))

    def set_volume(self, volume) -> None:
        self.calls.append(("set_volume", volume))

    def set_volume_muted(self, muted) -> None:
        self.calls.append(("set_volume_muted", muted))

    def disconnect(self, timeout=None) -> None:
        self.calls.append(("disconnect", timeout))

    def quit_app(self, timeout=10.0) -> None:
        self.calls.append(("quit_app", timeout))


@pytest.mark.asyncio
async def test_phase2_cast_discovery_creates_normalized_devices():
    cast = FakeCast()
    backend, browser = make_backend(cast)

    devices = await backend.discover(refresh=True)

    assert browser.started is True
    assert len(devices) == 1
    device = devices[0]
    assert device.renderer_id == "cast:11111111-1111-1111-1111-111111111111"
    assert device.kind == "cast"
    assert device.native_id == "11111111-1111-1111-1111-111111111111"
    assert device.name == "Kitchen Cast"
    assert device.ip == "192.0.2.55"
    assert device.cast_type == "audio"
    assert device.capabilities.supports_events is True


@pytest.mark.asyncio
async def test_phase2_cast_manual_add_registers_known_host():
    cast = FakeCast()
    backend, browser = make_backend(cast)

    device = await backend.add_manual("192.0.2.55")

    assert device is not None
    assert device.ip == "192.0.2.55"
    assert "192.0.2.55" in backend.known_hosts
    assert browser.host_browser.added == ["192.0.2.55"]


@pytest.mark.asyncio
async def test_phase2_cast_browser_callbacks_maintain_registry():
    """Devices appear and disappear via CastBrowser callbacks, without any
    explicit rescans — the whole point of persistent discovery."""
    cast = FakeCast()
    backend, browser = make_backend(cast)
    browser.devices.clear()  # nothing known at startup
    await backend.start()
    assert await backend.list_devices() == []

    # TV announces itself later; the add callback registers it.
    browser.devices[cast.cast_info.uuid] = cast.cast_info
    backend._on_cast_added(cast.cast_info.uuid, "svc")
    devices = await backend.list_devices()
    assert len(devices) == 1
    assert devices[0].name == "Kitchen Cast"

    # mDNS removal drops it from the registry.
    backend._on_cast_removed(cast.cast_info.uuid, "svc", cast.cast_info)
    assert await backend.list_devices() == []


@pytest.mark.asyncio
async def test_phase2_cast_client_creation_deferred_off_callback_thread(monkeypatch):
    """Without an injected cast factory, the browser callback must register the
    device immediately (pure data) but defer Chromecast client creation to the
    event loop's worker threads — pychromecast's constructor can do a blocking
    zeroconf lookup, which raises if run inside zeroconf's own callback loop."""
    cast = FakeCast()
    browser = FakeBrowser()
    backend = CastRendererBackend(
        browser_factory=lambda _backend: browser,
        discovery_timeout=0,
    )
    monkeypatch.setattr(backend, "_create_cast", lambda _info: cast)
    await backend.start()

    browser.devices[cast.cast_info.uuid] = cast.cast_info
    backend._on_cast_added(cast.cast_info.uuid, "svc")

    # Device is listed synchronously; the client does not exist yet.
    devices = await backend.list_devices()
    assert len(devices) == 1
    assert backend.casts == {}

    # The scheduled task creates the client shortly after (via a worker
    # thread, so give it real time rather than bare loop yields).
    for _ in range(200):
        if backend.casts:
            break
        await asyncio.sleep(0.01)
    assert "11111111-1111-1111-1111-111111111111" in backend.casts


@pytest.mark.asyncio
async def test_phase2_cast_client_created_lazily_at_play(monkeypatch):
    """If the deferred creation never ran (no loop at callback time), playback
    still works: _get_ready_cast creates the client on demand."""
    cast = FakeCast()
    browser = FakeBrowser({cast.cast_info.uuid: cast.cast_info})
    backend = CastRendererBackend(
        browser_factory=lambda _backend: browser,
        discovery_timeout=0,
    )
    monkeypatch.setattr(backend, "_create_cast", lambda _info: cast)
    backend.browser = browser  # browser known, but no clients created

    ready = await backend._get_ready_cast("cast:11111111-1111-1111-1111-111111111111")

    assert ready is cast
    assert ("wait", 10) in cast.calls


@pytest.mark.asyncio
async def test_phase2_cast_play_and_controls_call_pychromecast_shape():
    cast = FakeCast()
    backend, _browser = make_backend(cast)
    await backend.discover(refresh=True)
    renderer_id = "cast:11111111-1111-1111-1111-111111111111"

    await backend.play_track(
        renderer_id,
        {
            "id": 902,
            "path": "/music/song.flac",
            "title": "Song",
            "artist": "Artist",
            "album": "Album",
            "mime": "audio/flac",
            "duration_seconds": 180,
        },
        PlaybackContext(base_url="http://127.0.0.1:8111", user_id=42, token_ttl_seconds=1800),
    )
    await backend.pause(renderer_id)
    await backend.resume(renderer_id)
    await backend.seek(renderer_id, 33)
    await backend.set_volume(renderer_id, 65)
    await backend.stop_playback(renderer_id)
    await backend.get_status(renderer_id)

    assert cast.calls[0] == ("wait", 10)
    assert cast.calls[1][0] == "start_app"
    play_call = cast.media_controller.calls[0]
    assert play_call[0] == "play_media"
    assert play_call[1][0].startswith("http://127.0.0.1:8111/api/stream/902?token=")
    assert play_call[1][1] == "audio/flac"
    assert play_call[2]["title"] == "Song"
    assert ("pause", (), {}) in cast.media_controller.calls
    assert ("play", (), {}) in cast.media_controller.calls
    assert ("seek", (33,), {}) in cast.media_controller.calls
    assert ("stop", (), {}) in cast.media_controller.calls
    assert ("update_status", (), {}) in cast.media_controller.calls
    assert ("set_volume", 0.65) in cast.calls
    assert ("quit_app", 10) in cast.calls


def test_phase2_cast_status_mapping_and_end_detection():
    backend = CastRendererBackend()
    renderer_id = "cast:11111111-1111-1111-1111-111111111111"
    status = SimpleNamespace(
        player_state="IDLE",
        adjusted_current_time=180,
        duration=180,
        volume_level=0.5,
        volume_muted=False,
        content_id="http://media",
    )

    mapped = backend.status_from_media_status(
        renderer_id,
        status,
        previous_state="PLAYING",
        started_at=0,
    )

    assert mapped.state == "IDLE"
    assert mapped.ended is True
    assert mapped.position_seconds == 180
    assert mapped.duration_seconds == 180
    assert mapped.volume_percent == 50


def test_phase2_cast_status_prefers_receiver_volume_over_media_stream_volume():
    backend = CastRendererBackend()
    renderer_id = "cast:11111111-1111-1111-1111-111111111111"
    media_status = SimpleNamespace(
        player_state="PLAYING",
        adjusted_current_time=12,
        duration=120,
        volume_level=1.0,
        volume_muted=False,
        content_id="http://media",
    )
    receiver_status = SimpleNamespace(volume_level=0.27, volume_muted=True)

    mapped = backend.status_from_media_status(
        renderer_id,
        media_status,
        receiver_status=receiver_status,
    )

    assert mapped.volume_percent == 27
    assert mapped.volume_muted is True


def test_phase2_cast_early_idle_does_not_stop_playback():
    backend = CastRendererBackend()
    renderer_id = "cast:11111111-1111-1111-1111-111111111111"
    status = SimpleNamespace(
        player_state="IDLE",
        adjusted_current_time=0,
        duration=None,
        volume_level=None,
        volume_muted=False,
        content_id=None,
    )

    mapped = backend.status_from_media_status(
        renderer_id,
        status,
        previous_state="UNKNOWN",
        started_at=time.time(),
    )

    assert mapped.state == "UNKNOWN"
    assert mapped.ended is False


@pytest.mark.asyncio
async def test_phase2_cast_status_listener_dispatches_to_async_callback():
    cast = FakeCast()
    backend, _browser = make_backend(cast)
    await backend.start()
    renderer_id = "cast:11111111-1111-1111-1111-111111111111"
    received = []

    async def callback(status):
        received.append(status)

    backend.register_status_listener(renderer_id, callback)
    listener = cast.media_controller.listeners[0]
    listener.last_state = "PLAYING"
    listener.started_at = 0
    listener.new_media_status(SimpleNamespace(player_state="IDLE", current_time=99, duration=99))
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert received
    assert received[0].ended is True
