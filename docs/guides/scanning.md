# Scanning a Library

Jamarr ingests music in two phases: a fast tag scan, then external metadata
enrichment. Rationale: [ADR-0005](../architecture/decisions/0005-scanner-two-phase.md).
Full command/flag reference: [Scanner CLI](../reference/scanner-cli.md).

## First scan

In production, run inside the container:

```bash
docker compose run --rm jamarr uv run python -m app.scanner.cli scan
docker compose run --rm jamarr uv run python -m app.scanner.cli metadata
```

In a dev checkout you can run directly:

```bash
uv run python -m app.scanner.cli scan
uv run python -m app.scanner.cli metadata
```

1. **`scan`** walks `MUSIC_PATH`, reads tags, and creates tracks/artists/albums
   with MusicBrainz IDs. Fast — your library is browsable as soon as this
   finishes.
2. **`metadata`** fills bios, artwork, sort names, and external links from
   MusicBrainz/Spotify/etc. Only blank fields are filled; tag-based names are
   never overwritten. Multi-artist names that were blank after `scan` get
   resolved here.

## Common tasks

Scan one folder, forcing a full re-read:

```bash
uv run python -m app.scanner.cli scan --path "/music/New Added" --force
```

Re-enrich a single artist:

```bash
uv run python -m app.scanner.cli metadata --artist "Bear's Den"
uv run python -m app.scanner.cli metadata --mbid ef5aab86-887d-4fc2-a883-431ef017175a
```

Refresh only external links, or only bio + images:

```bash
uv run python -m app.scanner.cli metadata --links-only
uv run python -m app.scanner.cli metadata --bio-only
```

Remove orphans (files gone from disk, empty artists/albums, unused artwork):

```bash
uv run python -m app.scanner.cli prune
```

Everything at once (`scan` → `metadata` → `prune`):

```bash
uv run python -m app.scanner.cli full
```

Add `-v` / `--verbose` to any command for debug logging.

## Scanning from the UI/API

The web UI triggers scans via `POST /api/library/scan` and streams progress over
SSE (`GET /api/library/events`). These run the same pipeline as the CLI.
