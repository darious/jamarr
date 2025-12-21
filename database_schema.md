# Database Schema

The application uses a SQLite database located at `cache/library.sqlite`.

## Tables

### `tracks`
Stores metadata for individual audio files.

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | INTEGER | Primary Key, Auto-incrementing ID. |
| `path` | TEXT | Absolute file path. Unique. |
| `mtime` | REAL | Last modification time of the file. |
| `title` | TEXT | Track title. |
| `artist` | TEXT | Artist name (from tags). |
| `album` | TEXT | Album name. |
| `album_artist` | TEXT | Album artist name. |
| `track_no` | INTEGER | Track number. |
| `disc_no` | INTEGER | Disc number. |
| `date` | TEXT | Release date (YYYY-MM-DD). |
| `genre` | TEXT | Genre. |
| `duration_seconds` | REAL | Duration in seconds. |
| `codec` | TEXT | Audio codec (e.g., 'mp3', 'flac'). |
| `sample_rate_hz` | INTEGER | Sample rate in Hz. |
| `bit_depth` | INTEGER | Bit depth (e.g., 16, 24). |
| `bitrate` | INTEGER | Bitrate in bps. |
| `channels` | INTEGER | Number of audio channels. |
| `label` | TEXT | Record label. |
| `mb_artist_id` | TEXT | MusicBrainz Artist ID. |
| `mb_album_artist_id` | TEXT | MusicBrainz Album Artist ID. |
| `mb_track_id` | TEXT | MusicBrainz Track ID. |
| `mb_release_track_id` | TEXT | MusicBrainz Release Track ID. |
| `mb_release_id` | TEXT | MusicBrainz Release ID. |
| `art_id` | INTEGER | Foreign Key referencing `artwork.id`. |

### `artists`
Stores rich metadata for artists, fetched from external sources (MusicBrainz, Spotify, etc.).

| Column | Type | Description |
| :--- | :--- | :--- |
| `mbid` | TEXT | Primary Key. MusicBrainz Artist ID. |
| `name` | TEXT | Artist name. |
| `sort_name` | TEXT | Sort name (e.g., "Beatles, The"). |
| `bio` | TEXT | Artist biography. |
| `image_url` | TEXT | URL to artist image (external reference). |
| `art_id` | INTEGER | Foreign Key referencing `artwork.id` for cached artist image. |
| `spotify_url` | TEXT | URL to Spotify artist page. |
| `homepage` | TEXT | Artist's homepage URL. |
| `similar_artists` | TEXT | JSON string of similar artists. |
| `top_tracks` | TEXT | JSON string of top tracks. |
| `last_updated` | REAL | Timestamp of last metadata update. |
| `wikipedia_url` | TEXT | URL to Wikipedia page. |
| `qobuz_url` | TEXT | URL to Qobuz artist page. |
| `musicbrainz_url` | TEXT | URL to MusicBrainz artist page. |
| `singles` | TEXT | JSON string of artist singles. |
| `albums` | TEXT | JSON string of artist albums. |

### `artwork`
Stores unique artwork to avoid duplication. Artwork files are organized in subdirectories based on the first 2 characters of the SHA1 hash.

**Storage Structure:**
- Album artwork: `cache/art/album/{sha1[:2]}/{sha1}`
- Artist images: `cache/art/artist/{sha1[:2]}/{sha1}`

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | INTEGER | Primary Key, Auto-incrementing ID. |
| `sha1` | TEXT | SHA1 hash of the image content. Unique. |
| `type` | TEXT | Type of artwork: 'album' or 'artist'. |
| `mime` | TEXT | MIME type of the image. |
| `width` | INTEGER | Image width in pixels. |
| `height` | INTEGER | Image height in pixels. |
| `path_on_disk` | TEXT | Path to the cached image file (optional/legacy). |

### `renderers`
Stores discovered UPnP/DLNA renderers.

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | INTEGER | Primary Key, Auto-incrementing ID. |
| `friendly_name` | TEXT | Display name of the device. |
| `udn` | TEXT | Unique Device Name (UUID). Unique. |
| `location_url` | TEXT | URL to the device description. |
| `last_seen` | REAL | Timestamp when the device was last seen. |
| `control_url` | TEXT | UPnP AVTransport control URL. |
| `rendering_control_url` | TEXT | UPnP RenderingControl URL. |
| `ip` | TEXT | IP address of the device. |

### `renderer_states`
Stores the current playback state for each renderer (local or UPnP). This allows persistent state and queue management.

| Column | Type | Description |
| :--- | :--- | :--- |
| `renderer_udn` | TEXT | Primary Key. UDN of the renderer. |
| `queue` | TEXT | JSON list of tracks in the queue. |
| `current_index` | INTEGER | Index of the currently playing track. |
| `position_seconds` | REAL | Last saved playback position. |
| `is_playing` | BOOLEAN | Whether playback is active. |
| `transport_state` | TEXT | UPnP Transport State (e.g., PLAYING, STOPPED). |
| `updated_at` | DATETIME | Timestamp of last update. |

### `client_sessions`
Maps client IDs to their active renderer UDN.

| Column | Type | Description |
| :--- | :--- | :--- |
| `client_id` | TEXT | Primary Key. UUID of the client. |
| `active_renderer_udn` | TEXT | UDN of the renderer the client is controlling. |
| `last_seen` | DATETIME | Timestamp of last activity. |

### `playback_state` (Deprecated)
*Legacy table, superseded by `renderer_states`.*
Singleton table (row id=1) storing the current playback status.

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | INTEGER | Primary Key. Always 1. |
| `queue` | TEXT | JSON list of tracks in the queue. |
| `current_index` | INTEGER | Index of the currently playing track. |
| `position_seconds` | REAL | Last saved playback position. |
| `is_playing` | BOOLEAN | Whether playback is active. |

### `playback_history`
Log of played tracks.

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | INTEGER | Primary Key. |
| `track_id` | INTEGER | Foreign Key referencing `tracks.id`. |
| `timestamp` | DATETIME | Time of playback. |
| `client_ip` | TEXT | IP address of the controller/client. |
| `hostname` | TEXT | Hostname of the controller. |

---

## Performance Tuning

### Indexes

**Integrity & Joins:**
- `idx_tracks_art_id` on `tracks(art_id)` - Fast artwork lookups
- `idx_tracks_mb_artist_id` on `tracks(mb_artist_id)` - Artist metadata joins

**Browsing (artist → album → tracks):**
- `idx_tracks_artist_album` on `tracks(artist COLLATE NOCASE, album COLLATE NOCASE, disc_no, track_no)` - Artist/album browsing
- `idx_tracks_album` on `tracks(album COLLATE NOCASE, disc_no, track_no)` - Album track ordering
- `idx_artists_name` on `artists(name COLLATE NOCASE)` - Artist list sorting

**Maintenance:**
- `idx_tracks_mtime` on `tracks(mtime)` - Recently added/changed tracks

### Full-Text Search (FTS5)

The `tracks_fts` virtual table provides fast full-text search across:
- `title`
- `artist`
- `album`
- `album_artist`

**Usage Example:**
```sql
-- Search for tracks matching "love"
SELECT t.* FROM tracks t
JOIN tracks_fts ON tracks_fts.rowid = t.id
WHERE tracks_fts MATCH 'love'
ORDER BY rank;
```
