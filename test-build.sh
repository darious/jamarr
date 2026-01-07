#!/bin/bash
set -euo pipefail

# Use a dedicated compose project to avoid clashing with dev/prod containers
export COMPOSE_PROJECT_NAME=${COMPOSE_PROJECT_NAME:-jamarr-test}

echo "🧹 Cleaning up any existing test stack..."
docker compose -f docker-compose.test.yml down --remove-orphans >/dev/null 2>&1 || true

echo "🏗️  Starting Frontend Build Check..."

# We use 'run --rm' to spin up the container, execute the command, and remove it.
# No need to start it in detached mode first.

echo "📦 Installing dependencies (npm install)..."
# Using 'npm ci' would be better for reproducible builds if lockfile exists, 
# but 'npm install' is safer if lockfile is out of sync in dev.
if ! docker compose -f docker-compose.test.yml run --rm jamarr_test_web npm install; then
    echo "❌ Dependencies failed to install."
    exit 1
fi

echo "🔨 Running Production Build (npm run build)..."
# This runs the actual SvelteKit/Vite build process
if docker compose -f docker-compose.test.yml run --rm jamarr_test_web npm run build; then
    echo ""
    echo "✅ PRODUCTION BUILD SUCCEEDED!"
    echo "   The frontend code compiles correctly."
else
    echo ""
    echo "❌ PRODUCTION BUILD FAILED!"
    echo "   Please fix the errors above."
    exit 1
fi

# Cleanup
echo "🧹 Cleaning up..."
docker compose -f docker-compose.test.yml down >/dev/null 2>&1 || true

exit 0
