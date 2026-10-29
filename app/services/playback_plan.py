"""Renderer-aware audio output planning.

A playback plan answers one question for one track on one renderer: which
bytes do we send, and why. It takes the track's *actual* audio properties
(codec, container, sample rate, bit depth, channels), whether loudness
normalization needs the samples changed, and the renderer's constraints, and
picks the least destructive output that the renderer can play:

1. the original bytes, when the renderer takes them as they are;
2. a lossless remux (same codec bytes, different container);
3. a lossless decode to FLAC, WAV or L16 PCM -- resampling, downmixing or
   reducing bit depth only when a constraint actually requires it;
4. a lossy encode, only when nothing lossless is accepted or when a lossy
   quality was explicitly chosen for the renderer.

The plan is pure data. ``/api/stream`` re-reads it from the stream token
(``token_claims`` / ``OutputSpec.from_claims``), so the Content-Type served is
the MIME that went into DIDL-Lite / the Cast LOAD.

Constraints are data too (``RendererConstraints``): backends derive them from
what the device advertises (UPnP sink protocolInfo, Cast receiver defaults)
and ``renderer.audio_constraints`` in config.yaml overrides them per device.
Device quirks such as the FLAC block-size limit or a sample-rate ceiling are
opt-in config, never universal rules.
"""

from __future__ import annotations

import logging
import mimetypes
import os
from dataclasses import dataclass, field, replace
from typing import Any, Iterable

logger = logging.getLogger(__name__)


# --- MIME families ---------------------------------------------------------

# Every alias a renderer may advertise, folded onto one family. MIME alone
# does not establish codec support (audio/mp4 can be AAC or ALAC), which is
# why constraints carry codecs separately.
_MIME_FAMILIES: dict[str, str] = {
    "audio/flac": "flac",
    "audio/x-flac": "flac",
    "application/flac": "flac",
    "application/x-flac": "flac",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
    "audio/vnd.wave": "wav",
    "audio/x-pn-wav": "wav",
    "audio/l16": "l16",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/mpeg3": "mp3",
    "audio/x-mpeg": "mp3",
    "audio/x-mp3": "mp3",
    "audio/mp4": "mp4",
    "audio/m4a": "mp4",
    "audio/x-m4a": "mp4",
    "audio/aac": "mp4",
    "audio/x-aac": "mp4",
    "audio/ogg": "ogg",
    "audio/x-ogg": "ogg",
    "application/ogg": "ogg",
    "audio/opus": "ogg",
    "audio/vorbis": "ogg",
    "audio/aiff": "aiff",
    "audio/x-aiff": "aiff",
    "audio/matroska": "mka",
    "audio/x-matroska": "mka",
    "audio/webm": "webm",
    "audio/x-ms-wma": "wma",
}

# Formats the Cast Default Media Receiver documents as supported. ALAC is not
# among them, so an ALAC .m4a is decoded rather than sent as audio/mp4.
CAST_DEFAULT_MIME_TYPES = frozenset(
    {"audio/flac", "audio/mpeg", "audio/mp4", "audio/wav", "audio/ogg", "audio/webm"}
)
CAST_DEFAULT_CODECS = frozenset({"flac", "mp3", "aac", "vorbis", "opus", "pcm"})

LOSSLESS_CODECS = frozenset({"flac", "alac", "pcm", "wavpack", "ape", "tta", "ofr", "dsd"})

# Standard FLAC block sizes, largest first, for re-blocking under a limit.
_FLAC_BLOCK_SIZES = (4608, 4096, 2304, 2048, 1152, 1024, 576, 512, 256, 192)


def mime_family(mime_type: str | None) -> str | None:
    if not mime_type:
        return None
    base = mime_type.split(";", 1)[0].strip().lower()
    return _MIME_FAMILIES.get(base)


def source_mime_type(path: str) -> str:
    """The Content-Type ``/api/stream`` serves a file's original bytes as."""
    media_type, _ = mimetypes.guess_type(path)
    if media_type is not None:
        return media_type
    ext = os.path.splitext(path)[1].lower()
    return {
        ".flac": "audio/flac",
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".wav": "audio/wav",
        ".ogg": "audio/ogg",
    }.get(ext, "application/octet-stream")


# --- Source properties -----------------------------------------------------

