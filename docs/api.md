# API Map and Android Stage 0 Notes

This document records the Stage 0 API survey for the native Android and Android
Auto work described in [android.md](android.md).

The goal of Stage 0 is not to redesign Jamarr's API. It is to identify the
existing path from "logged in" to "play one track" and note any compatibility
gaps that might affect an Android Media3 prototype.

## Sources Reviewed

- `app/main.py`
- `app/api/deps.py`
- `app/api/auth.py`
- `app/api/stream.py`
- `app/api/search.py`
- `app/api/library.py`
- `app/media/art.py`
- `app/playlist.py`
- `app/api/player.py`
- `app/api/history.py`
- `app/api/charts.py`
- `app/api/recommendation.py`
- `app/api/scheduler.py`
- `app/api/media_quality.py`
- `web/src/lib/api/index.ts`
- `web/src/lib/stores/player.ts`
- `web/src/lib/components/PlayerBar.svelte`

## Stage 0 Conclusion

The existing API is enough to build a native Android phone playback prototype.

The smallest working path is:

1. `POST /api/auth/login`
2. `GET /api/search?q=<query>` or browse existing library endpoints
3. Select a returned `track.id`
4. `GET /api/stream-url/{track_id}`
5. Play the returned `/api/stream/{track_id}?token=...` URL with ExoPlayer

No backend change is required for Stage 1 unless the Android app finds a small
response-shape issue while implementing the prototype.

Android Auto may still need a small browse adapter later because the current
library endpoints are web-shaped and mostly unpaginated. That is Stage 4 in
`docs/android.md`, not a prerequisite for native playback.

## Authentication

Most API routes require a JWT access token:

```http
Authorization: Bearer <access_token>
```

`get_current_user_jwt` also accepts an access token in the query string as
`access_token=<jwt>`. The web UI uses this for EventSource endpoints. Android
should prefer the Authorization header except where a URL-only API requires a
query token.

Refresh tokens are stored in an HttpOnly cookie named `jamarr_refresh` by
default. The cookie path is `/api`. Refresh tokens rotate on refresh.

### `POST /api/auth/login`

Request:

```json
{
  "username": "alice",
  "password": "secret"
}
```

Response includes user fields plus:

```json
{
  "access_token": "<jwt>",
  "token_type": "bearer",
  "user": {
    "id": 1,
    "username": "alice",
    "email": "alice@example.com",
    "display_name": "Alice",
    "accent_color": "#ff006e",
    "theme_mode": "dark"
  }
}
```

Side effect: sets the refresh cookie.

### `POST /api/auth/refresh`

Uses the refresh cookie. Response:

```json
{
  "access_token": "<jwt>",
  "token_type": "bearer"
}
```

Side effect: revokes the previous refresh token and sets a new refresh cookie.

### Other Auth Routes

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/auth/signup` | Create a user, return access token, set refresh cookie |
| `POST` | `/api/auth/logout` | Revoke current refresh token and clear cookie |
| `POST` | `/api/auth/logout-all` | Revoke all refresh sessions for current user |
| `GET` | `/api/auth/me` | Return current user profile |
| `PUT` | `/api/auth/profile` | Update email/display name |
| `POST` | `/api/auth/password` | Change password |
| `PATCH` | `/api/auth/preferences` | Update accent/theme preferences |

## Streaming

Streaming already has the right shape for Android Media3.

### `GET /api/stream-url/{track_id}`

Requires JWT auth. Verifies the track exists and returns a short-lived stream
URL.

Response:

```json
{
  "url": "/api/stream/123?token=<stream_jwt>"
}
```

The stream token is bound to the track ID. Default TTL is controlled by
`STREAM_TOKEN_TTL_SECONDS`, currently defaulting to 300 seconds.

### `GET /api/stream/{track_id}?token=<stream_jwt>`

Serves the audio file. Accepts either:

- a valid stream token in the query string; or
- a valid JWT access token via Authorization header or `access_token` query
  parameter.

This endpoint returns a `FileResponse` with a guessed audio MIME type. Known
fallbacks include FLAC, MP3, M4A, WAV, and OGG.

Android should use `/api/stream-url/{track_id}` immediately before playback,
then give the returned URL to ExoPlayer.

## Artwork

Artwork routes are registered twice:

- `/art/...`
- `/api/art/...`

The current router has no auth dependency. The web UI generally uses
`/api/art/file/{sha1}`.

### `GET /api/art/file/{sha1}`

Query params:

| Param | Type | Purpose |
| --- | --- | --- |
| `max_size` | integer | Optional resize request. Snaps to 100, 200, 300, 400, or 600. |

Returns the artwork file, with long-lived cache headers and ETag support. If
`max_size` is set, resized JPEGs are cached under `cache/art/resized`.

### Other Artwork Routes

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/art/test` | Test JPEG for UPnP album art |
| `GET` | `/api/art/renderer/{udn}` | Renderer icon by UDN |

