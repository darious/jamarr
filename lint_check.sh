#!/bin/bash
set -e

echo "🔍 Running Svelte Check..."
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec -T jamarr_web npm run check
