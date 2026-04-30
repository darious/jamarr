import pytest

from app.services.renderer.contracts import (
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
        capabilities=RendererCapabilities(supported_mime_types={"audio/flac"}),
    )

    data = device.as_api_dict()

    assert data["renderer_id"] == "upnp:uuid:test"
    assert data["kind"] == "upnp"
    assert data["native_id"] == "uuid:test"
    assert data["udn"] == "uuid:test"
    assert data["type"] == "upnp"
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
    assert device.capabilities.supported_mime_types == {"audio/flac", "audio/mpeg"}


def test_phase1_upnp_transport_mapping():
    assert UpnpRendererBackend.normalize_transport_state("PLAYING") == "PLAYING"
    assert UpnpRendererBackend.normalize_transport_state("TRANSITIONING") == "PLAYING"
    assert UpnpRendererBackend.normalize_transport_state("PAUSED_PLAYBACK") == "PAUSED"
    assert UpnpRendererBackend.normalize_transport_state("STOPPED") == "IDLE"
    assert UpnpRendererBackend.normalize_transport_state("VENDOR_DEFINED") == "UNKNOWN"
