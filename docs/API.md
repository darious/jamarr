# Jamarr API Documentation

Base URL: `/` (Relative to server root)

Auth: session cookie `jamarr_session`. Many player endpoints also expect `X-Jamarr-Client-Id` (unique per browser/device); if omitted it defaults to `unknown_client`.

## Authentication (`/api/auth`)

Authentication is cookie-based using `jamarr_session`.

### Signup
Create a new user account.

**POST** `/api/auth/signup`

**Body:** `application/json`
```json
{
  "username": "user",
  "email": "user@example.com",
  "password": "password123",
  "display_name": "User Name"
}
```

**Response:** `200 OK`
Returns user profile and sets `jamarr_session` cookie.
```json
{
  "id": 1,
  "username": "user",
  "email": "user@example.com",
  "display_name": "User Name",
  "created_at": "2023-01-01T12:00:00.000000",
  "last_login": "2023-01-01T12:00:00.000000"
}
```

**Curl:**
```bash
curl -X POST http://localhost:8000/api/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"username": "test", "email": "test@test.com", "password": "password", "display_name": "Test User"}'
```

### Login
Log in an existing user.

**POST** `/api/auth/login`

**Body:** `application/json`
```json
{
  "username": "user",
  "password": "password123"
}
```

**Response:** `200 OK`
Returns user profile and sets `jamarr_session` cookie.

**Curl:**
```bash
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "user", "password": "password"}' \
  -c cookies.txt
```

### Logout
Log out the current user.

**POST** `/api/auth/logout`

**Response:** `200 OK`
Clears `jamarr_session` cookie.
```json
{
  "ok": true
}
```

**Curl:**
```bash
curl -X POST http://localhost:8000/api/auth/logout -b cookies.txt
```

### Get Current User
Get details of the currently logged-in user.

**GET** `/api/auth/me`

**Response:** `200 OK`
```json
{
  "id": 1,
  "username": "user",
  "email": "user@example.com",
  "display_name": "User Name",
  "created_at": "...",
  "last_login": "..."
}
```

**Curl:**
```bash
curl http://localhost:8000/api/auth/me -b cookies.txt
```

### Update Profile
Update current user's profile.

**PUT** `/api/auth/profile`

**Body:** `application/json`
```json
{
  "email": "new@example.com",
  "display_name": "New Name"
}
```

**Response:** `200 OK`
Returns updated user profile.

**Curl:**
```bash
curl -X PUT http://localhost:8000/api/auth/profile \
  -H "Content-Type: application/json" \
  -d '{"email": "new@example.com", "display_name": "New Name"}' \
  -b cookies.txt
```

### Change Password
Change current user's password.

**POST** `/api/auth/password`

**Body:** `application/json`
```json
{
  "current_password": "oldpassword",
  "new_password": "newpassword"
}
```

**Response:** `200 OK`
```json
{
  "ok": true
}
```

## Library (`/api`)

### Get Artists
Retrieve a list of artists or details for a single artist.

**GET** `/api/artists`

**Parameters:**
- `limit` (int, default=1000): Number of results.
- `offset` (int, default=0): Offset for pagination.
- `name` (str, optional): Filter by artist name (exact match, case-insensitive).
- `mbid` (str, optional): Filter by MusicBrainz ID.
- `with_missing` (bool, optional): Include artists with missing/blank names.

**Response:** `200 OK`
List of artist objects.
```json
[
  {
    "mbid": "...",
    "name": "Artist Name",
    "sort_name": "Name, Artist",
    "image_url": "...",
    "primary_album_count": 5,
    "qobuz_url": "...",
    "musicbrainz_url": "...",
    "top_tracks": [ ... ] 
  }
]
```

**Curl:**
```bash
curl "http://localhost:8000/api/artists?limit=10"
```

### Get Albums
Retrieve a list of albums.

**GET** `/api/albums`

**Parameters:**
- `artist` (str, optional): Filter by artist name.
- `album_mbid` (str, optional): Filter by release group or release MBID.

**Response:** `200 OK`
List of album objects.
```json
[
  {
    "album": "Album Title",
    "artist_name": "Artist",
    "year": "2023",
    "track_count": 12,
    "release_type": "Album",
    "description": "Album description...",
    "peak_chart_position": 1,
    "art_id": 123
  }
]
```

**Curl:**
```bash
curl "http://localhost:8000/api/albums?artist=Taylor%20Swift"
```

### Get Tracks
Retrieve a list of tracks.

**GET** `/api/tracks`

