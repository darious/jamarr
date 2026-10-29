import pytest

from app.services.renderer.contracts import (
    PlaybackContext,
    RendererCapabilities,
    RendererDevice,
    make_renderer_id,
    split_renderer_id,
)
from app.services.renderer.registry import RendererRegistry
from app.services.renderer.token_policy import stream_token_ttl_seconds
from app.services.renderer.upnp_backend import UpnpRendererBackend
from tests.helpers.fake_renderers import FakeUpnpManager


def test_phase1_renderer_id_helpers_treat_legacy_ids_as_upnp():
    assert make_renderer_id("upnp", "uuid:test") == "upnp:uuid:test"
    assert make_renderer_id("cast", "cast-id") == "cast:cast-id"
    assert split_renderer_id("uuid:test") == ("upnp", "uuid:test")
    assert split_renderer_id("cast:cast-id") == ("cast", "cast-id")


def test_phase1_renderer_device_api_shape_includes_backcompat_fields():
    device = RendererDevice(
        renderer_id="upnp:uuid:test",
        kind="upnp",
        native_id="uuid:test",
        udn="uuid:test",
        name="Living Room",
        icon_url="/art/renderer/uuid:test",
        icon_mime="image/png",
        icon_width=64,
        icon_height=64,
        capabilities=RendererCapabilities(supported_mime_types={"audio/flac"}),
    )

    data = device.as_api_dict()

    assert data["renderer_id"] == "upnp:uuid:test"
    assert data["kind"] == "upnp"
    assert data["native_id"] == "uuid:test"
    assert data["udn"] == "uuid:test"
    assert data["type"] == "upnp"
    assert data["icon_url"] == "/art/renderer/uuid:test"
    assert data["icon_mime"] == "image/png"
    assert data["icon_width"] == 64
    assert data["icon_height"] == 64
    assert data["capabilities"]["supported_mime_types"] == ["audio/flac"]


def test_phase1_registry_maps_legacy_state_keys():
    registry = RendererRegistry()

    assert registry.normalize_renderer_id("uuid:test") == "upnp:uuid:test"
    assert registry.normalize_renderer_id("upnp:uuid:test") == "upnp:uuid:test"
    assert registry.legacy_or_renderer_id_to_state_key("upnp:uuid:test") == "uuid:test"
    assert registry.state_key_to_renderer_id("uuid:test") == "upnp:uuid:test"
    assert registry.state_key_to_renderer_id("local:abc") == "local:abc"
    assert registry.state_key_to_renderer_id("cast:abc") == "cast:abc"


def test_phase1_cast_stream_token_ttl_policy(monkeypatch):
    monkeypatch.setenv("CAST_STREAM_TOKEN_TTL_SECONDS", "7200")

    assert stream_token_ttl_seconds("upnp", 3600) is None
    assert stream_token_ttl_seconds("cast", 100) == 1800
    assert stream_token_ttl_seconds("cast", 4000) == 7200
    assert stream_token_ttl_seconds("cast", None) == 7200


@pytest.mark.asyncio
async def test_phase1_upnp_backend_lists_normalized_devices():
    fake = FakeUpnpManager()
    fake.renderers = {
        "uuid:test": {
            "udn": "uuid:test",
            "friendly_name": "Kitchen",
            "ip": "192.0.2.10",
            "manufacturer": "Test",
            "model_name": "Model",
            "model_number": "One",
            "device_type": "urn:schemas-upnp-org:device:MediaRenderer:1",
            "icon_url": "/art/renderer/uuid:test",
            "icon_mime": "image/png",
            "icon_width": 64,
            "icon_height": 64,
            "supported_mime_types": "audio/flac,audio/mpeg",
        }
    }
    backend = UpnpRendererBackend(fake)

    devices = await backend.list_devices()

    assert len(devices) == 1
    device = devices[0]
    assert device.renderer_id == "upnp:uuid:test"
    assert device.native_id == "uuid:test"
    assert device.name == "Kitchen"
    assert device.icon_url == "/art/renderer/uuid:test"
    assert device.icon_mime == "image/png"
    assert device.icon_width == 64
    assert device.icon_height == 64
    assert device.model_number == "One"
    assert device.device_type == "urn:schemas-upnp-org:device:MediaRenderer:1"
    assert device.capabilities.supported_mime_types == {"audio/flac", "audio/mpeg"}


