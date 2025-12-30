#!/usr/bin/env bash
set -euo pipefail

COMPOSE="docker compose"

# Prefer HOST_IP from env; otherwise derive via an internal route (DNS server REDACTED_IP)
if [[ -z "${HOST_IP:-}" ]]; then
  HOST_IP="$(ip route get REDACTED_IP 2>/dev/null | awk '{for(i=1;i<=NF;i++){if($i=="src"){print $(i+1); exit}}}')"
fi

if [[ -z "${HOST_IP:-}" ]]; then
  echo "Unable to determine HOST_IP (tried route to REDACTED_IP). Set HOST_IP manually and retry." >&2
  exit 1
fi

export HOST_IP
echo "Using HOST_IP=${HOST_IP}"

echo "[1/6] Stopping app container..."
${COMPOSE} stop jamarr || true

echo "[2/6] Updating repository..."
git pull --rebase

echo "[3/6] Ensuring database container is up..."
${COMPOSE} up -d jamarr_db

echo "[4/6] Building latest application image..."
${COMPOSE} build jamarr

echo "[5/6] Applying database migrations..."
${COMPOSE} run --rm jamarr python scripts/apply_migrations.py

echo "[6/6] Starting app container..."
${COMPOSE} up -d jamarr

echo "✅ Deploy complete"
