# Database Schema

The application uses a **PostgreSQL** database (running in Docker on port 8110).

## Extensions
- `citext`: Enabled for case-insensitive text matching (used for usernames, emails, artist names).

## Tables

### `track`
Stores metadata for individual audio files.

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | BIGSERIAL | Primary Key. |
| `path` | TEXT | Absolute file path. Unique, Not Null. |
| `updated_at` | TIMESTAMPTZ | Timestamp of last update. Default: NOW(). |
| `title` | TEXT | Track title. |
| `artist` | TEXT | Artist name (from tags). |
| `album` | TEXT | Album name. |
| `album_artist` | TEXT | Album artist name. |
| `track_no` | INTEGER | Track number. |
| `disc_no` | INTEGER | Disc number. |
| `date` | TEXT | Release date. |
| `genre` | TEXT | Genre. |
| `duration_seconds` | DOUBLE PRECISION | Duration in seconds. |
| `codec` | TEXT | Audio codec. |
| `sample_rate_hz` | INTEGER | Sample rate in Hz. |
| `bit_depth` | INTEGER | Bit depth. |
| `bitrate` | INTEGER | Bitrate in bps. |
| `channels` | INTEGER | Number of audio channels. |
| `label` | TEXT | Record label. |
| `artist_mbid` | TEXT | MusicBrainz Artist ID. |
| `album_artist_mbid` | TEXT | MusicBrainz Album Artist ID. |
| `track_mbid` | TEXT | MusicBrainz Track ID. |
| `release_track_mbid` | TEXT | MusicBrainz Release Track ID. |
| `release_mbid` | TEXT | MusicBrainz Release ID. |
| `release_group_mbid` | TEXT | MusicBrainz Release Group ID. |
| `artwork_id` | BIGINT | Foreign Key referencing `artwork.id`. |
| `fts_vector` | TSVECTOR | Full-text search vector (title, artist, album). |

### `artist`
Stores rich metadata for artists.

| Column | Type | Description |
| :--- | :--- | :--- |
| `mbid` | TEXT | Primary Key. MusicBrainz Artist ID. |
| `name` | CITEXT | Artist name (case-insensitive). |
| `sort_name` | TEXT | Sort name. |
| `bio` | TEXT | Artist biography. |
| `image_url` | TEXT | URL to external artist image. |
| `artwork_id` | BIGINT | Foreign Key referencing `artwork.id`. |
| `updated_at` | TIMESTAMPTZ | Timestamp of last update. |

### `album`
Stores derived album information.

| Column | Type | Description |
| :--- | :--- | :--- |
| `mbid` | TEXT | Primary Key. MusicBrainz Release Group ID. |
| `title` | TEXT | Album title. |
| `release_date` | TEXT | Release date. |
| `primary_type` | TEXT | Album type (e.g., Album, EP). |
| `secondary_types` | TEXT | Secondary types. |
| `artwork_id` | BIGINT | Foreign Key referencing `artwork.id`. |
| `updated_at` | TIMESTAMPTZ | Timestamp of last update. |

### `artist_album`
Junction table linking artists to albums.

| Column | Type | Description |
| :--- | :--- | :--- |
| `artist_mbid` | TEXT | Foreign Key `artist.mbid`. |
| `album_mbid` | TEXT | Foreign Key `album.mbid`. |
| `type` | TEXT | Relationship type. |

### `external_link`
Stores external URLs for entities.

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | BIGSERIAL | Primary Key. |
| `entity_type` | TEXT | 'artist' or 'album'. |
| `entity_id` | TEXT | MBID of the entity. |
| `type` | TEXT | Link type (e.g., spotify, tidal). |
| `url` | TEXT | The external URL. |

### `track_artist`
Junction table linking artists to tracks.

| Column | Type | Description |
| :--- | :--- | :--- |
| `track_id` | BIGINT | Foreign Key `track.id`. |
| `artist_mbid` | TEXT | Foreign Key `artist.mbid`. |

### `artwork`
Stores unique artwork files.

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | BIGSERIAL | Primary Key. |
| `sha1` | TEXT | SHA1 hash of image. Unique. |
| `type` | TEXT | Image type. |
| `mime` | TEXT | MIME type. |
| `width` | INTEGER | Width in pixels. |
| `height` | INTEGER | Height in pixels. |
| `path_on_disk` | TEXT | Path to file. |
| `filesize_bytes` | BIGINT | File size. |
| `image_format` | TEXT | Format (e.g., JPEG). |
| `source` | TEXT | Source provider. |
| `source_url` | TEXT | Original URL. |
| `checked_at` | TIMESTAMPTZ | Last check time. |
| `check_errors` | TEXT | JSON details of errors. |

### `image_map`
Maps artwork to entities.

| Column | Type | Description |
| :--- | :--- | :--- |
| `artwork_id` | BIGINT | Foreign Key `artwork.id`. |
| `entity_type` | TEXT | 'artist', 'album', 'track'. |
| `entity_id` | TEXT | Entity identifier. |
| `image_type` | TEXT | e.g., 'artistthumb'. |
| `score` | DOUBLE PRECISION | Score/Rank. |
| `created_at` | TIMESTAMPTZ | Creation time. |

