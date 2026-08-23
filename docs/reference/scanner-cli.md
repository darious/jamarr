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

### `audio-analysis`

Decodes local audio with ffmpeg and stores per-track metrics in
`track_audio_analysis`. This is the data behind playback loudness
normalization — it is not produced by `scan` or `metadata`, and nothing runs it
automatically unless you schedule it (see
[Scanning a Library](../guides/scanning.md#scheduling-it)).

Phases:

| Phase | Produces |
|:---|:---|
| `1` | Loudness (LUFS), loudness range, sample peak, true peak, leading/trailing silence |
| `2` | Track ReplayGain, plus album ReplayGain once all of an album's tracks have current track ReplayGain |
| `3` | BPM estimate from decoded PCM |
| `4` | Derived playback/quality hints and local energy score |
| `all` | Runs 1 → 2 → 3 → 4 |

| Option | Description |
|:---|:---|
| `--phase <1\|2\|3\|4\|all>` | Phase to run (default: `1`) |
| `--batch-size <n>` | DB rows selected per batch (default: `audio_analysis.batch_size` in `config.yaml`, else 25) |
| `--concurrency <n>` | ffmpeg analyses run at once (default: `audio_analysis.concurrency`, else 2) |
| `--limit <n>` | Stop after this many tracks — use to chunk the first full-library run |
| `--track-id <id>` | Analyze one track by ID |
| `--path <path>` | Analyze one relative file path, or every track under a relative directory |
| `--force` | Re-analyze even when the cached analysis is current |
| `--dry-run` | List the tracks that would be selected; no ffmpeg, no writes |
| `--silence-threshold-db <db>` | Silence threshold in dBFS (default: -60) |
| `--silence-min-duration <s>` | Minimum silence duration in seconds (default: 0.2) |
| `--timeout <s>` | Per-track ffmpeg timeout (default: `audio_analysis.timeout_seconds`, else 600) |
| `--verbose` / `-v` | Enable detailed debug logging |

```bash
uv run python -m app.scanner.cli audio-analysis --phase all
uv run python -m app.scanner.cli audio-analysis --phase all --limit 500
uv run python -m app.scanner.cli audio-analysis --phase 1 --path "New Added" --force
```

Analysis is cached per track against `track_quick_hash` and the analysis
version, so re-runs skip tracks already current — the command is safe to repeat
and safe to interrupt. It shows a Rich progress bar with selected count, `x/y`,
percentage, elapsed time, and ETA.

## Architecture

For details on the v3 metadata pipeline architecture, see [Scanner Pipeline](../architecture/scanner-pipeline.md).
