import asyncio
import time
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.services.renderer.cast_backend import CastRendererBackend
from app.services.renderer.contracts import PlaybackContext, RendererLoadError, RendererStatus


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


LOAD_ACCEPTED = (
    True,
    {"type": "MEDIA_STATUS", "status": [{"mediaSessionId": 1, "playerState": "BUFFERING"}]},
)
LOAD_FAILED = (True, {"type": "LOAD_FAILED", "detailedErrorCode": 104, "itemId": 1})


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
            idle_reason=None,
        )
        self.load_response = LOAD_ACCEPTED
        self.pending_load_callback = None

    def play_media(self, *args, **kwargs) -> None:
        """Answers the LOAD like a receiver would: ``load_response`` is the
        (success, data) pair pychromecast hands the callback, or None for a
        receiver that never answers (the callback is kept for later)."""
        self.calls.append(("play_media", args, kwargs))
        callback = kwargs.get("callback_function")
        self.pending_load_callback = callback
        if self.load_response is None or callback is None:
            return
        success, data = self.load_response
        if success and (data or {}).get("type") == "MEDIA_STATUS":
            self.status.content_id = args[0]
            self.status.player_state = "BUFFERING"
            self.status.idle_reason = None
        callback(success, data)

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


@pytest.mark.asyncio
async def test_phase2_cast_prefers_context_stream_url_and_mime_type():
    cast = FakeCast()
    backend, _browser = make_backend(cast)
    await backend.discover(refresh=True)
    renderer_id = "cast:11111111-1111-1111-1111-111111111111"

    await backend.play_track(
        renderer_id,
        {
            "id": 903,
            "path": "/music/song.mp3",
            "title": "Song",
            "artist": "Artist",
            "album": "Album",
            "mime": "audio/mpeg",
            "duration_seconds": 180,
        },
        PlaybackContext(
            base_url="http://127.0.0.1:8111",
            user_id=42,
            stream_url="http://127.0.0.1:8111/api/stream/903?token=normalized",
            stream_mime_type="audio/flac",
        ),
    )

    play_call = cast.media_controller.calls[0]
    assert play_call[1][0] == "http://127.0.0.1:8111/api/stream/903?token=normalized"
    assert play_call[1][1] == "audio/flac"


