"""DIDL-Lite metadata construction for UPnP renderers."""

from types import SimpleNamespace

from app.services.upnp.device import UPnPDeviceControl, format_didl_duration


def test_format_didl_duration():
    assert format_didl_duration(181) == "0:03:01.000"
    assert format_didl_duration(180.72) == "0:03:00.720"
    assert format_didl_duration(3661.5) == "1:01:01.500"
    assert format_didl_duration(0) is None
    assert format_didl_duration(None) is None
    assert format_didl_duration(-3) is None


class FakeDmr:
    def __init__(self):
        self.set_uri_calls = []
        self.played = False

    async def async_set_transport_uri(self, media_url, media_title, meta_data):
        self.set_uri_calls.append(
            {"media_url": media_url, "media_title": media_title, "meta_data": meta_data}
        )

    async def async_wait_for_can_play(self, max_wait_time=5):
        pass

    async def async_play(self):
        self.played = True


async def test_play_track_didl_has_duration_and_proxy_urls(monkeypatch):
    udn = "uuid:didl-test"
    dmr = FakeDmr()
    manager = SimpleNamespace(
        active_renderer=udn,
        dmr_devices={udn: dmr},
        renderers={udn: {"friendly_name": "TV", "location": "http://10.0.0.2:1234"}},
        base_url="http://10.0.0.1:8111",
        renderer_base_url="http://10.0.0.1:8112",
    )
    control = UPnPDeviceControl(manager)
    monkeypatch.setattr(
        "app.services.upnp.device.create_stream_token", lambda *a, **kw: "tok"
    )

    await control.play_track(
        42,
        "/music/track.flac",
        {
            "title": "Song",
            "artist": "Artist",
            "album": "Album",
            "mime": "audio/flac",
            "duration_seconds": 181,
            "art_sha1": "cafebabe",
        },
    )

    assert dmr.played
    call = dmr.set_uri_calls[0]
    assert call["media_url"] == "http://10.0.0.1:8112/api/stream/42?token=tok"
    didl = call["meta_data"]
    assert 'duration="0:03:01.000"' in didl
    assert "http://10.0.0.1:8112/art/file/cafebabe" in didl
    assert "http://10.0.0.1:8111" not in didl


async def test_play_track_didl_omits_duration_when_unknown(monkeypatch):
    udn = "uuid:didl-test-2"
    dmr = FakeDmr()
    manager = SimpleNamespace(
        active_renderer=udn,
        dmr_devices={udn: dmr},
        renderers={udn: {"friendly_name": "TV", "location": "http://10.0.0.2:1234"}},
        base_url="http://10.0.0.1:8111",
        renderer_base_url="http://10.0.0.1:8112",
    )
    control = UPnPDeviceControl(manager)
    monkeypatch.setattr(
        "app.services.upnp.device.create_stream_token", lambda *a, **kw: "tok"
    )

    await control.play_track(
        43,
        "/music/track2.flac",
        {"title": "Song2", "artist": "Artist", "album": "Album", "mime": "audio/flac"},
    )

    didl = dmr.set_uri_calls[0]["meta_data"]
    assert "duration=" not in didl
    assert "size=" not in didl
