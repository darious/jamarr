import asyncio
from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient

from tests.unit.test_renderer_phase2_cast import FakeCast, make_backend


@pytest.fixture
async def phase2_cast_track(db):
    await db.execute(
        """
        INSERT INTO track (id, path, title, artist, album, duration_seconds)
        VALUES (901, '/music/phase2-cast.flac', 'Cast Song', 'Cast Artist', 'Cast Album', 240)
        """
    )


@pytest.fixture
async def selected_cast_renderer(db):
    renderer_id = "cast:11111111-1111-1111-1111-111111111111"
    await db.execute(
        """
        INSERT INTO client_session (
            client_id, active_renderer_udn, active_renderer_id, last_seen_at
        )
        VALUES ('phase2-client', $1, $1, NOW())
        """,
        renderer_id,
    )
    return renderer_id


@pytest.fixture
async def fake_cast_backend(monkeypatch):
    cast = FakeCast()
    backend, _browser = make_backend(cast)
    await backend.discover(refresh=True)
    monitor_starts = []

    import app.api.player as player_api
    import app.services.renderer.orchestrator as orchestrator_module

    monkeypatch.setitem(player_api.renderer_orchestrator.registry.backends, "cast", backend)
    monkeypatch.setattr(player_api, "start_monitor_task", lambda renderer: monitor_starts.append(renderer))
    monkeypatch.setattr(orchestrator_module, "start_monitor_task", lambda renderer: monitor_starts.append(renderer))
    return backend, cast, monitor_starts


@pytest.mark.asyncio
async def test_phase2_renderers_can_return_cast_devices(
    auth_client: AsyncClient,
    fake_cast_backend,
):
    response = await auth_client.get(
        "/api/renderers",
        headers={"X-Jamarr-Client-Id": "phase2-client"},
    )

    assert response.status_code == 200, response.text
    cast_rows = [row for row in response.json() if row["kind"] == "cast"]
    assert cast_rows
    assert cast_rows[0]["renderer_id"] == "cast:11111111-1111-1111-1111-111111111111"
    assert cast_rows[0]["cast_type"] == "audio"
    assert cast_rows[0]["capabilities"]["supports_events"] is True


@pytest.mark.asyncio
async def test_phase2_cast_state_syncs_receiver_volume_without_media(
    auth_client: AsyncClient,
    selected_cast_renderer,
    fake_cast_backend,
):
    _, cast, _ = fake_cast_backend
    headers = {"X-Jamarr-Client-Id": "phase2-client"}
    cast.media_controller.status.player_state = None
    cast.media_controller.status.volume_level = 1.0
    cast.media_controller.status.volume_muted = False
    cast.media_controller.status.content_id = None
    cast.status.volume_level = 0.25
    cast.status.volume_muted = False

    state = await auth_client.get("/api/player/state", headers=headers)

    assert state.status_code == 200, state.text
    assert state.json()["renderer_id"] == selected_cast_renderer
    assert state.json()["volume"] == 25


@pytest.mark.asyncio
async def test_phase2_player_controls_route_to_cast_backend(
    auth_client: AsyncClient,
    phase2_cast_track,
    selected_cast_renderer,
    fake_cast_backend,
):
    _, cast, monitor_starts = fake_cast_backend
    headers = {"X-Jamarr-Client-Id": "phase2-client"}

    play = await auth_client.post(
        "/api/player/play",
        json={"track_id": 901},
        headers=headers,
    )
    play_again = await auth_client.post(
        "/api/player/play",
        json={"track_id": 901},
        headers=headers,
    )
    pause = await auth_client.post("/api/player/pause", headers=headers)
    resume = await auth_client.post("/api/player/resume", headers=headers)
    seek = await auth_client.post("/api/player/seek", json={"seconds": 22}, headers=headers)
    volume = await auth_client.post("/api/player/volume", json={"percent": 44}, headers=headers)

    assert play.status_code == 200, play.text
    assert play.json() == {"status": "streaming_started", "renderer": selected_cast_renderer}
    assert play_again.status_code == 200, play_again.text
    assert play_again.json() == {"status": "already_playing", "renderer": selected_cast_renderer}
    assert pause.status_code == 200, pause.text
    assert resume.status_code == 200, resume.text
    assert seek.status_code == 200, seek.text
    assert volume.status_code == 200, volume.text

    assert any(call[0] == "start_app" for call in cast.calls)
    assert ("pause", (), {}) in cast.media_controller.calls
    assert ("play", (), {}) in cast.media_controller.calls
    assert ("seek", (22.0,), {}) in cast.media_controller.calls
    assert ("set_volume", 0.44) in cast.calls
    assert monitor_starts == []

    state = await auth_client.get("/api/player/state", headers=headers)
    assert state.status_code == 200
    assert state.json()["renderer_id"] == selected_cast_renderer
    assert state.json()["renderer_kind"] == "cast"
    assert state.json()["position_seconds"] == 12
    assert state.json()["volume"] == 40
    assert monitor_starts == []


@pytest.mark.asyncio
async def test_phase2_clear_queue_closes_cast_session(
    auth_client: AsyncClient,
    phase2_cast_track,
    selected_cast_renderer,
    fake_cast_backend,
):
    _, cast, monitor_starts = fake_cast_backend
    headers = {"X-Jamarr-Client-Id": "phase2-client"}

    play = await auth_client.post(
        "/api/player/play",
        json={"track_id": 901},
        headers=headers,
    )
    clear = await auth_client.post("/api/player/queue/clear", headers=headers)

    assert play.status_code == 200, play.text
    assert clear.status_code == 200, clear.text
    assert ("stop", (), {}) in cast.media_controller.calls
    assert ("quit_app", 10) in cast.calls
    assert monitor_starts == []


