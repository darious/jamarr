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
  auth.py auth_tokens.py security.py    JWT auth (pyjwt, argon2, slowapi)
  db.py config.py logging_conf.py scheduler.py charts.py lastfm*.py playlist.py upnp.py
web/src/             SvelteKit: routes/ (album,artist,charts,discovery,history,
                     login,playlists,queue,renderers,settings) + lib/
tui/jamarr_tui/      api, art, playback, screens, widgets
migrations/          NNN_*.sql  (raw SQL; auto-applied on app startup + by deploy.sh)
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
- DB changes = new `migrations/NNN_*.sql` (existing installs) **and** the matching
  DDL in `app/db.py` `init_db` (fresh installs + tests). Never edit old migrations.
  Migrations auto-apply on startup (lifespan → `apply_migrations`; `AUTO_MIGRATE=false`
  to disable). Fresh init_db schemas are *baselined* (recorded, not replayed), so a
  new migration must be compatible with the current schema, not just the old one.
  **init_db runs BEFORE migrations**, and `CREATE TABLE IF NOT EXISTS` is a no-op on
  an existing table — so when init_db indexes a column added by a later migration,
  it must first `ALTER TABLE … ADD COLUMN IF NOT EXISTS` (else startup crashes on the
  index for existing installs, before auto-migrate can add the column).
  Schema docs are generated (`docs/reference/schema/`) — don't hand-edit.
- Config: secrets in `.env` (see `.env.example`); non-secret app config in `config.yaml`.
- Commits: Conventional Commits (`feat(scope):`, `fix(charts):`, `chore(ci):`). **No AI co-author/attribution trailers.**
- Ports (dev): API 8111, Vite 5173, Postgres 8110, CloudBeaver 8978.

## Gotchas

- Python 3.14 required.
- Auth is Bearer-header only; no `access_token=` query fallback. SSE endpoints
  (`/api/library/events`, `/api/lastfm/events`) auth via the refresh cookie.
- `DB_PASS` has no compose default — must be set in `.env`. Production startup
  fails fast if `JWT_SECRET_KEY` is unset or a placeholder.
- UPnP needs host networking — discovery won't work in bridged containers.
- UPnP renderers fetch streams/art via a header-recasing proxy on port 8112
  (`app/services/renderer/stream_proxy.py`), not uvicorn directly — uvicorn
  lowercases response headers and some renderers parse them case-sensitively.
- `HOST_IP` auto-derived in `dev.sh`/`deploy.sh` via route lookup; override by exporting it.
- Frontend dev caches (`web/.svelte-kit`, `web/.vite`) are cleared on `dev.sh` start.
- New top-level route under `web/src/routes/` must also be added to
  `_SPA_ROUTE_PREFIXES` in `app/main.py`, or the backend 404s it.
- `android/test.sh` defaults `ANDROID_HOME=/opt/android-sdk` and caps gradle/kotlin
  heaps when <4 GiB memory available; instrumentation tests only run with a device attached.
- Headless emulator UI check (dev box has no DISPLAY): `JAVA_HOME=~/Android/jdk`,
  `ANDROID_HOME=~/Android/Sdk`, AVD `jamarr36`. Boot needs `sg kvm -c "…/emulator
  -avd jamarr36 -no-window -no-audio -gpu swiftshader_indirect"` (shells predate kvm
  group). Install: `./gradlew :app:installDebug` (`adb uninstall com.jamarr.android`
  first on signature mismatch). Drive via `adb shell input tap/text` +
  `adb exec-out uiautomator dump /dev/tty`; screenshot `adb exec-out screencap -p`.
  Emulator reaches LAN server at `http://192.168.1.107:8111` (not the app's
  `10.0.2.2` default); prod is `https://jamarr.darious.co.uk`. Test login lives in
  `~/prod_login.txt` on the dev box (pointer only — not in-repo). Force 3-button nav
  to test system-bar insets:
  `adb shell cmd overlay enable com.android.internal.systemui.navbar.threebutton`.

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
