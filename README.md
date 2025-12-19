# Jamarr

**Web-Based UPnP Music Controller**

Jamarr is an open-source, web-based music controller designed to scan a local music library, cache rich metadata, and play music to a Naim Uniti Atom (or other UPnP renderers) via a fast, responsive web UI.

## Features
- Fast library scanning and metadata extraction (mutagen).
- Local SQLite cache for instant browsing.
- **Organized artwork cache**: Separate subdirectories for album and artist artwork with SHA1-based distribution.
- **Artist image caching**: Downloads and caches artist images locally from Spotify.
- UPnP Control Point for Naim Atom and other renderers.
- Modern, responsive Web UI.
- **Refresh Metadata**: Targeted updates for artist information and external links.

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

## Running the Application

Start the backend server:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000`.

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
npm run dev -- --host
```

Build production assets (served by FastAPI from `web/build`):

```bash
cd web
npm run build
```

The FastAPI app is already configured to serve the built assets from `web/build`; rebuild whenever you change frontend code.
