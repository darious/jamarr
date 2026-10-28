"""Next-track staging (SetNextAVTransportURI) bookkeeping per UPnP renderer.

The monitor stages queue[current_index + 1] once the current track is
confirmed playing; the renderer can then roll into it without a STOPPED gap.
Transitions are recognised by the renderer's TrackURI turning into the staged
URI. Advertised support is provisional: a renderer that faults on the action
is switched off here (in memory, until restart) and the monitor falls back to
loading each track on STOPPED, as for any other renderer.
"""

from __future__ import annotations

import asyncio
import html
import logging
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from async_upnp_client.exceptions import UpnpConnectionError

logger = logging.getLogger(__name__)

# Transient failures (timeouts, connection drops) tolerated in a row before
# staging is switched off for the renderer as well.
MAX_TRANSIENT_FAILURES = 3
# Times a renderer may accept a staged URI and still stop at the end of the
# track (without rolling into it) before staging is switched off for it.
MAX_STAGED_MISSES = 2


@dataclass
class StagedTrack:
    queue_index: int
    track_id: int
    url: str
    staged_at: float
    expires_at: float | None = None


class NextTrackStaging:
    def __init__(self) -> None:
        self.staged: dict[str, StagedTrack] = {}
        # udn -> why staging was switched off at runtime.
        self.disabled: dict[str, str] = {}
        # Renderers whose device-side NextAVTransportURI may still hold a URI
        # we no longer track (a new track was loaded over a staged one).
        self.needs_clear: set[str] = set()
        self._transient_failures: dict[str, int] = {}
        self._misses: dict[str, int] = {}
        # udn -> (track_id, at) of the last staging attempt that did not stick,
        # so an unplayable next track is not retried every poll.
        self.last_attempt: dict[str, tuple[int, float]] = {}

    def get(self, udn: str) -> StagedTrack | None:
        return self.staged.get(udn)

    def record(self, udn: str, staged: StagedTrack) -> None:
        self.staged[udn] = staged
        self.needs_clear.discard(udn)
        self._transient_failures.pop(udn, None)
        self.last_attempt.pop(udn, None)

    def take(self, udn: str) -> StagedTrack | None:
        """Remove and return the staged track; a transition consumes it once."""
        self._misses.pop(udn, None)
        return self.staged.pop(udn, None)

    def forget(self, udn: str) -> None:
        """Drop the record after a new track was loaded over it."""
        if self.staged.pop(udn, None) is not None:
            self.needs_clear.add(udn)
        self.last_attempt.pop(udn, None)

    def cleared(self, udn: str) -> None:
        self.staged.pop(udn, None)
        self.needs_clear.discard(udn)

    def is_disabled(self, udn: str) -> bool:
        return udn in self.disabled

    def disable(self, udn: str, reason: str) -> None:
        if udn not in self.disabled:
            logger.warning(
                "[Gapless] Next-track staging disabled for %s: %s "
                "(falling back to loading each track; restart to re-enable)",
                udn,
                reason,
            )
        self.disabled[udn] = reason
        self.staged.pop(udn, None)

    def note_failure(self, udn: str, exc: BaseException) -> None:
        """Classify a SetNextAVTransportURI failure; faults disable staging."""
        if is_transient(exc):
            count = self._transient_failures.get(udn, 0) + 1
            self._transient_failures[udn] = count
            logger.info(
                "[Gapless] SetNextAVTransportURI on %s failed transiently (%d/%d): %s",
                udn,
                count,
                MAX_TRANSIENT_FAILURES,
                exc,
            )
            if count >= MAX_TRANSIENT_FAILURES:
                self.disable(udn, f"{count} consecutive transient failures ({exc})")
            return
        self.disable(udn, f"SetNextAVTransportURI fault: {exc}")

    def note_staged_miss(self, udn: str) -> None:
        """The renderer stopped at track end instead of starting the staged URI."""
        count = self._misses.get(udn, 0) + 1
        self._misses[udn] = count
        self.staged.pop(udn, None)
        self.needs_clear.add(udn)
        logger.warning(
            "[Gapless] %s stopped at the end of the track instead of starting the "
            "staged next track (%d/%d)",
            udn,
            count,
            MAX_STAGED_MISSES,
        )
        if count >= MAX_STAGED_MISSES:
            self.disable(udn, "renderer accepts staged URIs but does not play them")

    def reset(self, udn: str | None = None) -> None:
        stores = (
            self.staged,
            self.disabled,
            self._transient_failures,
            self._misses,
            self.last_attempt,
        )
        if udn is None:
            for store in stores:
                store.clear()
            self.needs_clear.clear()
            return
        for store in stores:
            store.pop(udn, None)
        self.needs_clear.discard(udn)


def is_transient(exc: BaseException) -> bool:
    return isinstance(exc, (UpnpConnectionError, asyncio.TimeoutError, TimeoutError))


def staging_allowed(udn: str, advertised: bool) -> bool:
    """Config override first, then runtime faults, then the device's advert."""
    try:
        from app.config import upnp_gapless_override

        override = upnp_gapless_override(udn)
    except Exception:
        logger.debug("Could not read upnp_gapless config", exc_info=True)
        override = None
    if override == "off":
        return False
    if staging.is_disabled(udn):
        return False
    if override == "on":
        return True
    return bool(advertised)


def _token(uri: str) -> str | None:
    try:
        values = parse_qs(urlsplit(uri).query).get("token")
    except ValueError:
        return None
    return values[0] if values else None


def same_media_uri(reported: str | None, expected: str | None) -> bool:
    """True if the renderer's TrackURI is the URI we gave it.

    Renderers echo the URI back, sometimes still XML-escaped or with the host
    rewritten; every staged URI carries a unique stream token, so a matching
    token is as good as a matching string.
    """
    if not reported or not expected:
        return False
    reported = html.unescape(reported.strip())
    expected = html.unescape(expected.strip())
    if reported == expected:
        return True
    token = _token(expected)
    return bool(token) and _token(reported) == token


staging = NextTrackStaging()