## Search

### `GET /api/search?q=<query>`

Requires JWT auth. Queries shorter than 2 characters return empty arrays.

Response:

```json
{
  "artists": [
    {
      "name": "Fleetwood Mac",
      "mbid": "...",
      "image_url": null,
      "art_sha1": "..."
    }
  ],
  "albums": [
    {
      "title": "Rumours",
      "artist": "Fleetwood Mac",
      "mbid": "...",
      "art_sha1": "..."
    }
  ],
  "tracks": [
    {
      "id": 123,
      "title": "Dreams",
      "artist": "Fleetwood Mac",
      "album": "Rumours",
      "mb_release_id": "...",
      "duration_seconds": 257.0,
      "art_sha1": "..."
    }
  ]
}
```

This is the easiest Stage 1 way to select one track for playback.

## Library Browse Endpoints

These routes require JWT auth.

### `GET /api/artists`

Query params:

| Param | Type | Purpose |
| --- | --- | --- |
| `limit` | integer | Present in signature, but the current unfiltered list path does not apply it. |
| `offset` | integer | Present in signature, but the current unfiltered list path does not apply it. |
| `name` | string | Exact-ish artist lookup by name |
| `mbid` | string | Artist lookup by MusicBrainz ID |
| `starts_with` | string | Filter by cached artist letter |

List response fields include:

- `mbid`
- `name`
- `sort_name`
- `bio`
- `art_sha1`
- `primary_album_count`
- `appears_on_album_count`

Single-artist lookups include heavier fields such as external links,
`top_tracks`, `most_listened`, `singles`, `genres`, and `background_sha1`.

Stage 0 caveat: unfiltered artist listing is not actually paginated at the
moment. That is acceptable for the phone prototype if search is used first, but
it is not ideal for Android Auto root browsing.

### `GET /api/artists/index`

Returns available artist index letters:

```json
["#", "A", "B", "C"]
```

### `GET /api/albums`

Query params:

| Param | Type | Purpose |
| --- | --- | --- |
| `artist` | string | Resolve artist name and list albums |
| `artist_mbid` | string | List albums for artist MBID |
| `album_mbid` | string | Return one album/release |

Response fields include:

- `album`
- `release_date`
- `release_type`
- `description`
- `peak_chart_position`
- `album_mbid`
- `mb_release_id`
- `type`
- `track_count`
- `total_duration`
- `is_hires`
- `label`
- `artist_name`
- `artists`
- `art_sha1`
- `external_links`
- `listens`

Stage 0 caveat: no pagination parameters are exposed.

### `GET /api/tracks`

Query params:

| Param | Type | Purpose |
| --- | --- | --- |
| `album` | string | Filter by album title |
| `artist` | string | Filter by artist name |
| `album_mbid` | string | Filter by release MBID or release-group MBID |

Response fields include:

- `id`
- `path`
- `title`
- `artist`
- `album`
- `album_artist`
- `track_no`
- `disc_no`
- `release_date`
- `duration_seconds`
- `codec`
- `sample_rate_hz`
- `bit_depth`
- `bitrate`
- `release_mbid`
- `release_group_mbid`
- `album_mbid`
- `art_sha1`
- `plays`
- `artists`
- `mb_release_id`
- `mb_release_group_id`

