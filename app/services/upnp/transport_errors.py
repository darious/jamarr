"""Readable reasons for AVTransport load failures, and which ones to retry.

UPnP faults arrive as SOAP error codes (AVTransport 7xx, generic 4xx/5xx/6xx,
vendor 8xx). The load path retries only faults that a different description
of the same stream can fix (illegal MIME type, rejected arguments, a renderer
choking on our DIDL); everything else is reported straight away with a reason
the UI can show.
"""

from __future__ import annotations

from typing import Optional

from async_upnp_client.exceptions import (
    UpnpActionError,
    UpnpCommunicationError,
    UpnpResponseError,
)

# Faults where re-describing the stream (exact advertised protocolInfo,
# simpler DIDL, no DIDL) has a chance: the device answered, but disliked what
# we sent rather than the transport state or the stream itself.
METADATA_FAULT_CODES = frozenset({402, 501, 600, 704, 714})

# code -> (reason, readable explanation). The reason is machine-readable and
# lands in RendererLoadError.reason; the text goes in its detail.
UPNP_ERROR_REASONS: dict[int, tuple[str, str]] = {
    401: ("action_unsupported", "does not support this action"),
    402: ("metadata_rejected", "rejected the request arguments (often the track metadata)"),
    501: ("load_failed", "reported that the action failed"),
    600: ("metadata_rejected", "rejected an argument value (often the track metadata)"),
    602: ("action_unsupported", "does not implement this action"),
    603: ("renderer_busy", "is out of memory"),
    604: ("input_unavailable", "needs attention on the device itself (human intervention required)"),
    701: (
        "input_unavailable",
        "refused the transition; it may be switched to another input/source or still busy",
    ),
    702: ("load_failed", "reported no content to play"),
    703: ("stream_unreachable", "could not read the stream"),
    704: ("unsupported_format", "cannot play this format"),
    705: (
        "input_unavailable",
        "has its transport locked; another controller or input source may be using it",
    ),
    706: ("load_failed", "reported a write error"),
    707: ("load_failed", "reports the media as protected or not writable"),
    712: ("load_failed", "does not support the requested play mode"),
    714: ("unsupported_format", "rejected the stream's MIME type"),
    715: ("renderer_busy", "reports the content as busy"),
    716: ("stream_unreachable", "could not fetch the stream URL"),
    718: ("load_failed", "rejected the transport instance"),
    719: ("drm", "reported a DRM error"),
    720: ("drm", "reports the content has expired"),
    721: ("drm", "does not allow this use of the content"),
    722: ("drm", "cannot determine allowed uses of the content"),
    723: ("drm", "reports the allowed uses of the content are exhausted"),
    724: ("drm", "failed device authentication"),
    725: ("drm", "has been revoked"),
}


def upnp_error_code(exc: BaseException) -> Optional[int]:
    code = getattr(exc, "error_code", None)
    try:
        return int(code) if code is not None else None
    except (TypeError, ValueError):
        return None


def is_metadata_fault(exc: BaseException) -> bool:
    """The device answered with a fault a different description might avoid."""
    if isinstance(exc, UpnpActionError):
        code = upnp_error_code(exc)
        # A SOAP fault without a usable code: plenty of renderers answer a
        # DIDL they cannot parse this way.
        return code is None or code in METADATA_FAULT_CODES
    if isinstance(exc, UpnpResponseError):
        # Bare HTTP 500 with no SOAP fault body: same story.
        return getattr(exc, "status", None) == 500
    return False


def is_unreachable(exc: BaseException) -> bool:
    """No answer at all (as opposed to an answer saying no)."""
    if isinstance(exc, (UpnpActionError, UpnpResponseError)):
        return False
    return isinstance(exc, (UpnpCommunicationError, OSError, TimeoutError))


def describe_transport_error(
    exc: BaseException,
    *,
    action: str,
    renderer_name: str = "Renderer",
    mime_type: Optional[str] = None,
    advertised_support: Optional[bool] = None,
    stream_host: Optional[str] = None,
) -> tuple[str, str]:
    """(reason, human-readable detail) for a failed transport action."""
    code = upnp_error_code(exc)
    if is_unreachable(exc):
        return (
            "unreachable",
            f"{renderer_name} did not answer {action} ({type(exc).__name__}: {exc})",
        )
    reason, text = UPNP_ERROR_REASONS.get(code, (None, None)) if code is not None else (None, None)
    if reason is None:
        if code is not None and 800 <= code <= 899:
            reason, text = "load_failed", "returned a device-specific error"
        else:
            reason, text = "load_failed", "refused the request"
    detail = f"{renderer_name} {text}"
    if reason == "unsupported_format" and mime_type:
        detail += f" ({mime_type}"
        if advertised_support is False:
            detail += "; not in the formats it advertises"
        elif advertised_support is True:
            detail += "; although it advertises it"
        detail += ")"
    if reason == "stream_unreachable" and stream_host:
        detail += f"; check that it can reach {stream_host}"
    desc = getattr(exc, "error_desc", None)
    if code is not None:
        detail += f" [{action}: UPnP {code}{f' {desc}' if desc else ''}]"
    else:
        detail += f" [{action}: {exc}]"
    return reason, detail
