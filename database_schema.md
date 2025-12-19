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
| `art_id` | INTEGER | Foreign Key referencing `artwork.id`. |

### `artists`
Stores rich metadata for artists, fetched from external sources (MusicBrainz, Spotify, etc.).

| Column | Type | Description |
| :--- | :--- | :--- |
| `mbid` | TEXT | Primary Key. MusicBrainz Artist ID. |
| `name` | TEXT | Artist name. |
| `sort_name` | TEXT | Sort name (e.g., "Beatles, The"). |
| `bio` | TEXT | Artist biography. |
| `image_url` | TEXT | URL to artist image. |
| `spotify_url` | TEXT | URL to Spotify artist page. |
| `homepage` | TEXT | Artist's homepage URL. |
| `similar_artists` | TEXT | JSON string of similar artists. |
| `top_tracks` | TEXT | JSON string of top tracks. |
| `last_updated` | REAL | Timestamp of last metadata update. |

### `artwork`
Stores unique artwork to avoid duplication.

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | INTEGER | Primary Key, Auto-incrementing ID. |
| `sha1` | TEXT | SHA1 hash of the image content. Unique. |
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
