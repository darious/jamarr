#!/bin/bash
# Development mode startup script
# This starts all services with hot-reload enabled

set -euo pipefail

# Derive HOST_IP via internal route to DNS server (192.168.0.11) unless provided
if [[ -z "${HOST_IP:-}" ]]; then
  HOST_IP="$(ip route get 192.168.0.11 2>/dev/null | awk '{for(i=1;i<=NF;i++){if($i=="src"){print $(i+1); exit}}}')"
fi

if [[ -z "${HOST_IP:-}" ]]; then
  echo "Unable to determine HOST_IP (tried route to 192.168.0.11). Set HOST_IP manually and retry." >&2
  exit 1
fi

export HOST_IP
SERVER_IP="${HOST_IP}"

echo "🚀 Starting Jamarr in development mode..."
echo ""
echo "Services:"
echo "  - Backend API: http://${SERVER_IP}:8111 (hot-reload enabled)"
echo "  - Frontend: http://${SERVER_IP}:5173 (Vite HMR enabled)"
echo "  - Database: PostgreSQL on ${SERVER_IP}:8110"
echo "  - CloudBeaver: http://${SERVER_IP}:8978"
echo ""
echo "Changes to frontend or backend code will auto-reload!"
echo "No Docker rebuilds needed! 🎉"
echo ""


# Check for dependency changes
DEP_HASH_FILE=".deps.sha256"
# Calculate hash of pyproject.toml and uv.lock (if it exists)
CURRENT_HASH=$(cat pyproject.toml uv.lock 2>/dev/null | sha256sum | awk '{print $1}')

if [[ -f "$DEP_HASH_FILE" ]]; then
  STORED_HASH=$(cat "$DEP_HASH_FILE")
else
  STORED_HASH=""
fi

if [[ "$CURRENT_HASH" != "$STORED_HASH" ]]; then
  echo "📦 Dependencies changed (pyproject.toml/uv.lock), rebuilding Docker image..."
  docker compose build jamarr
  echo "$CURRENT_HASH" > "$DEP_HASH_FILE"
  echo "✅ Build complete and hash updated."
else
  echo "✨ Dependencies unchanged, skipping build."
fi

# Start services in detached mode
docker compose down
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d

echo ""
echo "✅ All services started in background"
echo "View logs: docker compose logs -f"
echo "Stop services: docker compose down"
