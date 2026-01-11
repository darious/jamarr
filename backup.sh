#!/usr/bin/env bash
set -euo pipefail

COMPOSE="docker compose"
DB_CONTAINER="$(${COMPOSE} ps -q jamarr_db)"
BACKUP_DIR="/mnt/config/q-docker/jamarr"

usage() {
  cat <<'EOF'
Usage:
  ./backup.sh
  ./backup.sh restore <backup_file>

Defaults:
  Creates a compressed backup in /mnt/config/q-docker/jamarr.
EOF
}

if [[ -z "${DB_CONTAINER}" ]] || [[ "$(docker inspect -f '{{.State.Running}}' "${DB_CONTAINER}")" != "true" ]]; then
  echo "Database container not running; aborting." >&2
  exit 1
fi

MODE="${1:-}"
if [[ -z "${MODE}" ]]; then
  mkdir -p "${BACKUP_DIR}"
  BACKUP_PATH="${BACKUP_DIR}/jamarr_rescue_$(date +%F_%H%M%S).sql.gz"
  if ! docker exec -t jamarr_db pg_dump -h 127.0.0.1 -p 8110 -U jamarr -d jamarr --no-owner --no-privileges \
    | gzip -c > "${BACKUP_PATH}"; then
    echo "Database backup failed; aborting." >&2
    exit 1
  fi
  echo "Database backup created at ${BACKUP_PATH}"
  exit 0
fi

if [[ "${MODE}" != "restore" ]]; then
  usage >&2
  exit 1
fi

BACKUP_FILE="${2:-}"
if [[ -z "${BACKUP_FILE}" ]]; then
  echo "Restore mode requires a backup file." >&2
  usage >&2
  exit 1
fi

if [[ ! -f "${BACKUP_FILE}" ]]; then
  echo "Backup file not found: ${BACKUP_FILE}" >&2
  exit 1
fi

if [[ "${BACKUP_FILE}" == *.gz ]]; then
  gzip -dc "${BACKUP_FILE}" \
    | docker exec -i jamarr_db psql -h 127.0.0.1 -p 8110 -U jamarr -d jamarr
else
  cat "${BACKUP_FILE}" \
    | docker exec -i jamarr_db psql -h 127.0.0.1 -p 8110 -U jamarr -d jamarr
fi

echo "Database restore completed from ${BACKUP_FILE}"
