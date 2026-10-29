"""UPnP/DLNA protocolInfo parsing and stream-format negotiation.

A renderer's ConnectionManager ``GetProtocolInfo`` Sink lists what it says it
can play as ``protocol:network:contentFormat:additionalInfo`` entries, e.g.

    http-get:*:audio/flac:*
    http-get:*:audio/mpeg:DLNA.ORG_PN=MP3;DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000...
    http-get:*:audio/L16;rate=44100;channels=2:DLNA.ORG_PN=LPCM

The whole entry is kept (MIME parameters and DLNA.ORG_* fields included), not
just the MIME type: the exact entry is one of the retry stages when a renderer
rejects our default description, and the parameters are what later audio
output planning needs.

Negotiation only ever relabels a stream within one *alias family* -- names
for the same container/codec bytes (``audio/flac`` vs ``audio/x-flac``). A
MIME label never converts audio, so ``audio/aac`` (raw ADTS) is not an alias
of ``audio/mp4`` (MP4 container) and ``audio/L16`` (headerless big-endian
PCM) is not an alias of ``audio/wav`` (RIFF, little-endian). The label chosen
here goes into both the DIDL ``res@protocolInfo`` and, via the stream URL's
``mime`` parameter, the HTTP ``Content-Type`` the renderer is served, so the
two always agree.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

# Wildcard fourth field: what Jamarr has always sent, and the default.
DEFAULT_ADDITIONAL_INFO = "*"

# Canonical MIME -> every name renderers use for the same bytes, in the order
# we prefer to send them when a renderer advertises several.
MIME_FAMILIES: dict[str, tuple[str, ...]] = {
    "audio/flac": ("audio/flac", "audio/x-flac"),
    "audio/mpeg": ("audio/mpeg", "audio/mp3", "audio/x-mp3", "audio/mpeg3", "audio/x-mpeg"),
    "audio/mp4": ("audio/mp4", "audio/x-m4a", "audio/m4a"),
    "audio/wav": ("audio/wav", "audio/x-wav", "audio/wave", "audio/vnd.wave"),
    "audio/ogg": ("audio/ogg", "application/ogg", "audio/x-ogg"),
    "audio/aiff": ("audio/aiff", "audio/x-aiff"),
    "audio/dsf": ("audio/dsf", "audio/x-dsf"),
    "audio/dff": ("audio/dff", "audio/x-dff"),
}

_ALIAS_TO_CANONICAL: dict[str, str] = {
    alias: canonical for canonical, aliases in MIME_FAMILIES.items() for alias in aliases
}

_HTTP_PROTOCOLS = {"http-get", "*"}


def mime_base(mime: Optional[str]) -> str:
    """``audio/L16;rate=44100`` -> ``audio/l16``; lower-cased, no parameters."""
    return (mime or "").split(";", 1)[0].strip().lower()


def mime_params_of(mime: Optional[str]) -> dict[str, str]:
    """``audio/L16;rate=44100;channels=2`` -> ``{"rate": "44100", "channels": "2"}``."""
    params: dict[str, str] = {}
    for part in (mime or "").split(";")[1:]:
        key, _, value = part.partition("=")
        if key.strip():
            params[key.strip().lower()] = value.strip()
    return params


def params_compatible(stream: dict[str, str], advertised: dict[str, str]) -> bool:
    """An advertised entry's MIME parameters describe the stream's bytes.

    Every parameter both name must agree (``rate``/``channels`` for L16); a
    parameter only one side names is no conflict. ``audio/L16;rate=48000``
    is a different stream from ``audio/L16;rate=44100``, not an alias.
    """
    for key, value in advertised.items():
        if key in stream and stream[key].lower() != value.lower():
            return False
    return True


def canonical_mime(mime: Optional[str]) -> str:
    base = mime_base(mime)
    return _ALIAS_TO_CANONICAL.get(base, base)


def mime_family(mime: Optional[str]) -> tuple[str, ...]:
    """Every alias of mime (itself first if it is not a known alias)."""
    base = mime_base(mime)
    family = MIME_FAMILIES.get(_ALIAS_TO_CANONICAL.get(base, ""))
    return family if family else ((base,) if base else ())


def is_alias(a: Optional[str], b: Optional[str]) -> bool:
    """True if a and b name the same container/codec."""
    if not mime_base(a) or not mime_base(b):
        return False
    return canonical_mime(a) == canonical_mime(b)


def served_content_type(actual: str, requested: Optional[str]) -> str:
    """The Content-Type to serve: ``requested`` if it is an alias of ``actual``.

    The stream endpoint uses this to honour the label negotiated for the
    renderer without ever claiming a different format than the bytes it sends.
    """
    if requested and is_alias(actual, requested):
        if mime_base(requested) == mime_base(actual):
            # Same name: the plan's MIME, parameters (L16 rate/channels) and all.
            return actual
        return mime_base(requested)
    return actual


@dataclass(frozen=True)
class ProtocolInfo:
    """One ``protocol:network:contentFormat:additionalInfo`` entry."""

    protocol: str
    network: str
    content_format: str
    additional_info: str

    @property
    def raw(self) -> str:
        return ":".join(
            (self.protocol, self.network, self.content_format, self.additional_info)
        )

    @property
    def mime(self) -> str:
        return mime_base(self.content_format)

    @property
    def mime_params(self) -> dict[str, str]:
        return mime_params_of(self.content_format)

    @property
    def dlna(self) -> dict[str, str]:
        """DLNA.ORG_* fields of the fourth field (``PN``, ``OP``, ``FLAGS``, ...)."""
        fields: dict[str, str] = {}
        if self.additional_info in ("", "*"):
            return fields
        for part in self.additional_info.split(";"):
            key, _, value = part.partition("=")
            key = key.strip()
            if key.upper().startswith("DLNA.ORG_"):
                fields[key.upper()[len("DLNA.ORG_"):]] = value.strip()
        return fields

    @property
    def is_http(self) -> bool:
        return self.protocol.lower() in _HTTP_PROTOCOLS

    @property
    def is_wildcard_format(self) -> bool:
        return self.content_format.strip() == "*"

    def as_dict(self) -> dict:
        return {
            "protocol_info": self.raw,
            "protocol": self.protocol,
            "network": self.network,
            "mime": self.mime,
            "mime_params": self.mime_params,
            "dlna": self.dlna,
        }


def split_protocol_info_list(value: Optional[str]) -> list[str]:
    """Split a CSV protocolInfo list, honouring DLNA's ``\\,`` escape."""
    if not value:
        return []
    entries: list[str] = []
    current: list[str] = []
    chars = iter(value)
    for ch in chars:
        if ch == "\\":
            nxt = next(chars, "")
            # Keep the escape: the entry is stored and re-sent verbatim.
            current.append(ch + nxt)
        elif ch == ",":
            entries.append("".join(current))
            current = []
        else:
            current.append(ch)
    entries.append("".join(current))
    return [e.strip() for e in entries if e.strip()]


