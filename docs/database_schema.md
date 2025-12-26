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
| `mb_release_group_id` | TEXT | MusicBrainz Release Group ID. |
| `art_id` | INTEGER | Foreign Key referencing `artwork.id`. |

### `artists`
Stores rich metadata for artists, fetched from external sources (MusicBrainz, Spotify, etc.).
Normalized: External links, albums, and singles are now stored in separate tables.

| Column | Type | Description |
| :--- | :--- | :--- |
| `mbid` | TEXT | Primary Key. MusicBrainz Artist ID. |
| `name` | TEXT | Artist name. |
| `sort_name` | TEXT | Sort name (e.g., "Beatles, The"). |
| `bio` | TEXT | Artist biography. |
| `image_url` | TEXT | URL to artist image (external reference). |
| `art_id` | INTEGER | Foreign Key referencing `artwork.id` for cached artist image. |
| `last_updated` | REAL | Timestamp of last metadata update. |

### `albums`
Stores derived album information from MusicBrainz Release Groups.

| Column | Type | Description |
| :--- | :--- | :--- |
| `mbid` | TEXT | Primary Key. MusicBrainz Release Group ID. |
| `title` | TEXT | Album title. |
| `release_date` | TEXT | Release date. |
| `primary_type` | TEXT | Primary type (e.g., Album, EP, Single). |
| `secondary_types` | TEXT | Secondary types. |
| `art_id` | INTEGER | Foreign Key referencing `artwork.id`. |
| `last_updated` | REAL | Timestamp of last metadata update. |

### `artist_albums`
Junction table linking artists to albums (Many-to-Many).

| Column | Type | Description |
| :--- | :--- | :--- |
| `artist_mbid` | TEXT | Foreign Key `artists.mbid`. |
| `album_mbid` | TEXT | Foreign Key `albums.mbid`. |
| `type` | TEXT | Relationship type (e.g., 'primary', 'featured'). |

### `track_artists`
Junction table linking artists to individual tracks (Many-to-Many).

| Column | Type | Description |
| :--- | :--- | :--- |
| `track_id` | INTEGER | Foreign Key `tracks.id`. |
| `mbid` | TEXT | Foreign Key `artists.mbid`. |

### `external_links`
Stores URLs for Artists and Albums (e.g., Spotify, Tidal, Wikipedia).

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | INTEGER | Primary Key. |
| `entity_type` | TEXT | 'artist' or 'album'. |
| `entity_id` | TEXT | MBID of the entity. |
| `type` | TEXT | Link type ('spotify', 'tidal', 'qobuz', 'wikipedia', 'homepage'). |
| `url` | TEXT | The external URL. |

### `tracks_top`
Stores top tracks for artists (fetched from Spotify).

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | INTEGER | Primary Key. |
| `artist_mbid` | TEXT | Foreign Key `artists.mbid`. |
| `type` | TEXT | 'top' or 'single'. |
| `track_id` | INTEGER | Foreign Key `tracks.id` (if matched locally). |
| `external_name` | TEXT | Track name from external source. |
| `external_album` | TEXT | Album name from external source. |
| `external_date` | TEXT | Release date. |
| `external_duration_ms` | INTEGER | Duration in ms. |
| `external_mbid` | TEXT | External ID (e.g., Spotify ID). |
| `popularity` | INTEGER | Track popularity (0-100). |
| `rank` | INTEGER | Rank in the list. |
| `last_updated` | REAL | Timestamp of last update. |

### `similar_artists`
Stores similar artists data.

| Column | Type | Description |
| :--- | :--- | :--- |
| `artist_mbid` | TEXT | Source Artist MBID. |
| `similar_artist_name` | TEXT | Name of similar artist. |
| `similar_artist_mbid` | TEXT | MBID of similar artist (if known). |
| `rank` | INTEGER | Similarity rank. |
| `last_updated` | REAL | Timestamp of last update. |

### `artwork`
Stores unique artwork to avoid duplication. Artwork files are organized in subdirectories based on the first 2 characters of the SHA1 hash.

**Storage Structure:**
- All artwork: `cache/art/{sha1[:2]}/{sha1}`

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | INTEGER | Primary Key, Auto-incrementing ID. |
| `sha1` | TEXT | SHA1 hash of the image content. Unique. |
| `mime` | TEXT | MIME type of the image. |
| `width` | INTEGER | Image width in pixels. |
| `height` | INTEGER | Image height in pixels. |
| `path_on_disk` | TEXT | Path to the cached image file. |
| `filesize_bytes` | INTEGER | Cached file size. |
| `image_format` | TEXT | Image format reported by Pillow. |
| `source` | TEXT | Source provider for the artwork (e.g., 'fanart.tv'). |
| `source_url` | TEXT | Original URL the artwork was fetched from. |
| `checked_at` | REAL | Unix timestamp of last quality check. |
| `check_errors` | TEXT | JSON array of issue codes/details from the last check. |

### `image_mapping`
Maps artwork to entities and their semantic role.

