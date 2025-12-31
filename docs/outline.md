# Jamarr - System Architecture

## Overview
Jamarr is a web-based music controller designed to provide a rich, fast, and reliable music playback experience, primarily targeting UPnP renderers like the Naim Uniti Atom. It combines a robust Python backend for metadata management and playback control with a modern, responsive SvelteKit frontend.

## Core Components

### 1. Backend (Python/FastAPI)
The backend is the brain of the operation, responsible for:
-   **Library Scanning**: Recursively scans the filesystem, extracts tags (mutagen), and caches metadata in SQLite.
-   **Metadata Enrichment**: Fetches high-quality metadata (artist bios, images, album details) from MusicBrainz and Spotify.
-   **UPnP Control**: Acts as a Control Point, managing playback state, volume, and queue for UPnP devices.
-   **Queue Management**: Maintains the active play queue and playback state in the database (`renderer_states`) to ensure persistence and reliability even if the frontend disconnects.
-   **Tidal Integration**: Maps local artists/albums to Tidal URLs for external listening.
-   **API**: Exposes REST endpoints for the frontend.

### 2. Database (PostgreSQL)
A PostgreSQL database serves as the single source of truth for:
-   **Library**: Tracks, Artists, Albums, and Artwork.
-   **State**: Current queue, active renderer, and playback position per device.
-   **History**: Log of played tracks.
-   **Search Index**: Full-text search capabilities.

The database runs in a Docker container and is accessible via CloudBeaver for administration.

### 3. Frontend (SvelteKit)
The frontend provides a polished, app-like user experience:
-   **Responsive UI**: Built with SvelteKit, Skeleton UI, and Tailwind CSS.
-   **Real-time State**: Polls the backend for playback status (position, track, transport state).
-   **Optimistic UI**: Updates the UI immediately on user actions while syncing with the backend.
-   **Visuals**: high-resolution artwork, dark mode, and smooth transitions.

## Key Workflows

### Library Scanning
1.  **Walk**: The scanner traverses the configured music directory.
2.  **Extract**: Reads tags (ID3, FLAC, Vorbis) and checks for changes via `mtime`.
3.  **Enrich**:
    -   Lookup artist metadata on MusicBrainz/Spotify.
    -   Download and cache artist images.
    -   Identify Tidal links.
4.  **Index**: Updates SQLite tables and FTS search index.

### Playback & Queue
1.  **Selection**: User clicks "Play" or "Queue" on a track/album.
2.  **State Update**: Frontend sends the new queue to the Backend API.
3.  **Persistence**: Backend updates `renderer_states` table.
4.  **Control**:
    -   **Local**: Frontend uses `<audio>` element to play the stream.
    -   **UPnP**: Backend sends `SetAVTransportURI` and `Play` commands to the device.
5.  **Monitoring**:
    -   Backend runs a background task to poll the UPnP device for position and transport state (`STOPPED`, `PLAYING`).
    -   **Auto-Advance**: When the backend detects the UPnP device has `STOPPED` (and queue has more tracks), it automatically initiates playback of the next track.

## Directory Structure

```
├── app/                  # Python Backend
│   ├── api/              # FastAPI Routers (library, player, etc.)
│   ├── scanner/          # Library Scanning Logic
│   │   ├── cli.py        # CLI Entrypoint
│   │   ├── scan_manager.py # Orchestrates scanning tasks
│   │   ├── core.py       # Core Scanner Logic
│   │   ├── metadata.py   # Metadata Fetching (MusicBrainz/Spotify)
│   │   └── tags.py       # Tag Extraction
│   ├── upnp/             # UPnP Manager & Control Logic
│   ├── main.py           # App Entrypoint
│   ├── db.py             # Database Models & Connection
│   ├── auth.py           # Authentication & User Management
│   └── tidal.py          # Tidal Integration Helper
├── web/                  # SvelteKit Frontend
│   ├── src/
│   │   ├── routes/       # Pages (Home, Artist, Queue, etc.)
│   │   ├── lib/          # Components, Stores, API helpers
│   └── static/           # Static assets
├── cache/                # Data Directory (PostgreSQL data, cached images)
├── docs/                 # Documentation
│   ├── DEV_MODE.md       # Development setup guide
│   ├── database_schema.md # Database schema reference
│   └── outline.md        # System architecture
├── docker-compose.yml    # Production Docker Compose
├── docker-compose.dev.yml # Development overrides
├── Dockerfile            # Production container build
├── dev.sh                # Development mode startup script
├── prod.sh               # Production startup (no migrations)
├── update.sh             # Production deploy (git pull + build + migrations + restart)
└── config.yaml           # Application configuration
```

## Deployment & Operations

### Environments and Compose
- **Production**: `docker-compose.yml` with host networking. `HOST_IP` is provided via environment (defaults to 127.0.0.1 in Compose).
- **Development**: `docker-compose.yml` + `docker-compose.dev.yml` overrides; hot-reload for backend/frontend; local paths for cache/DB.
- **Testing**: `docker-compose.test.yml` with isolated project name (`jamarr-test`) to avoid clashing with dev/prod.

### Scripts
- `prod.sh`: Builds and starts the prod stack (no migration step).
- `dev.sh`: Starts dev stack with hot-reload; derives `HOST_IP` from an internal route if not provided.
- `update.sh`: Full prod deploy. Steps: stop app container, `git pull --rebase`, ensure DB is up, build app image, run DB migrations (`docker compose run --rm jamarr python scripts/apply_migrations.py`), then start the app container.
- `test.sh`: Runs the test suite in Docker; brings up the test DB, runs pytest inside `jamarr_test_runner`, tears down the stack on success (leaves DB running on failure for debugging).
- `test-slow.sh`: Delegates to `test.sh -m "slow"` with the same lifecycle and project isolation.
- `lint.sh [python|svelte|all]`: Runs Ruff and/or Svelte Check (Svelte via the dev Compose stack).

### Database Migrations
- Location: `scripts/migrations/*.sql`, ordered numerically (e.g., `001_*.sql`).
- Tracking: `schema_migration` table stores applied versions and checksums; runner will rename an old `schema_migrations` table if present.
- Runner: `scripts/apply_migrations.py` acquires a PostgreSQL advisory lock, validates checksums, and applies pending SQL files in order. Reads DB settings from environment (provided automatically inside the `jamarr` service by Compose).
- Idempotency: Migrations use `IF NOT EXISTS`/`IF EXISTS` guards or DO blocks so they can be re-run safely.