@pytest.mark.asyncio
async def test_phase2_switching_away_from_cast_closes_previous_session(
    auth_client: AsyncClient,
    selected_cast_renderer,
    fake_cast_backend,
):
    _, cast, monitor_starts = fake_cast_backend
    headers = {"X-Jamarr-Client-Id": "phase2-client"}

    response = await auth_client.post(
        "/api/player/renderer",
        json={"renderer_id": "local:phase2-client"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["renderer_id"] == "local:phase2-client"
    assert ("stop", (), {}) in cast.media_controller.calls
    assert ("quit_app", 10) in cast.calls
    assert monitor_starts == []


@pytest.mark.asyncio
async def test_phase2_cast_progress_logs_history_and_scrobbles(
    auth_client: AsyncClient,
    db,
    phase2_cast_track,
    selected_cast_renderer,
    fake_cast_backend,
):
    _, cast, monitor_starts = fake_cast_backend
    headers = {"X-Jamarr-Client-Id": "phase2-client"}
    user = await db.fetchrow('SELECT id FROM "user" WHERE username = $1', "testuser")
    await db.execute(
        """
        UPDATE "user"
        SET lastfm_username = $1,
            lastfm_session_key = $2,
            lastfm_enabled = TRUE
        WHERE id = $3
        """,
        "testuser_lastfm",
        "test_session_key",
        user["id"],
    )

    play = await auth_client.post(
        "/api/player/play",
        json={"track_id": 901},
        headers=headers,
    )
    cast.media_controller.status.adjusted_current_time = 35
    cast.media_controller.status.current_time = 35

    with patch("app.lastfm.scrobble_track", new_callable=AsyncMock) as mock_scrobble:
        state = await auth_client.get("/api/player/state", headers=headers)
        await asyncio.sleep(0.1)

    assert play.status_code == 200, play.text
    assert state.status_code == 200, state.text
    assert state.json()["queue"][0]["logged"] is True
    rows = await db.fetch("SELECT track_id, client_id, user_id FROM playback_history WHERE track_id = 901")
    assert len(rows) == 1
    assert rows[0]["client_id"] == selected_cast_renderer
    assert rows[0]["user_id"] == user["id"]
    assert mock_scrobble.called
    assert mock_scrobble.call_args.kwargs["session_key"] == "test_session_key"
    assert mock_scrobble.call_args.kwargs["track_info"]["track"] == "Cast Song"
    assert monitor_starts == []


# --- Truthful Cast loading and completion (issue #316) ---------------------

HEADERS = {"X-Jamarr-Client-Id": "phase2-client"}


@pytest.fixture
def clean_cast_player_globals(selected_cast_renderer, monkeypatch):
    import app.api.player as player_api
    from app.services.player.globals import last_stop_reason

    last_stop_reason.pop(selected_cast_renderer, None)
    # The orchestrator is a process singleton; its end-of-track debounce must
    # not leak in from another test.
    monkeypatch.setattr(player_api.renderer_orchestrator, "_last_ended_at", {})
    yield player_api.renderer_orchestrator
    last_stop_reason.pop(selected_cast_renderer, None)


@pytest.fixture
async def two_track_cast_queue(db, auth_client, phase2_cast_track, fake_cast_backend, selected_cast_renderer):
    """Track 901 playing on the Cast device, with 902 queued after it."""
    from app.services.player.state import get_renderer_state_db, update_renderer_state_db

    await db.execute(
        """
        INSERT INTO track (id, path, title, artist, album, duration_seconds)
        VALUES (902, '/music/phase2-cast-2.flac', 'Next Song', 'Cast Artist', 'Cast Album', 200)
        """
    )
    play = await auth_client.post("/api/player/play", json={"track_id": 901}, headers=HEADERS)
    assert play.status_code == 200, play.text
    state = await get_renderer_state_db(db, selected_cast_renderer)
    state["queue"].append(
        {"id": 902, "title": "Next Song", "artist": "Cast Artist", "album": "Cast Album", "duration_seconds": 200}
    )
    await update_renderer_state_db(db, selected_cast_renderer, state)
    return fake_cast_backend


def _play_media_calls(cast):
    return [call for call in cast.media_controller.calls if call[0] == "play_media"]


def _receiver_goes_idle(cast, idle_reason):
    status = cast.media_controller.status
    status.player_state = "IDLE"
    status.idle_reason = idle_reason
    status.adjusted_current_time = 239
    # A snapshot: the fake mutates its live status when the next LOAD lands.
    return SimpleNamespace(**vars(status))


@pytest.mark.asyncio
async def test_cast_rejected_load_surfaces_error_and_clears_playing(
    auth_client: AsyncClient,
    db,
    phase2_cast_track,
    selected_cast_renderer,
    fake_cast_backend,
    clean_cast_player_globals,
):
    from tests.unit.test_renderer_phase2_cast import LOAD_FAILED

    _, cast, _ = fake_cast_backend
    cast.media_controller.load_response = LOAD_FAILED

    play = await auth_client.post("/api/player/play", json={"track_id": 901}, headers=HEADERS)

    assert play.status_code == 502, play.text
    assert "could not play" in play.json()["detail"]
    row = await db.fetchrow(
        "SELECT is_playing, transport_state FROM renderer_state WHERE renderer_udn = $1",
        selected_cast_renderer,
    )
    assert row["is_playing"] is False
    assert row["transport_state"] == "STOPPED"

    # The receiver sits idle after refusing the media.
    cast.media_controller.status.player_state = "IDLE"
    state = await auth_client.get("/api/player/state", headers=HEADERS)
    assert state.status_code == 200, state.text
    assert state.json()["is_playing"] is False
    assert state.json()["stopped_reason"] == "load_failed"


@pytest.mark.asyncio
async def test_cast_load_timeout_surfaces_error(
    auth_client: AsyncClient,
    db,
    phase2_cast_track,
    selected_cast_renderer,
    fake_cast_backend,
    clean_cast_player_globals,
):
    backend, cast, _ = fake_cast_backend
    backend.load_timeout = 0.05
    cast.media_controller.load_response = None

    play = await auth_client.post("/api/player/play", json={"track_id": 901}, headers=HEADERS)

    assert play.status_code == 502, play.text
    assert "did not confirm" in play.json()["detail"]
    assert await db.fetchval(
        "SELECT is_playing FROM renderer_state WHERE renderer_udn = $1", selected_cast_renderer
    ) is False


@pytest.mark.asyncio
async def test_cast_finished_advances_queue_once(
    auth_client: AsyncClient,
    db,
    selected_cast_renderer,
    two_track_cast_queue,
    clean_cast_player_globals,
):
    from app.services.player.state import get_renderer_state_db

    backend, cast, _ = two_track_cast_queue
    orchestrator = clean_cast_player_globals
    finished = _receiver_goes_idle(cast, "FINISHED")

    status = backend.status_from_media_status(selected_cast_renderer, finished)
    assert status.ended is True
    await orchestrator.handle_status(selected_cast_renderer, status)

    state = await get_renderer_state_db(db, selected_cast_renderer)
    assert state["current_index"] == 1
    assert state["is_playing"] is True
    assert len(_play_media_calls(cast)) == 2
    assert "/api/stream/902" in _play_media_calls(cast)[1][1][0]

    # A repeated FINISHED for the old media (re-broadcast, poll) is ignored.
    repeat = backend.status_from_media_status(
        selected_cast_renderer, finished, previous_state="PLAYING", started_at=0
    )
    orchestrator._last_ended_at.clear()
    await orchestrator.handle_status(selected_cast_renderer, repeat)

    state = await get_renderer_state_db(db, selected_cast_renderer)
    assert state["current_index"] == 1
    assert len(_play_media_calls(cast)) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("idle_reason", "stopped_reason"),
    [
        ("CANCELLED", "renderer_stopped"),
        ("INTERRUPTED", "renderer_stopped"),
        ("ERROR", "renderer_error"),
    ],
)
async def test_cast_non_finished_idle_halts_queue(
    auth_client: AsyncClient,
    db,
    selected_cast_renderer,
    two_track_cast_queue,
    clean_cast_player_globals,
    idle_reason,
    stopped_reason,
):
    from app.services.player.state import get_renderer_state_db

    backend, cast, _ = two_track_cast_queue
    orchestrator = clean_cast_player_globals
    idle = _receiver_goes_idle(cast, idle_reason)

    status = backend.status_from_media_status(
        selected_cast_renderer, idle, previous_state="PLAYING", started_at=0
    )
    await orchestrator.handle_status(selected_cast_renderer, status)

    state = await get_renderer_state_db(db, selected_cast_renderer)
    assert state["current_index"] == 0
    assert state["is_playing"] is False
    assert len(_play_media_calls(cast)) == 1

    # Polling sees the same idle receiver: still no advance, reason kept.
    polled = await auth_client.get("/api/player/state", headers=HEADERS)
    assert polled.status_code == 200, polled.text
    assert polled.json()["current_index"] == 0
    assert polled.json()["is_playing"] is False
    assert polled.json()["stopped_reason"] == stopped_reason
    assert len(_play_media_calls(cast)) == 1


@pytest.mark.asyncio
async def test_cast_resume_after_halt_reloads_and_seeks(
    auth_client: AsyncClient,
    db,
    selected_cast_renderer,
    two_track_cast_queue,
    clean_cast_player_globals,
):
    backend, cast, _ = two_track_cast_queue
    orchestrator = clean_cast_player_globals
    await db.execute(
        "UPDATE renderer_state SET position_seconds = 120 WHERE renderer_udn = $1",
        selected_cast_renderer,
    )
    idle = _receiver_goes_idle(cast, "CANCELLED")
    status = backend.status_from_media_status(
        selected_cast_renderer, idle, previous_state="PLAYING", started_at=0
    )
    await orchestrator.handle_status(selected_cast_renderer, status)

    resumed = await auth_client.post("/api/player/resume", headers=HEADERS)

    assert resumed.status_code == 200, resumed.text
    # The halted session has nothing to play(); the track is loaded again.
    assert ("play", (), {}) not in cast.media_controller.calls
    assert len(_play_media_calls(cast)) == 2
    assert "/api/stream/901" in _play_media_calls(cast)[1][1][0]
    assert ("seek", (120,), {}) in cast.media_controller.calls


@pytest.mark.asyncio
async def test_polled_cast_finished_advances_in_background_once(
    auth_client: AsyncClient,
    db,
    selected_cast_renderer,
    two_track_cast_queue,
    clean_cast_player_globals,
):
    """GET /api/player/state seeing FINISHED moves the queue, but the next
    LOAD (seconds on a slow receiver) does not hold the request."""
    backend, cast, _ = two_track_cast_queue
    orchestrator = clean_cast_player_globals
    backend.load_timeout = 5
    _receiver_goes_idle(cast, "FINISHED")
    cast.media_controller.pending_load_callback = None
    cast.media_controller.load_response = None  # the next LOAD hangs

    state = await asyncio.wait_for(
        auth_client.get("/api/player/state", headers=HEADERS), timeout=2
    )

    assert state.status_code == 200, state.text
    assert state.json()["current_index"] == 1
    assert state.json()["is_playing"] is True
    for _ in range(200):
        if cast.media_controller.pending_load_callback:
            break
        await asyncio.sleep(0.01)
    assert len(_play_media_calls(cast)) == 2
    assert "/api/stream/902" in _play_media_calls(cast)[1][1][0]

    # Polling again while that LOAD is pending neither reloads nor advances.
    again = await asyncio.wait_for(
        auth_client.get("/api/player/state", headers=HEADERS), timeout=2
    )
    assert again.json()["current_index"] == 1
    assert len(_play_media_calls(cast)) == 2

    from tests.unit.test_renderer_phase2_cast import LOAD_ACCEPTED

    cast.media_controller.pending_load_callback(*LOAD_ACCEPTED)
    await asyncio.wait_for(
        asyncio.gather(*orchestrator._background_tasks), timeout=2
    )
    assert backend._loads[selected_cast_renderer].confirmed is True


@pytest.mark.asyncio
async def test_superseded_cast_load_is_not_a_failure(
    auth_client: AsyncClient,
    db,
    selected_cast_renderer,
    two_track_cast_queue,
    clean_cast_player_globals,
    monkeypatch,
):
    """The first of two rapid skips is cancelled by the second: no 502, no
    load_failed banner, and the newer load's state is left alone."""
    from app.services.player.globals import last_stop_reason
    from app.services.renderer.contracts import RendererLoadError

    backend, _cast, _ = two_track_cast_queue

    async def superseded(renderer_id, track, context):
        raise RendererLoadError(renderer_id, "superseded", "LOAD_CANCELLED")

    monkeypatch.setattr(backend, "play_track", superseded)
    # The fixture tracks are not on disk in the test container.
    import app.services.renderer.orchestrator as orchestrator_module

    monkeypatch.setattr(orchestrator_module, "track_path_exists", lambda track: True)

    skip = await auth_client.post("/api/player/index", json={"index": 1}, headers=HEADERS)

    assert skip.status_code == 200, skip.text
    assert selected_cast_renderer not in last_stop_reason
    assert await db.fetchval(
        "SELECT is_playing FROM renderer_state WHERE renderer_udn = $1", selected_cast_renderer
    ) is True


@pytest.mark.asyncio
async def test_load_failure_for_a_track_no_longer_current_records_nothing(
    db,
    selected_cast_renderer,
    two_track_cast_queue,
    clean_cast_player_globals,
):
    from app.services.player.globals import last_stop_reason
    from app.services.player.state import get_renderer_state_db, update_renderer_state_db
    from app.services.renderer.contracts import RendererLoadError

    orchestrator = clean_cast_player_globals
    state = await get_renderer_state_db(db, selected_cast_renderer)
    state["current_index"] = 1  # 902 started after the 901 load was issued
    await update_renderer_state_db(db, selected_cast_renderer, state)

    recorded = await orchestrator._record_load_failure(
        selected_cast_renderer,
        {"id": 901},
        RendererLoadError(selected_cast_renderer, "load_rejected", "LOAD_FAILED"),
        db=db,
    )

    assert recorded is False
    assert selected_cast_renderer not in last_stop_reason
    state = await get_renderer_state_db(db, selected_cast_renderer)
    assert state["is_playing"] is True


class _FailingUpnpManager:
    """UPnP manager whose renderer refuses SetAVTransportURI."""

    def __init__(self, exc):
        self.exc = exc
        self.renderers = {"uuid:refuses": {"friendly_name": "Amp"}}
        self.dmr_devices = {}
        self.local_ip = "127.0.0.1"
        self.base_url = "http://127.0.0.1:8111"
        self.renderer_base_url = "http://127.0.0.1:8112"
        self.active_renderer = None
        self.control_failures = []

    async def set_renderer(self, udn):
        self.active_renderer = udn

    async def play_track(self, track_id, track_path, metadata, username=None):
        raise self.exc

    def note_control_failure(self, udn):
        self.control_failures.append(udn)


@pytest.fixture
async def refusing_upnp_renderer(db, monkeypatch):
    from async_upnp_client.exceptions import UpnpActionError

    import app.api.player as player_api
    from app.services.player.globals import last_stop_reason
    from app.services.renderer.upnp_backend import UpnpRendererBackend

    manager = _FailingUpnpManager(UpnpActionError(error_code=714, error_desc="Illegal MIME-type"))
    monkeypatch.setitem(
        player_api.renderer_orchestrator.registry.backends,
        "upnp",
        UpnpRendererBackend(manager=manager),
    )
    await db.execute(
        """
        INSERT INTO client_session (
            client_id, active_renderer_udn, active_renderer_id, last_seen_at
        )
        VALUES ('phase2-client', 'uuid:refuses', 'upnp:uuid:refuses', NOW())
        """
    )
    last_stop_reason.pop("uuid:refuses", None)
    yield manager
    last_stop_reason.pop("uuid:refuses", None)


@pytest.mark.asyncio
async def test_upnp_refused_load_rolls_back_like_cast(
    auth_client: AsyncClient,
    db,
    phase2_cast_track,
    refusing_upnp_renderer,
):
    from app.services.player.globals import last_stop_reason

    play = await auth_client.post("/api/player/play", json={"track_id": 901}, headers=HEADERS)

    assert play.status_code == 502, play.text
    assert "could not play" in play.json()["detail"]
    row = await db.fetchrow(
        "SELECT is_playing, transport_state FROM renderer_state WHERE renderer_udn = $1",
        "uuid:refuses",
    )
    assert row["is_playing"] is False
    assert row["transport_state"] == "STOPPED"
    assert last_stop_reason["uuid:refuses"]["reason"] == "load_failed"
    assert refusing_upnp_renderer.control_failures == ["uuid:refuses"]


@pytest.mark.asyncio
async def test_upnp_unregistered_device_still_raises_value_error():
    """ValueError (device not registered) is not turned into a load error:
    stale-renderer healing keys on it."""
    from app.services.renderer.upnp_backend import UpnpRendererBackend
    from app.services.renderer.contracts import PlaybackContext

    backend = UpnpRendererBackend(manager=_FailingUpnpManager(ValueError("DMR device not found")))
    with pytest.raises(ValueError):
        await backend.play_track(
            "upnp:uuid:refuses",
            {"id": 901, "path": "/music/x.flac"},
            PlaybackContext(base_url="http://127.0.0.1:8111", user_id=None),
        )


def _token_claims(url):
    from urllib.parse import parse_qs, urlparse

    import jwt

    return jwt.decode(
        parse_qs(urlparse(url).query)["token"][0], options={"verify_signature": False}
    )


@pytest.mark.asyncio
async def test_cast_load_mime_matches_plan_and_state_exposes_it(
    auth_client: AsyncClient,
    db,
    selected_cast_renderer,
    fake_cast_backend,
    monkeypatch,
):
    """An ALAC .m4a is not playable on the Default Media Receiver: the plan
    decodes it, the LOAD and the token agree on audio/flac, and player state
    and the renderer API explain it."""
    from app import config as app_config

    monkeypatch.setattr(app_config, "_config", {"renderer": {}})
    monkeypatch.setattr(
        "app.services.audio_streaming.probe_audio_file", lambda _path: {"codec": "alac"}
    )
    monkeypatch.setattr("app.services.audio_streaming.os.path.exists", lambda _p: True)
    await db.execute(
        """
        INSERT INTO track (id, path, title, artist, album, duration_seconds,
                           codec, sample_rate_hz, bit_depth, channels)
        VALUES (905, '/music/alac.m4a', 'Alac Song', 'Artist', 'Album', 200,
                'MP4', 44100, 24, 2)
        """
    )
    _, cast, _ = fake_cast_backend

    play = await auth_client.post("/api/player/play", json={"track_id": 905}, headers=HEADERS)
    assert play.status_code == 200, play.text

    url, load_mime = _play_media_calls(cast)[-1][1][0], _play_media_calls(cast)[-1][1][1]
    assert load_mime == "audio/flac"
    claims = _token_claims(url)
    assert claims["out"] == "flac" and claims["out_mime"] == load_mime

    state = await auth_client.get("/api/player/state", headers=HEADERS)
    assert state.status_code == 200, state.text
    plan = state.json()["output_plan"]
    assert plan["action"] == "decode"
    assert plan["mime_type"] == "audio/flac"
    assert "ALAC" in plan["reason"]
    assert plan["quality_label"] == "FLAC 24 bit 44.1 kHz"

    renderers = (await auth_client.get("/api/renderers", headers=HEADERS)).json()
    cast_row = next(r for r in renderers if r["kind"] == "cast")
    assert "audio/flac" in cast_row["output_constraints"]["supported_mime_types"]
    assert cast_row["output_constraints"]["flac_max_block_size"] is None


class _RecordingUpnpManager(_FailingUpnpManager):
    def __init__(self, renderer_info):
        super().__init__(None)
        self.renderers = {"uuid:refuses": renderer_info}
        self.played = []

    async def play_track(self, track_id, track_path, metadata, username=None):
        self.played.append(metadata)


@pytest.mark.asyncio
async def test_upnp_didl_mime_and_size_follow_the_plan(
    auth_client: AsyncClient, db, phase2_cast_track, refusing_upnp_renderer, monkeypatch
):
    """A WAV-only renderer: DIDL gets audio/wav (the served Content-Type) and
    loses the FLAC file's size, which no longer describes the bytes."""
    import app.api.player as player_api
    from app import config as app_config
    from app.services.renderer.upnp_backend import UpnpRendererBackend

    monkeypatch.setattr(app_config, "_config", {"renderer": {}})
    await db.execute(
        "UPDATE track SET codec = 'FLAC', sample_rate_hz = 44100, bit_depth = 16, "
        "channels = 2, size_bytes = 12345 WHERE id = 901"
    )
    manager = _RecordingUpnpManager(
        {"friendly_name": "Amp", "supported_mime_types": "audio/wav,audio/mpeg"}
    )
    monkeypatch.setitem(
        player_api.renderer_orchestrator.registry.backends,
        "upnp",
        UpnpRendererBackend(manager=manager),
    )

    play = await auth_client.post(
        "/api/player/play",
        json={"track_id": 901},
        headers=HEADERS,
    )

    assert play.status_code == 200, play.text
    metadata = manager.played[-1]
    assert metadata["mime"] == "audio/wav"
    assert "size_bytes" not in metadata
    assert _token_claims(metadata["stream_url"])["out"] == "wav"


# --- Cast receiver status, queue mode and restart re-adoption (#316) -------


@pytest.fixture
def cast_queue_mode(two_track_cast_queue, clean_cast_player_globals, monkeypatch):
    """The two-track Cast queue with receiver-queue staging switched on."""
    import app.services.renderer.orchestrator as orchestrator_module

    backend, cast, _ = two_track_cast_queue
    orchestrator = clean_cast_player_globals
    monkeypatch.setattr(backend, "queue_mode_enabled", lambda renderer_id: True)
    # The fixture tracks are not on disk in the test container.
    monkeypatch.setattr(orchestrator_module, "track_path_exists", lambda track: True)
    monkeypatch.setattr(orchestrator, "_staging_in_flight", set())
    monkeypatch.setattr(orchestrator, "_stage_failures", {})
    return backend, cast, orchestrator


def _media_snapshot(cast, **changes):
    status = cast.media_controller.status
    for key, value in changes.items():
        setattr(status, key, value)
    return SimpleNamespace(**vars(status))


async def _drain(orchestrator):
    if orchestrator._background_tasks:
        await asyncio.wait_for(asyncio.gather(*orchestrator._background_tasks), timeout=5)


def _queue_inserts(cast):
    return [m for m in cast.media_controller.sent_messages if m.get("type") == "QUEUE_INSERT"]


@pytest.mark.asyncio
async def test_cast_queue_mode_stages_next_and_follows_receiver_advance(
    auth_client: AsyncClient,
    db,
    selected_cast_renderer,
    cast_queue_mode,
):
    from app.services.player.state import get_renderer_state_db

    backend, cast, orchestrator = cast_queue_mode
    playing = _media_snapshot(cast, player_state="PLAYING", adjusted_current_time=15)

    await orchestrator.handle_status(
        selected_cast_renderer, backend.status_from_media_status(selected_cast_renderer, playing)
    )
    await _drain(orchestrator)

    inserts = _queue_inserts(cast)
    assert len(inserts) == 1
    staged_url = inserts[0]["items"][0]["media"]["contentId"]
    assert "/api/stream/902" in staged_url
    assert backend.staged_track_id(selected_cast_renderer) == 902

    # Played on: no second insert for the same next track.
    await orchestrator.handle_status(
        selected_cast_renderer, backend.status_from_media_status(selected_cast_renderer, playing)
    )
    await _drain(orchestrator)
    assert len(_queue_inserts(cast)) == 1

    # The current item finishes; the receiver holds it, then plays 902 itself.
    finished = _receiver_goes_idle(cast, "FINISHED")
    await orchestrator.handle_status(
        selected_cast_renderer, backend.status_from_media_status(selected_cast_renderer, finished)
    )
    state = await get_renderer_state_db(db, selected_cast_renderer)
    assert state["current_index"] == 0

    rolled = _media_snapshot(
        cast,
        player_state="PLAYING",
        idle_reason=None,
        adjusted_current_time=1,
        content_id=staged_url,
        media_custom_data=inserts[0]["items"][0]["media"]["customData"],
    )
    status = backend.status_from_media_status(selected_cast_renderer, rolled)
    assert status.advanced_by_renderer is True
    await orchestrator.handle_status(selected_cast_renderer, status)
    again = backend.status_from_media_status(selected_cast_renderer, rolled)
    await orchestrator.handle_status(selected_cast_renderer, again)

    state = await get_renderer_state_db(db, selected_cast_renderer)
    assert state["current_index"] == 1
    assert state["is_playing"] is True
    # Exactly once, and nothing was reloaded.
    assert len(_play_media_calls(cast)) == 1


@pytest.mark.asyncio
async def test_cast_queue_mode_stale_queued_item_loads_real_next(
    auth_client: AsyncClient,
    db,
    selected_cast_renderer,
    cast_queue_mode,
):
    from app.services.player.state import get_renderer_state_db, update_renderer_state_db

    backend, cast, orchestrator = cast_queue_mode
    await db.execute(
        """
        INSERT INTO track (id, path, title, artist, album, duration_seconds)
        VALUES (903, '/music/phase2-cast-3.flac', 'Other Song', 'Cast Artist', 'Cast Album', 210)
        """
    )
    playing = _media_snapshot(cast, player_state="PLAYING", adjusted_current_time=15)
    await orchestrator.handle_status(
        selected_cast_renderer, backend.status_from_media_status(selected_cast_renderer, playing)
    )
    await _drain(orchestrator)
    staged = _queue_inserts(cast)[0]["items"][0]["media"]

    # The listener edits the queue: 903 replaces 902 as the next track.
    state = await get_renderer_state_db(db, selected_cast_renderer)
    state["queue"][1] = {"id": 903, "title": "Other Song", "duration_seconds": 210}
    await update_renderer_state_db(db, selected_cast_renderer, state)

    rolled = _media_snapshot(
        cast,
        player_state="PLAYING",
        adjusted_current_time=1,
        content_id=staged["contentId"],
        media_custom_data=staged["customData"],
    )
    await orchestrator.handle_status(
        selected_cast_renderer, backend.status_from_media_status(selected_cast_renderer, rolled)
    )

    state = await get_renderer_state_db(db, selected_cast_renderer)
    assert state["current_index"] == 1
    assert len(_play_media_calls(cast)) == 2
    assert "/api/stream/903" in _play_media_calls(cast)[1][1][0]


def _queue_removes(cast):
    return [m for m in cast.media_controller.sent_messages if m.get("type") == "QUEUE_REMOVE"]


@pytest.mark.asyncio
async def test_cast_queue_mode_removes_staged_item_when_no_next_track_remains(
    auth_client: AsyncClient,
    db,
    selected_cast_renderer,
    cast_queue_mode,
):
    from app.services.player.state import get_renderer_state_db, update_renderer_state_db

    backend, cast, orchestrator = cast_queue_mode
    playing = _media_snapshot(cast, player_state="PLAYING", adjusted_current_time=15)
    await orchestrator.handle_status(
        selected_cast_renderer, backend.status_from_media_status(selected_cast_renderer, playing)
    )
    await _drain(orchestrator)
    [insert] = _queue_inserts(cast)
    assert backend.staged_track_id(selected_cast_renderer) == 902
    assert _queue_removes(cast) == []

    # The listener removes the only next track from the queue.
    state = await get_renderer_state_db(db, selected_cast_renderer)
    state["queue"] = state["queue"][:1]
    await update_renderer_state_db(db, selected_cast_renderer, state)

    await orchestrator.handle_status(
        selected_cast_renderer, backend.status_from_media_status(selected_cast_renderer, playing)
    )
    await _drain(orchestrator)

    [remove] = _queue_removes(cast)
    assert remove["itemIds"] == [100]
    assert backend.staged_track_id(selected_cast_renderer) is None

    # Played on: nothing staged, nothing further sent.
    sent = len(cast.media_controller.sent_messages)
    await orchestrator.handle_status(
        selected_cast_renderer, backend.status_from_media_status(selected_cast_renderer, playing)
    )
    await _drain(orchestrator)
    assert len(cast.media_controller.sent_messages) == sent
    assert len(_queue_inserts(cast)) == 1


@pytest.mark.asyncio
async def test_cast_queue_mode_refused_remove_is_not_retried_at_once(
    auth_client: AsyncClient,
    db,
    selected_cast_renderer,
    cast_queue_mode,
):
    from app.services.player.state import get_renderer_state_db, update_renderer_state_db

    backend, cast, orchestrator = cast_queue_mode
    playing = _media_snapshot(cast, player_state="PLAYING", adjusted_current_time=15)
    await orchestrator.handle_status(
        selected_cast_renderer, backend.status_from_media_status(selected_cast_renderer, playing)
    )
    await _drain(orchestrator)

    state = await get_renderer_state_db(db, selected_cast_renderer)
    state["queue"] = state["queue"][:1]
    await update_renderer_state_db(db, selected_cast_renderer, state)
    cast.media_controller.message_response = (
        True,
        {"type": "INVALID_REQUEST", "reason": "INVALID_COMMAND"},
    )

    for _ in range(2):
        await orchestrator.handle_status(
            selected_cast_renderer, backend.status_from_media_status(selected_cast_renderer, playing)
        )
        await _drain(orchestrator)

    assert len(_queue_removes(cast)) == 1
    # Kept, so the receiver starting it later is still recognised as stale.
    assert backend.staged_track_id(selected_cast_renderer) == 902


@pytest.mark.asyncio
async def test_cast_queue_mode_off_keeps_per_track_loads(
    auth_client: AsyncClient,
    db,
    selected_cast_renderer,
    two_track_cast_queue,
    clean_cast_player_globals,
):
    backend, cast, _ = two_track_cast_queue
    orchestrator = clean_cast_player_globals
    playing = _media_snapshot(cast, player_state="PLAYING", adjusted_current_time=15)

    await orchestrator.handle_status(
        selected_cast_renderer, backend.status_from_media_status(selected_cast_renderer, playing)
    )
    await _drain(orchestrator)

    assert _queue_inserts(cast) == []


@pytest.mark.asyncio
async def test_cast_receiver_volume_and_mute_update_player_state(
    auth_client: AsyncClient,
    db,
    phase2_cast_track,
    selected_cast_renderer,
    fake_cast_backend,
    clean_cast_player_globals,
):
    from app.services.player.globals import renderer_muted

    backend, cast, _ = fake_cast_backend
    backend._loop = asyncio.get_running_loop()
    play = await auth_client.post("/api/player/play", json={"track_id": 901}, headers=HEADERS)
    assert play.status_code == 200, play.text
    await db.execute(
        "UPDATE renderer_state SET position_seconds = 10 WHERE renderer_udn = $1",
        selected_cast_renderer,
    )
    calls_before = list(cast.media_controller.calls)

    # Volume turned down and muted on the device's own remote.
    cast.receiver_status(0.2, True)
    for _ in range(100):
        row = await db.fetchrow(
            "SELECT volume, position_seconds FROM renderer_state WHERE renderer_udn = $1",
            selected_cast_renderer,
        )
        if row["volume"] == 20:
            break
        await asyncio.sleep(0.02)

    assert row["volume"] == 20
    assert row["position_seconds"] == 10  # progress untouched
    assert renderer_muted[selected_cast_renderer] is True
    assert cast.media_controller.calls == calls_before  # no polling
    renderer_muted.pop(selected_cast_renderer, None)


@pytest.mark.asyncio
async def test_cast_server_restart_readopts_receiver_media(
    auth_client: AsyncClient,
    db,
    selected_cast_renderer,
    two_track_cast_queue,
    clean_cast_player_globals,
    monkeypatch,
):
    """After a restart the server finds its own media on the receiver, one
    track further on than the stored queue: it follows it instead of treating
    it as foreign, without reloading, and listens for it again."""
    backend, cast, _ = two_track_cast_queue
    orchestrator = clean_cast_player_globals
    # The restart: no loads tracked, no listeners registered.
    backend._loads.clear()
    cast.media_controller.listeners.clear()
    cast.receiver_listeners.clear()
    monkeypatch.setattr(orchestrator, "_status_unsubscribers", {})
    url = "http://127.0.0.1:8111/api/stream/902?token=old"
    _media_snapshot(
        cast,
        player_state="PLAYING",
        adjusted_current_time=30,
        content_id=url,
        media_custom_data=backend.media_custom_data(902, url),
    )

    state = await auth_client.get("/api/player/state", headers=HEADERS)

    assert state.status_code == 200, state.text
    assert state.json()["current_index"] == 1
    assert state.json()["is_playing"] is True
    assert len(_play_media_calls(cast)) == 1
    assert backend._loads[selected_cast_renderer].adopted is True
    assert len(cast.media_controller.listeners) == 1
    assert len(cast.receiver_listeners) == 1


@pytest.mark.asyncio
async def test_cast_other_controllers_media_is_not_adopted(
    auth_client: AsyncClient,
    db,
    selected_cast_renderer,
    two_track_cast_queue,
    clean_cast_player_globals,
    monkeypatch,
):
    backend, cast, _ = two_track_cast_queue
    orchestrator = clean_cast_player_globals
    backend._loads.clear()
    monkeypatch.setattr(orchestrator, "_status_unsubscribers", {})
    _media_snapshot(
        cast,
        player_state="PLAYING",
        content_id="https://video.example/clip.mp4",
        media_custom_data={},
    )

    state = await auth_client.get("/api/player/state", headers=HEADERS)

    assert state.status_code == 200, state.text
    assert state.json()["current_index"] == 0
    assert selected_cast_renderer not in backend._loads


# --- Review fixes (#316): Previous race, planned staged items ---------------


@pytest.mark.asyncio
async def test_cast_previous_is_not_undone_by_the_old_media_still_playing(
    auth_client: AsyncClient,
    db,
    selected_cast_renderer,
    two_track_cast_queue,
    clean_cast_player_globals,
    monkeypatch,
):
    """Previous from 902 to 901: until the new LOAD lands, the receiver still
    plays 902, which is now queue[current + 1]. A status for it (a callback,
    or GET /api/player/state's sync) is no advance: current_index stays 0."""
    import app.services.renderer.orchestrator as orchestrator_module
    from app.services.player.state import get_renderer_state_db

    backend, cast, _ = two_track_cast_queue
    orchestrator = clean_cast_player_globals
    monkeypatch.setattr(orchestrator_module, "track_path_exists", lambda track: True)
    nxt = await auth_client.post("/api/player/index", json={"index": 1}, headers=HEADERS)
    assert nxt.status_code == 200, nxt.text
    old_media = _media_snapshot(cast, player_state="PLAYING", adjusted_current_time=40)
    assert "/api/stream/902" in old_media.content_id

    seen_during_load = []
    real_play_track = backend.play_track

    async def play_track_after_stale_status(renderer_id, track, context):
        # The old media reports in while the new track is being prepared.
        status = backend.status_from_media_status(renderer_id, old_media)
        assert status.current_track_id == 902 and not status.advanced_by_renderer
        await orchestrator.handle_status(selected_cast_renderer, status)
        seen_during_load.append(
            (await get_renderer_state_db(db, selected_cast_renderer))["current_index"]
        )
        return await real_play_track(renderer_id, track, context)

    monkeypatch.setattr(backend, "play_track", play_track_after_stale_status)
    prev = await auth_client.post("/api/player/index", json={"index": 0}, headers=HEADERS)
    assert prev.status_code == 200, prev.text

    assert seen_during_load == [0]
    state = await get_renderer_state_db(db, selected_cast_renderer)
    assert state["current_index"] == 0
    assert "/api/stream/901" in _play_media_calls(cast)[-1][1][0]

    # Settled, and no load in flight: 902 reported again (say, a late status)
    # is still not a receiver advance, so the queue does not jump.
    await orchestrator.handle_status(
        selected_cast_renderer, backend.status_from_media_status(selected_cast_renderer, old_media)
    )
    state = await get_renderer_state_db(db, selected_cast_renderer)
    assert state["current_index"] == 0


@pytest.mark.asyncio
async def test_cast_receiver_advance_during_a_load_is_not_followed(
    clean_cast_player_globals, monkeypatch
):
    """A receiver-queue advance reported while a load is in flight describes
    media that load replaces: not followed, and no 'stale' reload either."""
    from app.services.player.monitor import _clear_monitor_starting, _mark_monitor_starting
    from app.services.renderer.contracts import RendererStatus

    orchestrator = clean_cast_player_globals
    key = "cast:review-race"
    state = {"queue": [{"id": 1}, {"id": 2}, {"id": 3}], "current_index": 0}
    advanced = RendererStatus(
        renderer_id=key, state="PLAYING", current_track_id=3, advanced_by_renderer=True
    )
    _mark_monitor_starting(key)
    try:
        assert await orchestrator._follow_renderer_track(None, key, state, advanced) == "loading"
    finally:
        _clear_monitor_starting(key)
    # Without a load in flight the same report is a stale receiver item...
    assert await orchestrator._follow_renderer_track(None, key, state, advanced) == "stale"
    # ...and a plain PLAYING report naming the next track is not an advance.
    plain = RendererStatus(renderer_id=key, state="PLAYING", current_track_id=2)
    assert await orchestrator._follow_renderer_track(None, key, state, plain) is None


@pytest.mark.asyncio
async def test_cast_queue_mode_staged_item_is_planned_like_a_load(
    auth_client: AsyncClient,
    db,
    selected_cast_renderer,
    cast_queue_mode,
    monkeypatch,
):
    """The staged next track goes through the playback plan: an ALAC file is
    decoded to FLAC for the Default Media Receiver, QUEUE_INSERT says
    audio/flac like the token, and the plan is recorded for that track."""
    from app import config as app_config
    from app.services.player.globals import output_plan_for

    backend, cast, orchestrator = cast_queue_mode
    monkeypatch.setattr(app_config, "_config", {"renderer": {}})
    monkeypatch.setattr(
        "app.services.audio_streaming.probe_audio_file", lambda _path: {"codec": "alac"}
    )
    monkeypatch.setattr("app.services.audio_streaming.os.path.exists", lambda _p: True)
    await db.execute(
        """
        UPDATE track SET path = '/music/phase2-cast-2.m4a', codec = 'MP4',
               sample_rate_hz = 44100, bit_depth = 24, channels = 2
        WHERE id = 902
        """
    )
    playing = _media_snapshot(cast, player_state="PLAYING", adjusted_current_time=15)

    await orchestrator.handle_status(
        selected_cast_renderer, backend.status_from_media_status(selected_cast_renderer, playing)
    )
    await _drain(orchestrator)

    [insert] = _queue_inserts(cast)
    media = insert["items"][0]["media"]
    claims = _token_claims(media["contentId"])
    assert media["contentType"] == "audio/flac"
    assert claims["out"] == "flac" and claims["out_mime"] == "audio/flac"
    plan = output_plan_for(selected_cast_renderer, 902)
    assert plan is not None and plan["action"] == "decode"
    assert plan["mime_type"] == "audio/flac"
