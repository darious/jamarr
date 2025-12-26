#!/bin/bash
# Development mode startup script
# This starts all services with hot-reload enabled

set -e

# Get server IP from docker-compose.yml
SERVER_IP=$(grep "HOST_IP=" docker-compose.yml | cut -d'=' -f2 | cut -d'#' -f1 | tr -d ' ')

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
