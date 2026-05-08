from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from typing import Any

import httpx

log = logging.getLogger("jamarr_tui.api")

_REFRESH_INTERVAL_SECONDS = 8 * 60


class AuthError(Exception):
    """Raised on 401 from the API."""


class ApiError(Exception):
    """Raised for non-2xx responses other than 401."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"{status_code}: {message}")
        self.status_code = status_code
        self.message = message


class JamarrClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._access_token: str | None = None
        self._client_id = f"jamarr-tui-{uuid.uuid4().hex[:8]}"
        self._refresh_task: asyncio.Task[bool] | None = None
        self._refresh_loop_task: asyncio.Task[None] | None = None
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            headers={"X-Jamarr-Client-Id": self._client_id},
            transport=transport,
        )

    @property
    def is_authenticated(self) -> bool:
        return self._access_token is not None

    @property
    def client_id(self) -> str:
        return self._client_id

    async def aclose(self) -> None:
        await self._stop_token_refresh()
        if self._refresh_task is not None and not self._refresh_task.done():
            self._refresh_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._refresh_task
        await self._http.aclose()

    def _auth_headers(self) -> dict[str, str]:
        if not self._access_token:
            return {}
        return {"Authorization": f"Bearer {self._access_token}"}

    def _clear_access_token(self) -> None:
        self._access_token = None

    async def _stop_token_refresh(self) -> None:
        if self._refresh_loop_task is None:
            return
        task = self._refresh_loop_task
        self._refresh_loop_task = None
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    def _start_token_refresh(self) -> None:
        if self._refresh_loop_task is None or self._refresh_loop_task.done():
            self._refresh_loop_task = asyncio.create_task(self._refresh_loop())

    async def _refresh_loop(self) -> None:
        while True:
            await asyncio.sleep(_REFRESH_INTERVAL_SECONDS)
            try:
                refreshed = await self.refresh_access_token()
            except Exception:
                log.exception("background token refresh failed")
                refreshed = False
            if not refreshed:
                log.warning("background token refresh stopped; session expired")
                return

    async def _refresh_access_token(self) -> bool:
        resp = await self._http.post("/api/auth/refresh")
        if resp.status_code == 401:
            self._clear_access_token()
            return False
        if resp.status_code >= 400:
            raise ApiError(resp.status_code, resp.text)
        data = resp.json()
        token = data.get("access_token")
        if not token:
            self._clear_access_token()
            return False
        self._access_token = token
        return True

    async def refresh_access_token(self) -> bool:
        """Refresh the access token via the server-managed refresh cookie."""
        task = self._refresh_task
        if task is None or task.done():
            task = asyncio.create_task(self._refresh_access_token())
            self._refresh_task = task
        try:
            refreshed = await task
            if refreshed and asyncio.current_task() is not self._refresh_loop_task:
                self._start_token_refresh()
            return refreshed
        finally:
            if self._refresh_task is task:
                self._refresh_task = None

    async def _send(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        return await self._http.request(
            method,
            path,
            json=json,
            params=params,
            headers=self._auth_headers(),
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        resp = await self._send(method, path, json=json, params=params)
        if resp.status_code == 401 and await self.refresh_access_token():
            resp = await self._send(method, path, json=json, params=params)
        if resp.status_code == 401:
            raise AuthError("unauthenticated")
        if resp.status_code >= 400:
            raise ApiError(resp.status_code, resp.text)
        if not resp.content:
            return None
        return resp.json()

    # -- auth -----------------------------------------------------------------

    async def login(self, username: str, password: str) -> dict[str, Any]:
        resp = await self._http.post(
            "/api/auth/login",
            json={"username": username, "password": password},
        )
        if resp.status_code == 401:
            raise AuthError("invalid credentials")
        if resp.status_code >= 400:
            raise ApiError(resp.status_code, resp.text)
        data = resp.json()
        self._access_token = data["access_token"]
        self._start_token_refresh()
        return data

    # -- home ------------------------------------------------------------------

    async def recently_added_albums(self, limit: int = 30) -> list[dict[str, Any]]:
        return await self._request(
            "GET", "/api/home/recently-added-albums", params={"limit": limit}
        )

    async def new_releases(self, limit: int = 30) -> list[dict[str, Any]]:
        return await self._request(
            "GET", "/api/home/new-releases", params={"limit": limit}
        )

    async def discover_artists(self, limit: int = 30) -> list[dict[str, Any]]:
        return await self._request(
            "GET", "/api/home/discover-artists", params={"limit": limit}
        )

    async def recently_played_albums(self, limit: int = 30) -> list[dict[str, Any]]:
        return await self._request(
            "GET", "/api/history/albums", params={"limit": limit}
        )

    async def recently_played_artists(self, limit: int = 30) -> list[dict[str, Any]]:
        return await self._request(
            "GET", "/api/history/artists", params={"limit": limit}
        )

    # -- playlists ------------------------------------------------------------

    async def list_playlists(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/api/playlists")

    async def get_playlist(self, playlist_id: int) -> dict[str, Any]:
        return await self._request("GET", f"/api/playlists/{playlist_id}")

    async def create_playlist(self, name: str) -> dict[str, Any]:
        return await self._request(
            "POST", "/api/playlists", json={"name": name}
        )

    async def update_playlist(
        self,
        playlist_id: int,
        *,
        name: str | None = None,
    ) -> None:
        body: dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        await self._request(
            "PUT", f"/api/playlists/{playlist_id}", json=body
        )

    async def delete_playlist(self, playlist_id: int) -> None:
        await self._request("DELETE", f"/api/playlists/{playlist_id}")

    async def add_tracks_to_playlist(
        self, playlist_id: int, track_ids: list[int]
    ) -> None:
        await self._request(
            "POST",
            f"/api/playlists/{playlist_id}/tracks",
            json={"track_ids": track_ids},
        )

    async def remove_track_from_playlist(
        self, playlist_id: int, playlist_track_id: int
    ) -> None:
        await self._request(
            "DELETE",
            f"/api/playlists/{playlist_id}/tracks/{playlist_track_id}",
        )

    async def reorder_playlist(
        self, playlist_id: int, ordering: list[int]
    ) -> None:
        await self._request(
            "POST",
            f"/api/playlists/{playlist_id}/reorder",
            json={"allowed_playlist_track_ids": ordering},
        )

    # -- library --------------------------------------------------------------

    async def album_tracks(
        self,
        *,
        album: str | None = None,
        artist: str | None = None,
        album_mbid: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if album_mbid:
            params["album_mbid"] = album_mbid
        if album:
            params["album"] = album
        if artist:
            params["artist"] = artist
        return await self._request("GET", "/api/tracks", params=params)

    async def artist_albums(self, artist_mbid: str) -> list[dict[str, Any]]:
        return await self._request(
            "GET", "/api/albums", params={"artist_mbid": artist_mbid}
        )

    async def artist_detail(self, mbid: str) -> dict[str, Any] | None:
        rows = await self._request("GET", "/api/artists", params={"mbid": mbid})
        if not rows:
            return None
        return rows[0]

    # -- artwork --------------------------------------------------------------

    async def fetch_art(self, sha1: str, *, max_size: int = 200) -> bytes:
        resp = await self._http.get(
            f"/api/art/file/{sha1}",
            params={"max_size": max_size},
        )
        if resp.status_code == 401:
            raise AuthError("unauthenticated")
        if resp.status_code >= 400:
            raise ApiError(resp.status_code, resp.text)
        return resp.content

    # -- search ---------------------------------------------------------------

    async def search(self, q: str) -> dict[str, list[dict[str, Any]]]:
        data = await self._request("GET", "/api/search", params={"q": q})
        return data or {"artists": [], "albums": [], "tracks": []}

    # -- streaming -------------------------------------------------------------

    async def stream_url(self, track_id: int) -> str:
        data = await self._request("GET", f"/api/stream-url/{track_id}")
        rel = data["url"]
        if rel.startswith("http://") or rel.startswith("https://"):
            return rel
        # Relative URL — but the server sometimes returns just a path. mpv
        # needs an absolute URL with the bearer-style stream token already
        # in the query string.
        return f"{self.base_url}{rel}"

    # -- player state (server-side history reporting) -------------------------

    @staticmethod
    def _track_for_server(track: dict[str, Any]) -> dict[str, Any]:
        """Project a track dict onto the fields the server's Track model accepts."""
        allowed = {
            "id",
            "title",
            "artist",
            "album",
            "duration_seconds",
            "art_sha1",
            "codec",
            "bit_depth",
            "sample_rate_hz",
            "artist_mbid",
            "album_mbid",
            "mb_release_id",
            "path",
            "album_artist",
            "track_no",
            "disc_no",
            "release_date",
            "bitrate",
            "plays",
            "artists",
        }
        out: dict[str, Any] = {}
        for k in allowed:
            if k in track and track[k] is not None:
                out[k] = track[k]
        # Server requires these as non-optional with sensible defaults.
        out.setdefault("title", "")
        out.setdefault("artist", "")
        out.setdefault("album", "")
        out.setdefault("duration_seconds", 0.0)
        return out

    async def set_player_queue(
        self, tracks: list[dict[str, Any]], start_index: int
    ) -> None:
        payload = {
            "queue": [self._track_for_server(t) for t in tracks],
            "start_index": start_index,
        }
        await self._request("POST", "/api/player/queue", json=payload)

    async def set_player_index(self, index: int) -> None:
        await self._request("POST", "/api/player/index", json={"index": index})

    async def reorder_player_queue(self, tracks: list[dict[str, Any]]) -> None:
        payload = {
            "queue": [self._track_for_server(t) for t in tracks],
            "start_index": 0,
        }
        await self._request("POST", "/api/player/queue/reorder", json=payload)

    async def clear_player_queue(self) -> None:
        await self._request("POST", "/api/player/queue/clear")

    async def player_state(self) -> dict[str, Any]:
        return await self._request("GET", "/api/player/state")

    async def pause_player(self) -> None:
        await self._request("POST", "/api/player/pause")

    async def resume_player(self) -> None:
        await self._request("POST", "/api/player/resume")

    async def seek_player(self, seconds: float) -> None:
        await self._request(
            "POST", "/api/player/seek", json={"seconds": float(seconds)}
        )

    async def set_player_volume(self, percent: int) -> None:
        await self._request(
            "POST", "/api/player/volume", json={"percent": int(percent)}
        )

    # -- renderers ------------------------------------------------------------

    async def list_renderers(self, *, refresh: bool = False) -> list[dict[str, Any]]:
        return await self._request(
            "GET", "/api/renderers", params={"refresh": "true"} if refresh else None
        )

    async def set_renderer(self, renderer_id: str) -> dict[str, Any]:
        return await self._request(
            "POST", "/api/player/renderer", json={"renderer_id": renderer_id}
        )

    async def update_progress(
        self, position_seconds: float, is_playing: bool
    ) -> None:
        await self._request(
            "POST",
            "/api/player/progress",
            json={
                "position_seconds": float(position_seconds),
                "is_playing": bool(is_playing),
            },
        )
