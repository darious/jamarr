import asyncio

import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient

from app.services.renderer.cast_backend import CastRendererBackend
from tests.unit.test_renderer_phase2_cast import FakeBrowser, FakeCast


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
    backend = CastRendererBackend(chromecast_getter=lambda **_: ([cast], FakeBrowser()))
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
