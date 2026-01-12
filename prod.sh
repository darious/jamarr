#!/bin/bash
# Production mode startup script
# This builds and starts all services for production deployment

set -euo pipefail

# Derive HOST_IP from the primary network interface (ignoring loopback)
if [[ -z "${HOST_IP:-}" ]]; then
  # Grab the first IP address that isn't 127.0.0.1
  HOST_IP="$(hostname -I | awk '{print $1}')"
fi

# Fallback: If hostname -I fails, try the route method but default to your known static if needed
if [[ -z "${HOST_IP:-}" || "${HOST_IP}" == "127.0.0.1" ]]; then
  HOST_IP="$(ip route get 1.1.1.1 2>/dev/null | awk '{print $7}')"
fi

if [[ -z "${HOST_IP:-}" ]]; then
  echo "Unable to determine HOST_IP. Set HOST_IP manually and retry." >&2
  exit 1
fi

export HOST_IP
SERVER_IP="${HOST_IP}"

echo "🚀 Building and starting Jamarr in production mode..."
echo "📍 Detected HOST_IP: ${HOST_IP}"
echo ""
echo "This will:"
echo "  1. Build the frontend (npm run build)"
echo "  2. Build the Docker image with bundled frontend"
echo "  3. Start all services in production mode"
echo ""

# Build and start services
docker compose build

# Explicitly pass HOST_IP to ensure Compose overrides any .env values
HOST_IP="${HOST_IP}" docker compose up -d

echo ""
echo "✅ Production deployment complete!"
echo ""
echo "Services:"
echo "  - Application: http://${SERVER_IP}:8111"
echo "  - Database: PostgreSQL on ${SERVER_IP}:8110"
echo ""
echo "View logs: docker compose logs -f"
echo "Stop services: docker compose down"