Stage 0 caveat: this endpoint should not be used as an unfiltered "all tracks"
root in Android Auto because it has no pagination.

### Home/Discovery Library Routes

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/home/new-releases?limit=20` | Recent releases by release date |
| `GET` | `/api/home/recently-added-albums?limit=20` | Recently imported albums |
| `GET` | `/api/home/discover-artists?limit=20` | Recently added artists |
| `GET` | `/api/artists/{mbid}/missing` | Missing albums for artist |
| `POST` | `/api/scan/missing` | Start missing-albums scan |
| `POST` | `/api/library/optimize` | Optimize DB |
| `POST` | `/api/download/pearlarr` | Queue a Pearlarr download |

## Playlists

Playlist routes require JWT auth. The playlist router is included twice in
`app/main.py`; this should not affect the Android prototype but is worth noting.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/playlists` | List current user's playlists |
| `POST` | `/api/playlists` | Create playlist |
| `GET` | `/api/playlists/{playlist_id}` | Playlist details and ordered tracks |
| `PUT` | `/api/playlists/{playlist_id}` | Update playlist metadata |
| `DELETE` | `/api/playlists/{playlist_id}` | Delete playlist |
| `POST` | `/api/playlists/{playlist_id}/tracks` | Add tracks |
| `DELETE` | `/api/playlists/{playlist_id}/tracks/{playlist_track_id}` | Remove one playlist track instance |
| `POST` | `/api/playlists/{playlist_id}/reorder` | Reorder tracks |
| `GET` | `/api/artists/{artist_mbid}/playlists` | Playlists containing an artist |

`GET /api/playlists/{playlist_id}` returns playlist metadata plus `tracks`.
Track objects include `track_id`, `title`, `artist`, `album`,
`duration_seconds`, `art_sha1`, codec fields, artist MBIDs, album MBIDs, and
playlist position.

## Player and Renderer API

These routes are designed for the current web UI and Jamarr's local/UPnP player
state. Android Auto should not use them for car playback in the first Android
work. Android should own playback through Media3.

They are still useful to document because the web UI depends on them.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/client-ip` | Resolve client IP |
| `GET` | `/api/player/state` | Current Jamarr renderer/player state |
| `POST` | `/api/player/queue` | Replace queue |
| `POST` | `/api/player/queue/append` | Append tracks |
| `POST` | `/api/player/queue/reorder` | Reorder queue |
| `POST` | `/api/player/queue/clear` | Clear queue |
| `POST` | `/api/player/index` | Set queue index |
| `POST` | `/api/player/log-play` | Backward-compatible no-op |
| `POST` | `/api/player/progress` | Update local renderer position and history threshold |
| `GET` | `/api/scan-status` | UPnP scan status |
| `GET` | `/api/renderers` | List local pseudo-renderer plus UPnP renderers |
| `POST` | `/api/player/renderer` | Set active renderer for a client |
| `POST` | `/api/player/play` | Start web/UPnP playback of one track |
| `POST` | `/api/player/pause` | Pause active renderer |
| `POST` | `/api/player/resume` | Resume active renderer |
| `POST` | `/api/player/volume` | Set renderer volume |
| `POST` | `/api/player/seek` | Seek active renderer |
| `GET` | `/api/player/debug` | Debug renderer/player state |
| `POST` | `/api/player/add_manual` | Add UPnP renderer by IP |
| `GET` | `/api/player/test_upnp` | UPnP debug endpoint |

Most player routes use `X-Jamarr-Client-Id` to separate browser/local renderer
state. Android Auto playback should avoid this state path initially.

## History

History routes require JWT auth.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/history/tracks` | Paginated playback history |
| `GET` | `/api/history/stats` | History stats for charting |
| `GET` | `/api/history/albums` | Top/recent albums |
| `GET` | `/api/history/artists` | Top/recent artists |

`/api/history/tracks` supports filters:

- `scope`
- `source`
- `artist_mbid`
- `album_mbid`
- `track_id`
- `from`
- `to`
- `page`
- `limit`

## Other Protected API Groups

These are not needed for the first Android playback prototype.

### Charts