**Parameters:**
- `album` (str, optional): Filter by album title.
- `artist` (str, optional): Filter by artist name.
- `album_mbid` (str, optional): Filter by album MBID.
- `limit` (int, optional) / `offset` (int, optional): Pagination.

**Response:** `200 OK`
List of track objects.

**Curl:**
```bash
curl "http://localhost:8000/api/tracks?album=Midnights"
```

### Missing Albums
Get a list of missing albums for an artist (albums they released but are not in the library).

**GET** `/api/artists/{mbid}/missing`

**Response:** `200 OK`
List of missing album details.

**Curl:**
```bash
curl "http://localhost:8000/api/artists/mbid-here/missing"
```

### Home Feeds
Various endpoints for the home page.

- **GET** `/api/home/new-releases`: Latest albums added.
- **GET** `/api/home/recently-added-albums`: Same as above (alias in logic?).
- **GET** `/api/home/recently-played-albums`: Albums played recently.
- **GET** `/api/home/recently-played-artists`: Artists played recently.
- **GET** `/api/home/discover-artists`: Random or specific discovery logic.

## Player (`/api/player`)

### Get Player State
Get current playback state.

**GET** `/api/player/state`

**Headers:**
- `X-Jamarr-Client-Id`: Unique client identifier.

**Response:** `200 OK`
```json
{
  "queue": [ ... ],
  "current_index": 0,
  "position_seconds": 12.5,
  "is_playing": true,
  "renderer": "local:client-123",
  "transport_state": "PLAYING",
  "volume": 100
}
```

**Curl:**
```bash
curl http://localhost:8000/api/player/state -H "X-Jamarr-Client-Id: my-web-client"
```

### Set Queue
Replace the current queue.

**POST** `/api/player/queue`

**Body:** `application/json`
```json
{
  "queue": [ { "id": 1, ... }, { "id": 2, ... } ],
  "start_index": 0
}
```

**Response:** `200 OK`
```json
{ "status": "ok" }
```

### Append to Queue
Add tracks to the end of the queue.

**POST** `/api/player/queue/append`

**Body:** `application/json`
```json
{
  "tracks": [ { "id": 3, ... } ]
}
```

### Set Active Renderer
Persist the active renderer for this client (UPnP or local browser).

**POST** `/api/player/renderer`

**Headers:** `X-Jamarr-Client-Id`

**Body:**
```json
{ "udn": "uuid:device-udn-or-local:<client-id>" }
```

**Response:** `200 OK`
```json
{ "active": "uuid:..." }
```

### List Renderers
Returns all known renderers plus the local placeholder.

**GET** `/api/renderers`
- `refresh` (bool, optional): Trigger UPnP discovery before returning results.

### Renderer Scan Status
**GET** `/api/scan-status`
Returns current UPnP scan status/logs for renderer discovery.

### Playback Controls
All require `X-Jamarr-Client-Id`.

- **POST** `/api/player/play` — Body: `{ "track_id": 123 }`
- **POST** `/api/player/pause`
- **POST** `/api/player/resume`
- **POST** `/api/player/seek` — Body: `{ "seconds": 42 }`
- **POST** `/api/player/volume` — Body: `{ "percent": 50 }`
- **POST** `/api/player/index` — Body: `{ "index": 1 }` (jump in queue)

### Set Index
Skip to a specific track index in the queue.

**POST** `/api/player/index`

**Body:** `application/json`
```json
{
  "index": 2
}
```

### Get History
Get playback history.

**GET** `/api/player/history`

**Parameters:**
- `scope`: `all` or `mine`.

### Get History Stats
Get listening statistics.

**GET** `/api/player/history/stats`

**Parameters:**
- `scope`: `all` or `mine`.
- `days`: Number of days to include (default 7).

### Progress / Logging
- **POST** `/api/player/progress` — `{ "position_seconds": <float>, "is_playing": true }` (logs play once thresholds are met)
- **POST** `/api/player/log-play` — Legacy manual log helper; accepts `{ "track_id": <id>, "timestamp": "ISO" }`

### Debug/UPnP Helpers
- **GET** `/api/player/debug` — Current queue/state snapshot.
- **POST** `/api/player/add_manual` — Add a manual renderer (for testing).
- **GET** `/api/player/test_upnp` — Simple UPnP connectivity test.

## Scanner (`/api/library`)

### Trigger Scan
Start a library scan.

**POST** `/api/library/scan`

**Body:** `application/json`
```json
{
  "type": "filesystem", // 'filesystem', 'metadata', 'full', 'prune'
  "path": "/music/New", // Optional
  "force": false
}
```

