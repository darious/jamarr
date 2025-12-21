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

### 2. Database (SQLite)
A local SQLite database (`cache/library.sqlite`) serves as the single source of truth for:
-   **Library**: Tracks, Artists, Albums, and Artwork.
-   **State**: Current queue, active renderer, and playback position per device.
-   **History**: Log of played tracks.
-   **Search Index**: FTS5 virtual tables for instant full-text search.

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
│   ├── upnp/             # UPnP Manager & Control Logic
│   ├── main.py           # App Entrypoint
│   └── db.py             # Database Models & Connection
├── web/                  # SvelteKit Frontend
│   ├── src/
│   │   ├── routes/       # Pages (Home, Artist, Queue, etc.)
│   │   ├── lib/          # Components, Stores, API helpers
│   └── static/           # Static assets
├── cache/                # Data Directory
│   ├── library.sqlite    # SQLite DB
│   └── art/              # Cached Images
└── docker-compose.yml    # Deployment Config
```
