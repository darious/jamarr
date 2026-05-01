#!/bin/bash
set -euo pipefail

# Use a dedicated compose project to avoid clashing with dev/prod containers
export COMPOSE_PROJECT_NAME=${COMPOSE_PROJECT_NAME:-jamarr-test}
CI=${CI:-false}

cleanup() {
    local status=$?
    if [[ "$CI" == "true" || "$status" -eq 0 ]]; then
        echo "🧹 Cleaning up..."
        docker compose -f docker-compose.test.yml down >/dev/null 2>&1 || true
    else
        echo "⚠️  Test build stack left running for debugging."
    fi
    exit "$status"
}
trap cleanup EXIT

echo "🧹 Cleaning up any existing test stack..."
docker compose -f docker-compose.test.yml down --remove-orphans >/dev/null 2>&1 || true

echo "🏗️  Starting Frontend Checks..."

# We use 'run --rm' to spin up the container, execute the command, and remove it.
# No need to start it in detached mode first.

if [[ "$CI" == "true" ]]; then
    echo "📦 Installing dependencies (npm ci)..."
    if ! docker compose -f docker-compose.test.yml run --rm jamarr_test_web npm ci; then
        echo "❌ Dependencies failed to install."
        exit 1
    fi
else
    echo "📦 Installing dependencies (npm install)..."
    if ! docker compose -f docker-compose.test.yml run --rm jamarr_test_web npm install; then
        echo "❌ Dependencies failed to install."
        exit 1
    fi
fi

echo "🔧 Syncing SvelteKit generated files (npx svelte-kit sync)..."
if ! docker compose -f docker-compose.test.yml run --rm jamarr_test_web npx svelte-kit sync; then
    echo "❌ SvelteKit sync failed."
    exit 1
fi

echo "🧪 Running frontend unit tests (npm run test)..."
if ! docker compose -f docker-compose.test.yml run --rm jamarr_test_web npm run test; then
    echo ""
    echo "❌ FRONTEND TESTS FAILED!"
    exit 1
fi

echo "🔎 Running Svelte type/check pass (npm run check)..."
if ! docker compose -f docker-compose.test.yml run --rm jamarr_test_web npm run check; then
    echo ""
    echo "❌ FRONTEND CHECK FAILED!"
    exit 1
fi

echo "🔨 Running production build (npm run build)..."
if docker compose -f docker-compose.test.yml run --rm jamarr_test_web npm run build; then
    echo ""
    echo "✅ FRONTEND CHECKS PASSED!"
else
    echo ""
    echo "❌ PRODUCTION BUILD FAILED!"
    echo "   Please fix the errors above."
    exit 1
fi

exit 0
