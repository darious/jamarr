# Jamarr

**Self-hosted web-based music controller.**

Scan a local music library, enrich it with metadata from MusicBrainz and Spotify, then browse and play music through a fast web UI. Supports local playback and UPnP renderers (e.g., Naim Uniti Atom) with gapless queue management.

## Features

- **Library scanning** — fast tag-based scan with incremental updates and MusicBrainz ID extraction
- **Rich metadata** — artist bios, artwork, similar artists, top tracks, and external links
- **Local + UPnP playback** — local streaming and UPnP control (play/pause/seek/volume)
- **Gapless playback** — via UPnP SetNextAVTransportURI queue management
- **Instant search** — across artists, albums, and tracks
- **History + Last.fm** — local playback history with matched Last.fm scrobbles
- **Recommendations** — artist/album/track recommendations from listening history
- **Playlists** — create and manage playlists with ordering support
- **Modern UI** — responsive SvelteKit interface with renderer switching

## Quick Start

### 1. Configure

```bash
cp .env.example .env
```

Edit `.env` and set the required values:

| Variable | Description |
|:---|:---|
| `HOST_IP` | Your server's LAN IP (auto-detected by `deploy.sh` if left unset) |
| `MUSIC_NFS_ADDR` | NFS server address hosting your music library |
| `MUSIC_NFS_PATH` | NFS export path on the server |
| `DB_DATA_PATH` | Host directory for PostgreSQL data |
| `CACHE_PATH` | Host directory for Jamarr cache |
| `JWT_SECRET_KEY` | Generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` | Spotify API credentials (for metadata enrichment) |
| `LASTFM_API_KEY` / `LASTFM_SHARED_SECRET` | Last.fm API credentials (for scrobbling) |

Optional API keys for additional metadata sources: `QOBUZ_*`, `TIDAL_*`, `FANARTTV_API_KEY`.

Non-secret app config (MusicBrainz URL, logging, concurrency) lives in `config.yaml`.

### 2. Deploy

```bash
./deploy.sh
```

This pulls the latest image, backs up the database, runs migrations, and restarts the stack. The container uses `network_mode: "host"` for UPnP device discovery.

### 3. Scan your library

```bash
docker compose run --rm jamarr uv run python -m app.scanner.cli scan
docker compose run --rm jamarr uv run python -m app.scanner.cli metadata
```

See [Scanner CLI](docs/scanner.md) for full command reference.

### 4. Open the UI

`http://your-server-ip:8111`

## Documentation

| Document | Description |
|:---|:---|
| [Architecture & Outline](docs/outline.md) | System overview and design |
| [Database Schema](docs/DATABASE_SCHEMA.md) | Tables, views, and indexes |
| [Scanner CLI](docs/scanner.md) | Library scanning and metadata enrichment |
| [API](docs/api.md) | API endpoints |
| [Auth](docs/auth.md) | Authentication and JWT |
| [Dev Mode](docs/DEV_MODE.md) | Development with hot-reload |
| [Contributing](CONTRIBUTING.md) | Development setup, tests, linting |

## License

Jamarr is licensed under the GNU Affero General Public License v3.0 only (`AGPL-3.0-only`). See [LICENSE](LICENSE).

Third-party dependencies, logos, service names, and trademarks remain under their own licenses. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
