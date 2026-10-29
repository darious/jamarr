"""Renderer-aware audio output planning (issue #316, P2 audio selection)."""

import pytest

from app import config as app_config
from app.services.playback_plan import (
    CAST_DEFAULT_MIME_TYPES,
    AudioProperties,
    OutputSpec,
    RendererConstraints,
    apply_plan_to_metadata,
    audio_properties_from_track,
    constraints_for_cast,
    constraints_for_upnp,
    needs_probe,
    normalize_renderer_key,
    parse_protocol_info,
    plan_playback,
)
from app.services.renderer.cast_backend import CastRendererBackend
from app.services.renderer.contracts import PlaybackContext


def flac(rate=44100, depth=16, channels=2, blocks=(4096, 4096)) -> AudioProperties:
    return AudioProperties(
        codec="flac",
        container="flac",
        mime_type="audio/flac",
        sample_rate_hz=rate,
        bit_depth=depth,
        channels=channels,
        flac_min_block_size=blocks[0] if blocks else None,
        flac_max_block_size=blocks[1] if blocks else None,
        label=f"FLAC {depth} bit",
    )


MP3 = AudioProperties(
    codec="mp3", container="mp3", mime_type="audio/mpeg", sample_rate_hz=44100, channels=2, label="MP3"
)
ALAC = AudioProperties(
    codec="alac", container="mp4", mime_type="audio/mp4", sample_rate_hz=44100, bit_depth=24, channels=2
)
OGG_FLAC = AudioProperties(
    codec="flac", container="ogg", mime_type="audio/ogg", sample_rate_hz=48000, bit_depth=24, channels=2
)


def upnp(*mimes, **kwargs) -> RendererConstraints:
    return RendererConstraints(supported_mime_types=frozenset(mimes), **kwargs)


# --- selection matrix ------------------------------------------------------


def test_compatible_original_is_sent_untouched():
    plan = plan_playback(flac(96000, 24), upnp("audio/flac", "audio/mpeg"))
    assert plan.action == "original"
    assert plan.output.is_original
    assert plan.mime_type == "audio/flac"
    assert plan.lossless
    assert plan.operations == ()


def test_unknown_renderer_gets_the_original():
    assert plan_playback(flac(192000, 24), None).action == "original"
    assert plan_playback(MP3, RendererConstraints()).action == "original"


def test_mime_aliases_count_as_support():
    assert plan_playback(flac(), upnp("audio/x-flac")).action == "original"
    assert plan_playback(MP3, upnp("audio/mp3")).action == "original"


def test_sample_rate_above_ceiling_resamples_within_the_family():
    plan = plan_playback(flac(176400, 24), upnp("audio/flac", max_sample_rate_hz=96000))
    assert plan.action == "decode"
    assert plan.output.format == "flac"
    assert plan.output.sample_rate_hz == 88200  # 44.1k family, not 96k
    assert plan.output.bit_depth == 24
    assert "resample" in plan.operations
    assert "176.4 kHz exceeds maximum 96 kHz" in plan.reason
    assert plan.lossless
    args = plan.output.ffmpeg_args()
    assert args[args.index("-ar") + 1] == "88200"


def test_rate_within_ceiling_is_not_resampled():
    plan = plan_playback(flac(48000, 24), upnp("audio/flac", max_sample_rate_hz=96000))
    assert plan.action == "original"


def test_bit_depth_above_ceiling_is_reduced_without_resampling():
    plan = plan_playback(flac(96000, 24), upnp("audio/flac", max_bit_depth=16))
    assert plan.action == "decode"
    assert plan.output.bit_depth == 16
    assert plan.output.sample_rate_hz == 96000
    assert not plan.output.resample
    assert plan.operations == ("reduce_depth",)
    args = plan.output.ffmpeg_args()
    assert "-ar" not in args
    assert args[args.index("-sample_fmt") + 1] == "s16"


def test_multichannel_is_downmixed_to_stereo():
    plan = plan_playback(flac(48000, 24, channels=6), upnp("audio/flac", max_channels=2))
    assert plan.output.channels == 2
    assert plan.output.downmix
    assert "downmix" in plan.operations
    assert "6 channels exceed maximum 2" in plan.reason
    args = plan.output.ffmpeg_args()
    assert args[args.index("-ac") + 1] == "2"


def test_flac_block_constraint_reblocks_large_blocks():
    plan = plan_playback(flac(96000, 24, blocks=(8192, 8192)), upnp("audio/flac", flac_max_block_size=4608))
    assert plan.action == "decode"
    assert plan.output.format == "flac"
    assert plan.output.flac_block_size == 4608
    assert plan.output.sample_rate_hz == 96000 and plan.output.bit_depth == 24
    assert "exceed renderer limit 4608" in plan.reason
    args = plan.output.ffmpeg_args()
    assert args[args.index("-frame_size") + 1] == "4608"


