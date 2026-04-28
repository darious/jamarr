# Jamarr - System Architecture

## Overview
Jamarr is a web-based music controller focused on fast library browsing and reliable playback across both local streaming and UPnP renderers (e.g., Naim Uniti Atom). It combines a Python/FastAPI backend for metadata, playback control, and enrichment with a modern SvelteKit frontend.

## Core Components

### 1. Backend (Python/FastAPI)
The backend is the brain of the operation, responsible for:
-   **Library Scanning**: Recursively scans the filesystem, extracts tags (mutagen), and caches metadata in PostgreSQL.
-   **Metadata Enrichment**: Uses a v3 pipeline architecture to fetch high-quality metadata (artist bios, images, album details, external links) from MusicBrainz, Wikidata, Last.fm, Fanart.tv, Spotify, and Qobuz. See [Scanner V3 Documentation](scanner_v3.md) for details.
-   **Playback & Streaming**: Issues short-lived stream URLs via `/api/stream-url/{track_id}` and streams local files from `/api/stream/{track_id}?token=...` while managing playback state for both local and UPnP renderers.
-   **UPnP Control**: Acts as a Control Point, managing playback state, volume, and queue for UPnP devices.
-   **Queue Management**: Maintains the active play queue and playback state in the database (`renderer_state`) to ensure persistence and reliability even if the frontend disconnects.
-   **Last.fm Integration**: Syncs scrobbles, matches them to local tracks, and merges them into playback history.
-   **Recommendations**: Generates artist/album/track recommendations from listening history and similarity data.
-   **Charts & Scheduling**: Stores chart data and runs scheduled jobs for background maintenance.
-   **API**: Exposes REST and streaming endpoints for the frontend.

### 2. Database (PostgreSQL)
A PostgreSQL database serves as the single source of truth for:
-   **Library**: Tracks, Artists, Albums, and Artwork.
-   **State**: Current queue, active renderer, and playback position per device.
-   **History**: Local playback history, Last.fm scrobbles, and a combined history view/materialized view.
-   **Search Index**: Full-text search and trigram indexes for fast browsing.
-   **Auxiliary Data**: Similar artists, top tracks, charts, and scheduler tasks.

The database runs in a Docker container on port 8110 and is accessible via `psql` or any PostgreSQL client.

### 3. Frontend (SvelteKit)
The frontend provides a polished, app-like user experience:
-   **Responsive UI**: Built with SvelteKit, Skeleton UI, and Tailwind CSS.
-   **Real-time State**: Polls the backend for playback status (position, track, transport state).
-   **Optimistic UI**: Updates the UI immediately on user actions while syncing with the backend.
-   **Renderer Switching**: Supports local playback via `<audio>` and remote playback via UPnP renderers.
-   **Visuals**: High-resolution artwork, themed UI, and smooth transitions.
-   **Artwork Access**: Artwork loads from authenticated `/api/art/*` endpoints with an access token.

## Key Workflows

### Library Scanning
1.  **Walk**: The scanner traverses the configured music directory.
2.  **Extract**: Reads tags (ID3, FLAC, Vorbis) and checks for changes via `mtime`.
3.  **Enrich**:
    -   Lookup artist metadata on MusicBrainz/Spotify.
    -   Download and cache artist images.
    -   Identify Tidal links.
4.  **Index**: Updates PostgreSQL tables and FTS/trigram search indexes.

### Playback & Queue
1.  **Selection**: User clicks "Play" or "Queue" on a track/album.
2.  **State Update**: Frontend sends the new queue to the Backend API.
3.  **Persistence**: Backend updates `renderer_state` table.
4.  **Control**:
    -   **Local**: Frontend requests `/api/stream-url/{track_id}` and then uses `<audio>` with `/api/stream/{track_id}?token=...`.
    -   **UPnP**: Backend sends `SetAVTransportURI` and `Play` commands to the device.
5.  **Monitoring**:
    -   Backend runs a background task to poll the UPnP device for position and transport state (`STOPPED`, `PLAYING`).
    -   **Auto-Advance**: When the backend detects the UPnP device has `STOPPED` (and queue has more tracks), it automatically initiates playback of the next track.

### History & Recommendations
1.  **Local History**: Backend logs playback into `playback_history`.
2.  **Last.fm Sync**: Scrobbles are pulled, matched to local tracks, and stored in `lastfm_scrobble_match`.
3.  **Unified View**: `combined_playback_history_mat` materializes local + Last.fm history.
4.  **Recommendations**: API reads the combined history view to produce seed and candidate recommendations.

## Directory Structure

