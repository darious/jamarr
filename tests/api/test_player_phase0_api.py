import pytest
from httpx import AsyncClient

from tests.helpers.fake_renderers import FakeUpnpManager


@pytest.fixture
async def phase0_tracks(db):
    await db.execute(
        """
        INSERT INTO track (id, path, title, artist, album, duration_seconds)
        VALUES
            (501, '/music/phase0-a.flac', 'Phase A', 'Artist', 'Album', 120),
            (502, '/music/phase0-b.mp3', 'Phase B', 'Artist', 'Album', 180)
        """
    )


@pytest.fixture
async def selected_remote_renderer(db):
    udn = "uuid:phase0-upnp"
    await db.execute(
        """
        INSERT INTO client_session (client_id, active_renderer_udn, last_seen_at)
        VALUES ('phase0-client', $1, NOW())
        """,
        udn,
    )
    return udn


@pytest.mark.asyncio
async def test_phase0_remote_transport_controls_call_upnp_manager(
    auth_client: AsyncClient,
    db,
    monkeypatch,
    selected_remote_renderer,
):
    fake_upnp = FakeUpnpManager()
    import app.api.player as player_api
    import app.services.renderer.orchestrator as orchestrator_module
    from app.services.renderer.upnp_backend import UpnpRendererBackend

    monkeypatch.setitem(
        player_api.renderer_orchestrator.registry.backends,
        "upnp",
        UpnpRendererBackend(fake_upnp),
    )
    monkeypatch.setattr(orchestrator_module, "start_monitor_task", lambda udn: None)
    headers = {"X-Jamarr-Client-Id": "phase0-client"}

    pause = await auth_client.post("/api/player/pause", headers=headers)
    resume = await auth_client.post("/api/player/resume", headers=headers)
    seek = await auth_client.post("/api/player/seek", json={"seconds": 42.5}, headers=headers)
    volume = await auth_client.post("/api/player/volume", json={"percent": 77}, headers=headers)

    assert pause.status_code == 200, pause.text
    assert resume.status_code == 200, resume.text
    assert seek.status_code == 200, seek.text
    assert volume.status_code == 200, volume.text

    assert [cmd.name for cmd in fake_upnp.commands] == [
        "set_renderer",
        "pause",
        "set_renderer",
        "resume",
        "set_renderer",
        "seek",
        "set_renderer",
        "set_volume",
    ]
    assert fake_upnp.commands[0].args == (selected_remote_renderer,)
    assert fake_upnp.commands[5].args == (42.5,)
    assert fake_upnp.commands[7].args == (77,)

    state = await auth_client.get("/api/player/state", headers=headers)
    assert state.status_code == 200
    assert state.json()["volume"] == 77


@pytest.mark.asyncio
async def test_phase0_remote_play_route_sets_base_url_and_starts_monitor(
    auth_client: AsyncClient,
    db,
    monkeypatch,
    phase0_tracks,
    selected_remote_renderer,
):
    fake_upnp = FakeUpnpManager()
    import app.api.player as player_api
    import app.services.renderer.orchestrator as orchestrator_module
    from app.services.renderer.upnp_backend import UpnpRendererBackend

    monkeypatch.setitem(
        player_api.renderer_orchestrator.registry.backends,
        "upnp",
        UpnpRendererBackend(fake_upnp),
    )
    monkeypatch.setattr(orchestrator_module, "start_monitor_task", lambda udn: None)
    headers = {"X-Jamarr-Client-Id": "phase0-client"}

    response = await auth_client.post(
        "/api/player/play",
        json={"track_id": 501},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"status": "streaming_started", "renderer": selected_remote_renderer}
    assert [cmd.name for cmd in fake_upnp.commands] == ["set_renderer", "play_track"]
    assert fake_upnp.commands[0].args == (selected_remote_renderer,)
    assert fake_upnp.commands[1].args[0] == 501
    assert fake_upnp.commands[1].args[1] == "/music/phase0-a.flac"
    assert fake_upnp.base_url == "http://127.0.0.1:8111"

    state = await auth_client.get("/api/player/state", headers=headers)
    data = state.json()
    assert data["renderer"] == selected_remote_renderer
    assert data["queue"][0]["id"] == 501
    assert data["is_playing"] is True
    assert data["transport_state"] == "PLAYING"