def test_flac_block_constraint_rejects_variable_blocks():
    plan = plan_playback(flac(blocks=(1152, 4608)), upnp("audio/flac", flac_max_block_size=4608))
    assert plan.action == "decode"


def test_flac_block_constraint_accepts_fixed_small_blocks():
    plan = plan_playback(flac(blocks=(4096, 4096)), upnp("audio/flac", flac_max_block_size=4608))
    assert plan.action == "original"


def test_flac_block_constraint_with_unknown_blocks_is_conservative():
    plan = plan_playback(flac(blocks=None), upnp("audio/flac", flac_max_block_size=4608))
    assert plan.action == "decode"
    assert "block size unknown" in plan.reason


def test_flac_block_constraint_is_opt_in():
    assert plan_playback(flac(blocks=(8192, 8192)), upnp("audio/flac")).action == "original"


def test_normalization_forces_a_lossless_decode_at_source_depth():
    plan = plan_playback(flac(44100, 16), upnp("audio/flac"), gain_db=-3.5, gain_mode="track")
    assert plan.action == "decode"
    assert plan.output.format == "flac"
    assert plan.output.bit_depth == 16
    assert not plan.output.resample
    assert plan.operations == ("normalize",)
    assert plan.gain_db == -3.5 and plan.gain_mode == "track"
    assert "loudness normalization" in plan.reason


def test_normalization_prefers_wav_when_configured():
    plan = plan_playback(
        flac(), upnp("audio/flac", "audio/wav", prefer_wav=True), gain_db=1.0, gain_mode="album"
    )
    assert plan.output.format == "wav"
    assert plan.mime_type == "audio/wav"
    args = plan.output.ffmpeg_args()
    assert args[args.index("-c:a") + 1] == "pcm_s16le"


def test_flac_unsupported_decodes_to_wav():
    plan = plan_playback(flac(96000, 24), upnp("audio/wav", "audio/mpeg"))
    assert plan.action == "decode"
    assert plan.output.format == "wav"
    assert plan.output.bit_depth == 24
    assert "pcm_s24le" in plan.output.ffmpeg_args()
    assert plan.quality_label == "WAV 24 bit 96 kHz"


def test_l16_only_renderer_gets_16_bit_pcm_at_an_advertised_rate():
    constraints = RendererConstraints(
        supported_mime_types=frozenset({"audio/l16"}), l16_rates=frozenset({44100, 48000})
    )
    plan = plan_playback(flac(96000, 24), constraints)
    assert plan.output.format == "l16"
    assert plan.output.bit_depth == 16
    assert plan.output.sample_rate_hz == 48000
    assert plan.mime_type == "audio/L16;rate=48000;channels=2"
    assert plan.output.ffmpeg_args()[-2:] == ("-f", "s16be")


def test_lossy_is_the_last_resort_only():
    plan = plan_playback(flac(), upnp("audio/mpeg"))
    assert plan.action == "lossy"
    assert plan.output.format == "mp3"
    assert plan.mime_type == "audio/mpeg"
    assert not plan.lossless
    assert "accepts no lossless output" in plan.reason


def test_lossy_fallback_can_be_disabled():
    plan = plan_playback(flac(), upnp("audio/mpeg", allow_lossy=False))
    assert plan.action == "original"
    assert "no compatible output" in plan.reason


def test_explicit_lossy_quality_is_honoured():
    plan = plan_playback(flac(), upnp("audio/flac", "audio/ogg", quality="opus_128"))
    assert plan.action == "lossy"
    assert plan.output.format == "opus"
    assert plan.mime_type == "audio/ogg"
    assert "explicitly selected" in plan.reason


def test_explicit_lossless_profile_acts_as_a_ceiling():
    plan = plan_playback(flac(96000, 24), upnp("audio/flac"), requested_quality="flac_16_48")
    assert plan.output.sample_rate_hz == 48000
    assert plan.output.bit_depth == 16


def test_alac_on_cast_is_decoded_not_sent_as_mp4():
    plan = plan_playback(ALAC, constraints_for_cast("cast:abc", "abc"))
    assert plan.action == "decode"
    assert plan.output.format == "flac"
    assert plan.output.bit_depth == 24
    assert "does not decode ALAC" in plan.reason


def test_ogg_flac_is_remuxed_when_ogg_is_not_accepted():
    plan = plan_playback(OGG_FLAC, upnp("audio/flac"))
    assert plan.action == "remux"
    assert plan.output.remux
    assert plan.output.ffmpeg_args()[-4:] == ("-c:a", "copy", "-f", "flac")


