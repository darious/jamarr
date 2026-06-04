# Install

Jamarr runs as a Docker Compose stack. The container uses
`network_mode: "host"` so UPnP and Chromecast device discovery work.

## 1. Configure

```bash
cp .env.example .env
```

Edit `.env` and set the required values:

| Variable | Description |
|---|---|
| `HOST_IP` | Your server's LAN IP (auto-detected by `deploy.sh` if left unset) |
| `MUSIC_NFS_ADDR` | NFS server address hosting your music library |
| `MUSIC_NFS_PATH` | NFS export path on the server |
| `DB_DATA_PATH` | Host directory for PostgreSQL data |
| `CACHE_PATH` | Host directory for Jamarr cache |
| `JWT_SECRET_KEY` | Generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` | Spotify API credentials (metadata enrichment) |
| `LASTFM_API_KEY` / `LASTFM_SHARED_SECRET` | Last.fm API credentials (scrobbling) |

Optional metadata sources: `QOBUZ_*`, `TIDAL_*`, `FANARTTV_API_KEY`. Full list:
[Environment Variables](../reference/env-vars.md).

## 2. Deploy

```bash
./deploy.sh
```

This pulls the latest image, backs up the database, runs migrations, then
restarts the stack.

## 3. Scan your library

```bash
docker compose run --rm jamarr uv run python -m app.scanner.cli scan
docker compose run --rm jamarr uv run python -m app.scanner.cli metadata
```

Full command reference: [Scanner CLI](../reference/scanner-cli.md) ·
walkthrough: [Scanning a Library](../guides/scanning.md).

## 4. Open the UI

`http://your-server-ip:8111`

## Next steps

- Connect [Last.fm](../guides/lastfm.md) for scrobble history
- Set up [Dev Mode](dev-mode.md) for hot-reload development
- Review production [cookie/HTTPS hardening](../architecture/auth.md)