```
├── app/                  # Python Backend
│   ├── api/              # FastAPI Routers (library, player, auth, etc.)
│   ├── scanner/          # Library Scanning Logic
│   │   ├── scan_manager.py  # Orchestrates scanning tasks
│   │   ├── core.py          # Core filesystem scanner
│   │   ├── stats.py         # Statistics tracker
│   │   ├── tags.py          # Tag extraction (mutagen)
│   │   ├── artwork.py       # Artwork resolution & migration
│   │   ├── dns_resolver.py  # DNS caching for API calls
│   │   ├── missing_scanner.py # Missing album detection
│   │   ├── album_helpers.py # Album grouping helpers
│   │   ├── similar_helpers.py # Similar artist matching
│   │   ├── utils.py         # Shared utilities
│   │   ├── pipeline/        # V3 pipeline architecture
│   │   │   ├── planner.py   # Enrichment planner
│   │   │   ├── executor.py  # Pipeline executor
│   │   │   ├── adapter.py   # Integration adapter
│   │   │   ├── models.py    # Data models
│   │   │   └── stages/      # Enrichment stages
│   │   └── services/        # External API clients
│   │       ├── musicbrainz.py
│   │       ├── lastfm.py
│   │       ├── artwork.py
│   │       └── wikidata.py
│   ├── services/         # Playback, UPnP, and state services
│   ├── media/            # Artwork helpers and image lookup
│   ├── models/           # Pydantic models
│   ├── matching/         # Last.fm scrobble matching
│   ├── main.py           # App entrypoint (FastAPI)
│   ├── db.py             # Database pool + init_db() schema seeder
│   ├── auth.py           # Authentication & user management
│   ├── auth_tokens.py    # JWT creation/verification
│   ├── security.py       # Security middleware & config
│   ├── logging_conf.py   # Logging configuration
│   ├── monitoring.py     # Production monitoring
│   ├── scheduler.py      # Background task scheduler
│   ├── upnp.py           # UPnP device discovery & control
│   ├── charts.py         # Chart data ingestion
│   └── lastfm.py         # Last.fm integration
├── web/                  # SvelteKit Frontend
│   ├── src/
│   │   ├── routes/       # Pages (Home, Artist, Queue, etc.)
│   │   ├── lib/          # Components, Stores, API helpers
│   └── static/           # Static assets
├── migrations/           # Versioned DB migration SQL files
├── tests/                # Backend test suite (pytest)
├── scripts/              # Utility and helper scripts
│   ├── artwork/          # Artwork tidying tools
│   ├── lastfm/           # Last.fm pull & review tools
│   ├── playlist/         # Playlist import/export
│   ├── sample/           # Chart sampling tools
│   ├── scanner/          # Scanner validation & debug
│   ├── backup.sh         # Manual database backup/restore
│   ├── db-reset.sh       # Database reset helper
│   ├── demo-jwt-auth.sh  # JWT auth demo
│   ├── demo-jwt.sh       # JWT token demo
│   ├── scanlog.sh        # Scan log viewer
│   ├── test-build.sh     # Frontend CI build check
│   └── test-ext-api.sh   # External API smoke tests
├── cache/                # App runtime cache (scanner state, artwork)
├── docs/                 # Documentation
│   ├── DEV_MODE.md       # Development setup guide
│   ├── DATABASE_SCHEMA.md # Database schema reference
│   ├── scanner_v3.md     # V3 pipeline architecture
│   ├── api.md            # API endpoint reference
│   ├── auth.md           # Authentication system
│   ├── android.md        # Android app documentation
│   ├── artwork-audit.md  # Artwork system audit
│   ├── plan-mobile.md    # Mobile development plan
│   ├── playlist--spec.md # Playlist feature spec (pre-implementation)
│   └── outline.md        # System architecture
├── docker-compose.yml    # Production Docker Compose
├── docker-compose.dev.yml # Development overrides
├── Dockerfile            # Production container build
├── dev.sh                # Development mode startup script
├── deploy.sh             # Production deploy (backup → migrate → restart)
└── config.yaml           # Application configuration
```

## Deployment & Operations

### Environments and Compose
- **Production**: `docker-compose.yml` with host networking. `HOST_IP` is provided via environment (defaults to 127.0.0.1 in Compose).
- **Development**: `docker-compose.yml` + `docker-compose.dev.yml` overrides; hot-reload for backend/frontend; local paths for cache/DB.
- **Testing**: `docker-compose.test.yml` with isolated project name (`jamarr-test`) to avoid clashing with dev/prod.

### Scripts
- `deploy.sh`: Full prod deploy. Steps: pull latest image, ensure DB is up, create pre-migration backup, run DB migrations (`docker compose run --rm jamarr python migrations/apply_migrations.py`), restart the app container.
- `dev.sh`: Starts dev stack with hot-reload; derives `HOST_IP` from an internal route if not provided.
- `test.sh`: Runs the test suite in Docker; brings up the test DB, runs pytest inside `jamarr_test_runner`, tears down the stack on success (leaves DB running on failure for debugging).
- `lint.sh [python|svelte|all]`: Runs Ruff and/or Svelte Check (Svelte via the dev Compose stack).

### Database Migrations
- Location: `migrations/*.sql`, ordered numerically (e.g., `001_*.sql`).
- Tracking: `schema_migration` table stores applied versions and checksums; runner will rename an old `schema_migrations` table if present.
- Runner: `migrations/apply_migrations.py` acquires a PostgreSQL advisory lock, validates checksums, and applies pending SQL files in order. Reads DB settings from environment (provided automatically inside the `jamarr` service by Compose).
- Idempotency: Migrations use `IF NOT EXISTS`/`IF EXISTS` guards or DO blocks so they can be re-run safely.
