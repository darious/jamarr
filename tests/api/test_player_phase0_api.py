import pytest
from httpx import AsyncClient
import jwt
from urllib.parse import parse_qs, urlparse

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
async def test_mute_route_mutes_upnp_and_state_reports_it(
    auth_client: AsyncClient,
    db,
    monkeypatch,
    selected_remote_renderer,
):
    fake_upnp = FakeUpnpManager()
    fake_upnp.mutable = {selected_remote_renderer}
    import app.api.player as player_api
    from app.services.player.globals import renderer_muted
    from app.services.renderer.upnp_backend import UpnpRendererBackend

    monkeypatch.setitem(
        player_api.renderer_orchestrator.registry.backends,
        "upnp",
        UpnpRendererBackend(fake_upnp),
    )
    monkeypatch.setitem(renderer_muted, selected_remote_renderer, None)
    headers = {"X-Jamarr-Client-Id": "phase0-client"}

    bad = await auth_client.post("/api/player/mute", json={"muted": "yes"}, headers=headers)
    assert bad.status_code == 400

    muted = await auth_client.post("/api/player/mute", json={"muted": True}, headers=headers)
    assert muted.status_code == 200, muted.text
    assert muted.json() == {"status": "ok", "muted": True}
    assert ("set_mute", (True,)) in [(c.name, c.args) for c in fake_upnp.commands]

    state = await auth_client.get("/api/player/state", headers=headers)
    assert state.json()["muted"] is True

    unmuted = await auth_client.post("/api/player/mute", json={"muted": False}, headers=headers)
    assert unmuted.status_code == 200, unmuted.text
    state = await auth_client.get("/api/player/state", headers=headers)
    assert state.json()["muted"] is False


class _FakeMuteEvents:
    """The slice of UpnpEventManager _upnp_muted reads: (muted, evented at),
    or None once RenderingControl events are dropped or unhealthy."""

    def __init__(self):
        self.state = None

    def muted_state(self, udn):
        return self.state


@pytest.mark.asyncio
async def test_state_mute_is_the_latest_of_evented_and_jamarr_set(
    auth_client: AsyncClient,
    db,
    monkeypatch,
    selected_remote_renderer,
):
    """An older evented unmute must not hide the mute Jamarr just set, a newer
    event wins over it, and a dropped subscription's mute is no longer shown."""
    import time

    import app.api.player as player_api
    from app.services.player.globals import renderer_muted, renderer_muted_at
    from app.services.renderer.upnp_backend import UpnpRendererBackend

    fake_upnp = FakeUpnpManager()
    fake_upnp.mutable = {selected_remote_renderer}
    fake_upnp.events = _FakeMuteEvents()
    monkeypatch.setitem(
        player_api.renderer_orchestrator.registry.backends,
        "upnp",
        UpnpRendererBackend(fake_upnp),
    )
    monkeypatch.setitem(renderer_muted, selected_remote_renderer, None)
    monkeypatch.setitem(renderer_muted_at, selected_remote_renderer, 0.0)
    headers = {"X-Jamarr-Client-Id": "phase0-client"}

    async def shown():
        state = await auth_client.get("/api/player/state", headers=headers)
        assert state.status_code == 200, state.text
        return state.json()["muted"]

    fake_upnp.events.state = (False, time.time() - 60)  # evented a minute ago
    assert await shown() is False
    muted = await auth_client.post("/api/player/mute", json={"muted": True}, headers=headers)
    assert muted.status_code == 200, muted.text
    assert await shown() is True  # Jamarr's mute is newer than the event

    fake_upnp.events.state = (False, time.time() + 1)  # unmuted on the device since
    assert await shown() is False

    fake_upnp.events.state = None  # subscription dropped: back to what Jamarr set
    assert await shown() is True


@pytest.mark.asyncio
async def test_mute_route_refuses_renderers_without_set_mute(
    auth_client: AsyncClient,
    db,
    monkeypatch,
    selected_remote_renderer,
):
    fake_upnp = FakeUpnpManager()
    import app.api.player as player_api
    from app.services.renderer.upnp_backend import UpnpRendererBackend

    monkeypatch.setitem(
        player_api.renderer_orchestrator.registry.backends,
        "upnp",
        UpnpRendererBackend(fake_upnp),
    )
    headers = {"X-Jamarr-Client-Id": "phase0-client"}

    response = await auth_client.post("/api/player/mute", json={"muted": True}, headers=headers)
    assert response.status_code == 400
    assert "SetMute" in response.json()["detail"]
    assert not any(c.name == "set_mute" for c in fake_upnp.commands)


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


@pytest.mark.asyncio
async def test_phase0_remote_play_uses_generic_normalized_stream_url(
    auth_client: AsyncClient,
    db,
    monkeypatch,
    phase0_tracks,
    selected_remote_renderer,
):
    await db.execute(
        """
        INSERT INTO track_audio_analysis (
            track_id, status, loudness_lufs, true_peak_db
        )
        VALUES (501, 'complete', -20.0, -8.0)
        """
    )
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
    metadata = fake_upnp.commands[1].args[2]
    assert metadata["mime"] == "audio/flac"
    assert metadata["stream_url"].startswith("http://127.0.0.1:8111/api/stream/501?token=")
    token = parse_qs(urlparse(metadata["stream_url"]).query)["token"][0]
    claims = jwt.decode(token, options={"verify_signature": False})
    assert claims["loudness_normalized"] is True
    assert claims["loudness_gain_mode"] == "track"
    assert claims["loudness_gain_db"] == pytest.approx(4.0)
