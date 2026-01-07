#!/bin/bash
set -euo pipefail

# Use a dedicated compose project to avoid clashing with dev/prod containers
export COMPOSE_PROJECT_NAME=${COMPOSE_PROJECT_NAME:-jamarr-test}
CI=${CI:-false}

cleanup() {
    local status=$?
    if [[ "$CI" == "true" || "$status" -eq 0 ]]; then
        echo "🧹 Cleaning up test stack..."
        docker compose -f docker-compose.test.yml down --remove-orphans >/dev/null 2>&1 || true
        docker rm -f jamarr_test_db jamarr_test_runner >/dev/null 2>&1 || true
    else
        echo "⚠️  Test stack left running for debugging."
    fi
    exit "$status"
}
trap cleanup EXIT

echo "🧹 Cleaning up any existing test stack..."
docker compose -f docker-compose.test.yml down --remove-orphans >/dev/null 2>&1 || true
docker rm -f jamarr_test_db jamarr_test_runner >/dev/null 2>&1 || true

# Build test runner image (shares main image)
echo "🔨 Building test runner image..."
docker compose -f docker-compose.test.yml build jamarr_test_runner

echo "🚀 Starting Test Database on port 8109..."
docker compose -f docker-compose.test.yml up -d jamarr_test_db

# Wait for DB to be ready
echo "⏳ Waiting for Test Database to be ready..."
# Small grace period before first check
sleep 1

# Retrying for up to 30 seconds using pg_isready from the DB container
DB_READY=0
for i in {1..30}; do
    if docker compose -f docker-compose.test.yml exec -T jamarr_test_db pg_isready -h 127.0.0.1 -p 5432 -U jamarr_test >/dev/null 2>&1; then
        echo "✅ Test Database is ready!"
        DB_READY=1
        break
    fi
    echo "..."
    sleep 1
done

if [ "$DB_READY" -ne 1 ]; then
    echo "❌ Test Database did not become ready on port 8109."
    exit 1
fi

echo "🧪 Running tests..."
PYTEST_MARK_EXPR=${PYTEST_MARK_EXPR:-"not slow"}

# Run pytest inside the container with Test DB environment variables
# We use set +e to capture the exit code
set +e
docker compose -f docker-compose.test.yml run --rm jamarr_test_runner \
    env PYTHONPATH=/app uv run pytest -m "$PYTEST_MARK_EXPR" "$@"

EXIT_CODE=$?
set -e

if [ $EXIT_CODE -eq 0 ]; then
    echo ""
    echo "✅ Tests Passed!"
    exit 0
else
    echo ""
    echo "❌ Tests Failed!"
    if [[ "$CI" != "true" ]]; then
        echo "⚠️  Test Database (jamarr_test_db) is LEFT RUNNING on port 8109 for debugging."
        echo "   You can inspect it with: docker compose -f docker-compose.test.yml logs"
        echo "   Or connect via: psql -h localhost -p 8109 -U jamarr_test -d jamarr_test"
    fi
    exit $EXIT_CODE
fi