def test_lossy_source_normalized_is_decoded_to_16_bit_flac():
    plan = plan_playback(MP3, upnp("audio/flac", "audio/mpeg"), gain_db=2.0, gain_mode="track")
    assert plan.output.format == "flac"
    assert plan.output.bit_depth == 16
    assert not plan.lossless


# --- claims / properties ---------------------------------------------------


def test_output_spec_round_trips_through_token_claims():
    plan = plan_playback(flac(176400, 24, channels=6), upnp("audio/flac", max_sample_rate_hz=96000, max_channels=2, flac_max_block_size=4608))
    restored = OutputSpec.from_claims(plan.output.token_claims())
    assert restored == plan.output
    assert restored.cache_key() == plan.output.cache_key()


def test_original_spec_round_trips():
    plan = plan_playback(MP3, upnp("audio/mpeg"))
    assert OutputSpec.from_claims(plan.output.token_claims()) == plan.output
    assert OutputSpec.from_claims({}) is None


def test_track_row_maps_scanner_codec_and_probe():
    props = audio_properties_from_track(
        {"path": "/m/a.m4a", "codec": "MP4", "sample_rate_hz": 44100, "bit_depth": 16, "channels": 2},
        {"codec": "alac"},
    )
    assert props.codec == "alac" and props.container == "mp4" and props.lossless
    props = audio_properties_from_track({"path": "/m/a.flac", "codec": "FLAC", "bit_depth": 0})
    assert props.codec == "flac" and props.bit_depth is None
    assert needs_probe({"path": "/m/a.m4a", "codec": "MP4"}, RendererConstraints())
    assert not needs_probe({"path": "/m/a.flac", "codec": "FLAC"}, RendererConstraints())
    assert needs_probe({"path": "/m/a.flac", "codec": "FLAC"}, RendererConstraints(flac_max_block_size=4608))


def test_parse_protocol_info_reads_full_entries_and_l16_rates():
    mimes, rates = parse_protocol_info(
        [
            "http-get:*:audio/flac:*",
            "http-get:*:audio/L16;rate=44100;channels=2:DLNA.ORG_PN=LPCM",
            "http-get:*:audio/L16;rate=48000;channels=2:*",
        ]
    )
    assert mimes == {"audio/flac", "audio/l16"}
    assert rates == {44100, 48000}
    assert parse_protocol_info("audio/mpeg,audio/x-flac")[0] == {"audio/mpeg", "audio/x-flac"}


def test_upnp_constraints_prefer_full_protocol_info(monkeypatch):
    monkeypatch.setattr(app_config, "_config", {"renderer": {}})
    constraints = constraints_for_upnp(
        {"supported_mime_types": "audio/mpeg", "protocol_info": ["http-get:*:audio/wav:*"]}, "uuid:x"
    )
    assert constraints.supported_mime_types == frozenset({"audio/wav"})
    assert constraints_for_upnp({}, "uuid:x").supported_mime_types is None


def test_upnp_reads_stored_sink_protocol_info(monkeypatch):
    monkeypatch.setattr(app_config, "_config", {"renderer": {}})
    constraints = constraints_for_upnp(
        {"supported_mime_types": "audio/mpeg", "sink_protocol_info": ["http-get:*:audio/wav:*"]},
        "uuid:x",
    )
    assert constraints.supported_mime_types == frozenset({"audio/wav"})


def test_upnp_never_goes_lossy_unless_configured(monkeypatch):
    # An advertised list can be incomplete: a renderer that plays FLAC but
    # only lists MP3 keeps getting the original, as before planning existed.
    monkeypatch.setattr(app_config, "_config", {"renderer": {}})
    info = {"sink_protocol_info": ["http-get:*:audio/mpeg:*"]}
    plan = plan_playback(flac(), constraints_for_upnp(info, "uuid:x"))
    assert plan.action == "original"

    monkeypatch.setattr(
        app_config,
        "_config",
        {"renderer": {"audio_constraints": {"uuid:x": {"allow_lossy": True}}}},
    )
    plan = plan_playback(flac(), constraints_for_upnp(info, "uuid:x"))
    assert plan.action == "lossy"


def test_config_constraints_match_by_renderer_id_udn_or_cast_uuid(monkeypatch):
    monkeypatch.setattr(
        app_config,
        "_config",
        {
            "renderer": {
                "audio_constraints": {
                    "uuid:ABC-123": {"max_sample_rate_hz": 48000, "prefer_wav": True},
                    "cast:9f8e": {"flac_max_block_size": 4608, "unknown_key": 1},
                }
            }
        },
    )
    upnp_constraints = constraints_for_upnp({"supported_mime_types": "audio/flac"}, "abc-123")
    assert upnp_constraints.max_sample_rate_hz == 48000
    assert upnp_constraints.prefer_wav
    assert "config" in upnp_constraints.sources
    cast_constraints = constraints_for_cast("cast:9F8E", "9f8e")
    assert cast_constraints.flac_max_block_size == 4608
    assert cast_constraints.supported_mime_types == CAST_DEFAULT_MIME_TYPES
    # Quirks are opt-in: another Cast device gets neither limit.
    other = constraints_for_cast("cast:other", "other")
    assert other.flac_max_block_size is None and other.max_sample_rate_hz is None