# Scanner stores mutagen's class name in track.codec.
_CODEC_BY_SCANNER_NAME: dict[str, tuple[str, str]] = {
    # name: (codec, container)
    "flac": ("flac", "flac"),
    "oggflac": ("flac", "ogg"),
    "mp3": ("mp3", "mp3"),
    "mpeg audio": ("mp3", "mp3"),
    "easymp3": ("mp3", "mp3"),
    "mp4": ("aac", "mp4"),  # refined by probing: may be ALAC
    "easymp4": ("aac", "mp4"),
    "aac": ("aac", "aac"),
    "oggvorbis": ("vorbis", "ogg"),
    "oggopus": ("opus", "ogg"),
    "oggspeex": ("speex", "ogg"),
    "oggtheora": ("vorbis", "ogg"),
    "wave": ("pcm", "wav"),
    "wav": ("pcm", "wav"),
    "aiff": ("pcm", "aiff"),
    "wavpack": ("wavpack", "wv"),
    "monkeysaudio": ("ape", "ape"),
    "trueaudio": ("tta", "tta"),
    "optimfrog": ("ofr", "ofr"),
    "dsf": ("dsd", "dsf"),
    "dsdiff": ("dsd", "dff"),
    "asf": ("wma", "asf"),
    "musepack": ("mpc", "mpc"),
    "ac3": ("ac3", "ac3"),
}

_CODEC_BY_EXTENSION: dict[str, tuple[str, str]] = {
    ".flac": ("flac", "flac"),
    ".mp3": ("mp3", "mp3"),
    ".m4a": ("aac", "mp4"),
    ".mp4": ("aac", "mp4"),
    ".ogg": ("vorbis", "ogg"),
    ".oga": ("vorbis", "ogg"),
    ".opus": ("opus", "ogg"),
    ".wav": ("pcm", "wav"),
    ".aif": ("pcm", "aiff"),
    ".aiff": ("pcm", "aiff"),
    ".wv": ("wavpack", "wv"),
    ".ape": ("ape", "ape"),
    ".dsf": ("dsd", "dsf"),
    ".dff": ("dsd", "dff"),
    ".wma": ("wma", "asf"),
}


@dataclass(frozen=True)
class AudioProperties:
    """What the file on disk actually is."""

    codec: str | None
    container: str | None
    mime_type: str
    sample_rate_hz: int | None = None
    bit_depth: int | None = None
    channels: int | None = None
    # FLAC STREAMINFO block sizes; only probed when a constraint needs them.
    flac_min_block_size: int | None = None
    flac_max_block_size: int | None = None
    label: str = ""

    @property
    def lossless(self) -> bool:
        return self.codec in LOSSLESS_CODECS


def _positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def audio_properties_from_track(
    track: dict[str, Any], probe: dict[str, Any] | None = None
) -> AudioProperties:
    """Build source properties from a track row (plus optional file probe)."""
    from app.services.stream_profiles import original_quality_label

    path = str(track.get("path") or "")
    scanner_codec = str(track.get("codec") or "").strip().lower()
    codec, container = _CODEC_BY_SCANNER_NAME.get(scanner_codec) or _CODEC_BY_EXTENSION.get(
        os.path.splitext(path)[1].lower(), (scanner_codec or None, None)
    )
    probe = probe or {}
    if probe.get("codec"):
        codec = probe["codec"]
    return AudioProperties(
        codec=codec,
        container=container,
        mime_type=source_mime_type(path) if path else "application/octet-stream",
        sample_rate_hz=_positive_int(track.get("sample_rate_hz")),
        bit_depth=_positive_int(track.get("bit_depth")),
        channels=_positive_int(track.get("channels")),
        flac_min_block_size=_positive_int(probe.get("flac_min_block_size")),
        flac_max_block_size=_positive_int(probe.get("flac_max_block_size")),
        label=original_quality_label(track),
    )


def needs_probe(track: dict[str, Any], constraints: "RendererConstraints") -> bool:
    """Whether the planner needs facts the scanner did not store."""
    codec = str(track.get("codec") or "").strip().lower()
    path = str(track.get("path") or "").lower()
    if codec in {"mp4", "easymp4"} or path.endswith((".m4a", ".mp4")):
        return True  # AAC or ALAC?
    if constraints.flac_max_block_size and (
        codec in {"flac", "oggflac"} or path.endswith(".flac")
    ):
        return True
    return False


