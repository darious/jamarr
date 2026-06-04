#!/usr/bin/env bash
# Generate docs/reference/schema/ from the database schema using tbls.
#
# Brings up the dockerised test Postgres, builds the full schema (base tables
# via init_db() + incremental migrations), then runs tbls to emit per-table
# markdown + an ER diagram. Build-time output; gitignored; CI regenerates.
#
# Requires: docker compose, tbls (https://github.com/k1LoW/tbls), .env present.
set -euo pipefail

cd "$(dirname "$0")/../.."

COMPOSE="docker compose -f docker-compose.test.yml"
DB_SVC="jamarr_test_db"
RUNNER="jamarr_test_runner"

cleanup() { $COMPOSE down --remove-orphans >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "==> Starting test database"
$COMPOSE up -d "$DB_SVC"

echo "==> Waiting for Postgres"
for _ in $(seq 1 30); do
  if $COMPOSE exec -T "$DB_SVC" pg_isready -h 127.0.0.1 -p 5432 >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo "==> Building schema (init_db + migrations)"
$COMPOSE run --rm "$RUNNER" env PYTHONPATH=/app uv run python -c \
  "import asyncio; from app.db import init_db, close_db; asyncio.run(init_db()); asyncio.run(close_db())"
$COMPOSE run --rm "$RUNNER" env PYTHONPATH=/app uv run python migrations/apply_migrations.py

echo "==> Generating schema docs with tbls"
# Load TEST_DB_* so the .tbls.yml DSN resolves.
set -a; . ./.env; set +a
rm -rf docs/reference/schema
tbls doc --force

echo "==> Schema docs written to docs/reference/schema/"
