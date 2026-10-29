"""Optional renderer capabilities: defaults, serialisation, truthful backends."""

from types import SimpleNamespace

from app.services.renderer.contracts import (
    OutputConstraints,
    PairingRequirement,
    QueueOperation,
    QueueOwnership,
    RendererCapabilities,
    RendererDevice,
    SupportsNextTrackStaging,
    SupportsPairing,
    backend_supports,
)
from app.services.renderer.registry import RendererRegistry
from app.services.renderer.upnp_backend import UpnpRendererBackend
from tests.helpers.fake_renderers import FakeUpnpManager


def test_defaults_describe_a_plain_server_queue_renderer():
    caps = RendererCapabilities().as_dict()

    assert caps["queue_ownership"] == "server"
    assert caps["queue_operations"] == []
    assert caps["can_stage_next"] is False
    assert caps["pairing"] == "none"
    assert caps["has_credentials"] is None
    assert caps["output"] == {
        "codecs": [],
        "max_sample_rate_hz": None,
        "max_bit_depth": None,
        "max_channels": None,
        "source": None,
    }
    # Pre-existing keys keep their meaning and defaults.
    assert caps["can_play"] is True and caps["can_enqueue"] is False


def test_renderer_owned_queue_serialises_sorted_plain_strings():
    caps = RendererCapabilities(
        queue_ownership=QueueOwnership.RENDERER,
        queue_operations={QueueOperation.INSERT, QueueOperation.DELETE, QueueOperation.READ},
        pairing=PairingRequirement.REQUIRED,
        has_credentials=True,
        output=OutputConstraints(codecs={"flac", "alac"}, max_sample_rate_hz=192000, source="advertised"),
    ).as_dict()

    assert caps["queue_ownership"] == "renderer"
    assert type(caps["queue_ownership"]) is str
    assert caps["queue_operations"] == ["delete", "insert", "read"]
    assert caps["pairing"] == "required"
    assert caps["output"]["codecs"] == ["alac", "flac"]
    assert caps["output"]["max_sample_rate_hz"] == 192000


def test_device_api_dict_carries_new_capabilities():
    device = RendererDevice(
        renderer_id="upnp:uuid:x",
        kind="upnp",
        native_id="uuid:x",
        name="X",
        capabilities=RendererCapabilities(can_stage_next=True),
    )
    assert device.as_api_dict()["capabilities"]["can_stage_next"] is True


def test_local_renderer_uses_the_shared_capability_shape():
    caps = RendererRegistry().local_renderer("c1")["capabilities"]
    assert caps == RendererCapabilities().as_dict()


class StagingManager(FakeUpnpManager):
    def __init__(self, allowed: bool, events: bool | None = None) -> None:
        super().__init__()
        self.allowed = allowed
        self.cleared: list[str] = []
        if events is not None:
            self.events = SimpleNamespace(supports_events=lambda udn: events)

    def next_track_staging_allowed(self, udn: str) -> bool:
        return self.allowed

    async def clear_next_track(self, udn: str) -> None:
        self.cleared.append(udn)


def _upnp_devices(manager, persisted_events: bool = False):
    manager.renderers = {
        "uuid:a": {
            "udn": "uuid:a",
            "friendly_name": "A",
            # The verdict a subscription persisted in an earlier run.
            "supports_events": persisted_events,
            "supported_mime_types": "audio/flac",
        }
    }
    return UpnpRendererBackend(manager)


async def test_upnp_reports_staging_only_when_allowed():
    allowed = await _upnp_devices(StagingManager(True)).list_devices()
    refused = await _upnp_devices(StagingManager(False)).list_devices()

    assert allowed[0].capabilities.can_stage_next is True
    assert refused[0].capabilities.can_stage_next is False


async def test_upnp_events_follow_subscription_health_not_discovery():
    no_verdict = await _upnp_devices(StagingManager(True)).list_devices()
    proven_now = await _upnp_devices(StagingManager(True, events=True)).list_devices()
    proven_before = await _upnp_devices(
        StagingManager(True, events=False), persisted_events=True
    ).list_devices()

    assert no_verdict[0].capabilities.supports_events is False
    assert proven_now[0].capabilities.supports_events is True
    assert proven_before[0].capabilities.supports_events is True


async def test_upnp_backend_implements_next_track_staging():
    manager = StagingManager(True)
    backend = _upnp_devices(manager)

    assert isinstance(backend, SupportsNextTrackStaging)
    assert not isinstance(backend, SupportsPairing)
    assert "next_track_staging" in backend_supports(backend)
    assert backend.next_track_staging_allowed("upnp:uuid:a") is True
    await backend.clear_next_track("upnp:uuid:a")
    assert manager.cleared == ["uuid:a"]


def test_cast_reports_documented_output_and_server_queue():
    from tests.unit.test_renderer_phase2_cast import FakeCast, make_backend

    backend, _ = make_backend(FakeCast())
    device = backend._device_from_info("u1", None, FakeCast())
    caps = device.capabilities
    assert caps.queue_ownership == QueueOwnership.SERVER
    assert caps.can_stage_next is False
    assert caps.output.source == "documented"
    assert caps.output.max_sample_rate_hz == 96000
