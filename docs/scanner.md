# Scanner CLI

Jamarr includes a CLI to manage the library and metadata.

```bash
uv run python -m app.scanner.cli <command> [options]
```

## Workflow

The scanner uses a two-phase approach:

1. **`scan`**: Extracts metadata directly from file tags (artist names, album titles, track info, MusicBrainz IDs)
2. **`metadata`**: Enriches the database with additional data from MusicBrainz/Spotify (bios, artwork, sort names, external links)

This separation ensures fast initial scans while allowing rich metadata to be fetched on-demand.

## Commands

### `scan`

Scans the filesystem for music files and adds them to the library.

- Extracts all tag data: title, artist, album, track numbers, MusicBrainz IDs
- Populates artist names for single-artist tracks
- Creates album records from release group IDs in tags
- Multi-artist collaborations will have blank names (filled by `metadata` command)

| Option | Description |
|:---|:---|
| `--path <path>` | Scan a specific directory (default: `MUSIC_PATH` from config) |
| `--force` | Force a full rescan of all files, even if unchanged |
| `--verbose` / `-v` | Enable detailed debug logging |

```bash
uv run python -m app.scanner.cli scan -v
uv run python -m app.scanner.cli scan --path "/music/New Added" --force
```

### `metadata`

Fetches artist/album metadata from MusicBrainz & Spotify.

- Fills in missing artist names (e.g., for multi-artist collaborations)
- Populates `sort_name` for all artists
- Fetches bios, images, and external links (Spotify, Tidal, Qobuz, Wikipedia)
- Only updates blank fields — never overwrites tag-based names

| Option | Description |
|:---|:---|
| `--artist <name>` | Filter to update only artists matching this name |
| `--mbid <id>` | Filter to update only a specific artist by MusicBrainz ID |
| `--links-only` | Only update external links without fetching bio/images |
| `--bio-only` | Only update bio & images |
| `--verbose` / `-v` | Enable detailed debug logging |

```bash
uv run python -m app.scanner.cli metadata -v
uv run python -m app.scanner.cli metadata --artist "Bear's Den"
uv run python -m app.scanner.cli metadata --mbid ef5aab86-887d-4fc2-a883-431ef017175a
```

### `prune`

Cleans up orphaned data: removes DB entries for files no longer on disk, artists/albums with no remaining tracks, and unused cached artwork.

```bash
uv run python -m app.scanner.cli prune
```

### `full`

Runs `scan` followed by `metadata` then `prune`.

```bash
uv run python -m app.scanner.cli full
```

## Architecture

For details on the v3 metadata pipeline architecture, see [Scanner V3 Documentation](scanner_v3.md).
