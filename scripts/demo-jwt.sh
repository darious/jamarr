#!/bin/bash
# Demo script to show Phase 1 JWT functionality
# This runs the Python demo inside the Docker container

set -e

echo "🚀 Starting Phase 1 JWT Demo..."
echo ""

# Check if dev stack is running
if ! docker compose ps | grep -q "jamarr.*running"; then
    echo "❌ Dev stack not running. Starting it now..."
    echo ""
    ./dev.sh
    echo ""
    echo "⏳ Waiting for services to be ready..."
    sleep 5
fi

echo "▶️  Running demo inside Docker container..."
echo ""

docker compose -f docker-compose.yml -f docker-compose.dev.yml exec jamarr python scripts/demo_jwt_phase1.py