### `renderer`
Stores discovered UPnP devices.

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | BIGSERIAL | Primary Key. |
| `friendly_name` | TEXT | Device name. |
| `udn` | TEXT | Unique Device Name. Unique. |
| `location_url` | TEXT | Device description URL. |
| `ip` | TEXT | Device IP. |
| `control_url` | TEXT | AVTransport URL. |
| `rendering_control_url` | TEXT | RenderingControl URL. |
| `supports_events` | BOOLEAN | If device supports UPnP events. |
| `supports_gapless` | BOOLEAN | If device supports gapless playback. |
| `supported_mime_types` | TEXT | List of supported MIME types. |
| `last_seen_at` | TIMESTAMPTZ | Last seen timestamp. |

### `renderer_state`
Current playback state for renderers.

| Column | Type | Description |
| :--- | :--- | :--- |
| `renderer_udn` | TEXT | Primary Key. |
| `queue` | TEXT | JSON queue. |
| `current_index` | INTEGER | Current track index. |
| `position_seconds` | DOUBLE PRECISION | Playback position. |
| `is_playing` | BOOLEAN | Playback status. |
| `transport_state` | TEXT | UPnP state (e.g., PLAYING). |
| `volume` | INTEGER | Volume (0-100). |
| `updated_at` | TIMESTAMPTZ | Last update. |

### `client_session`
Maps clients to active renderers.

| Column | Type | Description |
| :--- | :--- | :--- |
| `client_id` | TEXT | Primary Key. |
| `active_renderer_udn` | TEXT | Active renderer UDN. |
| `last_seen_at` | TIMESTAMPTZ | Last activity. |

### `playback_history`
Log of played tracks.

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | BIGSERIAL | Primary Key. |
| `track_id` | BIGINT | Foreign Key `track.id`. |
| `timestamp` | TIMESTAMPTZ | Playback time. |
| `client_ip` | TEXT | Client IP. |
| `hostname` | TEXT | Hostname. |
| `client_id` | TEXT | Client ID. |
| `user_id` | BIGINT | User ID. |

### `user`
User accounts.

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | BIGSERIAL | Primary Key. |
| `username` | CITEXT | Username (case-insensitive). Unique. |
| `email` | CITEXT | Email (case-insensitive). Unique. |
| `password_hash` | TEXT | Hashed password. |
| `display_name` | TEXT | Display name. |
| `created_at` | TIMESTAMPTZ | Creation time. |
| `last_login_at` | TIMESTAMPTZ | Last login. |
| `is_active` | BOOLEAN | Active status. |

### `session`
User sessions.

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | BIGSERIAL | Primary Key. |
| `user_id` | BIGINT | Foreign Key `user.id`. |
| `token` | TEXT | Session token. Unique. |
| `created_at` | TIMESTAMPTZ | Creation time. |
| `expires_at` | TIMESTAMPTZ | Expiration time. |
| `user_agent` | TEXT | User agent. |
| `ip` | TEXT | IP address. |

### `top_track`
Top tracks for artists.

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | BIGSERIAL | Primary Key. |
| `artist_mbid` | TEXT | Foreign Key `artist.mbid`. |
| `type` | TEXT | 'top' or 'single'. |
| `track_id` | BIGINT | Foreign Key `track.id` (optional). |
| `external_name` | TEXT | External track name. |
| `external_album` | TEXT | External album name. |
| `external_date` | TEXT | Release date. |
| `external_duration_ms` | INTEGER | Duration in ms. |
| `external_mbid` | TEXT | External ID. |
| `popularity` | INTEGER | 0-100. |
| `rank` | INTEGER | Rank. |
| `updated_at` | TIMESTAMPTZ | Last update. |

### `similar_artist`
Similar artists.

| Column | Type | Description |
| :--- | :--- | :--- |
| `artist_mbid` | TEXT | Source Artist MBID. |
| `similar_artist_name` | TEXT | Name of similar artist. |
| `similar_artist_mbid` | TEXT | MBID of similar artist. |
| `rank` | INTEGER | Rank. |
| `updated_at` | TIMESTAMPTZ | Last update. |

### `artist_genre`
Artist genres.

| Column | Type | Description |
| :--- | :--- | :--- |
| `artist_mbid` | TEXT | Foreign Key `artist.mbid`. |
| `genre` | TEXT | Genre. |
| `count` | INTEGER | Weight/Count. |
| `updated_at` | TIMESTAMPTZ | Last update. |

### `missing_album`
Missing albums from discography.

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | BIGSERIAL | Primary Key. |
| `artist_mbid` | TEXT | Foreign Key `artist.mbid`. |
| `release_group_mbid` | TEXT | Release Group MBID. |
| `title` | TEXT | Title. |
| `release_date` | TEXT | Date. |
| `primary_type` | TEXT | Type. |
| `image_url` | TEXT | Artwork URL. |
| `musicbrainz_url` | TEXT | MB URL. |
| `tidal_url` | TEXT | Tidal URL. |
| `qobuz_url` | TEXT | Qobuz URL. |
| `updated_at` | TIMESTAMPTZ | Last update. |

## Indexes

- **Full Text Search**: `idx_track_fts` (GIN on `track.fts_vector`).
- **Lookups**: `idx_session_token`, `idx_session_user`, `idx_track_artwork`, `idx_track_artist_mbid`.
- **Browsing**: `idx_track_nav` (`artist`, `album`, ...), `idx_track_album`, `idx_artist_name`.
- **Maintenance**: `idx_track_updated`.
- **Integrity**: Indexes on Foreign Keys and Join columns for performance.