Mounted as `/api/charts`.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/charts` | Current chart albums enriched with library state |
| `POST` | `/api/charts/refresh` | Refresh chart data |

### Recommendations

Mounted as `/api/recommendations`.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/recommendations/seeds?days=30` | Seed artists from listening history |
| `GET` | `/api/recommendations/artists?days=30` | Recommended artists |
| `GET` | `/api/recommendations/albums?days=30` | Recommended albums |
| `GET` | `/api/recommendations/tracks?days=30` | Recommended tracks |

### Media Quality

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/media-quality/items` | Filtered media quality/missing metadata item list |
| `GET` | `/api/media-quality/summary` | Summary stats for media quality UI |

### Scheduler

Mounted as `/api/scheduler`.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/scheduler/jobs` | List available job definitions |
| `GET` | `/api/scheduler/tasks` | List scheduled tasks |
| `POST` | `/api/scheduler/tasks` | Create task |
| `PATCH` | `/api/scheduler/tasks/{task_id}` | Update task |
| `DELETE` | `/api/scheduler/tasks/{task_id}` | Delete task |
| `POST` | `/api/scheduler/tasks/{task_id}/run` | Run task now |
| `POST` | `/api/scheduler/tasks/{task_id}/stop` | Stop running task |
| `GET` | `/api/scheduler/tasks/{task_id}/runs` | Recent task runs |

### Library Scanning

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/library/scan` | Start scan |
| `POST` | `/api/library/cancel` | Cancel scan |
| `GET` | `/api/library/status` | Scan status |
| `GET` | `/api/library/events` | SSE scan events |

### Last.fm

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/lastfm/status` | Integration status |
| `GET` | `/api/lastfm/auth/start` | Start Last.fm auth |
| `GET` | `/api/lastfm/callback` | Last.fm callback |
| `POST` | `/api/lastfm/disconnect` | Disconnect Last.fm |
| `POST` | `/api/lastfm/toggle` | Enable/disable integration |
| `POST` | `/api/lastfm/sync` | Start sync |
| `GET` | `/api/lastfm/events` | SSE sync events |

## Android Stage 1 Recommended Endpoint Path

Use search first. It avoids unpaginated root browsing and proves playback with
minimal moving parts.

```http
POST /api/auth/login
Authorization: none
Content-Type: application/json

{"username":"alice","password":"secret"}
```

Save `access_token` and keep the refresh cookie.

```http
GET /api/search?q=dreams
Authorization: Bearer <access_token>
```

Pick `tracks[0].id`.

```http
GET /api/stream-url/123
Authorization: Bearer <access_token>
```

Resolve the relative response URL against the configured Jamarr base URL and
pass it to ExoPlayer:

```text
https://jamarr.example.test/api/stream/123?token=<stream_jwt>
```

For artwork, if the selected track has `art_sha1`, load:

```http
GET /api/art/file/{art_sha1}?max_size=600
```

## Stage 0 Gaps and Risks

These are observations only. They are not required fixes before Stage 1.

1. The main library browse endpoints are not consistently paginated. This is
   the biggest reason Android Auto may eventually want a tiny `/api/android`
   browse adapter.
2. `/api/artists` exposes `limit` and `offset`, but the unfiltered list branch
   currently returns the whole artist list.
3. `/api/albums` and `/api/tracks` do not expose pagination.
4. Artwork routes are currently unauthenticated even though other docs describe
   authenticated artwork access. Android can use them as implemented, but this
   mismatch should be reviewed separately from Android work.
5. Player routes update Jamarr renderer state and are coupled to local browser
   and UPnP behavior. Android Auto should avoid them for playback and use
   Media3 instead.
6. The playlist router appears to be included twice in `app/main.py`. This is
   unrelated to Android, but it is worth cleaning up separately if it affects
   OpenAPI output or route duplication.

## Do Not Change Yet

Do not add these for Stage 1:

- `/api/android`
- `/api/mobile/v1`
- Android-specific queue persistence
- Android-specific playback history
- offline download endpoints
- new auth/session schema
- UPnP integration for Android Auto

The first proof should validate that existing Jamarr stream URLs play cleanly
through Android Media3.
