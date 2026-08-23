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
- Versions live in the git tag, never in a file. Two independent streams, and
  the codename's letter says which: server `vX.Y.Z` takes a **Z** artist
  (Docker image incl. the web UI, `latest` moves, `JAMARR_VERSION` baked in);
  app `android-vX.Y.Z` takes an **A** artist (signed APK, `versionName` from
  the tag, `versionCode` = `major*10000 + minor*100 + patch`). The numbers drift on purpose — align
  them only when a change to one *requires* the other. Nothing else is
  versioned: the web UI ships inside the image, the TUI runs from a checkout,
  and the `0.1.0`s in `pyproject.toml`/`web/package.json` are inert. Cut with
  `release.sh <tag> "<Name>"` — see `docs/reference/release-names.md`.
- CI builds on PRs and on release tags only; a merge to `main` builds nothing.
  `deploy.sh` pulls `:latest`, which now moves on server tags rather than on
  every merge, so deploys land released versions. `workflow_dispatch` on
  `publish_docker.yml` publishes an untagged `main` when you need it.
- Ports (dev): API 8111, Vite 5173, Postgres 8110, CloudBeaver 8978.

## Gotchas

- Python 3.14 required.
- Auth is Bearer-header only; no `access_token=` query fallback. SSE endpoints
  (`/api/library/events`, `/api/lastfm/events`) auth via the refresh cookie.
- `DB_PASS` has no compose default — must be set in `.env`. Production startup
  fails fast if `JWT_SECRET_KEY` is unset or a placeholder.
- DB connections: `Depends(get_db)` in FastAPI handlers, `async with db_conn()`
  everywhere else. **Never** `async for db in get_db():` — a `break` or an
  exception strands the generator and leaks the connection out of the pool for
  good. Two other rules keep the pool (20 conns) alive: never acquire a second
  connection while holding one (declare `Depends(get_db)` on the handler and
  FastAPI shares the auth dependency's), and never let a yield-dependency reach
  a long-lived response — dependency teardown waits for the response to finish,
  so on SSE it waits forever. Health check: `/api/health` (unauthenticated,
  touches the DB); `/` is the static SPA and answers 200 even when the API is
  wedged, so it is useless for uptime monitoring.
- UPnP needs host networking — discovery won't work in bridged containers.
- UPnP renderers fetch streams/art via a header-recasing proxy on port 8112
  (`app/services/renderer/stream_proxy.py`), not uvicorn directly — uvicorn
  lowercases response headers and some renderers parse them case-sensitively.
- `HOST_IP` auto-derived in `dev.sh`/`deploy.sh` via route lookup; override by exporting it.
- Frontend dev caches (`web/.svelte-kit`, `web/.vite`) are cleared on `dev.sh` start.
- `test-web.sh`/`lint.sh` run in containers as root and leave root-owned artifacts in
  the bind mount (`web/.svelte-kit`, `web/build`, `__pycache__/`). `dev.sh` then dies
  on "Permission denied" clearing those caches. Fix without sudo:
  `docker run --rm -v "$PWD":/repo alpine:3 chown -R 1000:1000 /repo/<paths>`.
  The dev web container also runs `npm install`, which can add optional-peer entries
  to `web/package-lock.json` — revert that noise before committing.
- New top-level route under `web/src/routes/` must also be added to
  `_SPA_ROUTE_PREFIXES` in `app/main.py`, or the backend 404s it.
- `android/test.sh` probes for the SDK (`~/Android/Sdk`, then `/opt/android-sdk`) and
  for a JDK (`~/Android/jdk`, then the usual `/usr/lib/jvm` LTS paths) when
  `ANDROID_HOME`/`JAVA_HOME` are unset, so it runs bare; it caps gradle/kotlin heaps
  when <4 GiB memory available. Instrumentation tests run when a device is attached —
  detected via `$ANDROID_HOME/platform-tools/adb`, since the SDK's `adb` is normally
  not on PATH. The check runs once at script start, so an emulator booted in parallel
  is missed. `RUN_ANDROID_INSTRUMENTATION=1` makes them mandatory: with no device
  attached it boots the headless AVD via `android/scripts/emulator.sh` and stops it
  on exit.
- Android toolchain (user-local, no root): JDK 21 (Temurin) at `~/Android/jdk`, SDK at
  `~/Android/Sdk`, installed via `cmdline-tools`. AGP 9 / Gradle 9 need JDK 17+.
  `compileSdk = 37` resolves to the `platforms;android-37.0` package, not
  `platforms;android-37`. **Neither is in the repo or provisioned by any script** —
  on a fresh box both are absent and `test.sh` exits with "No Android SDK found".
  To reinstall: unpack a Temurin JDK 21 tarball to `~/Android/jdk`, unzip the linux
  `commandlinetools` bundle to `~/Android/Sdk/cmdline-tools/latest`, then
  `yes | sdkmanager --licenses` and `sdkmanager "platform-tools"
  "platforms;android-37.0" "build-tools;37.0.0" "emulator"
  "system-images;android-36;google_apis;x86_64"` (~2 GiB). Last known-good set:
  JDK 21.0.12+8, cmdline-tools 22.0, platform-tools 37.0.1, build-tools 37.0.0,
  emulator 37.1.11. `sdkmanager` and `avdmanager` live in
  `~/Android/Sdk/cmdline-tools/latest/bin` and are not on PATH; `sdkmanager` warns
  that it is deprecated in favour of the `android` CLI, but still works.
- Headless emulator UI check (dev box has no DISPLAY): AVD `jamarr36`
  (API 36 `google_apis;x86_64`, pixel_6). `android/scripts/emulator.sh
  start|stop|status` does all of the following, creating the AVD if it is missing;
  the manual equivalent is `avdmanager create avd -n jamarr36 -k
  "system-images;android-36;google_apis;x86_64" -d pixel_6` (it prints a harmless
  `Could not load devices from .../devices.xml` error but still applies the
  profile), then fixing the generated `~/.android/avd/jamarr36.avd/config.ini`, which
  ships `avd.id`/`avd.name` as the literal `<build>` and GPU off — set those to
  `jamarr36`, `hw.gpu.enabled=yes`, `hw.gpu.mode=swiftshader_indirect`, and
  `hw.keyboard=yes` (needed for `adb shell input text`). Boot with
  `~/Android/Sdk/emulator/emulator -avd jamarr36 -no-window -no-audio
  -gpu swiftshader_indirect`; ~40s to `sys.boot_completed=1`, because the dev box
  grants `/dev/kvm` through a POSIX ACL rather than `kvm` group membership, so
  acceleration works without sudo — check with `getfacl /dev/kvm`, not `id`. Install:
  `./gradlew :app:installDebug` (`adb uninstall com.jamarr.android` first on
  signature mismatch). Drive via `adb shell input tap/text` +
  `adb exec-out uiautomator dump /dev/tty`; screenshot `adb exec-out screencap -p`.
  Emulator reaches the prod LAN server at `http://192.168.1.107:8111` (not the app's
  `10.0.2.2` default), or a locally-run `dev.sh` at `http://192.168.0.22:8111` — the
  dev box is `192.168.0.22/23`, so both live on one subnet. Prod over the internet is
  `https://jamarr.darious.co.uk`. Only **debug** builds can use those http URLs:
  `res/xml/network_security_config.xml` permits cleartext under `debug-overrides`
  only, and `src/release/AndroidManifest.xml` pins `usesCleartextTraffic=false`.
  Test login lives in
  `~/jamarr_prod.txt` on the dev box (pointer only — not in-repo). Force 3-button nav
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