def test_phase1_upnp_transport_mapping():
    assert UpnpRendererBackend.normalize_transport_state("PLAYING") == "PLAYING"
    assert UpnpRendererBackend.normalize_transport_state("TRANSITIONING") == "PLAYING"
    assert UpnpRendererBackend.normalize_transport_state("PAUSED_PLAYBACK") == "PAUSED"
    assert UpnpRendererBackend.normalize_transport_state("STOPPED") == "IDLE"
    assert UpnpRendererBackend.normalize_transport_state("VENDOR_DEFINED") == "UNKNOWN"


@pytest.mark.asyncio
async def test_phase1_upnp_backend_prefers_context_stream_url_and_mime_type():
    fake = FakeUpnpManager()
    backend = UpnpRendererBackend(fake)

    await backend.play_track(
        "upnp:uuid:test",
        {
            "id": 904,
            "path": "/music/song.mp3",
            "title": "Song",
            "mime": "audio/mpeg",
        },
        PlaybackContext(
            base_url="http://127.0.0.1:8111",
            user_id=42,
            stream_url="http://127.0.0.1:8111/api/stream/904?token=normalized",
            stream_mime_type="audio/flac",
        ),
    )

    assert [cmd.name for cmd in fake.commands] == ["set_renderer", "play_track"]
    metadata = fake.commands[1].args[2]
    assert metadata["stream_url"] == "http://127.0.0.1:8111/api/stream/904?token=normalized"
    assert metadata["mime"] == "audio/flac"


@pytest.mark.asyncio
async def test_upnp_mute_uses_set_mute_only_where_the_device_has_it():
    fake = FakeUpnpManager()
    fake.renderers = {
        "uuid:mutes": {"udn": "uuid:mutes", "friendly_name": "Has SetMute"},
        "uuid:plain": {"udn": "uuid:plain", "friendly_name": "No SetMute"},
    }
    fake.mutable = {"uuid:mutes"}
    backend = UpnpRendererBackend(fake)

    caps = {d.native_id: d.capabilities.can_mute for d in await backend.list_devices()}
    assert caps == {"uuid:mutes": True, "uuid:plain": False}

    status = await backend.mute("upnp:uuid:mutes", True)
    assert status.volume_muted is True
    assert [(c.name, c.args) for c in fake.commands if c.name != "get_renderers"] == [
        ("set_renderer", ("uuid:mutes",)),
        ("set_mute", (True,)),
    ]

    with pytest.raises(NotImplementedError):
        await backend.mute("upnp:uuid:plain", True)
    assert sum(c.name == "set_mute" for c in fake.commands) == 1


class _FakeDmr:
    def __init__(self, actions: set[str]) -> None:
        self.actions = actions
        self.muted: list[bool] = []

    def _action(self, service: str, action: str):
        return object() if service == "RC" and action in self.actions else None

    async def async_mute_volume(self, mute: bool) -> None:
        self.muted.append(mute)


class _FakeControlManager:
    def __init__(self, dmrs) -> None:
        self.dmr_devices = dmrs
        self.active_renderer = None

    def log(self, message: str) -> None:
        pass


@pytest.mark.asyncio
async def test_upnp_control_checks_the_set_mute_action_and_calls_it():
    from app.services.upnp.device import UPnPDeviceControl

    dmr = _FakeDmr({"SetMute", "SetVolume"})
    manager = _FakeControlManager({"uuid:a": dmr, "uuid:b": _FakeDmr({"SetVolume"})})
    control = UPnPDeviceControl(manager)

    assert control.can_mute("uuid:a") is True
    assert control.can_mute("uuid:b") is False
    assert control.can_mute("uuid:missing") is False

    with pytest.raises(ValueError):
        await control.set_mute(True)
    manager.active_renderer = "uuid:a"
    await control.set_mute(True)
    await control.set_mute(False)
    assert dmr.muted == [True, False]


class _VolumeAction:
    async def async_call(self, **kwargs):
        assert kwargs == {"InstanceID": 0, "Channel": "Master"}
        return {"CurrentVolume": 30}


class _VolumeDmr:
    def _action(self, service: str, action: str):
        # async_upnp_client resolves services by abbreviation only.
        return _VolumeAction() if (service, action) == ("RC", "GetVolume") else None

    def _state_variable(self, service: str, name: str):
        if (service, name) == ("RC", "Volume"):
            return type("Var", (), {"max_value": 60})()
        return None


@pytest.mark.asyncio
async def test_get_volume_reads_rendering_control_and_scales_to_its_range():
    from app.services.upnp.device import UPnPDeviceControl

    control = UPnPDeviceControl(_FakeControlManager({"uuid:a": _VolumeDmr()}))

    assert await control.get_volume("uuid:a") == 50