@pytest.mark.parametrize(
    "key",
    [
        "upnp:uuid:DEV-1",
        "uuid:dev-1",
        "dev-1",
        "UPnP:uuid:dev-1",
        "cast:dev-1",
    ],
)
def test_normalize_renderer_key_drops_every_known_kind(key):
    assert normalize_renderer_key(key) == "dev-1"


def test_config_constraints_match_any_spelling_of_the_renderer_id(monkeypatch):
    """Keys written as the renderer id apply as well as the bare UDN (review fix, #316)."""
    monkeypatch.setattr(
        app_config,
        "_config",
        {"renderer": {"audio_constraints": {"upnp:uuid:dev-1": {"max_sample_rate_hz": 96000}}}},
    )
    dev = constraints_for_upnp({"supported_mime_types": "audio/flac"}, "uuid:dev-1")
    assert dev.max_sample_rate_hz == 96000
    assert constraints_for_upnp({}, "uuid:DEV-1", "upnp:uuid:dev-1").max_sample_rate_hz == 96000
    # Not another device's.
    assert constraints_for_upnp({}, "uuid:other").max_sample_rate_hz is None


def test_plan_metadata_drops_original_size_when_transcoded():
    plan = plan_playback(flac(96000, 24), upnp("audio/wav"))
    metadata = {"mime": "audio/flac", "size_bytes": 123}
    apply_plan_to_metadata(metadata, plan)
    assert metadata == {"mime": "audio/wav"}
    original = plan_playback(flac(), upnp("audio/flac"))
    metadata = {"mime": "audio/x-flac", "size_bytes": 123}
    apply_plan_to_metadata(metadata, original)
    assert metadata == {"mime": "audio/flac", "size_bytes": 123}


# --- Cast MIME consistency -------------------------------------------------


@pytest.mark.parametrize(
    "source,expected",
    [(ALAC, "audio/flac"), (flac(), "audio/flac"), (MP3, "audio/mpeg")],
)
def test_cast_load_mime_is_the_plans_mime(monkeypatch, source, expected):
    monkeypatch.setattr(app_config, "_config", {"renderer": {}})
    backend = CastRendererBackend(browser_factory=lambda _b: None, discovery_timeout=0)
    plan = plan_playback(source, backend.output_constraints("cast:abc"))
    context = PlaybackContext(
        base_url="http://x",
        user_id=1,
        stream_url="http://x/api/stream/1?token=t",
        # A stale/forwarded MIME must not win over the plan.
        stream_mime_type="audio/x-something",
        playback_plan=plan,
    )
    assert backend._load_mime_type({"mime": "audio/mp4"}, context) == expected == plan.mime_type


def test_cast_capabilities_advertise_the_planner_defaults():
    backend = CastRendererBackend(browser_factory=lambda _b: None, discovery_timeout=0)
    device = backend._device_from_info("abc", None)
    assert device.capabilities.supported_mime_types == set(CAST_DEFAULT_MIME_TYPES)


def test_sonos_gets_its_documented_flac_limit():
    """A Sonos lists audio/flac with no rate, then stops on 24/96 (seen on a
    Play:3): plan within Sonos's documented 24-bit/48 kHz instead."""
    info = {"manufacturer": "Sonos, Inc.", "supported_mime_types": "audio/flac,audio/mpeg"}
    constraints = constraints_for_upnp(info, "uuid:RINCON_X")
    assert constraints.max_sample_rate_hz == 48000 and constraints.max_bit_depth == 24
    assert "documented" in constraints.sources

    plan = plan_playback(flac(96000, 24), constraints)
    assert plan.output.sample_rate_hz == 48000
    assert plan.lossless
    # 16/44.1 still goes out untouched.
    assert plan_playback(flac(44100, 16), constraints).action == "original"
    # Other vendors get no invented limit.
    other = constraints_for_upnp({"manufacturer": "Naim Audio", "supported_mime_types": "audio/flac"}, "uuid:N")
    assert other.max_sample_rate_hz is None


def test_config_overrides_the_documented_sonos_limit(monkeypatch):
    monkeypatch.setattr(
        app_config,
        "_config",
        {"renderer": {"audio_constraints": {"uuid:RINCON_X": {"max_sample_rate_hz": 44100}}}},
    )
    info = {"manufacturer": "Sonos, Inc.", "supported_mime_types": "audio/flac"}
    assert constraints_for_upnp(info, "uuid:RINCON_X").max_sample_rate_hz == 44100
