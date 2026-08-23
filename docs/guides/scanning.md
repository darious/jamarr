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

## Audio analysis (loudness, ReplayGain, BPM)

Tag scans never open the audio itself. A second, separate pass decodes each file
with ffmpeg and stores the results in `track_audio_analysis` — this is what
feeds playback loudness normalization, so **until a track has been analysed it
plays back un-normalized**.

Run every phase (in production):

```bash
docker compose run --rm jamarr uv run python -m app.scanner.cli audio-analysis --phase all
```

Phases, in order:

| Phase | Produces |
|:---|:---|
| `1` | Loudness (LUFS), loudness range, sample peak, true peak, leading/trailing silence |
| `2` | Track ReplayGain via ffmpeg, plus album ReplayGain once every track on an album has current track ReplayGain |
| `3` | BPM estimate from decoded PCM |
| `4` | Derived playback/quality hints and a local energy score |

Loudness normalization only needs phase 1 (phase 2 adds album-mode gain), so
`--phase 1` is enough if that is all you are after.

The first full-library run is long — it decodes every file. Chunk it and repeat
until nothing is selected:

```bash
docker compose run --rm jamarr uv run python -m app.scanner.cli audio-analysis --phase all --limit 500
```

Results are cached per track against `track_quick_hash` and the analysis
version, so re-runs skip anything already current and only pick up new or
changed files. That makes the command safe to repeat and safe to interrupt.

Full flag list: [Scanner CLI → `audio-analysis`](../reference/scanner-cli.md#audio-analysis).

### Scheduling it

The pass is **not** automatic — nothing triggers it after a library scan. To
keep it current, add a schedule in the web UI under **Settings → Scheduler**
using the **Audio Analysis (All Phases)** job, which runs phases 1–4 over
whatever still needs them. A nightly cron after your scan job works well.

Tuning lives in `config.yaml` (both the CLI and the scheduled job read it):

```yaml
audio_analysis:
  batch_size: 25 # DB rows selected per batch
  concurrency: 2 # ffmpeg analyses run at once
  timeout_seconds: 600 # per-track ffmpeg timeout
```

`concurrency` is the one to raise on a machine with spare cores — analysis is
ffmpeg-bound. Progress is logged (throttled to once a minute per phase) to the
app log, and each phase logs its final counts.

## Scanning from the UI/API

The web UI triggers scans via `POST /api/library/scan` and streams progress over
SSE (`GET /api/library/events`). These run the same pipeline as the CLI.
