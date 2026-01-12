#!/usr/bin/env bash
set -euo pipefail

COMPOSE="docker compose"

# Derive HOST_IP from the primary network interface (ignoring loopback)
if [[ -z "${HOST_IP:-}" ]]; then
  # Grab the first IP address that isn't 127.0.0.1
  HOST_IP="$(hostname -I | awk '{print $1}')"
fi
echo "Using HOST_IP=${HOST_IP}"

echo "[1/7] Building latest application image..."
# Build before stopping. If this fails, the old version keeps running.
${COMPOSE} build jamarr

echo "[2/7] Ensuring database container is up..."
${COMPOSE} up -d jamarr_db

echo "[3/7] Waiting for database readiness..."
DB_READY="false"
for _ in {1..30}; do
    if docker exec jamarr_db pg_isready -h 127.0.0.1 -p 8110 -U jamarr >/dev/null 2>&1; then
        DB_READY="true"
        break
    fi
    sleep 1
done

if [[ "${DB_READY}" != "true" ]]; then
    echo "Error: Database did not become ready; aborting." >&2
    exit 1
fi

echo "[4/7] Creating database backup (pre-migration)..."
BACKUP_DIR="/mnt/config/q-jamarr/jamarr"
mkdir -p "${BACKUP_DIR}"
BACKUP_PATH="${BACKUP_DIR}/jamarr_rescue_$(date +%F_%H%M%S).sql.gz"

# Use -i (interactive) and NOT -t (tty) to ensure binary integrity of the compressed dump
if docker exec -i jamarr_db pg_dump -h 127.0.0.1 -p 8110 -U jamarr -d jamarr --no-owner --no-privileges | gzip -c > "${BACKUP_PATH}"; then
    echo "Backup created: ${BACKUP_PATH}"
else
    echo "Error: Database backup failed; aborting." >&2
    exit 1
fi

echo "[5/7] Applying database migrations..."
# Run migrations using the new image we just built
${COMPOSE} run --rm jamarr python scripts/apply_migrations.py

echo "[6/7] Restarting app container..."
# 'up -d' recreates only the containers that have changed images or config
${COMPOSE} up -d jamarr

echo "[7/7] Cleaning up old images..."
docker image prune -f

echo "✅ Deploy complete"