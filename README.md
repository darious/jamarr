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
- **Queue Persistence**: Playback state and queue are saved to the database, ensuring seamless resumption.

For a detailed system overview, see [Architecture & Outline](outline.md).
For database details, see [Database Schema](database_schema.md).

## Setup

### Prerequisites
- Python 3.9+
- `ffmpeg` (for `ffprobe`) - *Coming soon for scanning*

### Installation

1.  **Create a virtual environment:**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

2.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
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
- Node.js 20+
- `ffmpeg` (optional, for analysis)

### Backend
1.  Create venv: `python3 -m venv venv && source venv/bin/activate`
2.  Install: `pip install -r requirements.txt`
3.  Run: `uvicorn app.main:app --reload --host 0.0.0.0 --port 8111`

### Frontend
1.  Apps lives in `web/`.
2.  Install: `cd web && npm install`
3.  Run: `npm run dev -- --host 0.0.0.0 --port 4173`


### Running the Scanner

To scan your music library and populate the database (including fetching artist metadata from Spotify), run:

```bash
python scan.py
```

Options:
- `-v`: Verbose mode. Shows every file being scanned.
- `-vv`: Very verbose mode. Shows detailed API lookups and HTTP requests.
- `--force-metadata`: Force update of artist metadata.

Ensure your `MUSIC_PATH` environment variable is set if your music is not in the default location, or update the path in `app/scanner/scan.py`.

## Project Structure

- `app/`: Backend application code (FastAPI).
- `web/`: Frontend (SvelteKit + TypeScript + Skeleton UI).
- `cache/`: Local database and artwork cache.
  - `cache/library.sqlite`: SQLite database.
  - `cache/art/album/`: Album artwork organized in subdirectories (00-ff).
  - `cache/art/artist/`: Artist images organized in subdirectories (00-ff).
- `requirements.txt`: Python dependencies.

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