**Options for metadata/full runs:**
- `missing_only` (bool): Only fill gaps.
- `artist_filter` / `mbid_filter`: Limit to specific artist(s).
- `fetch_metadata` / `fetch_bio` / `fetch_artwork` / `fetch_spotify_artwork` / `fetch_links` (bools)
- `refresh_top_tracks` / `refresh_singles` / `fetch_similar_artists` (bools)

**Curl:**
```bash
curl -X POST http://localhost:8000/api/library/scan \
  -H "Content-Type: application/json" \
  -d '{"type": "filesystem"}'
```

### Cancel Scan
Stop running scan.

**POST** `/api/library/cancel`

### Scan Status
Get current scanner status.

**GET** `/api/library/status`

### Scan Events
Listen for realtime scan updates via SSE.

**GET** `/api/library/events`

### Scan Missing Albums
Trigger a scan for missing albums (gaps in discography).

**POST** `/api/scan/missing`

**Parameters:**
- `artist` (str, optional): Filter by artist name.
- `mbid` (str, optional): Filter by artist MBID.

### Optimize Database
Run database maintenance tasks (VACUUM, ANALYZE).

**POST** `/api/library/optimize`

## Playlists (`/api/playlists`)

### List Playlists
Get all playlists for the current user.

**GET** `/api/playlists`

**Response:**
```json
[
  {
    "id": 1,
    "name": "My Playlist",
    "track_count": 10,
    "thumbnails": ["sha1...", "sha1..."]
  }
]
```

### Get Playlist
Get detailed playlist info and tracks.

**GET** `/api/playlists/{id}`

### Create Playlist
**POST** `/api/playlists`
Body: `{ "name": "New Playlist", "description": "Optional" }`

### Update Playlist
**PUT** `/api/playlists/{id}`
Body: `{ "name": "Updated Name", "is_public": true }`

### Add Tracks
**POST** `/api/playlists/{id}/tracks`
Body: `{ "track_ids": [1, 2, 3] }`

### Remove Track
**DELETE** `/api/playlists/{id}/tracks/{playlist_track_id}`

### Reorder Tracks
Atomic reorder of tracks.
**POST** `/api/playlists/{id}/reorder`
Body: `{ "allowed_playlist_track_ids": [3, 1, 2] }`


## Search (`/api/search`)

### Global Search
Search for artists, albums, and tracks.

**GET** `/api/search`

**Parameters:**
- `q`: Search query.

**Response:** `200 OK`
```json
{
  "artists": [ ... ],
  "albums": [ ... ],
  "tracks": [ ... ]
}
```

**Curl:**
```bash
curl "http://localhost:8000/api/search?q=pink"
```

## Stream (`/api/stream`)

### Stream Track
Stream audio file for a track.

**GET** `/api/stream/{track_id}`

**Response:** Binary stream (audio/flac, audio/mp3, etc.). Supports `Range` headers for seeking. `HEAD` returns headers only. 

**Curl:**
```bash
curl -O http://localhost:8000/api/stream/123
```

## Media (`/api/art`)

### Get Artwork
Get artwork image, optionally resized.

**GET** `/api/art/{artwork_id}`
**GET** `/api/art/{artwork_id}.jpg`
**GET** `/api/art/file/{sha1}`

**Parameters:**
- `max_size` (int): Max width/height in pixels.

**Response:** Binary image (image/jpeg).

## Media Quality (`/api/media-quality`)

### Get Summary
Get statistics about library media quality (metadata, artwork, etc.).

**GET** `/api/media-quality/summary`

**Response:** `200 OK`
Returns summary statistics for artists (all and primary) and albums.
```json
{
  "artist_stats": {
    "all": { "total": 100, "with_background": 50, "sources": { ... }, "link_stats": { ... } },
    "primary": { "total": 20, "with_background": 15, ... }
  },
  "album_stats": {
    "total": 50,
    "with_artwork": 45,
    "link_stats": { ... }
  }
}
```

### Get Items
Get a list of items matching a specific quality filter.

**GET** `/api/media-quality/items`

**Parameters:**
- `category`: `artist`, `primary` (primary artist), or `album`.
- `filter_type`: Filter logic to apply (`total`, `background`, `artwork`, `source`, `link_type`, `missing_link_type`).
- `filter_value` (optional): Specific value for the filter (e.g. `Fanart`, `spotify`).

**Response:** `200 OK`
List of item summaries.
```json
[
  {
    "name": "Album Name",
    "artist_name": "Artist Name",
    "sort_name": "Artist, Name",
    "mbid": "...",
    "image_url": "..."
  }
]
```
