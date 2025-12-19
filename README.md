# Jamarr

**Web-Based UPnP Music Controller**

Jamarr is an open-source, web-based music controller designed to scan a local music library, cache rich metadata, and play music to a Naim Uniti Atom (or other UPnP renderers) via a fast, responsive web UI.

## Features (Planned)
- Fast library scanning and metadata extraction (mutagen).
- Local SQLite cache for instant browsing.
- High-quality artwork support.
- UPnP Control Point for Naim Atom.
- Modern, responsive Web UI.

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

Ensure your `MUSIC_PATH` environment variable is set if your music is not in the default location, or update the path in `app/scanner/scan.py`.

## Project Structure

- `app/`: Backend application code (FastAPI).
- `web/`: Frontend assets (HTML/JS/CSS).
- `cache/`: Local database and artwork cache.
- `requirements.txt`: Python dependencies.