| Column | Type | Description |
| :--- | :--- | :--- |
| `artwork_id` | INTEGER | Foreign Key referencing `artwork.id`. |
| `entity_type` | TEXT | One of 'artist', 'album', 'track'. |
| `entity_id` | TEXT | Identifier of the entity (MBID for artist/album, track id for track fallback). |
| `image_type` | TEXT | Role for the image (e.g., 'artistthumb', 'album'). |
| `score` | REAL | Optional score/rank (e.g., likes). |
| `created_at` | REAL | Timestamp when the mapping was created. |

### `renderers`
Stores discovered UPnP/DLNA renderers.

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | INTEGER | Primary Key, Auto-incrementing ID. |
| `friendly_name` | TEXT | Display name of the device. |
| `udn` | TEXT | Unique Device Name (UUID). Unique. |
| `location_url` | TEXT | URL to the device description. |
| `ip` | TEXT | IP address of the device. |
| `control_url` | TEXT | UPnP AVTransport control URL. |
| `rendering_control_url` | TEXT | UPnP RenderingControl URL. |
| `last_seen` | REAL | Timestamp when the device was last seen. |

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
| `volume` | INTEGER | Current volume level (0-100). |
| `updated_at` | DATETIME | Timestamp of last update. |

### `client_sessions`
Maps client IDs to their active renderer UDN.

| Column | Type | Description |
| :--- | :--- | :--- |
| `client_id` | TEXT | Primary Key. UUID of the client. |
| `active_renderer_udn` | TEXT | UDN of the renderer the client is controlling. |
| `last_seen` | DATETIME | Timestamp of last activity. |

### `artist_genres`
Stores genres associated with artists.

| Column | Type | Description |
| :--- | :--- | :--- |
| `artist_mbid` | TEXT | Foreign Key `artists.mbid`. |
| `genre` | TEXT | Genre name. |
| `count` | INTEGER | Vote count or weight for the genre. |
| `last_updated` | REAL | Timestamp of last update. |

### `missing_albums`
Stores albums found in MusicBrainz/Tidal that are missing from the local library.

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | INTEGER | Primary Key. |
| `artist_mbid` | TEXT | Foreign Key `artists.mbid`. |
| `release_group_mbid` | TEXT | MusicBrainz Release Group ID. |
| `title` | TEXT | Album title. |
| `release_date` | TEXT | Release date. |
| `primary_type` | TEXT | Album type. |
| `image_url` | TEXT | URL to album artwork. |
| `musicbrainz_url` | TEXT | Link to MusicBrainz. |
| `tidal_url` | TEXT | Link to Tidal. |
| `qobuz_url` | TEXT | Link to Qobuz. |
| `last_updated` | REAL | Timestamp of last update. |

### `users`
Stores user accounts for authentication.

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | INTEGER | Primary Key. |
| `username` | TEXT | Unique username. |
| `email` | TEXT | Unique email address. |
| `password_hash` | TEXT | Hashed password. |
| `display_name` | TEXT | Display name. |
| `created_at` | DATETIME | Creation timestamp. |
| `last_login` | DATETIME | Last login timestamp. |
| `is_active` | BOOLEAN | Account active status. |

### `sessions`
Stores active user sessions.

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | INTEGER | Primary Key. |
| `user_id` | INTEGER | Foreign Key `users.id`. |
| `token` | TEXT | Unique session token. |
| `created_at` | DATETIME | Creation timestamp. |
| `expires_at` | DATETIME | Expiration timestamp. |
| `user_agent` | TEXT | User agent string. |
| `ip` | TEXT | IP address. |

### `media_quality_issues`
Stores outstanding media quality findings across artwork, tracks, albums, and artists.

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | INTEGER | Primary Key. |
| `entity_type` | TEXT | Entity type (`artwork`, `track`, `album`, `artist`, `cache_file`). |
| `entity_id` | TEXT | Identifier for the entity (artwork id, track id, MBID, sha1). |
| `issue_code` | TEXT | Code for the detected issue. |
| `details` | TEXT | JSON payload with extra details. |
| `created_at` | REAL | Unix timestamp when issue was recorded. |
| `resolved_at` | REAL | Unix timestamp when issue was resolved (NULL if open). |

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
- `idx_tracks_art_id` on `tracks(art_id)`
- `idx_tracks_mb_artist_id` on `tracks(mb_artist_id)`
- `idx_links_entity` on `external_links(entity_type, entity_id)`
- `idx_tracks_top_artist` on `tracks_top(artist_mbid, type)`
- `idx_similar_artists_artist` on `similar_artists(artist_mbid)`

**Browsing:**
- `idx_tracks_artist_album` on `tracks(artist, album, disc_no, track_no)`
- `idx_tracks_album` on `tracks(album, disc_no, track_no)`
- `idx_artists_name` on `artists(name)`

**Maintenance:**
- `idx_tracks_mtime` on `tracks(mtime)`

### Full-Text Search (FTS5)
The `tracks_fts` virtual table provides fast full-text search across `title`, `artist`, `album`, and `album_artist`.
