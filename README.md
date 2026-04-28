# Jamarr

**Web-Based Music Controller**

Jamarr is an open-source, web-based music controller designed to scan a local music library, cache rich metadata, and play music locally or to UPnP renderers (e.g., Naim Uniti Atom) via a fast, responsive web UI.

It supports **gapless playback** (via UPnP queue management), **instant search**, **rich artist metadata** (biographies, images, similar artists), and **seamless deployment** via Docker.

## Features
- **Dockerized Deployment**: Reproducible stack via Docker Compose.
- **Local + UPnP Playback**: Local streaming via `/api/stream/{track_id}` and UPnP control (Play/Pause/Seek/Volume).
- **Rich Metadata**: Artist bios, images, similar artists, top tracks, and external links.
- **Fast Scanning**: Efficient library scan with incremental updates.
- **Modern UI**: Responsive SvelteKit interface with renderer switching.
- **History + Last.fm**: Local playback history plus matched Last.fm scrobbles.
- **Recommendations**: Artist/album/track recs derived from listening history.
- **Playlists**: Create and manage local playlists with ordering support.
- **Queue Persistence**: Playback state and queue are saved to PostgreSQL.

For a detailed system overview, see [Architecture & Outline](docs/outline.md).
For database details, see [Database Schema](docs/DATABASE_SCHEMA.md).

## License

Jamarr is licensed under the GNU Affero General Public License v3.0 only (`AGPL-3.0-only`). See [LICENSE](LICENSE).

Third-party dependencies, logos, service names, and trademarks remain under their own licenses and ownership. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Contributions are welcome under the same license. See [CONTRIBUTING.md](CONTRIBUTING.md) and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Setup

### Prerequisites
- Python 3.14+
- `uv` (fast Python package/dependency manager)
- Docker + Docker Compose (recommended for dev/prod workflows)

### Installation (Local API Only)

1.  **Install dependencies with uv (creates .venv):**
    ```bash
    uv sync
    ```

2.  **Run the API locally:**
    ```bash
    uv run uvicorn app.main:app --host 0.0.0.0 --port 8111
    ```

## Quick Start Helper Scripts

We provide helper scripts to simplify development, production, and testing workflows.

| Script | description |
| :--- | :--- |
| `./dev.sh` | Starts the stack in development mode (hot-reload enabled). |
| `./deploy.sh` | Full production deploy (backup → migrate → restart). |
| `./test.sh` | Runs backend tests in the Docker test stack. |
| `./scripts/test-build.sh` | Builds the frontend in a test container (CI-style). |
| `./scripts/test-ext-api.sh` | Runs external API smoke checks. |
| `./lint.sh [python|svelte|css|all]` | Runs Ruff and/or Svelte check. |

### Deployment & Migrations (tl;dr)
- `deploy.sh`: Full production deploy (backup → migrate → restart). Expects `HOST_IP` set.
- Migrations: Versioned SQL files in `migrations/` tracked via `schema_migration` table. Runner (`migrations/apply_migrations.py`) takes an advisory lock, checks checksums, and applies pending files in order. Runs inside the app container via `docker compose run --rm jamarr python migrations/apply_migrations.py`.
- `dev.sh`: Start dev stack with hot-reload and dev overrides.
- `init_db()` in `app/db.py`: Seeds a fresh database from scratch (dev setup, CI, new deployments). Uses `CREATE TABLE IF NOT EXISTS` for schema.
- Tests: `test.sh` runs the backend suite in an isolated Compose project and manages the test DB lifecycle (see `tests/TESTING.md`).
- Linting: `lint.sh [python|svelte|css|all]` runs Ruff and/or Svelte check.

## Deployment (Docker)

The recommended way to run Jamarr in production is via `deploy.sh` or Docker Compose.

1. **Configure Volumes**:
   Edit `docker-compose.yml` to point to your music library and set your server IP:
   ```yaml
   volumes:
     music:
       driver_opts:
         device: ":/path/to/your/music"
   environment:
     - HOST_IP=192.168.1.xxx  # Your server IP
   ```

2. **Build and Run**:
   ```bash
   ./deploy.sh
   # OR
   docker compose build && docker compose up -d
   ```

3. **Access**:
   Open `http://your-server-ip:8111`.

**Note**: The container uses `network_mode: "host"` to enable UPnP device discovery on your local network.

## Development Setup

For the best development experience, use the provided Docker Compose setup with hot-reload enabled for both frontend and backend.

### Quick Start

```bash
./dev.sh
```

This starts all services in development mode:
- **Backend API** (port 8111) - Auto-reloads on Python code changes
- **Frontend** (port 5173) - Vite HMR for instant updates
- **PostgreSQL** (port 8110) - Database

`dev.sh` auto-detects `HOST_IP` (or use `HOST_IP=... ./dev.sh`) and rebuilds if Python dependencies changed. See [Development Mode Guide](docs/DEV_MODE.md) for details.

### Manual Development (Without Docker)

If you prefer to run services manually:

#### Backend
1. Install deps: `uv sync`
2. Start PostgreSQL (or use Docker: `docker compose up jamarr_db -d`)
3. Run: `uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8111`

#### Frontend
1. Navigate to `web/`
2. Install: `npm install`
3. Run: `npm run dev:host`


### Running Tests

To run the full API test suite inside the Docker container:

```bash
./test.sh
```
    
Pass pytest arguments directly to the script:
```bash
./test.sh -v               # Verbose output
./test.sh -k "test_search" # Run only specific tests
```

See `tests/TESTING.md` for details on the test stack and troubleshooting.

### Linting

We provide a helper script to run linters for both the backend (Python/Ruff) and frontend (Svelte/Check).

```bash
./lint.sh         # Run all checks (Python, Svelte, CSS)
./lint.sh python  # Run only Python checks (ruff)
./lint.sh svelte  # Run only Svelte checks
./lint.sh css     # Run only CSS checks
```

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

## Scanner V3 Architecture

The metadata scanner uses a modern **v3 pipeline architecture** that provides:

- **Clean separation of concerns**: Each enrichment stage is independent and focused
- **Real-time statistics**: Live updates showing missing/searched/hits/misses for each stage
- **Automatic parallelization**: Independent stages run concurrently
- **Qobuz integration**: Automatic search fallback when links aren't in MusicBrainz/Wikidata
- **Testability**: 201 tests covering all components

**Key Components:**
1. **Enrichment Planner**: Analyzes artist state and determines which stages to run
2. **Pipeline Executor**: Executes stages in dependency order with parallelization
3. **8 Enrichment Stages**: Core Metadata, External Links, Artwork, Bio, Top Tracks, Similar Artists, Singles, Album Metadata
4. **Statistics Tracker**: Real-time metrics for each stage

For detailed architecture documentation, see [Scanner V3 Documentation](docs/scanner_v3.md).

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
    
    # Find artists with blank names (PostgreSQL)
    psql -h localhost -p 8110 -U jamarr -d jamarr -c "select mbid, name from artist where name is null or name = ''"
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

See `docs/DATABASE_SCHEMA.md` for the current table list, views, and indexes.

## Frontend (SvelteKit + Skeleton)

The web UI is built with SvelteKit, Skeleton UI, and Tailwind CSS.

### Development
Use the Docker Compose dev mode (see [Development Setup](#development-setup)) for the best experience with hot-reload.

### Production Build
The Dockerfile automatically builds the frontend and bundles it with the backend. To build manually:

```bash
cd web
npm install
npm run build
```

The FastAPI backend serves the built assets from `web/build`.