def test_phase2_cast_status_mapping_and_end_detection():
    backend = CastRendererBackend()
    renderer_id = "cast:11111111-1111-1111-1111-111111111111"
    status = SimpleNamespace(
        player_state="IDLE",
        idle_reason="FINISHED",
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
    listener.new_media_status(
        SimpleNamespace(player_state="IDLE", idle_reason="FINISHED", current_time=99, duration=99)
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert received
    assert received[0].ended is True


# --- LOAD confirmation and idleReason handling (issue #316) ----------------

RENDERER_ID = "cast:11111111-1111-1111-1111-111111111111"
TRACK = {
    "id": 904,
    "path": "/music/song.flac",
    "title": "Song",
    "mime": "audio/flac",
    "duration_seconds": 180,
}
STREAM_URL = "http://127.0.0.1:8111/api/stream/904?token=t"
CONTEXT = PlaybackContext(base_url="http://127.0.0.1:8111", user_id=42, stream_url=STREAM_URL)


def idle_status(idle_reason, content_id=STREAM_URL, position=170):
    return SimpleNamespace(
        player_state="IDLE",
        idle_reason=idle_reason,
        adjusted_current_time=position,
        duration=180,
        content_id=content_id,
    )


async def loaded_backend(**kwargs):
    cast = FakeCast()
    backend, _browser = make_backend(cast)
    for key, value in kwargs.items():
        setattr(backend, key, value)
    await backend.discover(refresh=True)
    return backend, cast


@pytest.mark.asyncio
async def test_cast_play_waits_for_accepted_load():
    backend, cast = await loaded_backend()

    status = await backend.play_track(RENDERER_ID, TRACK, CONTEXT)

    # The LOAD reply reports BUFFERING, which maps to PLAYING throughout.
    assert status.state == "PLAYING"
    assert status.current_media_url == STREAM_URL
    assert backend._loads[RENDERER_ID].confirmed is True


@pytest.mark.asyncio
async def test_cast_accepted_load_without_player_state_is_transitioning():
    backend, cast = await loaded_backend()
    cast.media_controller.load_response = (True, {"type": "MEDIA_STATUS", "status": []})

    status = await backend.play_track(RENDERER_ID, TRACK, CONTEXT)

    assert status.state == "TRANSITIONING"


@pytest.mark.asyncio
async def test_cast_rejected_load_raises_and_forgets_load():
    backend, cast = await loaded_backend()
    cast.media_controller.load_response = LOAD_FAILED

    with pytest.raises(RendererLoadError) as excinfo:
        await backend.play_track(RENDERER_ID, TRACK, CONTEXT)

    assert excinfo.value.reason == "load_rejected"
    assert "LOAD_FAILED" in excinfo.value.detail
    assert "104" in excinfo.value.detail
    assert RENDERER_ID not in backend._loads


@pytest.mark.asyncio
async def test_cast_load_media_error_status_is_a_rejection():
    backend, cast = await loaded_backend()
    cast.media_controller.load_response = (
        True,
        {"type": "MEDIA_STATUS", "status": [{"playerState": "IDLE", "idleReason": "ERROR"}]},
    )

    with pytest.raises(RendererLoadError) as excinfo:
        await backend.play_track(RENDERER_ID, TRACK, CONTEXT)

    assert excinfo.value.reason == "load_rejected"


@pytest.mark.asyncio
async def test_cast_load_without_answer_from_connection_is_a_failure():
    backend, cast = await loaded_backend()
    cast.media_controller.load_response = (False, None)

    with pytest.raises(RendererLoadError) as excinfo:
        await backend.play_track(RENDERER_ID, TRACK, CONTEXT)

    assert excinfo.value.reason == "load_failed"


@pytest.mark.asyncio
async def test_cast_play_media_exception_is_a_load_failure():
    backend, cast = await loaded_backend()

    def boom(*_args, **_kwargs):
        raise RuntimeError("socket gone")

    cast.media_controller.play_media = boom

    with pytest.raises(RendererLoadError) as excinfo:
        await backend.play_track(RENDERER_ID, TRACK, CONTEXT)

    assert excinfo.value.reason == "load_failed"
    assert "socket gone" in str(excinfo.value)


@pytest.mark.asyncio
async def test_cast_load_timeout_raises_and_stops_media():
    backend, cast = await loaded_backend(load_timeout=0.05)
    cast.media_controller.load_response = None  # receiver never answers

    with pytest.raises(RendererLoadError) as excinfo:
        await backend.play_track(RENDERER_ID, TRACK, CONTEXT)

    assert excinfo.value.reason == "load_timeout"
    assert ("stop", (), {}) in cast.media_controller.calls
    assert RENDERER_ID not in backend._loads
    # A late answer after the timeout is harmless.
    cast.media_controller.pending_load_callback(*LOAD_ACCEPTED)
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_cast_statuses_during_pending_load_are_transitioning():
    backend, cast = await loaded_backend()
    cast.media_controller.load_response = None
    play = asyncio.create_task(backend.play_track(RENDERER_ID, TRACK, CONTEXT))
    for _ in range(200):
        if cast.media_controller.pending_load_callback:
            break
        await asyncio.sleep(0.01)

    # The previous media is replaced: IDLE/INTERRUPTED (and even FINISHED)
    # for it must neither advance nor halt anything.
    for reason in ("INTERRUPTED", "FINISHED"):
        mapped = backend.status_from_media_status(
            RENDERER_ID,
            idle_status(reason, content_id="http://old"),
            previous_state="PLAYING",
            started_at=0,
        )
        assert mapped.state == "TRANSITIONING"
        assert mapped.ended is False
        assert mapped.stop_reason is None

    cast.media_controller.pending_load_callback(*LOAD_ACCEPTED)
    status = await play
    assert status.state == "PLAYING"
    assert backend._loads[RENDERER_ID].confirmed is True


@pytest.mark.asyncio
async def test_cast_finished_advances_exactly_once():
    backend, _cast = await loaded_backend()
    await backend.play_track(RENDERER_ID, TRACK, CONTEXT)

    first = backend.status_from_media_status(RENDERER_ID, idle_status("FINISHED"))
    # Listener re-broadcasts and /api/player/state polls see it again.
    again = backend.status_from_media_status(
        RENDERER_ID, idle_status("FINISHED"), previous_state="PLAYING", started_at=0
    )
    polled = backend.status_from_media_status(RENDERER_ID, idle_status("FINISHED"), trust_idle=True)

    assert first.ended is True
    assert first.state == "IDLE"
    assert first.stop_reason is None
    assert again.ended is False
    assert polled.ended is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("idle_reason", "stop_reason"),
    [
        ("CANCELLED", "renderer_stopped"),
        ("INTERRUPTED", "renderer_stopped"),
        ("ERROR", "renderer_error"),
    ],
)
async def test_cast_non_finished_idle_halts_without_advancing(idle_reason, stop_reason):
    backend, _cast = await loaded_backend()
    await backend.play_track(RENDERER_ID, TRACK, CONTEXT)

    mapped = backend.status_from_media_status(
        RENDERER_ID, idle_status(idle_reason), previous_state="PLAYING", started_at=0
    )

    assert mapped.ended is False
    assert mapped.state == "IDLE"
    assert mapped.stop_reason == stop_reason
    assert mapped.completion_reported is True


@pytest.mark.asyncio
async def test_cast_explicit_stop_is_not_a_device_halt():
    backend, _cast = await loaded_backend()
    await backend.play_track(RENDERER_ID, TRACK, CONTEXT)
    await backend.stop_playback(RENDERER_ID)

    mapped = backend.status_from_media_status(
        RENDERER_ID, idle_status("CANCELLED"), previous_state="PLAYING", started_at=0
    )

    assert mapped.ended is False
    assert mapped.stop_reason is None


@pytest.mark.asyncio
async def test_cast_other_controllers_media_is_not_ours():
    backend, _cast = await loaded_backend()
    await backend.play_track(RENDERER_ID, TRACK, CONTEXT)

    mapped = backend.status_from_media_status(
        RENDERER_ID,
        idle_status("FINISHED", content_id="https://elsewhere/video.mp4"),
        previous_state="PLAYING",
        started_at=0,
    )

    assert mapped.ended is False
    assert mapped.stop_reason is None


def test_cast_untracked_idle_without_finished_does_not_end():
    backend = CastRendererBackend()
    for reason in (None, "CANCELLED", "INTERRUPTED", "ERROR"):
        mapped = backend.status_from_media_status(
            RENDERER_ID, idle_status(reason), previous_state="PLAYING", started_at=0
        )
        assert mapped.ended is False, reason


def test_orchestrator_position_heuristic_defers_to_reported_completion():
    from app.services.renderer.orchestrator import RendererOrchestrator

    state = {"queue": [{"id": 1, "duration_seconds": 180}], "current_index": 0, "position_seconds": 178}
    cancelled_near_end = RendererStatus(
        renderer_id=RENDERER_ID, state="IDLE", position_seconds=0, completion_reported=True
    )
    legacy = RendererStatus(renderer_id=RENDERER_ID, state="IDLE", position_seconds=0)

    assert RendererOrchestrator._detect_track_ended(state, cancelled_near_end, 178) is False
    assert RendererOrchestrator._detect_track_ended(state, legacy, 178) is True


async def _wait_for_pending_load(cast):
    for _ in range(200):
        if cast.media_controller.pending_load_callback:
            return cast.media_controller.pending_load_callback
        await asyncio.sleep(0.01)
    raise AssertionError("LOAD was never issued")


TRACK_B = {**TRACK, "id": 905, "title": "Song B"}
CONTEXT_B = PlaybackContext(
    base_url="http://127.0.0.1:8111",
    user_id=42,
    stream_url="http://127.0.0.1:8111/api/stream/905?token=b",
)


@pytest.mark.asyncio
async def test_cast_load_timeout_does_not_stop_a_newer_load():
    backend, cast = await loaded_backend(load_timeout=0.3)
    cast.media_controller.load_response = None  # the first LOAD never answers
    first = asyncio.create_task(backend.play_track(RENDERER_ID, TRACK, CONTEXT))
    await _wait_for_pending_load(cast)

    cast.media_controller.load_response = LOAD_ACCEPTED
    await backend.play_track(RENDERER_ID, TRACK_B, CONTEXT_B)

    with pytest.raises(RendererLoadError) as excinfo:
        await first
    assert excinfo.value.reason == "superseded"
    assert ("stop", (), {}) not in cast.media_controller.calls
    assert backend._loads[RENDERER_ID].track_id == 905
    assert backend._loads[RENDERER_ID].confirmed is True


@pytest.mark.asyncio
async def test_cast_load_cancelled_by_a_newer_load_is_superseded():
    """Rapid skips: our own second LOAD cancels the first, which is no failure."""
    backend, cast = await loaded_backend()
    cast.media_controller.load_response = None
    first = asyncio.create_task(backend.play_track(RENDERER_ID, TRACK, CONTEXT))
    first_callback = await _wait_for_pending_load(cast)

    cast.media_controller.load_response = LOAD_ACCEPTED
    await backend.play_track(RENDERER_ID, TRACK_B, CONTEXT_B)
    first_callback(True, {"type": "LOAD_CANCELLED", "itemId": 1})

    with pytest.raises(RendererLoadError) as excinfo:
        await first
    assert excinfo.value.reason == "superseded"
    assert backend._loads[RENDERER_ID].track_id == 905


def test_cast_untracked_idle_without_reason_defers_to_position():
    """After a restart nothing is tracked; an IDLE without idleReason (or a
    FINISHED as the first status seen) is not conclusive, so the position
    heuristic stays in charge rather than the queue silently stalling."""
    from app.services.renderer.orchestrator import RendererOrchestrator

    backend = CastRendererBackend()
    near_end = {"queue": [{"id": 1, "duration_seconds": 180}], "current_index": 0, "position_seconds": 178}
    mid_track = {**near_end, "position_seconds": 60}
    for reason, kwargs in (
        (None, {"previous_state": "PLAYING", "started_at": 0}),
        (None, {"trust_idle": True}),
        ("FINISHED", {"trust_idle": True}),  # first status, no PLAYING seen
    ):
        mapped = backend.status_from_media_status(
            RENDERER_ID, idle_status(reason, position=0), **kwargs
        )
        assert mapped.ended is False, reason
        assert mapped.completion_reported is False, reason
        assert RendererOrchestrator._detect_track_ended(near_end, mapped, 178) is True
        assert RendererOrchestrator._detect_track_ended(mid_track, mapped, 60) is False

    for reason in ("CANCELLED", "INTERRUPTED", "ERROR"):
        mapped = backend.status_from_media_status(
            RENDERER_ID, idle_status(reason, position=0), trust_idle=True
        )
        assert mapped.completion_reported is True, reason
        assert RendererOrchestrator._detect_track_ended(near_end, mapped, 178) is False

    # FINISHED after PLAYING still ends it outright, as before.
    finished = backend.status_from_media_status(
        RENDERER_ID, idle_status("FINISHED"), previous_state="PLAYING", started_at=0
    )
    assert finished.ended is True
    assert finished.completion_reported is True
