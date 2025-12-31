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

# Start services in detached mode
docker compose down
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d

echo ""
echo "✅ All services started in background"
echo "View logs: docker compose logs -f"
echo "Stop services: docker compose down"