def probe_audio_file(path: str) -> dict[str, Any]:
    """Read what the planner needs from the file headers (blocking; small read)."""
    result: dict[str, Any] = {}
    try:
        import mutagen

        audio = mutagen.File(path)
    except Exception:
        logger.debug("Audio probe failed for %s", path, exc_info=True)
        return result
    if audio is None or audio.info is None:
        return result
    info = audio.info
    mp4_codec = str(getattr(info, "codec", "") or "").lower()
    if mp4_codec:
        if mp4_codec.startswith("alac"):
            result["codec"] = "alac"
        elif mp4_codec.startswith("mp4a"):
            result["codec"] = "aac"
        elif mp4_codec.startswith(("ac-3", "ec-3")):
            result["codec"] = "ac3"
    if hasattr(info, "min_blocksize"):
        result["flac_min_block_size"] = getattr(info, "min_blocksize", None)
        result["flac_max_block_size"] = getattr(info, "max_blocksize", None)
    return result


# --- Renderer constraints --------------------------------------------------


@dataclass(frozen=True)
class RendererConstraints:
    """What a renderer accepts. ``None`` means unknown / unconstrained."""

    # Advertised MIME types; None = nothing advertised (assume the original
    # plays, which is how Jamarr behaved before planning existed).
    supported_mime_types: frozenset[str] | None = None
    # Codecs known to decode; None = judge by MIME only.
    supported_codecs: frozenset[str] | None = None
    max_sample_rate_hz: int | None = None
    max_bit_depth: int | None = None
    max_channels: int | None = None
    # Opt-in: decoders that need fixed-size FLAC blocks no larger than this
    # (some Cast receivers mis-handle large or variable blocks; 4608).
    flac_max_block_size: int | None = None
    # Decode to WAV rather than FLAC when a decode is needed anyway.
    prefer_wav: bool = False
    # Allow a lossy encode as the last resort when nothing lossless fits.
    allow_lossy: bool = True
    # An explicitly chosen stream quality profile (e.g. "mp3_320").
    quality: str | None = None
    # L16 sample rates the renderer lists, when it advertises audio/L16.
    l16_rates: frozenset[int] | None = None
    # Where these came from, for the renderer API ("cast-default", "config").
    sources: tuple[str, ...] = ()

    def families(self) -> set[str] | None:
        if self.supported_mime_types is None:
            return None
        if any(m in {"*", "*/*", "audio/*"} for m in self.supported_mime_types):
            return None
        return {f for f in (mime_family(m) for m in self.supported_mime_types) if f}

    def accepts_family(self, family: str) -> bool:
        families = self.families()
        return True if families is None else family in families

    def accepts_codec(self, codec: str | None) -> bool:
        if self.supported_codecs is None or codec is None:
            return True
        return codec in self.supported_codecs

    def as_dict(self) -> dict[str, Any]:
        return {
            "supported_mime_types": sorted(self.supported_mime_types)
            if self.supported_mime_types is not None
            else None,
            "supported_codecs": sorted(self.supported_codecs)
            if self.supported_codecs is not None
            else None,
            "max_sample_rate_hz": self.max_sample_rate_hz,
            "max_bit_depth": self.max_bit_depth,
            "max_channels": self.max_channels,
            "flac_max_block_size": self.flac_max_block_size,
            "prefer_wav": self.prefer_wav,
            "allow_lossy": self.allow_lossy,
            "quality": self.quality,
            "sources": list(self.sources),
        }


def parse_protocol_info(entries: Iterable[str] | str | None) -> tuple[set[str], set[int]]:
    """MIME types (and L16 rates) from UPnP sink protocolInfo entries.

    Accepts full ``protocol:network:contentFormat:additionalInfo`` entries or
    bare MIME strings, as a list or one comma-separated string.
    """
    if not entries:
        return set(), set()
    if isinstance(entries, str):
        entries = entries.split(",")
    mimes: set[str] = set()
    l16_rates: set[int] = set()
    for raw in entries:
        entry = str(raw or "").strip()
        if not entry:
            continue
        parts = entry.split(":")
        content = parts[2] if len(parts) >= 4 else entry
        content = content.strip()
        if not content:
            continue
        base, _, params = content.partition(";")
        base = base.strip().lower()
        mimes.add(base)
        if base == "audio/l16":
            for param in params.split(";"):
                key, _, value = param.partition("=")
                if key.strip().lower() == "rate":
                    rate = _positive_int(value.strip())
                    if rate:
                        l16_rates.add(rate)
    return mimes, l16_rates


