# Scripts

Command-line utilities for development, debugging, and operations.

Subfolders have their own READMEs:
- `scripts/lastfm/README.md` — Last.fm data pull & review
- `scripts/artwork/README.md` — Artwork tidying tools
- `scripts/scanner/README.md` — Scanner validation & debug
- `scripts/sample/README.md` — Chart sampling tools
- `scripts/playlist/README.md` — Playlist import/export

Use `uv run python scripts/<script>.py ...` for consistent deps.

## Shell scripts

| Script | Purpose |
|--------|---------|
| `backup.sh` | Manual database backup (`./backup.sh`) and restore (`./backup.sh restore <file>`) |
| `db-reset.sh` | Drop and recreate the dev database |
| `demo-jwt-auth.sh` | Demo the JWT auth flow (login, refresh, logout) |
| `demo-jwt.sh` | Generate and verify JWT tokens |
| `scanlog.sh` | Tail the scanner log |
| `test-build.sh` | Build the frontend in a CI-style Docker container |
| `test-ext-api.sh` | Smoke-test external API connectivity |

## Python scripts

### `check_spotify_rate_limit.py`
Checks Spotify API rate limit status using credentials from `app.config`.

```bash
uv run python scripts/check_spotify_rate_limit.py
```

### `test-ext-api.py`
Verifies external API connectivity using credentials from `.env`.

```bash
uv run python scripts/test-ext-api.py
```

### Debug utilities

| Script | Purpose |
|--------|---------|
| `debug_7day.py` | Inspect 7-day playback stats |
| `debug_all_users.py` | List all users |
| `debug_dates.py` | Inspect release dates in the library |
| `debug_eddie.py` | Artist-specific debug |
| `debug_recs.py` | Inspect recommendation data |
| `demo_jwt_phase1.py` | Phase 1 JWT auth demo |
| `test_calendar.py` | Calendar/release date utilities |
