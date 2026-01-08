# Scanner scripts

Utilities for validating the artist enrichment pipeline.

Use `uv run python scripts/scanner/<script>.py ...` for consistent deps.

## `validate-artist.py`

Runs the enrichment pipeline for a single artist without writing to the DB.

CLI options:
- `mbid`: Required. Artist MusicBrainz ID to validate.
- `--all`: Enable all enrichment options.
- `--missing-only`: Only fetch missing data.
- `--prod-scan`: Auto-enable dependencies when needed (e.g., bio needs metadata).
- `--metadata`: Fetch core metadata and links.
- `--artwork`: Fetch artwork.
- `--bio`: Fetch biography.
- `--top-tracks`: Fetch top tracks.
- `--similar`: Fetch similar artists.
- `--singles`: Fetch singles.
- `--albums`: Fetch album metadata.

Examples:
```bash
uv run python scripts/scanner/validate-artist.py b10bbbfc-cf9e-42e0-be17-e2c3e1d2600d --all
uv run python scripts/scanner/validate-artist.py b10bbbfc-cf9e-42e0-be17-e2c3e1d2600d --missing-only
uv run python scripts/scanner/validate-artist.py b10bbbfc-cf9e-42e0-be17-e2c3e1d2600d --metadata --artwork --bio
uv run python scripts/scanner/validate-artist.py b10bbbfc-cf9e-42e0-be17-e2c3e1d2600d --bio --prod-scan
```

## `validate-artist.sh`

Shell wrapper that loads `.env`, sets `PYTHONPATH`, and runs `validate-artist.py`.

CLI options:
- Pass-through. Accepts the same arguments as `validate-artist.py`.

Examples:
```bash
./scripts/scanner/validate-artist.sh b10bbbfc-cf9e-42e0-be17-e2c3e1d2600d --all
./scripts/scanner/validate-artist.sh b10bbbfc-cf9e-42e0-be17-e2c3e1d2600d --metadata --artwork --bio
```
