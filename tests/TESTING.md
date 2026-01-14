# Testing Guide

## Overview

Jamarr uses pytest for backend tests and a Docker Compose test stack for consistent database setup. The recommended path is `./test.sh`, which builds a test runner image, starts a disposable Postgres instance, runs pytest, and cleans up on success.

## Running Backend Tests (Recommended)

```bash
./test.sh
```

Notes:
- Uses `docker-compose.test.yml` with a dedicated project name (`jamarr-test`).
- Starts Postgres on port 8109 and passes DB env vars into the runner container.
- Default pytest marker expression is `not slow`.
- On failure (and when `CI` is not `true`), the DB container is left running for debugging.

### Common Options

```bash
./test.sh -v
./test.sh -k "test_search"
```

To include slow tests:

```bash
PYTEST_MARK_EXPR="slow" ./test.sh
PYTEST_MARK_EXPR="not slow" ./test.sh
```

## Frontend Build Check

Run a production build inside the test container:

```bash
./test-build.sh
```

This installs dependencies in the container and runs `npm run build` against the `web/` code.

## External API Smoke Checks

Run the external API script directly:

```bash
./test-ext-api.sh
```

## Running Pytest Locally (Advanced)

If you need to run pytest outside Docker, make sure a Postgres instance is available and the DB env vars match your local setup (see `docker-compose.test.yml` and `.env`). Then:

```bash
uv run pytest
```

## Test Layout

- `tests/api/`, `tests/integration/`, `tests/unit/`: grouped by scope.
- `tests/scanner/`: scanner-specific coverage.
- `tests/utils/`: shared fixtures/helpers.

## Debugging Failures

- If `./test.sh` fails, the DB remains on `localhost:8109` for inspection.
- Use `docker compose -f docker-compose.test.yml logs` to review service output.
