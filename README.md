# Jamarr

**Web-Based UPnP Music Controller**

Jamarr is an open-source, web-based music controller designed to scan a local music library, cache rich metadata, and play music to a Naim Uniti Atom (or other UPnP renderers) via a fast, responsive web UI.

It supports **gapless playback** (via UPnP queue management), **instant search**, **rich artist metadata** (biographies, images, similar artists), and **seamless deployment** via Docker.

## Features
- **Dockerized Deployment**: Single-container setup via Docker Compose.
- **UPnP Control**: Play/Pause, Next, Seek, and Volume control for network players.
- **Rich Metadata**: Auto-fetches artist bios, images, and similar artists from Spotify/MusicBrainz.
- **Fast Scanning**: efficiently scans large libraries with local caching.
- **Modern UI**: Dark-themed, responsive SvelteKit interface.
- **Playback History**: Tracks listening history for both local and remote playback.
- **Tidal Integration**: Links artists and albums to Tidal for external playback.
- **Top Tracks & Similar Artists**: Fetches and stores popular tracks and related artists.
- **Queue Persistence**: Playback state and queue are saved to the database, ensuring seamless resumption.

For a detailed system overview, see [Architecture & Outline](outline.md).
For database details, see [Database Schema](database_schema.md).

## Setup

### Prerequisites
- Python 3.12+
- `uv` (fast Python package/dependency manager)
- `ffmpeg` (for `ffprobe`) - *Required for scanning and analysis*

### Installation

1.  **Install dependencies with uv (creates .venv):**
    ```bash
    uv sync
    ```

2.  **Run the API locally:**
    ```bash
    uv run uvicorn app.main:app --host 0.0.0.0 --port 8111
    ```

## Deployment (Docker)

The recommended way to run Jamarr is via Docker Compose.

1.  **Configure Volumes**:
    Edit `docker-compose.yml` to point to your music library:
    ```yaml
    volumes:
      - /path/to/your/music:/app/music
      - ./cache:/app/cache
    ```

2.  **Run**:
    ```bash
    docker-compose up --build -d
    ```

3.  **Access**:
    Open `http://localhost:8111`.

**Note**: The container uses `network_mode: "host"` to enable UPnP device discovery on your local network.

## Development Setup

### Prerequisites
- Python 3.12+
- `uv`
- Node.js 20+
- `ffmpeg` (optional, for analysis)

### Backend
1.  Install deps: `uv sync`
2.  Run (auto-uses the uv-managed `.venv`): `uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8111`

### Frontend
1.  Apps lives in `web/`.
2.  Install: `cd web && npm install`
3.  Run: `npm run dev -- --host 0.0.0.0 --port 4173`


### Running the Scanner (CLI)

Jamarr includes a powerful CLI to manage the library and metadata.

**Basic Usage:**
```bash
uv run python -m app.scanner.cli <command> [options]
```

## Workflow Overview

The scanner uses a two-phase approach:

1. **`scan`**: Extracts metadata directly from file tags (artist names, album titles, track info, MusicBrainz IDs)
2. **`metadata`**: Enriches the database with additional data from MusicBrainz/Spotify (bios, artwork, sort names, external links)

This separation ensures fast initial scans while allowing rich metadata to be fetched on-demand.

**Commands:**

1.  **`scan`**: Scans the filesystem for music files and adds them to the library.
    *   Extracts all tag data: title, artist, album, track numbers, MusicBrainz IDs
    *   Populates artist names for single-artist tracks
    *   Creates album records from release group IDs in tags
    *   Multi-artist collaborations will have blank names (filled by `metadata` command)
    
    **Options:**
    *   `--path <path>`: Scan a specific directory (default: `MUSIC_PATH` from config)
    *   `--force`: Force a full rescan of all files, even if unchanged
    *   `--verbose` (`-v`): Enable detailed debug logging
    
    **Examples:**
    ```bash
    # Standard scan
    uv run python -m app.scanner.cli scan -v
    
    # Force rescan specific folder
    uv run python -m app.scanner.cli scan --path "/music/New Added" --force
    ```

