# Artwork scripts

Utilities for fetching, converting, and repairing album artwork.

Use `uv run python scripts/artwork/<script>.py ...` to ensure consistent deps.

## `album_art.py`

Exports JPG/JPEG/PNG images to JPEG, scales to a max of 2800px, and deletes the originals.

CLI options:
- `path`: Required. File or directory to scan for images.

Examples:
```bash
uv run python scripts/artwork/album_art.py /music/artwork
uv run python scripts/artwork/album_art.py /music/artwork/cover.png
```

## `fetch_art.py`

Fetches cover art for a MusicBrainz release and writes a processed JPEG.

CLI options:
- `mbid`: Required. MusicBrainz release ID.

Examples:
```bash
uv run python scripts/artwork/fetch_art.py 1f3b8a53-9b5b-4c5b-9c2b-5b3b4d4e2a72
```

## `fix_art.py`

Scans FLAC files for oversized embedded art and optionally rewrites it.

CLI options:
- `path`: Required. File or directory to scan for FLAC files.
- `--size`: Max pixel size for embedded art (default: 2800).
- `--apply`: Write changes (default is dry-run).

Examples:
```bash
uv run python scripts/artwork/fix_art.py /music/flac
uv run python scripts/artwork/fix_art.py /music/flac --size 2400 --apply
```

## Notes

- MusicBrainz base URL is resolved from `config.yaml` when available.