def parse_protocol_info(entry: Optional[str]) -> Optional[ProtocolInfo]:
    """Parse one entry; None if it does not have four fields."""
    if not entry:
        return None
    parts = entry.strip().split(":", 3)
    if len(parts) != 4:
        return None
    protocol, network, content_format, additional_info = (p.strip() for p in parts)
    if not protocol or not content_format:
        return None
    return ProtocolInfo(protocol, network, content_format, additional_info or "*")


def parse_protocol_info_list(value: Optional[str] | Iterable[str]) -> list[ProtocolInfo]:
    """Parse a Sink CSV string, or an already split list of entries."""
    raw = split_protocol_info_list(value) if isinstance(value, str) or value is None else value
    parsed = (parse_protocol_info(entry) for entry in raw)
    return [p for p in parsed if p is not None]


def mimes_from_protocol_info(entries: Iterable[ProtocolInfo]) -> set[str]:
    """The legacy ``supported_mime_types`` view: bare MIME types, no wildcards."""
    return {e.mime for e in entries if e.mime and not e.is_wildcard_format}


# res@protocolInfo fourth field for Jamarr's streams: byte-range seekable
# (OP=01), streaming, DLNA 1.5. DLNA renderers take seekability from here; a
# Sony Bravia given "*" refuses Seek. The "minimal" load stage falls back to
# the bare "*" for renderers that object to DLNA fields.
SEEKABLE_ADDITIONAL_INFO = "DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000"