2.  **`metadata`**: Fetches artist/album metadata from MusicBrainz & Spotify.
    *   Fills in missing artist names (e.g., for multi-artist collaborations)
    *   Populates `sort_name` for all artists (e.g., "Sheeran, Ed")
    *   Fetches bios, images, and external links (Spotify, Tidal, Qobuz, Wikipedia)
    *   **Only updates blank fields** - never overwrites tag-based names
    
    **Options:**
    *   `--artist <name>`: Filter to update only artists matching this name
    *   `--mbid <id>`: Filter to update only a specific artist by MusicBrainz ID
    *   `--links-only`: Only update external links (Tidal/Qobuz/Wiki) without fetching bio/images
    *   `--bio-only`: Only update bio & images (skips Album/Single fetch & Link Resolution)
    *   `--verbose` (`-v`): Enable detailed debug logging (shows API calls)

    **Examples:**
    ```bash
    # Update all metadata (recommended after first scan)
    uv run python -m app.scanner.cli metadata -v
    
    # Update specific artist by name
    uv run python -m app.scanner.cli metadata --artist "Bear's Den"
    
    # Update specific artist by MusicBrainz ID (useful for blank names)
    uv run python -m app.scanner.cli metadata --mbid ef5aab86-887d-4fc2-a883-431ef017175a
    
    # Find artists with blank names
    sqlite3 cache/library.sqlite "select mbid, name from artists where name is null or name = ''"
    ```

3.  **`prune`**: Cleans up the library by removing orphaned data.
    *   Removes database entries for files no longer on disk
    *   Removes Artists/Albums that have no remaining tracks
    *   Removes cached artwork files that are no longer used
    *   *Safe to run periodically to keep the database tidy*

    **Example:**
    ```bash
    uv run python -m app.scanner.cli prune
    ```

4.  **`full`**: Runs `scan` followed immediately by `metadata` and then `prune`.
    *   Equivalent to running all three commands sequentially
    
    **Example:**
    ```bash
    uv run python -m app.scanner.cli full
    ```

## Typical Workflow

```bash
# 1. Initial scan - populates tracks, albums, and single-artist names from tags
uv run python -m app.scanner.cli scan

# 2. Enrich with metadata - fills in missing names, sort names, bios, artwork
uv run python -m app.scanner.cli metadata

# 3. (Optional) Clean up orphaned data
uv run python -m app.scanner.cli prune
```

## Database Schema

The database has been normalized to improve data integrity and query performance.

### Core Tables
-   **`tracks`**: Individual audio files.
    -   Joined to `albums` via `mb_release_group_id`.
    -   Joined to `artists` via `track_artists` table (multi-artist support).
-   **`albums`**: Release groups (Albums, EPs, Singles).
    -   Stores `title`, `release_date`, `primary_type`.
    -   Source: MusicBrainz Release Group.
-   **`artists`**: Artist core info.
    -   Stores `name`, `bio`, `image_url` (path to cached artwork).
    -   Source: MusicBrainz (ID) & Spotify (Bio/Image).

### Junction & Helper Tables
-   **`artist_albums`**: Links artists to albums (Many-to-Many).
-   **`track_artists`**: Links artists to tracks (Many-to-Many).
-   **`external_links`**: Stores URLs for Artists and Albums.
    -   Types: `spotify`, `tidal`, `qobuz`, `wikipedia`, `homepage`.
    -   Supports prioritized link resolution (e.g., matching Digital Media releases).
-   **`artwork`**: Deduplicated artwork storage.
    -   Images stored by SHA1 hash to prevent duplicates.

### State Management
-   **`renderers`**: UPnP devices discovered on the network.
-   **`renderer_states`**: Current playback status (queue, position, volume) for each renderer.
-   **`client_sessions`**: Tracks active user sessions and their selected renderer.
-   **`playback_history`**: Log of all played tracks.

## Frontend (SvelteKit + Skeleton)

The web UI now lives in a SvelteKit app with Skeleton UI and Tailwind.

Install and run the frontend in dev mode:

```bash
cd web
npm install
npm run dev -- --host 0.0.0.0 --port 4173
```

Build production assets (served by FastAPI from `web/build`):

```bash
cd web
npm run build
```

The FastAPI app is already configured to serve the built assets from `web/build`; rebuild whenever you change frontend code.