def normalize_renderer_key(value: Any) -> str:
    """The native id behind any spelling of a renderer key.

    ``upnp:uuid:X``, ``uuid:X`` and ``X`` are one device, as are
    ``cast:ID`` and ``ID``: every known renderer kind prefix
    (``KNOWN_RENDERER_KINDS``) is dropped, then the UDN's ``uuid:``.
    """
    from app.services.renderer.contracts import KNOWN_RENDERER_KINDS

    key = str(value or "").strip().lower()
    kind, sep, rest = key.partition(":")
    if sep and kind in KNOWN_RENDERER_KINDS:
        key = rest
    if key.startswith("uuid:"):
        key = key[len("uuid:"):]
    return key


_CONFIG_KEYS = {
    "max_sample_rate_hz",
    "max_bit_depth",
    "max_channels",
    "flac_max_block_size",
    "prefer_wav",
    "allow_lossy",
    "quality",
    "supported_mime_types",
    "supported_codecs",
}


def configured_constraints(*renderer_keys: Any) -> dict[str, Any]:
    """``renderer.audio_constraints`` entry for any of these ids, or {}."""
    try:
        from app.config import load_config

        section = (load_config().get("renderer") or {}).get("audio_constraints") or {}
    except (FileNotFoundError, AttributeError):
        return {}
    if not isinstance(section, dict):
        return {}
    wanted = {normalize_renderer_key(k) for k in renderer_keys if k}
    for key, value in section.items():
        if normalize_renderer_key(key) in wanted and isinstance(value, dict):
            return {k: v for k, v in value.items() if k in _CONFIG_KEYS}
    return {}


def apply_overrides(
    constraints: RendererConstraints, overrides: dict[str, Any], source: str = "config"
) -> RendererConstraints:
    if not overrides:
        return constraints
    changes: dict[str, Any] = {}
    for key in ("max_sample_rate_hz", "max_bit_depth", "max_channels", "flac_max_block_size"):
        if key in overrides:
            changes[key] = _positive_int(overrides[key])
    for key in ("prefer_wav", "allow_lossy"):
        if key in overrides:
            changes[key] = bool(overrides[key])
    if "quality" in overrides:
        changes["quality"] = str(overrides["quality"]).strip().lower() or None
    if "supported_mime_types" in overrides:
        mimes, rates = parse_protocol_info(overrides["supported_mime_types"] or [])
        changes["supported_mime_types"] = frozenset(mimes)
        changes["l16_rates"] = frozenset(rates) or None
    if "supported_codecs" in overrides:
        codecs = overrides["supported_codecs"]
        changes["supported_codecs"] = (
            frozenset(str(c).strip().lower() for c in codecs) if codecs is not None else None
        )
    return replace(constraints, sources=(*constraints.sources, source), **changes)


def constraints_for_cast(renderer_id: str, native_id: str | None = None) -> RendererConstraints:
    base = RendererConstraints(
        supported_mime_types=CAST_DEFAULT_MIME_TYPES,
        supported_codecs=CAST_DEFAULT_CODECS,
        sources=("cast-default",),
    )
    return apply_overrides(base, configured_constraints(renderer_id, native_id))


def constraints_for_upnp(
    renderer_info: dict[str, Any] | None, udn: str, renderer_id: str | None = None
) -> RendererConstraints:
    """Constraints from a UPnP renderer record (manager.renderers[udn]).

    Uses complete protocolInfo entries when discovery provides them
    (``sink_protocol_info``), else the reduced ``supported_mime_types`` list.
    Lossy fallback is off unless configured: an advertised list can be
    incomplete, and sending the original (as before planning existed) is the
    safer failure than an unasked-for MP3.
    """
    info = renderer_info or {}
    entries = (
        info.get("sink_protocol_info")
        or info.get("protocol_info")
        or info.get("supported_mime_types")
    )
    mimes, rates = parse_protocol_info(entries)
    base = RendererConstraints(
        supported_mime_types=frozenset(mimes) if mimes else None,
        l16_rates=frozenset(rates) or None,
        allow_lossy=False,
        sources=("upnp-protocol-info",) if mimes else (),
    )
    # Keyed by the UDN (with or without upnp:) or the renderer id.
    return apply_overrides(base, configured_constraints(udn, renderer_id))


