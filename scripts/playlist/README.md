# Playlist Scripts

This directory contains tools for importing playlists and matching them against the local Jamarr library.

## ⚠️ Environment Setup

These scripts depend on the application configuration and require environment variables to be set.

We use `uv` to manage dependencies and run scripts. It can also handle loading the `.env` file for you.

### How to run

Run these scripts from the **project root directory** to ensure the `.env` file is accessible.

```bash
# General syntax
uv run --env-file .env scripts/playlist/<SCRIPT_NAME>.py <ARGS>
```

---

## Tools

### 1. Import Qobuz Playlist (`import_qobuz.py`)

Fetches tracks from a Qobuz playlist and matches them against your local library.

**Usage:**
```bash
uv run --env-file .env scripts/playlist/import_qobuz.py <PLAYLIST_URL_OR_ID> [options]
```

**Arguments:**
- `url`: Qobuz Playlist URL (e.g. `https://play.qobuz.com/playlist/123456`) or ID.
- `--output`, `-o`: Output file path (default: `qobuz_{id}.txt`).
- `--db-host`: Override database host.

**Example:**
```bash
uv run --env-file .env scripts/playlist/import_qobuz.py https://play.qobuz.com/playlist/1234567
```

**Prerequisites:**
- `QOBUZ_APP_ID` and `QOBUZ_SECRET` must be set in your `.env`.
- `QOBUZ_EMAIL` and `QOBUZ_PASSWORD` must be set in your `.env`.

### 2. Import Official Charts (`import_charts.py`)

Fetches "End of Year" singles charts from OfficialCharts.com and matches them against your local library.

**Usage:**
```bash
uv run --env-file .env scripts/playlist/import_charts.py <YEAR> [options]
```

**Arguments:**
- `year`: The year to fetch (e.g. `2024`).
- `--limit`: Number of tracks to process (default: 100).
- `--output`, `-o`: Output file path (default: `chart_{year}.txt`).
- `--db-host`: Override database host.

**Example:**
```bash
uv run --env-file .env scripts/playlist/import_charts.py 2024
```

### 3. Playlist Matcher (`playlist_matcher.py`)

This is a shared helper module used by the import scripts to perform the actual database matching. It is not intended to be run directly as a CLI tool.
