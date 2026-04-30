# Contributing to Jamarr

Thanks for taking the time to improve Jamarr. This project is a self-hosted music controller with a Python/FastAPI backend, Svelte frontend, PostgreSQL database, and Android client.

## License

Jamarr is licensed under the GNU Affero General Public License v3.0 only (`AGPL-3.0-only`).

By submitting a contribution, you agree that your contribution is licensed under `AGPL-3.0-only` and can be distributed as part of Jamarr under that license.

Do not submit code, assets, generated output, or copied snippets unless you have the right to contribute them under terms compatible with `AGPL-3.0-only`.

## Before You Start

- Open an issue or discussion before large changes, database changes, new integrations, or user-visible workflow changes.
- Keep changes scoped. Unrelated refactors make review harder.
- Do not commit secrets, personal credentials, signing keys, `.env` files, music files, database dumps, or private logs.
- Avoid committing generated build output unless the repository already tracks that exact type of file.

## Development

### Prerequisites

- Python 3.14+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- Docker + Docker Compose
- Node.js (for frontend work)

### Quick Start (Docker)

```bash
./dev.sh
```

Starts all services in development mode:
- **Backend API** (port 8111) — auto-reloads on Python changes
- **Frontend** (port 5173) — Vite HMR for instant updates
- **PostgreSQL** (port 8110)

`dev.sh` auto-detects `HOST_IP` (or use `HOST_IP=... ./dev.sh`) and rebuilds if Python dependencies changed. See [Dev Mode Guide](docs/DEV_MODE.md).

### Manual Development (Without Docker)

#### Backend
```bash
uv sync
docker compose up jamarr_db -d  # or use your own PostgreSQL
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8111
```

#### Frontend
```bash
cd web
npm install
npm run dev:host
```

Backend dependencies are managed with `uv`. Frontend dependencies live in `web/`. Android code lives in `android/`.

### Helper Scripts

| Script | Description |
|:---|:---|
| `./dev.sh` | Start dev stack with hot-reload |
| `./deploy.sh` | Full production deploy (backup → migrate → restart) |
| `./test.sh` | Run backend tests in Docker test stack |
| `./lint.sh [python\|svelte\|css\|all]` | Run Ruff and/or Svelte check |
| `./scripts/test-build.sh` | Build frontend in CI-style test container |
| `./scripts/test-ext-api.sh` | External API smoke checks |

### Running Tests

```bash
./test.sh                # Full API test suite
./test.sh -v             # Verbose output
./test.sh -k "test_search"  # Run specific tests
```

See `tests/TESTING.md` for details on the test stack and troubleshooting.

### Linting

```bash
./lint.sh         # Run all checks (Python, Svelte, CSS)
./lint.sh python  # Run only Python checks (ruff)
./lint.sh svelte  # Run only Svelte checks
./lint.sh css     # Run only CSS checks
```

Useful checks before submitting:

```bash
./test.sh
./lint.sh all
cd web && npm run check && npm run test
cd android && ./gradlew test
```

Some checks require Docker, the Android SDK, or local dependency caches. If a check cannot be run locally, say so in the pull request and include the reason.

## Database Migrations

Migrations are checksum-tracked. Treat files in `migrations/` as append-only once they have been released.

- Add a new migration for schema or data changes.
- Do not edit an already-released migration unless the project maintainer explicitly confirms that it has not been deployed.
- Keep migrations deterministic and safe to run once.
- Include tests for migration-sensitive behaviour where practical.

## Pull Requests

Good pull requests include:

- A clear description of what changed and why.
- Tests or a short explanation of why tests were not added.
- Notes for migrations, deployment changes, configuration changes, or security-sensitive behaviour.
- Screenshots for visible frontend or Android UI changes.

## Security

Do not report vulnerabilities in public issues. See `SECURITY.md`.