def constraints_for_device(device: Any) -> RendererConstraints:
    """Fallback for backends without their own ``output_constraints``."""
    kind = getattr(device, "kind", None)
    renderer_id = getattr(device, "renderer_id", None)
    native_id = getattr(device, "native_id", None)
    if kind in {"cast", "chromecast"}:
        return constraints_for_cast(renderer_id or "", native_id)
    caps = getattr(device, "capabilities", None)
    mimes = set(getattr(caps, "supported_mime_types", None) or ())
    base = RendererConstraints(
        supported_mime_types=frozenset(mimes) if mimes else None,
        sources=("device",) if mimes else (),
    )
    return apply_overrides(
        base, configured_constraints(renderer_id, native_id, getattr(device, "udn", None))
    )


# --- The plan ---------------------------------------------------------------

LOSSLESS_FORMATS = ("flac", "wav", "l16")
_LOSSY_FORMATS = {"mp3_320": ("mp3", "audio/mpeg"), "opus_128": ("opus", "audio/ogg")}
_FORMAT_FAMILY = {"flac": "flac", "wav": "wav", "l16": "l16", "mp3": "mp3", "opus": "ogg"}
_FORMAT_MIME = {"flac": "audio/flac", "wav": "audio/wav", "mp3": "audio/mpeg", "opus": "audio/ogg"}


@dataclass(frozen=True)
class OutputSpec:
    """The bytes to serve; round-trips through stream token claims."""

    format: str  # original | flac | wav | l16 | mp3 | opus
    mime_type: str
    sample_rate_hz: int | None = None
    bit_depth: int | None = None
    channels: int | None = None
    # Resample / downmix only when set (None = keep the source's).
    resample: bool = False
    downmix: bool = False
    # FLAC encoder block size (None = encoder default).
    flac_block_size: int | None = None
    # Container change only: copy the codec bytes.
    remux: bool = False
    # Lossy profile key, for format mp3/opus.
    profile: str | None = None

    @property
    def is_original(self) -> bool:
        return self.format == "original"

    def token_claims(self) -> dict[str, Any]:
        claims: dict[str, Any] = {"out": self.format, "out_mime": self.mime_type}
        if self.is_original:
            return claims
        claims.update(
            {
                "out_rate": self.sample_rate_hz if self.resample else None,
                "out_depth": self.bit_depth,
                "out_ch": self.channels if self.downmix else None,
                "out_block": self.flac_block_size,
                "out_remux": self.remux or None,
                "out_profile": self.profile,
            }
        )
        return {k: v for k, v in claims.items() if v is not None}

    @classmethod
    def from_claims(cls, claims: dict[str, Any]) -> "OutputSpec | None":
        fmt = claims.get("out")
        if not isinstance(fmt, str) or fmt not in {"original", *LOSSLESS_FORMATS, "mp3", "opus"}:
            return None
        rate = _positive_int(claims.get("out_rate"))
        channels = _positive_int(claims.get("out_ch"))
        return cls(
            format=fmt,
            mime_type=str(claims.get("out_mime") or _FORMAT_MIME.get(fmt) or ""),
            sample_rate_hz=rate,
            bit_depth=_positive_int(claims.get("out_depth")),
            channels=channels,
            resample=rate is not None,
            downmix=channels is not None,
            flac_block_size=_positive_int(claims.get("out_block")),
            remux=bool(claims.get("out_remux")),
            profile=claims.get("out_profile") if isinstance(claims.get("out_profile"), str) else None,
        )

    def cache_key(self) -> str:
        parts = [f"out-{self.format}"]
        if self.remux:
            parts.append("remux")
        if self.resample and self.sample_rate_hz:
            parts.append(f"r{self.sample_rate_hz}")
        if self.bit_depth:
            parts.append(f"b{self.bit_depth}")
        if self.downmix and self.channels:
            parts.append(f"c{self.channels}")
        if self.flac_block_size:
            parts.append(f"k{self.flac_block_size}")
        if self.profile:
            parts.append(self.profile)
        return "-".join(parts)

    @property
    def extension(self) -> str:
        return {"flac": "flac", "wav": "wav", "l16": "pcm", "mp3": "mp3", "opus": "opus"}.get(
            self.format, "bin"
        )

    def ffmpeg_args(self) -> tuple[str, ...]:
        """Encoder args (gain filters are appended separately)."""
        if self.is_original:
            return ()
        args: list[str] = ["-map", "0:a:0", "-vn"]
        if self.format in _LOSSY_FORMATS_BY_NAME:
            from app.services.stream_profiles import PROFILES

            return tuple(PROFILES[self.profile or _LOSSY_FORMATS_BY_NAME[self.format]].ffmpeg_args)
        if self.remux:
            return (*args, "-c:a", "copy", "-f", "flac")
        if self.resample and self.sample_rate_hz:
            args += ["-ar", str(self.sample_rate_hz)]
        if self.downmix and self.channels:
            args += ["-ac", str(self.channels)]
        depth = self.bit_depth or 16
        if self.format == "flac":
            if depth > 16:
                args += ["-sample_fmt", "s32", "-bits_per_raw_sample", "24"]
            else:
                args += ["-sample_fmt", "s16"]
            args += ["-c:a", "flac", "-compression_level", "5"]
            if self.flac_block_size:
                args += ["-frame_size", str(self.flac_block_size)]
            args += ["-f", "flac"]
        elif self.format == "wav":
            codec = {16: "pcm_s16le", 24: "pcm_s24le", 32: "pcm_s32le"}.get(depth, "pcm_s16le")
            args += ["-c:a", codec, "-f", "wav"]
        elif self.format == "l16":
            args += ["-c:a", "pcm_s16be", "-f", "s16be"]
        return tuple(args)


