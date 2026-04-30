import pytest

from tests.helpers.fake_renderers import FakeUpnpManager, status_ended, status_paused, status_playing


@pytest.mark.asyncio
async def test_phase0_play_next_track_internal_advances_queue(db, monkeypatch):
    from app.services.player import queue as queue_module
    from app.services.player.globals import last_track_start_time
    from app.services.player.state import update_renderer_state_db, get_renderer_state_db

    fake_upnp = FakeUpnpManager()
    monkeypatch.setattr(queue_module.UPnPManager, "get_instance", lambda: fake_upnp)

    udn = "uuid:phase0-upnp"
    state = {
        "queue": [
            {
                "id": 601,
                "title": "First",
                "artist": "Artist",
                "album": "Album",
                "path": "/music/first.flac",
                "duration_seconds": 100,
            },
            {
                "id": 602,
                "title": "Second",
                "artist": "Artist",
                "album": "Album",
                "path": "/music/second.mp3",
                "duration_seconds": 100,
            },
        ],
        "current_index": 0,
        "position_seconds": 72,
        "is_playing": True,
        "transport_state": "PLAYING",
        "volume": 30,
    }
    await update_renderer_state_db(db, udn, state)

    await queue_module.play_next_track_internal(udn)

    assert [cmd.name for cmd in fake_upnp.commands] == ["set_renderer", "play_track"]
    assert fake_upnp.commands[0].args == (udn,)
    assert fake_upnp.commands[1].args[0] == 602
    assert fake_upnp.commands[1].args[1] == "/music/second.mp3"
    assert fake_upnp.commands[1].args[2]["mime"] == "audio/mpeg"
    assert fake_upnp.base_url == "http://127.0.0.1:8111"
    assert udn in last_track_start_time

    updated = await get_renderer_state_db(db, udn)
    assert updated["current_index"] == 1
    assert updated["position_seconds"] == 0
    assert updated["is_playing"] is True


@pytest.mark.asyncio
async def test_phase0_play_next_track_internal_marks_end_of_queue(db, monkeypatch):
    from app.services.player import queue as queue_module
    from app.services.player.state import update_renderer_state_db, get_renderer_state_db

    fake_upnp = FakeUpnpManager()
    monkeypatch.setattr(queue_module.UPnPManager, "get_instance", lambda: fake_upnp)

    udn = "uuid:phase0-upnp"
    await update_renderer_state_db(
        db,
        udn,
        {
            "queue": [
                {
                    "id": 701,
                    "title": "Only",
                    "artist": "Artist",
                    "album": "Album",
                    "path": "/music/only.flac",
                    "duration_seconds": 100,
                }
            ],
            "current_index": 0,
            "position_seconds": 98,
            "is_playing": True,
            "transport_state": "PLAYING",
            "volume": None,
        },
    )

    await queue_module.play_next_track_internal(udn)

    assert fake_upnp.commands == []
    updated = await get_renderer_state_db(db, udn)
    assert updated["current_index"] == 0
    assert updated["position_seconds"] == 0
    assert updated["is_playing"] is False


def test_phase0_fake_status_helpers_cover_expected_states():
    assert status_playing("upnp:one", 12).state == "PLAYING"
    assert status_playing("upnp:one", 12).position_seconds == 12
    assert status_paused("upnp:one", 8).state == "PAUSED"
    ended = status_ended("upnp:one")
    assert ended.state == "IDLE"
    assert ended.ended is True
