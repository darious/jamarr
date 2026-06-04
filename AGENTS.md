# AGENTS.md

Orientation for AI agents working in this repo. Read this instead of re-scanning the tree.

## What Jamarr is

Self-hosted, web-based music controller. Scans a local music library (NFS), enriches metadata (MusicBrainz/Spotify/Last.fm/Qobuz/Tidal/Fanart.tv), browse + play via web UI. Local playback + UPnP renderers (gapless via `SetNextAVTransportURI`) + Chromecast.

## Stack

- **Backend**: Python 3.14, FastAPI, asyncpg (PostgreSQL), uvicorn. Managed by `uv`.
- **Frontend**: SvelteKit + Vite (`web/`).
- **TUI**: Python Textual app (`tui/`, uv workspace member).
- **Android**: Kotlin/Compose client (`android/`).
- **Infra**: Docker Compose. Container runs `network_mode: host` for UPnP discovery.

## Layout

```
app/                 backend (Python)
  main.py            FastAPI entrypoint / app factory
  api/               route modules: auth, library, search, player, stream,
                     history, favorites, charts, recommendation, scan,
                     scheduler, lastfm, media_quality, deps (DI)
  models/            data models
  scanner/           library scan + metadata pipeline; CLI: app.scanner.cli
    pipeline/ services/
  services/          domain services
    player/ renderer/ upnp/
  matching/          fuzzy match (rapidfuzz) for charts/metadata
  media/             artwork / media handling
  auth.py auth_tokens.py security.py    JWT auth (python-jose, argon2, slowapi)
  db.py config.py logging_conf.py scheduler.py charts.py lastfm*.py playlist.py upnp.py
web/src/             SvelteKit: routes/ (album,artist,charts,discovery,history,
                     login,playlists,queue,renderers,settings) + lib/
tui/jamarr_tui/      api, art, playback, screens, widgets
migrations/          NNN_*.sql  (raw SQL, applied by deploy.sh in order)
tests/               pytest: api/ auth/ integration/ scanner/ unit/ + top-level
docs/                outline.md, DATABASE_SCHEMA.md, api.md, auth.md, scanner.md,
                     DEV_MODE.md, tui.md, android.md
```

## Commands

Everything runs through `uv` (backend/tui) or Docker Compose. Do not `pip install`.

| Task | Command |
|---|---|
| Backend tests (dockerized DB) | `./test.sh` |
| TUI tests | `./test.sh tui`  (or `uv run --all-packages pytest tui/tests`) |
| Frontend tests/check/lint/build | `./test-web.sh [all\|unit\|check\|lint\|build]` |
| Lint (all) | `./lint.sh` (ruff for Python, svelte-check + css for web) |
| Dev (hot reload, all services) | `./dev.sh` |
| Deploy (pull img, backup db, migrate, restart) | `./deploy.sh` |
| Scan library | `docker compose run --rm jamarr uv run python -m app.scanner.cli scan` |
| Enrich metadata | `... app.scanner.cli metadata` |

Backend tests need the test DB stack (`docker-compose.test.yml`); `test.sh` brings it up/down. Run a single test: `./test.sh tests/test_charts.py` (args forwarded to pytest).

## Conventions

- Python: ruff (config in `pyproject.toml` / `lint.sh`). Async-first (asyncpg, httpx, aiofiles).
- DB changes = new `migrations/NNN_*.sql`, never edit old ones. Update `docs/DATABASE_SCHEMA.md`.
- Config: secrets in `.env` (see `.env.example`); non-secret app config in `config.yaml`.
- Commits: Conventional Commits (`feat(scope):`, `fix(charts):`, `chore(ci):`). **No AI co-author/attribution trailers.**
- Ports (dev): API 8111, Vite 5173, Postgres 8110, CloudBeaver 8978.

## Gotchas

- Python 3.14 required.
- UPnP needs host networking — discovery won't work in bridged containers.
- `HOST_IP` auto-derived in `dev.sh`/`deploy.sh` via route lookup; override by exporting it.
- Frontend dev caches (`web/.svelte-kit`, `web/.vite`) are cleared on `dev.sh` start.

## Deeper docs (read only when relevant)

Docs are an MkDocs site (`mkdocs.yml` defines nav; deployed to GitHub Pages on
merge to main). Source under `docs/`:

- `docs/architecture/` — `overview.md`, `auth.md`, `renderers.md`,
  `scanner-pipeline.md`, `artwork.md`, `decisions/` (ADRs)
- `docs/reference/` — `scanner-cli.md`, `env-vars.md`; **`api.md` and `schema/`
  are GENERATED** (FastAPI OpenAPI + tbls) — do not hand-edit. To change API
  docs, edit route metadata in `app/`; for schema, edit `app/db.py`/`migrations/`.
- `docs/getting-started/`, `docs/clients/`, `docs/guides/`, `docs/roadmap.md`

Generators: `scripts/docs/gen_openapi.py`, `scripts/docs/gen_schema.sh`. CI:
`.github/workflows/docs.yml`. `CONTRIBUTING.md` = dev setup.