_LOSSY_FORMATS_BY_NAME = {"mp3": "mp3_320", "opus": "opus_128"}


@dataclass(frozen=True)
class PlaybackPlan:
    output: OutputSpec
    # original | remux | decode | lossy
    action: str
    operations: tuple[str, ...]
    reasons: tuple[str, ...]
    source_label: str
    quality_label: str
    lossless: bool
    gain_db: float | None = None
    gain_mode: str | None = None
    constraint_sources: tuple[str, ...] = field(default=())

    @property
    def mime_type(self) -> str:
        return self.output.mime_type

    @property
    def is_original(self) -> bool:
        return self.output.is_original

    @property
    def reason(self) -> str:
        return "; ".join(self.reasons)

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "format": self.output.format,
            "mime_type": self.output.mime_type,
            "sample_rate_hz": self.output.sample_rate_hz,
            "bit_depth": self.output.bit_depth,
            "channels": self.output.channels,
            "lossless": self.lossless,
            "operations": list(self.operations),
            "reason": self.reason,
            "source_label": self.source_label,
            "quality_label": self.quality_label,
            "gain_db": self.gain_db,
            "gain_mode": self.gain_mode,
            "constraint_sources": list(self.constraint_sources),
        }


_DSD_PCM_RATE = 176400


def _rate_label(rate: int | None) -> str:
    if not rate:
        return ""
    return f"{rate // 1000} kHz" if rate % 1000 == 0 else f"{rate / 1000:.1f} kHz"


def _channels_label(channels: int | None) -> str:
    return {None: "", 1: "mono", 2: "", 6: "5.1", 8: "7.1"}.get(channels, f"{channels} ch")


def _output_label(spec: OutputSpec, source: AudioProperties) -> str:
    if spec.is_original:
        return source.label
    if spec.format in _LOSSY_FORMATS_BY_NAME:
        from app.services.stream_profiles import PROFILES

        return PROFILES[spec.profile or _LOSSY_FORMATS_BY_NAME[spec.format]].label
    parts = [spec.format.upper()]
    if spec.bit_depth:
        parts.append(f"{spec.bit_depth} bit")
    if spec.sample_rate_hz:
        parts.append(_rate_label(spec.sample_rate_hz))
    channels = _channels_label(spec.channels)
    if channels:
        parts.append(channels)
    return " ".join(parts)


def _target_rate(source_rate: int, max_rate: int) -> int:
    """Highest rate <= max_rate in the source's family (44.1k vs 48k)."""
    family = 44100 if source_rate % 44100 == 0 else 48000
    candidates = [family * m for m in (8, 4, 2, 1) if family * m <= max_rate]
    return candidates[0] if candidates else max_rate


def _flac_block_ok(source: AudioProperties, limit: int) -> bool | None:
    lo, hi = source.flac_min_block_size, source.flac_max_block_size
    if lo is None or hi is None:
        return None
    return lo == hi and hi <= limit


