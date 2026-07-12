# Environment Variables

Secrets and per-deployment settings live in `.env` (copy from `.env.example`).
Non-secret app config (MusicBrainz URL, logging, concurrency) lives in
`config.yaml`.

!!! note
    This table mirrors `.env.example`. When you add a variable there, add it here
    too — or point readers at `.env.example` as the source of truth.

## Environment

| Variable | Default | Description |
|---|---|---|
| `ENV` | `development` | `development` or `production` |

## App networking

| Variable | Default | Description |
|---|---|---|
| `HOST` | `0.0.0.0` | Bind address inside the container |
| `HOST_IP` | `127.0.0.1` | Docker host LAN IP — used for UPnP + stream URL generation. Auto-detected by `dev.sh`/`deploy.sh` |
| `HOST_PORT` | `8111` | Port Jamarr listens on |
| `RENDERER_PROXY_PORT` | `8112` | Port of the renderer stream proxy (UPnP renderers fetch streams/art through it; see [Renderers](../architecture/renderers.md#renderer-stream-proxy)). Overrides `renderer.stream_proxy_port` in `config.yaml` |

## Database

| Variable | Default | Description |
|---|---|---|
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `jamarr` | Credentials for the Postgres container |
| `DB_HOST` | `127.0.0.1` | Runtime DB host |
| `DB_PORT` | `8110` | Runtime DB port |
| `DB_USER` / `DB_PASS` / `DB_NAME` | `jamarr` | Runtime DB connection |
| `DB_LISTEN_ADDR` | `127.0.0.1` | Host interface the Postgres port binds to |

## Storage paths

| Variable | Description |
|---|---|
| `DB_DATA_PATH` | Host dir for PostgreSQL data (prod) |
| `CACHE_PATH` | Host dir for Jamarr cache (scan db, charts, artwork) |
| `DEV_DB_DATA_PATH` / `DEV_CACHE_PATH` | Dev overrides used by `docker-compose.dev.yml` |

## Music volume (NFS)

| Variable | Description |
|---|---|
| `MUSIC_NFS_ADDR` | NFS server address hosting the library |
| `MUSIC_NFS_PATH` | NFS export path |
| `MUSIC_CACHE_NFS_PATH` | Writable NFS export for adaptive stream cache |
| `MUSIC_PATH` | Container mount point for music (`/app/music/`) |
| `JAMARR_STREAM_CACHE_DIR` | Container path for transcode cache (`/app/music-cache/cache`) |

## Compose / frontend / test DB

| Variable | Default | Description |
|---|---|---|
| `COMPOSE_PROJECT_NAME` | `jamarr` | Container/volume name prefix |
| `VITE_API_URL` | `http://127.0.0.1:8111` | Backend URL for the Vite dev server |
| `TEST_DB_USER` / `TEST_DB_PASSWORD` / `TEST_DB_NAME` | `jamarr_test` | Test DB credentials (`docker-compose.test.yml`) |

## Service API keys

| Variable | Description |
|---|---|
| `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` | Spotify metadata enrichment |
| `LASTFM_API_KEY` / `LASTFM_SHARED_SECRET` | Last.fm scrobble sync |
| `QOBUZ_APP_ID` / `QOBUZ_SECRET` / `QOBUZ_EMAIL` / `QOBUZ_PASSWORD` | Qobuz metadata (optional) |
| `TIDAL_CLIENT_ID` / `TIDAL_CLIENT_SECRET` | Tidal metadata (optional) |
| `FANARTTV_API_KEY` | Fanart.tv artwork (optional) |

## External services

| Variable | Default | Description |
|---|---|---|
| `PEARLARR_URL` | — | Pearlarr download integration |
| `MUSICBRAINZ_ROOT_URL` | `https://musicbrainz.org` | MusicBrainz API root |

## JWT authentication

| Variable | Default | Description |
|---|---|---|
| `JWT_SECRET_KEY` | — | **Required.** Generate: `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `JWT_ALGORITHM` | `HS256` | Signing algorithm |
| `JWT_ISSUER` | `jamarr` | `iss` claim |
| `JWT_AUDIENCE` | `jamarr-api` | `aud` claim |
| `ACCESS_TOKEN_TTL_MINUTES` | `10` | Access token lifetime |
| `REFRESH_TOKEN_TTL_DAYS` | `21` | Refresh token lifetime |
| `STREAM_TOKEN_TTL_SECONDS` | `300` | Stream token lifetime (non-Cast) |
| `STREAM_TOKEN_AUDIENCE` | `jamarr-stream` | Stream token `aud` |
| `CAST_STREAM_TOKEN_TTL_SECONDS` | `86400` | Max Cast stream token TTL — see [ADR-0003](../architecture/decisions/0003-cast-stream-token-policy.md) |

## Session cookies & proxy hardening

| Variable | Default | Description |
|---|---|---|
| `REFRESH_COOKIE_SECURE` | `false` | Set `true` in production (requires HTTPS) |
| `REFRESH_COOKIE_NAME` | `jamarr_refresh` | Refresh cookie name |
| `ALLOWED_HOSTS` | empty | Comma-separated; empty allows all (dev only) |
| `ALLOWED_ORIGINS` | empty | CORS origins |
| `TRUSTED_PROXY_IPS` | empty | Reverse-proxy IPs trusted for client-IP resolution |
