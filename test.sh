#!/bin/bash
set -euo pipefail

# Use a dedicated compose project to avoid clashing with dev/prod containers
export COMPOSE_PROJECT_NAME=${COMPOSE_PROJECT_NAME:-jamarr-test}

# Clean up any leftover stack or named containers from prior runs (even with different project labels)
echo "🧹 Cleaning up any existing test stack..."
docker compose -f docker-compose.test.yml down --remove-orphans >/dev/null 2>&1 || true
docker rm -f jamarr_test_db jamarr_test_runner >/dev/null 2>&1 || true

# Ensure any leftover containers from a previous run are removed
echo "🧹 Cleaning up any existing test stack..."
docker compose -f docker-compose.test.yml down >/dev/null 2>&1 || true

# Derive HOST_IP via internal route to DNS server (192.168.0.11) unless provided
if [[ -z "${HOST_IP:-}" ]]; then
  HOST_IP="$(ip route get 192.168.0.11 2>/dev/null | awk '{for(i=1;i<=NF;i++){if($i=="src"){print $(i+1); exit}}}')"
fi

if [[ -z "${HOST_IP:-}" ]]; then
  echo "Unable to determine HOST_IP (tried route to 192.168.0.11). Set HOST_IP manually and retry." >&2
  exit 1
fi

export HOST_IP

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
    if docker compose -f docker-compose.test.yml exec -T jamarr_test_db pg_isready -h 127.0.0.1 -p 8109 -U jamarr_test >/dev/null 2>&1; then
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
    echo "✅ Tests Passed! Tearing down test stack..."
    docker compose -f docker-compose.test.yml down
else
    echo ""
    echo "❌ Tests Failed!"
    echo "⚠️  Test Database (jamarr_test_db) is LEFT RUNNING on port 8109 for debugging."
    echo "   You can inspect it with: docker compose -f docker-compose.test.yml logs"
    echo "   Or connect via: psql -h localhost -p 8109 -U jamarr_test -d jamarr_test"
    exit $EXIT_CODE
fi