def default_protocol_info(mime: str) -> str:
    return f"http-get:*:{mime}:{SEEKABLE_ADDITIONAL_INFO}"


def plain_protocol_info(mime: str) -> str:
    return f"http-get:*:{mime}:{DEFAULT_ADDITIONAL_INFO}"


@dataclass(frozen=True)
class NegotiatedFormat:
    """What to tell one renderer about one stream."""

    # Label for DIDL res@protocolInfo and the HTTP Content-Type. MIME
    # parameters of the stream (L16 ``rate``/``channels``) are kept, spelled
    # exactly as the stream endpoint serves them.
    mime: str
    # The advertised entry matching that label, if the renderer listed one.
    advertised: Optional[ProtocolInfo]
    # True: the renderer advertises this format (or every format). False: it
    # published a list and the format is not on it. None: no list known.
    advertised_support: Optional[bool]

    @property
    def protocol_info(self) -> str:
        """Default res@protocolInfo: seekable DLNA fourth field (see SEEKABLE_ADDITIONAL_INFO)."""
        return default_protocol_info(self.mime)

    @property
    def exact_protocol_info(self) -> Optional[str]:
        """The advertised entry, if it differs from the default.

        Its protocol/network/DLNA fields are the renderer's own; the content
        format is our label, so res@protocolInfo always names exactly the
        Content-Type the stream is served with (the entry matched it already,
        parameters included, so only spelling can differ).
        """
        if self.advertised is None:
            return None
        entry = self.advertised
        protocol = "http-get" if entry.protocol == "*" else entry.protocol
        entry = ProtocolInfo(protocol, entry.network, self.mime, entry.additional_info)
        raw = entry.raw
        return None if raw == self.protocol_info else raw


def _entry_rank(entry: ProtocolInfo) -> tuple[int, int]:
    # Prefer the plain entry: a DLNA.ORG_PN claims a specific profile, and
    # MIME parameters pin a rate/channel layout we may not match.
    return (1 if "PN" in entry.dlna else 0, 1 if entry.mime_params else 0)


def negotiate_format(
    stream_mime: Optional[str],
    entries: Iterable[ProtocolInfo] = (),
    fallback_mimes: Iterable[str] = (),
) -> NegotiatedFormat:
    """Pick the label (and matching advertised entry) for a stream of stream_mime.

    ``entries`` is the renderer's full Sink list; ``fallback_mimes`` the legacy
    MIME-only list for renderers not re-hydrated since full entries were kept.

    MIME parameters on ``stream_mime`` (the plan's ``audio/L16;rate=…;
    channels=…``) are kept in the returned label, and an advertised entry
    only matches when its own parameters agree with them.
    """
    full = (stream_mime or "").strip() or "audio/flac"
    base = mime_base(full)
    params = mime_params_of(full)
    suffix = full[len(full.split(";", 1)[0]):] if params else ""
    family = mime_family(base)
    # The stream's own name first, then the family in preference order.
    preference = [base] + [m for m in family if m != base]

    def label(candidate: str) -> str:
        # The stream's own spelling when the name is unchanged, so the label
        # equals the served Content-Type character for character.
        return full if candidate == base else candidate + suffix

    http_entries = [e for e in entries if e.is_http]
    if http_entries:
        by_mime: dict[str, list[ProtocolInfo]] = {}
        for entry in http_entries:
            if params_compatible(params, entry.mime_params):
                by_mime.setdefault(entry.mime, []).append(entry)
        for candidate in preference:
            matches = by_mime.get(candidate)
            if matches:
                return NegotiatedFormat(label(candidate), min(matches, key=_entry_rank), True)
        wildcard = any(e.is_wildcard_format for e in http_entries)
        return NegotiatedFormat(full, None, True if wildcard else False)

    legacy = {mime_base(m) for m in fallback_mimes if mime_base(m)}
    if legacy:
        for candidate in preference:
            if candidate in legacy:
                return NegotiatedFormat(label(candidate), None, True)
        return NegotiatedFormat(full, None, False)
    return NegotiatedFormat(full, None, None)