def _block_size_under(limit: int) -> int:
    for size in _FLAC_BLOCK_SIZES:
        if size <= limit:
            return size
    return _FLAC_BLOCK_SIZES[-1]


def plan_playback(
    source: AudioProperties,
    constraints: RendererConstraints | None = None,
    *,
    gain_db: float | None = None,
    gain_mode: str | None = None,
    requested_quality: str | None = None,
) -> PlaybackPlan:
    """Choose the output for ``source`` on a renderer with ``constraints``.

    ``gain_db`` set means loudness normalization applies, which needs the
    samples changed and so rules out serving the original bytes.
    """
    from app.services.stream_profiles import PROFILES, normalize_quality

    constraints = constraints or RendererConstraints()
    reasons: list[str] = []
    operations: list[str] = []

    quality = requested_quality or constraints.quality
    quality_key = normalize_quality(quality) if quality else "original"
    max_rate = constraints.max_sample_rate_hz
    max_depth = constraints.max_bit_depth
    explicit_lossy = quality_key in _LOSSY_FORMATS
    if quality_key != "original" and not explicit_lossy:
        # A lossless quality profile (flac_24_48 / flac_16_48) is a ceiling.
        profile = PROFILES[quality_key]
        if profile.sample_rate_hz:
            max_rate = min(max_rate or profile.sample_rate_hz, profile.sample_rate_hz)
        if profile.bit_depth:
            max_depth = min(max_depth or profile.bit_depth, profile.bit_depth)

    def build(spec: OutputSpec, action: str, lossless: bool) -> PlaybackPlan:
        return PlaybackPlan(
            output=spec,
            action=action,
            operations=tuple(operations),
            reasons=tuple(reasons) or ("original is compatible",),
            source_label=source.label,
            quality_label=_output_label(spec, source),
            lossless=lossless,
            gain_db=gain_db,
            gain_mode=gain_mode if gain_db is not None else None,
            constraint_sources=constraints.sources,
        )

    def lossy(profile_key: str) -> PlaybackPlan:
        fmt, mime = _LOSSY_FORMATS[profile_key]
        operations.append("lossy_encode")
        if gain_db is not None:
            operations.append("normalize")
        spec = OutputSpec(
            format=fmt,
            mime_type=mime,
            sample_rate_hz=48000,
            channels=min(source.channels or 2, 2),
            profile=profile_key,
        )
        return build(spec, "lossy", False)

    if explicit_lossy:
        fmt, _mime = _LOSSY_FORMATS[quality_key]
        if constraints.accepts_family(_FORMAT_FAMILY[fmt]):
            reasons.append(f"{PROFILES[quality_key].label} explicitly selected")
            return lossy(quality_key)
        reasons.append(f"{PROFILES[quality_key].label} selected but not accepted by renderer")

    if source.codec == "dsd":
        # DSD only reaches a renderer as PCM; FLAC tops out well below DSD rates.
        max_rate = min(max_rate or _DSD_PCM_RATE, _DSD_PCM_RATE)

    # What must change, regardless of container?
    target_rate = source.sample_rate_hz
    if source.sample_rate_hz and max_rate and source.sample_rate_hz > max_rate:
        target_rate = _target_rate(source.sample_rate_hz, max_rate)
        reasons.append(
            f"sample rate {_rate_label(source.sample_rate_hz)} exceeds maximum {_rate_label(max_rate)}"
        )
        operations.append("resample")
    target_depth = source.bit_depth if source.lossless else None
    if target_depth and max_depth and target_depth > max_depth:
        reasons.append(f"bit depth {target_depth} exceeds maximum {max_depth}")
        target_depth = max_depth
        operations.append("reduce_depth")
    target_channels = source.channels
    if source.channels and constraints.max_channels and source.channels > constraints.max_channels:
        reasons.append(
            f"{source.channels} channels exceed maximum {constraints.max_channels}"
        )
        target_channels = constraints.max_channels
        operations.append("downmix")
    if gain_db is not None:
        reasons.append("loudness normalization")
        operations.append("normalize")

    source_family = mime_family(source.mime_type)
    container_ok = source_family is not None and constraints.accepts_family(source_family)
    codec_ok = constraints.accepts_codec(source.codec)
    block_limit = constraints.flac_max_block_size
    block_ok: bool | None = True
    if block_limit and source.codec == "flac":
        block_ok = _flac_block_ok(source, block_limit)
    transform_needed = bool(operations)

    if not transform_needed and codec_ok and block_ok:
        if container_ok:
            return build(OutputSpec(format="original", mime_type=source.mime_type), "original", source.lossless)
        if source.codec == "flac" and constraints.accepts_family("flac"):
            reasons.append(f"renderer does not accept {source.mime_type}; FLAC moved to a native container")
            operations.append("remux")
            spec = OutputSpec(
                format="flac",
                mime_type="audio/flac",
                sample_rate_hz=source.sample_rate_hz,
                bit_depth=source.bit_depth,
                channels=source.channels,
                remux=True,
            )
            return build(spec, "remux", True)

    if not transform_needed:
        if not codec_ok:
            reasons.append(f"renderer does not decode {source.codec.upper() if source.codec else 'this codec'}")
        elif not container_ok:
            reasons.append(f"renderer does not accept {source.mime_type}")
        elif block_ok is None:
            reasons.append(f"FLAC block size unknown; renderer needs fixed blocks <= {block_limit}")
        elif not block_ok:
            reasons.append(
                f"FLAC blocks {source.flac_min_block_size}-{source.flac_max_block_size} "
                f"exceed renderer limit {block_limit}"
            )
        operations.append("decode")

    # Lossless decode: FLAC, WAV or L16, in preference order.
    order = ["wav", "flac", "l16"] if constraints.prefer_wav else ["flac", "wav", "l16"]
    depth = target_depth or (source.bit_depth if source.lossless else None) or 16
    depth = max(depth, 16)
    depth = min(depth, max_depth) if max_depth else depth
    for fmt in order:
        if not constraints.accepts_family(fmt):
            continue
        out_rate = target_rate
        out_depth = depth
        resample = target_rate != source.sample_rate_hz
        if fmt == "l16":
            if out_depth > 16:
                reasons.append("L16 carries 16-bit samples only")
                operations.append("reduce_depth")
                out_depth = 16
            rates = constraints.l16_rates
            if rates and out_rate and out_rate not in rates:
                allowed = sorted(r for r in rates if r <= out_rate) or sorted(rates)
                out_rate = allowed[-1] if allowed[-1] <= (out_rate or 0) else allowed[0]
                resample = True
                reasons.append(f"L16 rate limited to {_rate_label(out_rate)}")
                operations.append("resample")
        elif fmt == "wav" and out_depth not in (16, 24, 32):
            out_depth = 16 if out_depth < 16 else 24
        elif fmt == "flac" and out_depth > 24:
            out_depth = 24
        out_channels = target_channels
        mime = _FORMAT_MIME.get(fmt) or ""
        if fmt == "l16":
            mime = f"audio/L16;rate={out_rate or 44100};channels={out_channels or 2}"
        spec = OutputSpec(
            format=fmt,
            mime_type=mime,
            sample_rate_hz=out_rate,
            bit_depth=out_depth,
            channels=out_channels,
            resample=resample,
            downmix=target_channels != source.channels,
            flac_block_size=_block_size_under(block_limit) if (fmt == "flac" and block_limit) else None,
        )
        if fmt == "wav" and constraints.prefer_wav:
            reasons.append("renderer prefers WAV")
        return build(spec, "decode", source.lossless)

    if constraints.allow_lossy:
        for key in ("mp3_320", "opus_128"):
            fmt, _ = _LOSSY_FORMATS[key]
            if constraints.accepts_family(_FORMAT_FAMILY[fmt]):
                reasons.append("renderer accepts no lossless output")
                return lossy(key)

    reasons.append("no compatible output known; sending original")
    return build(OutputSpec(format="original", mime_type=source.mime_type), "original", source.lossless)


def apply_plan_to_metadata(metadata: dict[str, Any], plan: Any) -> None:
    """Describe the planned output, not the file on disk, in DIDL-Lite.

    The MIME becomes the plan's (the Content-Type /api/stream will send), and
    the original file size goes when the bytes are transcoded: a renderer
    that trusts res@size would otherwise stop early or wait for more.
    """
    if plan is None:
        return
    if getattr(plan, "mime_type", None):
        metadata["mime"] = plan.mime_type
    if not getattr(plan, "is_original", True):
        metadata.pop("size_bytes", None)
