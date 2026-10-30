# Install

Jamarr ships as a Docker image, `ghcr.io/darious/jamarr`, published per
[release](https://github.com/darious/jamarr/releases). A server needs three
files and no repository checkout: `docker-compose.yml`, `.env` and
`config.yaml`. All three are attached to every release and live at the top of
the repo. The container uses `network_mode: "host"` so UPnP and Chromecast
device discovery work.

## 1. Get the files

```bash
mkdir jamarr && cd jamarr
for f in docker-compose.yml .env.example config.yaml; do
  curl -fsSLO "https://raw.githubusercontent.com/darious/jamarr/main/$f"
done
cp .env.example .env
```

## 2. Configure

Edit `.env` and set the required values:

| Variable | Description |
|---|---|
| `HOST_IP` | Your server's LAN IP; renderers fetch streams and artwork from it |
| `MUSIC_NFS_ADDR` | NFS server address hosting your music library |
| `MUSIC_NFS_PATH` | NFS export path on the server |
| `DB_PASS` | PostgreSQL password; the stack refuses to start without one |
| `DB_DATA_PATH` | Host directory for PostgreSQL data |
| `CACHE_PATH` | Host directory for Jamarr cache |
| `JWT_SECRET_KEY` | Generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` | Spotify API credentials (metadata enrichment) |
| `LASTFM_API_KEY` / `LASTFM_SHARED_SECRET` | Last.fm API credentials (scrobbling) |

Optional metadata sources: `QOBUZ_*`, `TIDAL_*`, `FANARTTV_API_KEY`. Full list:
[Environment Variables](../reference/env-vars.md). Non-secret settings,
including per-renderer overrides, are in `config.yaml`
([Configuration](configuration.md)).

## 3. Start

```bash
docker compose pull && docker compose up -d
```

Database migrations apply when the app starts, so this is also the upgrade
command. To pin a version instead of `latest`, change the image tag in
`docker-compose.yml` (for example `ghcr.io/darious/jamarr:1.14.0`).

## 4. Scan your library

```bash
docker compose run --rm jamarr uv run python -m app.scanner.cli scan
docker compose run --rm jamarr uv run python -m app.scanner.cli metadata
```

Full command reference: [Scanner CLI](../reference/scanner-cli.md) ·
walkthrough: [Scanning a Library](../guides/scanning.md).

## 5. Open the UI

`http://your-server-ip:8111`

## Upgrading

```bash
docker compose pull && docker compose up -d
```

For a database dump before the upgrade, use `deploy.sh` from the release
assets in the same directory. It prunes unused images first (a full disk
otherwise makes the pull fail and leaves the old version running), pulls,
dumps the database to `./backups` keeping the last five, applies migrations,
and restarts. `BACKUP_DIR` and `BACKUP_KEEP` override the defaults.

A new release may change `docker-compose.yml` or add keys to `config.yaml`;
the release notes say so when it matters. Compare against the attached copies.

## Next steps

- Connect [Last.fm](../guides/lastfm.md) for scrobble history
- Set up [Dev Mode](dev-mode.md) for hot-reload development (this is where
  the repository checkout comes in)
- Review production [cookie/HTTPS hardening](../architecture/auth.md)
