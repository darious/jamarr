"""GetProtocolInfo retention, format negotiation, load retries and error mapping.

Devices are in-memory fakes; nothing here touches the network.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from async_upnp_client.exceptions import (
    UpnpActionError,
    UpnpActionResponseError,
    UpnpConnectionError,
    UpnpResponseError,
)

from app.services.renderer.contracts import (
    PlaybackContext,
    RendererCapabilities,
    RendererDevice,
    RendererLoadError,
)
from app.services.renderer.persistence import (
    register_or_update_renderer,
    renderer_row_to_api,
)
from app.services.renderer.upnp_backend import UpnpRendererBackend
from app.services.upnp.device import (
    LOAD_STAGES,
    UPnPDeviceControl,
    build_didl_lite,
    load_strategies,
    negotiate_mime,
    with_mime_param,
)
from app.services.upnp.protocol_info import (
    canonical_mime,
    is_alias,
    mimes_from_protocol_info,
    negotiate_format,
    parse_protocol_info,
    parse_protocol_info_list,
    served_content_type,
    split_protocol_info_list,
)
from app.services.upnp.staging import same_media_uri, staging
from app.services.upnp.transport_errors import (
    describe_transport_error,
    is_metadata_fault,
)
from app.upnp import UPnPManager

STREAM_URL = "http://10.0.0.1:8112/api/stream/7?token=tok"
MP3_PN = (
    "http-get:*:audio/mpeg:DLNA.ORG_PN=MP3;DLNA.ORG_OP=01;"
    "DLNA.ORG_FLAGS=01700000000000000000000000000000"
)


def fault(code, desc="Fault"):
    return UpnpActionResponseError(status=500, error_code=code, error_desc=desc)


# --- parsing ------------------------------------------------------------------


def test_parse_keeps_all_four_fields_params_and_dlna_info():
    entry = parse_protocol_info(MP3_PN)
    assert (entry.protocol, entry.network, entry.mime) == ("http-get", "*", "audio/mpeg")
    assert entry.dlna == {
        "PN": "MP3",
        "OP": "01",
        "FLAGS": "01700000000000000000000000000000",
    }
    assert entry.raw == MP3_PN

    l16 = parse_protocol_info("http-get:*:audio/L16;rate=44100;channels=2:DLNA.ORG_PN=LPCM")
    assert l16.mime == "audio/l16"
    assert l16.mime_params == {"rate": "44100", "channels": "2"}
    assert l16.dlna == {"PN": "LPCM"}

    assert parse_protocol_info("http-get:*:audio/flac") is None  # three fields
    assert parse_protocol_info("") is None


def test_split_honours_escaped_commas_and_skips_garbage():
    sink = (
        "http-get:*:audio/flac:*, http-get:*:audio/x-thing:FOO=a\\,b ,,"
        "nonsense,http-get:*:audio/mpeg:*"
    )
    raw = split_protocol_info_list(sink)
    assert raw == [
        "http-get:*:audio/flac:*",
        "http-get:*:audio/x-thing:FOO=a\\,b",
        "nonsense",
        "http-get:*:audio/mpeg:*",
    ]
    entries = parse_protocol_info_list(sink)
    assert [e.mime for e in entries] == ["audio/flac", "audio/x-thing", "audio/mpeg"]
    assert entries[1].raw == "http-get:*:audio/x-thing:FOO=a\\,b"  # kept verbatim


def test_mime_view_is_derived_without_wildcards():
    entries = parse_protocol_info_list(["http-get:*:audio/x-flac:*", "http-get:*:*:*", MP3_PN])
    assert mimes_from_protocol_info(entries) == {"audio/x-flac", "audio/mpeg"}


async def test_get_sink_protocol_info_returns_complete_entries():
    sink = "http-get:*:audio/x-flac:*," + MP3_PN + ",http-get:*:audio/x-flac:*"

    class Action:
        async def async_call(self):
            return {"Sink": sink, "Source": ""}

    cm = SimpleNamespace(
        service_type="urn:schemas-upnp-org:service:ConnectionManager:1",
        action=lambda name: Action(),
    )
    dmr = SimpleNamespace(device=SimpleNamespace(services={"cm": cm}))
    control = UPnPDeviceControl(SimpleNamespace(dmr_devices={"uuid:x": dmr}))

    assert await control.get_sink_protocol_info("uuid:x") == [
        "http-get:*:audio/x-flac:*",
        MP3_PN,
    ]
    assert await control.get_supported_protocols("uuid:x") == {"audio/x-flac", "audio/mpeg"}


# --- negotiation --------------------------------------------------------------


def _entries(*raw):
    return parse_protocol_info_list(list(raw))


@pytest.mark.parametrize(
    "stream, advertised, expected",
    [
        ("audio/flac", ["http-get:*:audio/x-flac:*"], "audio/x-flac"),
        ("audio/flac", ["http-get:*:audio/flac:*", "http-get:*:audio/x-flac:*"], "audio/flac"),
        ("audio/x-flac", ["http-get:*:audio/flac:*"], "audio/flac"),
        ("audio/mp4", ["http-get:*:audio/x-m4a:*"], "audio/x-m4a"),
        ("audio/mp4", ["http-get:*:audio/m4a:*"], "audio/m4a"),
        ("audio/x-wav", ["http-get:*:audio/wav:*"], "audio/wav"),
        ("audio/wav", ["http-get:*:audio/wave:*"], "audio/wave"),
        ("audio/mpeg", ["http-get:*:audio/mp3:*"], "audio/mp3"),
        ("audio/mpeg", [MP3_PN], "audio/mpeg"),
    ],
)
def test_alias_negotiation(stream, advertised, expected):
    negotiated = negotiate_format(stream, _entries(*advertised))
    assert negotiated.mime == expected
    assert negotiated.advertised_support is True
    assert negotiated.protocol_info == f"http-get:*:{expected}:*"  # wildcard default


def test_a_label_never_converts_audio():
    # ADTS AAC is not the MP4 container; L16 is headerless big-endian PCM, not WAV.
    mp4 = negotiate_format("audio/mp4", _entries("http-get:*:audio/aac:*"))
    assert (mp4.mime, mp4.advertised_support) == ("audio/mp4", False)
    wav = negotiate_format(
        "audio/x-wav", _entries("http-get:*:audio/L16;rate=44100;channels=2:*")
    )
    assert (wav.mime, wav.advertised_support) == ("audio/x-wav", False)
    assert not is_alias("audio/mp4", "audio/aac")
    assert not is_alias("audio/wav", "audio/L16;rate=44100")
    assert canonical_mime("AUDIO/X-FLAC") == "audio/flac"


def test_wildcard_and_unknown_lists_keep_the_stream_mime():
    wildcard = negotiate_format("audio/flac", _entries("http-get:*:*:*"))
    assert (wildcard.mime, wildcard.advertised_support, wildcard.advertised) == (
        "audio/flac",
        True,
        None,
    )
    unknown = negotiate_format("audio/flac")
    assert (unknown.mime, unknown.advertised_support) == ("audio/flac", None)
    # Old rows only have the MIME-only list.
    legacy = negotiate_format("audio/flac", (), {"audio/x-flac"})
    assert (legacy.mime, legacy.advertised) == ("audio/x-flac", None)
    assert negotiate_mime("audio/mp4", {"audio/x-m4a"}) == "audio/x-m4a"
    assert negotiate_mime("audio/flac", set()) == "audio/flac"


def test_exact_entry_prefers_plain_entries_and_differs_from_default():
    negotiated = negotiate_format(
        "audio/mpeg", _entries(MP3_PN, "http-get:*:audio/mpeg:DLNA.ORG_OP=01")
    )
    assert negotiated.exact_protocol_info == "http-get:*:audio/mpeg:DLNA.ORG_OP=01"
    plain = negotiate_format("audio/flac", _entries("http-get:*:audio/flac:*"))
    assert plain.exact_protocol_info is None  # same as the default: no extra stage
    star = negotiate_format("audio/flac", _entries("*:*:audio/flac:DLNA.ORG_OP=01"))
    assert star.exact_protocol_info == "http-get:*:audio/flac:DLNA.ORG_OP=01"
    non_http = negotiate_format("audio/flac", _entries("rtsp-rtp-udp:*:audio/flac:*"))
    assert non_http.advertised_support is None


def test_served_content_type_only_relabels_within_a_family():
    assert served_content_type("audio/flac", "audio/x-flac") == "audio/x-flac"
    assert served_content_type("audio/x-wav", "audio/wav") == "audio/wav"
    assert served_content_type("audio/mpeg", "audio/flac") == "audio/mpeg"
    assert served_content_type("audio/mp4", "audio/aac") == "audio/mp4"
    assert served_content_type("audio/flac", None) == "audio/flac"


def test_with_mime_param_replaces_and_keeps_the_token():
    url = with_mime_param(STREAM_URL, "audio/x-flac")
    assert url == STREAM_URL + "&mime=audio%2Fx-flac"
    assert with_mime_param(url, "audio/flac") == STREAM_URL + "&mime=audio%2Fflac"
    assert same_media_uri(url, STREAM_URL)


def test_didl_escapes_url_and_minimal_drops_extras():
    url = with_mime_param(STREAM_URL, "audio/x-flac")
    full = build_didl_lite(
        media_url=url,
        mime_type="audio/x-flac",
        title="A & B",
        artist="C",
        album="D",
        art_url="http://x/art",
        duration_seconds=60,
        size_bytes=1234,
        protocol_info=MP3_PN,
    )
    assert "token=tok&amp;mime=audio%2Fx-flac</res>" in full
    assert f'protocolInfo="{MP3_PN}"' in full
    minimal = build_didl_lite(
        media_url=url,
        mime_type="audio/x-flac",
        title="A & B",
        artist="C",
        album="D",
        art_url="http://x/art",
        duration_seconds=60,
        size_bytes=1234,
        minimal=True,
    )
    assert "A &amp; B" in minimal
    for absent in ("albumArtURI", "duration=", "size=", "upnp:album>"):
        assert absent not in minimal
    assert 'protocolInfo="http-get:*:audio/x-flac:*"' in minimal


# --- device control: DIDL/HTTP consistency and retries ------------------------


class ScriptedDmr:
    """Raises the scripted errors for SetAVTransportURI/SetNext calls in order."""

    has_next_transport_uri = True

    def __init__(self, set_errors=(), play_error=None):
        self.set_errors = list(set_errors)
        self.play_error = play_error
        self.set_calls = []
        self.next_calls = []
        self.played = 0

    async def _set(self, calls, media_url, meta_data):
        calls.append({"media_url": media_url, "meta_data": meta_data})
        if self.set_errors:
            error = self.set_errors.pop(0)
            if error is not None:
                raise error

    async def async_set_transport_uri(self, media_url, media_title, meta_data):
        await self._set(self.set_calls, media_url, meta_data)

    async def async_set_next_transport_uri(self, media_url, media_title, meta_data):
        await self._set(self.next_calls, media_url, meta_data)

    async def async_wait_for_can_play(self, max_wait_time=5):
        pass

    async def async_play(self):
        self.played += 1
        if self.play_error is not None:
            raise self.play_error


def _control(udn, dmr, sink=("http-get:*:audio/x-flac:DLNA.ORG_OP=01",), mimes=None):
    load_strategies.reset(udn)
    staging.reset(udn)
    manager = SimpleNamespace(
        active_renderer=udn,
        dmr_devices={udn: dmr},
        renderers={
            udn: {
                "friendly_name": "Amp",
                "sink_protocol_info": list(sink),
                "supported_mime_types": mimes
                if mimes is not None
                else ",".join(sorted(mimes_from_protocol_info(parse_protocol_info_list(list(sink))))),
            }
        },
        base_url="http://10.0.0.1:8111",
        renderer_base_url="http://10.0.0.1:8112",
    )
    return UPnPDeviceControl(manager)


META = {
    "title": "Song",
    "artist": "Artist",
    "album": "Album",
    "mime": "audio/flac",
    "duration_seconds": 61,
    "art_sha1": "cafe",
    "stream_url": STREAM_URL,
}


async def test_didl_label_and_http_content_type_agree():
    udn = "uuid:consistent"
    dmr = ScriptedDmr()
    control = _control(udn, dmr)

    await control.play_track(7, "/m/7.flac", dict(META))

    call = dmr.set_calls[0]
    assert 'protocolInfo="http-get:*:audio/x-flac:*"' in call["meta_data"]
    # The URL asks the stream endpoint for the same label the DIDL names...
    assert call["media_url"].endswith("&mime=audio%2Fx-flac")
    # ...which it serves for FLAC bytes (and would refuse for anything else).
    assert served_content_type("audio/flac", "audio/x-flac") == "audio/x-flac"
    assert load_strategies.get(udn, "SetAVTransportURI") is None  # default worked


async def test_url_is_untouched_when_no_relabel_is_needed():
    udn = "uuid:plain"
    dmr = ScriptedDmr()
    control = _control(udn, dmr, sink=("http-get:*:audio/flac:*",))
    await control.play_track(7, "/m/7.flac", dict(META))
    assert dmr.set_calls[0]["media_url"] == STREAM_URL


async def test_retry_with_exact_advertised_entry_then_remember_it():
    udn = "uuid:exact"
    dmr = ScriptedDmr(set_errors=[fault(714, "Illegal MIME-type")])
    control = _control(udn, dmr)

    await control.play_track(7, "/m/7.flac", dict(META))

    assert len(dmr.set_calls) == 2
    assert 'protocolInfo="http-get:*:audio/x-flac:*"' in dmr.set_calls[0]["meta_data"]
    second = dmr.set_calls[1]["meta_data"]
    assert 'protocolInfo="http-get:*:audio/x-flac:DLNA.ORG_OP=01"' in second
    assert "albumArtURI" in second  # still the full description
    assert load_strategies.get(udn, "SetAVTransportURI") == "advertised"
    assert dmr.played == 1

    # The next load starts with what worked.
    await control.play_track(8, "/m/8.flac", dict(META))
    assert 'DLNA.ORG_OP=01"' in dmr.set_calls[2]["meta_data"]
    assert len(dmr.set_calls) == 3


async def test_retry_with_simplified_didl():
    udn = "uuid:minimal"
    dmr = ScriptedDmr(set_errors=[fault(714), fault(402, "Invalid Args")])
    control = _control(udn, dmr)

    await control.play_track(7, "/m/7.flac", dict(META))

    assert len(dmr.set_calls) == 3
    minimal = dmr.set_calls[2]["meta_data"]
    assert "albumArtURI" not in minimal and "duration=" not in minimal
    assert "<res protocolInfo=" in minimal
    assert load_strategies.get(udn, "SetAVTransportURI") == "minimal"


async def test_retry_with_empty_metadata():
    udn = "uuid:empty"
    dmr = ScriptedDmr(set_errors=[fault(714), fault(714), UpnpResponseError(status=500)])
    control = _control(udn, dmr)

    await control.play_track(7, "/m/7.flac", dict(META))

    assert [c["meta_data"] == "" for c in dmr.set_calls] == [False, False, False, True]
    assert load_strategies.get(udn, "SetAVTransportURI") == "empty"


async def test_no_advertised_entry_skips_that_stage():
    udn = "uuid:legacy"
    dmr = ScriptedDmr(set_errors=[fault(714)])
    control = _control(udn, dmr, sink=(), mimes="audio/x-flac")
    await control.play_track(7, "/m/7.flac", dict(META))
    assert len(dmr.set_calls) == 2
    assert "albumArtURI" not in dmr.set_calls[1]["meta_data"]  # straight to minimal
    assert load_strategies.get(udn, "SetAVTransportURI") == "minimal"


async def test_attempts_are_bounded_and_the_error_is_actionable():
    udn = "uuid:never"
    dmr = ScriptedDmr(set_errors=[fault(714, "Illegal MIME-type")] * 10)
    control = _control(udn, dmr, sink=("http-get:*:audio/mpeg:DLNA.ORG_OP=01",))

    with pytest.raises(RendererLoadError) as info:
        await control.play_track(7, "/m/7.flac", dict(META))

    assert len(dmr.set_calls) == len(LOAD_STAGES) - 1  # no advertised flac entry
    err = info.value
    assert err.renderer_id == f"upnp:{udn}"
    assert err.reason == "unsupported_format"
    assert "audio/flac" in err.detail and "not in the formats it advertises" in err.detail
    assert "UPnP 714" in err.detail
    assert dmr.played == 0
    assert load_strategies.snapshot()["last_errors"][udn]["upnp_error_code"] == 714


async def test_stream_not_found_is_not_retried():
    udn = "uuid:404"
    dmr = ScriptedDmr(set_errors=[fault(716, "Resource not found")])
    control = _control(udn, dmr)

    with pytest.raises(RendererLoadError) as info:
        await control.play_track(7, "/m/7.flac", dict(META))

    assert len(dmr.set_calls) == 1
    assert info.value.reason == "stream_unreachable"
    assert "10.0.0.1:8112" in info.value.detail


async def test_input_mode_errors_are_reported():
    udn = "uuid:locked"
    dmr = ScriptedDmr(set_errors=[fault(705, "Transport is locked")])
    control = _control(udn, dmr)
    with pytest.raises(RendererLoadError) as info:
        await control.play_track(7, "/m/7.flac", dict(META))
    assert info.value.reason == "input_unavailable"
    assert "another controller or input" in info.value.detail
    assert len(dmr.set_calls) == 1


async def test_unreachable_renderer_is_not_retried():
    udn = "uuid:gone"
    dmr = ScriptedDmr(set_errors=[UpnpConnectionError("refused")])
    control = _control(udn, dmr)
    with pytest.raises(RendererLoadError) as info:
        await control.play_track(7, "/m/7.flac", dict(META))
    assert info.value.reason == "unreachable"
    assert len(dmr.set_calls) == 1


async def test_play_fault_is_mapped_and_701_still_ignored():
    udn = "uuid:play"
    control = _control(udn, ScriptedDmr(play_error=fault(704, "Format not supported")))
    with pytest.raises(RendererLoadError) as info:
        await control.play_track(7, "/m/7.flac", dict(META))
    assert info.value.reason == "unsupported_format"
    assert "[Play: UPnP 704" in info.value.detail

    control = _control(udn, ScriptedDmr(play_error=fault(701, "Transition not available")))
    await control.play_track(7, "/m/7.flac", dict(META))  # already playing: fine


async def test_set_next_uses_the_ladder_and_reraises_the_device_error():
    udn = "uuid:next"
    dmr = ScriptedDmr(set_errors=[fault(714), None])
    control = _control(udn, dmr)
    url = await control.set_next_track(udn, 7, dict(META))
    assert url.endswith("&mime=audio%2Fx-flac")
    assert len(dmr.next_calls) == 2
    assert load_strategies.get(udn, "SetNextAVTransportURI") == "advertised"
    assert load_strategies.get(udn, "SetAVTransportURI") is None  # tracked per action

    dmr = ScriptedDmr(set_errors=[fault(402)] * 10)
    control = _control(udn, dmr)
    with pytest.raises(UpnpActionError):  # staging classifies the raw fault
        await control.set_next_track(udn, 7, dict(META))
    assert len(dmr.next_calls) == len(LOAD_STAGES)  # bounded


def test_fault_classification_and_messages():
    assert is_metadata_fault(fault(714))
    assert is_metadata_fault(UpnpActionError(error_code=None, error_desc="?"))
    assert is_metadata_fault(UpnpResponseError(status=500))
    assert not is_metadata_fault(UpnpResponseError(status=404))
    assert not is_metadata_fault(fault(716))
    assert not is_metadata_fault(UpnpConnectionError("x"))

    reason, detail = describe_transport_error(
        fault(812, "Vendor"), action="SetAVTransportURI", renderer_name="TV"
    )
    assert reason == "load_failed"
    assert detail == "TV returned a device-specific error [SetAVTransportURI: UPnP 812 Vendor]"
    reason, detail = describe_transport_error(
        fault(701), action="SetAVTransportURI", renderer_name="AVR"
    )
    assert reason == "input_unavailable" and "another input" in detail
    reason, _ = describe_transport_error(TimeoutError(), action="Play")
    assert reason == "unreachable"


class _Manager:
    def __init__(self, error):
        self.error = error
        self.renderers = {}
        self.base_url = None

    async def set_renderer(self, udn):
        pass

    async def play_track(self, *args, **kwargs):
        raise self.error


async def test_backend_passes_the_mapped_load_error_through():
    error = RendererLoadError("upnp:uuid:b", "unsupported_format", "Amp rejected ...")
    backend = UpnpRendererBackend(manager=_Manager(error))
    with pytest.raises(RendererLoadError) as info:
        await backend.play_track(
            "upnp:uuid:b", {"id": 1, "path": "/x.flac"}, PlaybackContext(base_url="http://x", user_id=None)
        )
    assert info.value is error


def test_capabilities_expose_protocol_info():
    backend = UpnpRendererBackend(manager=_Manager(None))
    device = backend._device_from_renderer(
        {
            "udn": "uuid:c",
            "friendly_name": "Amp",
            "supported_mime_types": "audio/mpeg",
            "sink_protocol_info": [MP3_PN],
        }
    )
    caps = device.as_api_dict()["capabilities"]
    assert caps["protocol_info"] == [MP3_PN]
    assert caps["supported_mime_types"] == ["audio/mpeg"]
    row = {"udn": "uuid:c", "supported_mime_types": "audio/mpeg", "sink_protocol_info": [MP3_PN]}
    assert renderer_row_to_api(row)["capabilities"]["protocol_info"] == [MP3_PN]


def test_manager_diagnostics_include_protocol_negotiation():
    manager = UPnPManager()
    manager.renderers["uuid:d"] = {
        "friendly_name": "Amp",
        "sink_protocol_info": [MP3_PN],
        "supported_mime_types": "audio/mpeg",
    }
    load_strategies.reset("uuid:d")
    load_strategies.record("uuid:d", "SetAVTransportURI", "minimal")
    try:
        diag = manager.protocol_diagnostics()["uuid:d"]
    finally:
        manager.renderers.pop("uuid:d", None)
        load_strategies.reset("uuid:d")
    assert diag["sink_protocol_info"][0]["dlna"]["PN"] == "MP3"
    assert diag["load_stages"] == {"SetAVTransportURI": "minimal"}


# --- schema ---------------------------------------------------------------------


def test_migration_adds_the_column_idempotently():
    sql = Path("migrations/034_renderer_sink_protocol_info.sql").read_text()
    assert "ADD COLUMN IF NOT EXISTS sink_protocol_info TEXT[]" in sql


async def test_init_db_has_the_column_and_it_round_trips(db):
    col = await db.fetchrow(
        """
        SELECT data_type FROM information_schema.columns
        WHERE table_name = 'renderer' AND column_name = 'sink_protocol_info'
        """
    )
    assert col["data_type"] == "ARRAY"
    # The migration statement is a no-op on the fresh schema.
    await db.execute(Path("migrations/034_renderer_sink_protocol_info.sql").read_text())

    udn = "uuid:proto-roundtrip"
    entries = ["http-get:*:audio/x-flac:*", MP3_PN]
    await db.execute("DELETE FROM renderer WHERE udn = $1", udn)
    manager = UPnPManager()
    await manager.save_renderer(
        {"udn": udn, "friendly_name": "Amp", "supported_mime_types": "audio/mpeg,audio/x-flac",
         "sink_protocol_info": entries}
    )
    assert await manager._existing_protocol_info(udn) == entries

    # A save without entries (device did not answer) keeps the saved ones.
    await manager.save_renderer({"udn": udn, "friendly_name": "Amp"})
    assert await manager._existing_protocol_info(udn) == entries

    # So does the generic registry upsert, which has no protocolInfo for it.
    await register_or_update_renderer(
        db,
        RendererDevice(
            renderer_id=f"upnp:{udn}",
            kind="upnp",
            native_id=udn,
            udn=udn,
            name="Amp",
            capabilities=RendererCapabilities(supported_mime_types={"audio/mpeg"}),
        ),
    )
    row = await db.fetchrow("SELECT * FROM renderer WHERE udn = $1", udn)
    assert list(row["sink_protocol_info"]) == entries
    assert renderer_row_to_api(row)["capabilities"]["protocol_info"] == entries
    await db.execute("DELETE FROM renderer WHERE udn = $1", udn)


# --- L16 parameters end to end (review fix, #316) -------------------------------

L16_48K = "audio/L16;rate=48000;channels=2"
L16_SINK = (
    "http-get:*:audio/L16;rate=44100;channels=2:DLNA.ORG_PN=LPCM",
    "http-get:*:audio/L16;rate=48000;channels=2:DLNA.ORG_PN=LPCM",
)


def test_l16_keeps_its_parameters_and_matches_only_its_own_rate():
    negotiated = negotiate_format(L16_48K, _entries(*L16_SINK))
    assert negotiated.mime == L16_48K
    assert negotiated.advertised.mime_params == {"rate": "48000", "channels": "2"}
    assert negotiated.exact_protocol_info == f"http-get:*:{L16_48K}:DLNA.ORG_PN=LPCM"
    assert negotiated.protocol_info == f"http-get:*:{L16_48K}:*"

    # Only another rate advertised: no entry describes these bytes.
    other = negotiate_format(L16_48K, _entries(L16_SINK[0]))
    assert (other.mime, other.advertised, other.advertised_support) == (L16_48K, None, False)
    # An entry without parameters accepts any rate.
    bare = negotiate_format(L16_48K, _entries("http-get:*:audio/L16:*"))
    assert bare.mime == L16_48K and bare.advertised is not None


def test_served_content_type_keeps_l16_parameters():
    assert served_content_type(L16_48K, None) == L16_48K
    assert served_content_type(L16_48K, "audio/l16") == L16_48K
    assert served_content_type(L16_48K, L16_48K) == L16_48K


async def test_l16_didl_protocol_info_equals_the_served_content_type():
    udn = "uuid:l16"
    dmr = ScriptedDmr(set_errors=[fault(714, "Illegal MIME-type")])
    control = _control(udn, dmr, sink=L16_SINK)

    await control.play_track(7, "/m/7.flac", dict(META, mime=L16_48K))

    default, advertised = (c["meta_data"] for c in dmr.set_calls)
    served = served_content_type(L16_48K, None)
    assert f'protocolInfo="http-get:*:{served}:*"' in default
    # The retry stage uses the 48 kHz entry, never the 44.1 kHz one.
    assert f'protocolInfo="http-get:*:{served}:DLNA.ORG_PN=LPCM"' in advertised
    assert "44100" not in advertised
    # No relabel: the URL is the planned one, served with the plan's MIME.
    assert dmr.set_calls[0]["media_url"] == STREAM_URL
