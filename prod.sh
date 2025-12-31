#!/bin/bash
# Production mode startup script
# This builds and starts all services for production deployment

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

echo "🚀 Building and starting Jamarr in production mode..."
echo ""
echo "This will:"
echo "  1. Build the frontend (npm run build)"
echo "  2. Build the Docker image with bundled frontend"
echo "  3. Start all services in production mode"
echo ""

# Build and start services
docker compose build
docker compose up -d

echo ""
echo "✅ Production deployment complete!"
echo ""
echo "Services:"
echo "  - Application: http://${SERVER_IP}:8111"
echo "  - Database: PostgreSQL on ${SERVER_IP}:8110"
echo "  - CloudBeaver: http://${SERVER_IP}:8978"
echo ""
echo "View logs: docker compose logs -f"
echo "Stop services: docker compose down"
