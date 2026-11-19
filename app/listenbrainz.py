"""ListenBrainz API client.

Covers what Jamarr needs from https://listenbrainz.readthedocs.io/en/latest/users/api/:
token validation and listen submission (``single``, ``import``, ``playing_now``).
Auth is the user's own token (``Authorization: Token <token>``); there is no
application key.

The client follows ListenBrainz's rate-limit headers (``X-RateLimit-Remaining``
and ``X-RateLimit-Reset-In``) and raises typed errors so callers can tell a
bad token from a bad listen from "try again later".
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Iterable, Mapping, Optional
from urllib.parse import quote

import httpx

from app.config import get_listenbrainz_api_root
from app.version import __version__

logger = logging.getLogger(__name__)

USER_AGENT = f"Jamarr/{__version__} ( https://github.com/darious/jamarr )"
SUBMISSION_CLIENT = "Jamarr"
REQUEST_TIMEOUT_SECONDS = 15.0
# ListenBrainz accepts up to 1000 listens per request; stay well below the
# 10 MB payload cap.
MAX_LISTENS_PER_REQUEST = 1000
# Wait out a rate-limit window inline only when it is short; otherwise hand
# the wait back to the caller as RateLimitedError.
MAX_INLINE_RATE_LIMIT_WAIT_SECONDS = 10.0


class ListenBrainzError(Exception):
    """Base error. ``retryable`` says whether the same request may succeed later."""

    retryable = True

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class ListenBrainzAuthError(ListenBrainzError):
    """The token was rejected (HTTP 401). Retrying will not help."""

    retryable = False


class ListenBrainzRejectedError(ListenBrainzError):
    """The request was malformed or a listen was refused (HTTP 400)."""

    retryable = False


class ListenBrainzRateLimitedError(ListenBrainzError):
    """HTTP 429, or a rate-limit window too long to wait out inline."""

    def __init__(self, message: str, retry_after: float):
        super().__init__(message, status_code=429)
        self.retry_after = retry_after


class ListenBrainzUnavailableError(ListenBrainzError):
    """Network failure, timeout, or a 5xx from ListenBrainz."""


def _float_header(headers: Mapping[str, str], name: str) -> Optional[float]:
    value = headers.get(name)
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
        if isinstance(body, dict) and body.get("error"):
            return str(body["error"])
    except ValueError:
        pass
    text = response.text.strip()
    return text[:200] if text else f"HTTP {response.status_code}"


class ListenBrainzClient:
    """Thin async client. One instance is shared per process (see get_client)."""

    def __init__(
        self,
        api_root: Optional[str] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ):
        self.api_root = (api_root or get_listenbrainz_api_root()).rstrip("/")
        self._transport = transport
        self._http: Optional[httpx.AsyncClient] = None
        self._lock = asyncio.Lock()
        # Monotonic deadline before which the current window has no requests left.
        self._blocked_until = 0.0

    def _client(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(
                base_url=self.api_root,
                timeout=REQUEST_TIMEOUT_SECONDS,
                headers={"User-Agent": USER_AGENT},
                transport=self._transport,
            )
        return self._http

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def _wait_for_rate_limit(self) -> None:
        wait = self._blocked_until - time.monotonic()
        if wait <= 0:
            return
        if wait > MAX_INLINE_RATE_LIMIT_WAIT_SECONDS:
            raise ListenBrainzRateLimitedError(
                "ListenBrainz rate limit window not yet reset", retry_after=wait
            )
        await asyncio.sleep(wait)

    def _record_rate_limit(self, response: httpx.Response) -> None:
        remaining = _float_header(response.headers, "X-RateLimit-Remaining")
        reset_in = _float_header(response.headers, "X-RateLimit-Reset-In")
        if remaining is not None and remaining <= 0 and reset_in is not None:
            self._blocked_until = time.monotonic() + max(reset_in, 0.0)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        token: Optional[str] = None,
        json_body: Any = None,
        params: Optional[dict] = None,
    ) -> httpx.Response:
        headers = {}
        if token is not None:
            headers["Authorization"] = f"Token {token}"
        async with self._lock:
            await self._wait_for_rate_limit()
            try:
                response = await self._client().request(
                    method, path, headers=headers, json=json_body, params=params
                )
            except httpx.HTTPError as exc:
                raise ListenBrainzUnavailableError(
                    f"ListenBrainz unreachable: {exc.__class__.__name__}"
                ) from exc
            self._record_rate_limit(response)

        status = response.status_code
        if status == 429:
            retry_after = (
                _float_header(response.headers, "X-RateLimit-Reset-In")
                or _float_header(response.headers, "Retry-After")
                or 10.0
            )
            raise ListenBrainzRateLimitedError(
                "ListenBrainz rate limit exceeded", retry_after=retry_after
            )
        if status == 401:
            raise ListenBrainzAuthError(_error_message(response), status_code=status)
        if status in (400, 413):
            # The listens (or their size) were refused; resending them unchanged fails again.
            raise ListenBrainzRejectedError(_error_message(response), status_code=status)
        if status == 408 or status >= 500:
            raise ListenBrainzUnavailableError(
                f"ListenBrainz error {status}: {_error_message(response)}",
                status_code=status,
            )
        if status >= 400:
            # 403/404/405...: a wrong API root, a proxy or maintenance page. Not
            # the listens' fault, so callers retry rather than drop them.
            raise ListenBrainzError(
                f"ListenBrainz error {status}: {_error_message(response)}",
                status_code=status,
            )
        return response

    async def validate_token(self, token: str) -> Optional[str]:
        """Return the ListenBrainz username for a valid token, None for an invalid one.

        ListenBrainz answers 200 either way and reports validity in the body.
        """
        response = await self._request("GET", "/1/validate-token", token=token)
        try:
            body = response.json()
        except ValueError as exc:
            raise ListenBrainzUnavailableError("ListenBrainz sent a non-JSON reply") from exc
        if not isinstance(body, dict):
            raise ListenBrainzUnavailableError("ListenBrainz sent an unexpected reply")
        if body.get("valid"):
            return body.get("user_name")
        return None

    async def get_listens(
        self,
        username: str,
        *,
        max_ts: Optional[int] = None,
        count: int = 1000,
        token: Optional[str] = None,
    ) -> list[dict]:
        """Up to ``count`` listens before ``max_ts`` (newest first).

        Public data; a token only buys a higher rate limit.
        """
        params: dict[str, Any] = {"count": min(count, MAX_LISTENS_PER_REQUEST)}
        if max_ts is not None:
            params["max_ts"] = int(max_ts)
        response = await self._request(
            "GET", f"/1/user/{quote(username, safe='')}/listens", token=token, params=params
        )
        try:
            body = response.json()
        except ValueError as exc:
            raise ListenBrainzUnavailableError("ListenBrainz sent a non-JSON reply") from exc
        listens = (body.get("payload") or {}).get("listens") if isinstance(body, dict) else None
        if not isinstance(listens, list):
            raise ListenBrainzUnavailableError("ListenBrainz sent an unexpected reply")
        return listens

    async def submit_listens(
        self, token: str, listen_type: str, listens: list[dict]
    ) -> None:
        if listen_type not in ("single", "import", "playing_now"):
            raise ValueError(f"unknown listen_type {listen_type!r}")
        if not listens:
            return
        if listen_type in ("single", "playing_now") and len(listens) != 1:
            raise ValueError(f"{listen_type} takes exactly one listen")
        if len(listens) > MAX_LISTENS_PER_REQUEST:
            raise ValueError("too many listens for one request")
        await self._request(
            "POST",
            "/1/submit-listens",
            token=token,
            json_body={"listen_type": listen_type, "payload": listens},
        )


_client: Optional[ListenBrainzClient] = None


def get_client() -> ListenBrainzClient:
    global _client
    if _client is None:
        _client = ListenBrainzClient()
    return _client


def set_client(client: Optional[ListenBrainzClient]) -> None:
    """Swap the shared client (tests)."""
    global _client
    _client = client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _valid_mbid(value: Any) -> Optional[str]:
    if not value:
        return None
    try:
        return str(uuid.UUID(str(value).strip()))
    except ValueError:
        return None


def _mbid_list(value: Any) -> list[str]:
    """Track artist MBIDs are stored as one string, ``"a; b"`` for collaborations."""
    if not value:
        return []
    parts: Iterable[str] = str(value).replace(",", ";").split(";")
    seen: list[str] = []
    for part in parts:
        mbid = _valid_mbid(part)
        if mbid and mbid not in seen:
            seen.append(mbid)
    return seen


def build_track_metadata(track: Mapping[str, Any]) -> Optional[dict]:
    """ListenBrainz ``track_metadata`` for a Jamarr track row.

    ``track`` needs title, artist, album, track_no, duration_seconds and the
    MBID columns. Returns None when the track lacks the artist or title that
    ListenBrainz requires.
    """
    artist = (track.get("artist") or "").strip()
    title = (track.get("title") or "").strip()
    if not artist or not title:
        return None

    info: dict[str, Any] = {
        "submission_client": SUBMISSION_CLIENT,
        "submission_client_version": __version__,
        "media_player": SUBMISSION_CLIENT,
        "media_player_version": __version__,
    }
    artist_mbids = _mbid_list(track.get("artist_mbid"))
    if artist_mbids:
        info["artist_mbids"] = artist_mbids
    # Jamarr's track_mbid is the MusicBrainz recording; release_track_mbid is
    # what ListenBrainz calls track_mbid (the track on a specific release).
    for key, column in (
        ("recording_mbid", "track_mbid"),
        ("release_mbid", "release_mbid"),
        ("release_group_mbid", "release_group_mbid"),
        ("track_mbid", "release_track_mbid"),
    ):
        mbid = _valid_mbid(track.get(column))
        if mbid:
            info[key] = mbid
    if track.get("track_no"):
        info["tracknumber"] = int(track["track_no"])
    duration = track.get("duration_seconds")
    if duration and duration > 0:
        info["duration_ms"] = int(round(float(duration) * 1000))

    metadata: dict[str, Any] = {
        "artist_name": artist,
        "track_name": title,
        "additional_info": info,
    }
    album = (track.get("album") or "").strip()
    if album:
        metadata["release_name"] = album
    return metadata
