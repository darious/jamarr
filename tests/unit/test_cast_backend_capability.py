"""Cast backend hierarchy retry tests.

Drives ``CastRendererBackend.play_track`` through the FLAC -> FLAC 16/48
-> WAV 16/48 -> MP3 320 hierarchy by faking pychromecast's load callback
and short-circuiting the capability-cache DB layer. Verifies that the
backend retries with the next profile on failure, stops on the first
success, and emits the expected user-facing progress messages.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from app.services.renderer import cast_backend as cb
from app.services.renderer.cast_backend import CastRendererBackend
from app.services.renderer.cast_capability import CastProfile
from app.services.renderer.contracts import PlaybackContext


class _FakeBrowser:
    def stop_discovery(self) -> None:  # pragma: no cover - parity with prod browser
        pass


class _FakeConn:
    pass


class _FakePool:
    @asynccontextmanager
    async def acquire(self):
        yield _FakeConn()


class _ScriptedMediaController:
    """play_media drives a scripted sequence of (success, response) results."""

    def __init__(self, results: list[tuple[bool, Any]]) -> None:
        self.results = list(results)
        self.calls: list[dict[str, Any]] = []
        self.listeners: list[Any] = []
        self.status = SimpleNamespace(
            player_state="PLAYING",
            adjusted_current_time=0,
            duration=120,
            volume_level=0.5,
            volume_muted=False,
            content_id=None,
        )

    def play_media(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append({"args": args, "kwargs": kwargs})
        callback = kwargs.get("callback_function")
        result = self.results.pop(0) if self.results else (True, {})
        if callback is not None:
            callback(*result)

    def pause(self) -> None: ...
    def play(self) -> None: ...
    def stop(self) -> None: ...
    def seek(self, seconds: float) -> None: ...

    def register_status_listener(self, listener: Any) -> None:
        self.listeners.append(listener)


class _FakeCast:
    def __init__(self) -> None:
        self.uuid = UUID("11111111-1111-1111-1111-111111111111")
        self.name = "Living Room"
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
        self.media_controller: _ScriptedMediaController = _ScriptedMediaController([])
        self.status = SimpleNamespace(volume_level=0.5, volume_muted=False)

    def wait(self, timeout: float | None = None) -> None: ...
    def start_app(self, *args: Any, **kwargs: Any) -> None: ...


def _track() -> dict[str, Any]:
    return {
        "id": 902,
        "path": "/music/song.flac",
        "title": "Song",
        "artist": "Artist",
        "album": "Album",
        "mime": "audio/flac",
        "duration_seconds": 180,
        "sample_rate_hz": 96000,
        "bit_depth": 24,
        "channels": 2,
    }


def _ctx() -> PlaybackContext:
    return PlaybackContext(base_url="http://127.0.0.1:8111", user_id=42, token_ttl_seconds=1800)


@pytest.fixture
def patched_capability(monkeypatch: pytest.MonkeyPatch):
    """Stub the DB-touching capability helpers used by play_track."""

    saved: dict[str, Any] = {"success": [], "failure": []}

    async def fake_get_capability(_db: Any, _renderer_id: str):
        return None

    async def fake_record_success(_db: Any, renderer_id: str, profile: CastProfile, track):
        saved["success"].append((renderer_id, profile, track))

    async def fake_record_failure(_db: Any, renderer_id: str, profile: CastProfile, track, reason):
        saved["failure"].append((renderer_id, profile, track, reason))

    monkeypatch.setattr(cb, "get_capability", fake_get_capability)
    monkeypatch.setattr(cb, "record_success", fake_record_success)
    monkeypatch.setattr(cb, "record_failure", fake_record_failure)
    return saved


@pytest.fixture
def backend_with_pool(monkeypatch: pytest.MonkeyPatch):
    cast = _FakeCast()
    backend = CastRendererBackend(chromecast_getter=lambda **_: ([cast], _FakeBrowser()))
    monkeypatch.setattr(backend, "_safe_pool", staticmethod(lambda: _FakePool()))
    return backend, cast


@pytest.mark.asyncio
async def test_play_track_succeeds_on_original_first_attempt(
    backend_with_pool: tuple[CastRendererBackend, _FakeCast],
    patched_capability: dict[str, Any],
):
    backend, cast = backend_with_pool
    cast.media_controller = _ScriptedMediaController([(True, {})])
    await backend.discover(refresh=True)
    renderer_id = "cast:11111111-1111-1111-1111-111111111111"

    status = await backend.play_track(renderer_id, _track(), _ctx())
    assert await backend.wait_for_load_settled(renderer_id, timeout=2.0)

    assert status.state == "PLAYING"
    assert len(cast.media_controller.calls) == 1
    call = cast.media_controller.calls[0]
    assert call["args"][1] == "audio/flac"
    assert "profile=" not in call["args"][0]  # original = no profile query
    assert patched_capability["success"][-1][1] == CastProfile.ORIGINAL_FLAC
    assert patched_capability["failure"] == []


@pytest.mark.asyncio
async def test_play_track_walks_hierarchy_until_a_profile_succeeds(
    backend_with_pool: tuple[CastRendererBackend, _FakeCast],
    patched_capability: dict[str, Any],
):
    backend, cast = backend_with_pool
    cast.media_controller = _ScriptedMediaController(
        [
            (False, {"reason": "UNSUPPORTED_MEDIA"}),  # original fails
            (False, {"reason": "BAD_REQUEST"}),         # FLAC 16/48 fails
            (True, {}),                                 # WAV 16/48 succeeds
        ]
    )
    await backend.discover(refresh=True)
    renderer_id = "cast:11111111-1111-1111-1111-111111111111"

    status = await backend.play_track(renderer_id, _track(), _ctx())
    assert await backend.wait_for_load_settled(renderer_id, timeout=2.0)

    assert status.state == "PLAYING"
    profiles_attempted = [c["args"][0].split("profile=")[-1].split("&")[0] if "profile=" in c["args"][0] else "original_flac" for c in cast.media_controller.calls]
    assert profiles_attempted == ["original_flac", "flac_16_48", "wav_16_48"]
    mimes = [c["args"][1] for c in cast.media_controller.calls]
    assert mimes == ["audio/flac", "audio/flac", "audio/wav"]

    failures = [profile for (_, profile, _, _) in patched_capability["failure"]]
    assert failures == [CastProfile.ORIGINAL_FLAC, CastProfile.FLAC_16_48]
    assert patched_capability["success"][-1][1] == CastProfile.WAV_16_48
    # Lossless fallback succeeded; transient progress cleared.
    assert backend.get_progress_message(renderer_id) is None


@pytest.mark.asyncio
async def test_play_track_emergency_fallback_announces_mp3(
    backend_with_pool: tuple[CastRendererBackend, _FakeCast],
    patched_capability: dict[str, Any],
):
    backend, cast = backend_with_pool
    cast.media_controller = _ScriptedMediaController(
        [
            (False, {"reason": "UNSUPPORTED"}),
            (False, {"reason": "UNSUPPORTED"}),
            (False, {"reason": "UNSUPPORTED"}),
            (True, {}),  # MP3 320 succeeds last
        ]
    )
    await backend.discover(refresh=True)
    renderer_id = "cast:11111111-1111-1111-1111-111111111111"

    status = await backend.play_track(renderer_id, _track(), _ctx())
    assert await backend.wait_for_load_settled(renderer_id, timeout=2.0)

    assert status.state == "PLAYING"
    assert "MP3" in (backend.get_progress_message(renderer_id) or "")
    last_call = cast.media_controller.calls[-1]
    assert last_call["args"][1] == "audio/mpeg"
    assert "profile=mp3_320" in last_call["args"][0]


@pytest.mark.asyncio
async def test_play_track_records_failure_for_every_profile_when_all_fail(
    backend_with_pool: tuple[CastRendererBackend, _FakeCast],
    patched_capability: dict[str, Any],
):
    backend, cast = backend_with_pool
    cast.media_controller = _ScriptedMediaController(
        [(False, {"reason": "UNSUPPORTED"})] * 4
    )
    await backend.discover(refresh=True)
    renderer_id = "cast:11111111-1111-1111-1111-111111111111"

    await backend.play_track(renderer_id, _track(), _ctx())
    assert await backend.wait_for_load_settled(renderer_id, timeout=2.0)

    failed_profiles = [profile for (_, profile, _, _) in patched_capability["failure"]]
    assert set(failed_profiles) == set(CastProfile)
    assert backend.get_progress_message(renderer_id) == "Could not play this track on Cast"
    assert patched_capability["success"] == []
