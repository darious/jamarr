# Scripts

Command-line utilities. Subfolders have their own READMEs:

- `scripts/lastfm/README.md`
- `scripts/artwork/README.md`
- `scripts/scanner/README.md`
- `scripts/sample/README.md`

Use `uv run python scripts/<script>.py ...` for consistent deps.

## Top-level scripts

### `check_spotify_rate_limit.py`

Checks Spotify API rate limit status using credentials from `app.config`.

CLI options:
- None.

Example:
```bash
uv run python scripts/check_spotify_rate_limit.py
```

### `test-ext-api.py`

Verifies external API connectivity using credentials from `.env`.

CLI options:
- None.

Example:
```bash
uv run python scripts/test-ext-api.py
```
