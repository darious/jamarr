# Scripts

Command-line utilities. Subfolders have their own READMEs:

- `scripts/lastfm/README.md`
- `scripts/artwork/README.md`
- `scripts/scanner/README.md`
- `scripts/sample/README.md`

Use `uv run python scripts/<script>.py ...` for consistent deps.

## Top-level scripts

### `apply_migrations.py`

Applies all SQL migrations in `scripts/migrations/` using asyncpg and tracks them in `schema_migration`.

CLI options:
- None. Requires DB env vars: `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASS`, `DB_NAME`.

Example:
```bash
uv run python scripts/apply_migrations.py
```

### `check_migrations.py`

Prints applied migrations and lists pending SQL migration files.

CLI options:
- None. Uses the same DB env vars as `apply_migrations.py`.

Example:
```bash
uv run python scripts/check_migrations.py
```

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
