#!/usr/bin/env bash
set -euo pipefail

COMPOSE="docker compose"

# Prefer HOST_IP from env; otherwise derive via an internal route (DNS server 192.168.0.11)
if [[ -z "${HOST_IP:-}" ]]; then
  HOST_IP="$(ip route get 192.168.0.11 2>/dev/null | awk '{for(i=1;i<=NF;i++){if($i=="src"){print $(i+1); exit}}}')"
fi

if [[ -z "${HOST_IP:-}" ]]; then
  echo "Unable to determine HOST_IP (tried route to 192.168.0.11). Set HOST_IP manually and retry." >&2
  exit 1
fi

export HOST_IP
echo "Using HOST_IP=${HOST_IP}"

echo "[1/8] Stopping app container..."
${COMPOSE} stop jamarr || true

echo "[2/8] Updating repository..."
git pull --rebase

echo "[3/8] Ensuring database container is up..."
${COMPOSE} up -d jamarr_db

echo "[4/8] Building latest application image..."
${COMPOSE} build jamarr

echo "[5/8] Waiting for database container to be ready..."
DB_CONTAINER="$(${COMPOSE} ps -q jamarr_db)"
DB_READY="false"
if [[ -n "${DB_CONTAINER}" ]]; then
  for _ in {1..30}; do
    if [[ "$(docker inspect -f '{{.State.Status}}' "${DB_CONTAINER}")" == "running" ]]; then
      if docker exec -t jamarr_db pg_isready -h 127.0.0.1 -p 8110 -U jamarr >/dev/null 2>&1; then
        DB_READY="true"
        break
      fi
    fi
    sleep 1
  done
  if [[ "${DB_READY}" != "true" ]]; then
    echo "Database container did not become ready; aborting." >&2
    exit 1
  fi
fi

echo "[6/8] Backing up database if container is running..."
if [[ -n "${DB_CONTAINER}" ]] && [[ "${DB_READY}" == "true" ]]; then
  BACKUP_DIR="/mnt/config/q-docker/jamarr"
  mkdir -p "${BACKUP_DIR}"
  BACKUP_PATH="${BACKUP_DIR}/jamarr_rescue_$(date +%F_%H%M%S).sql.gz"
  for attempt in {1..5}; do
    if docker exec -t jamarr_db pg_dump -h 127.0.0.1 -p 8110 -U jamarr -d jamarr --no-owner --no-privileges \
      | gzip -c > "${BACKUP_PATH}"; then
      echo "Database backup created at ${BACKUP_PATH}"
      break
    fi
    if [[ "$(docker inspect -f '{{.State.Status}}' "${DB_CONTAINER}")" != "running" ]]; then
      sleep 1
      continue
    fi
    echo "Database backup failed; aborting." >&2
    exit 1
  done
  if [[ ! -s "${BACKUP_PATH}" ]]; then
    echo "Database backup failed; aborting." >&2
    exit 1
  fi
else
  echo "Database container not running; skipping backup."
fi

echo "[7/8] Applying database migrations..."
${COMPOSE} run --rm jamarr python scripts/apply_migrations.py

echo "[8/8] Starting app container..."
${COMPOSE} up -d jamarr

echo "✅ Deploy complete"
