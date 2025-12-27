#!/bin/bash
# Production mode startup script
# This builds and starts all services for production deployment

set -e

# Get server IP from docker-compose.yml
SERVER_IP=$(grep "HOST_IP=" docker-compose.yml | cut -d'=' -f2 | cut -d'#' -f1 | tr -d ' ')

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
