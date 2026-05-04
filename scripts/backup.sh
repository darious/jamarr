#!/usr/bin/env bash
set -euo pipefail

COMPOSE="docker compose"
DB_CONTAINER="$(${COMPOSE} ps -q jamarr_db)"
BACKUP_DIR="/mnt/config/q-jamarr/backup"
BACKUP_PREFIX="jamarr_rescue_"

cleanup_old_backups() {
  local now
  now=$(date +%s)

  for f in "${BACKUP_DIR}/${BACKUP_PREFIX}"*.sql.gz; do
    [ -f "$f" ] || continue
    local base name date_str ts
    name=$(basename "$f")
    # jamarr_rescue_YYYY-MM-DD_HHMMSS.sql.gz
    date_str="${name#${BACKUP_PREFIX}}"    # YYYY-MM-DD_HHMMSS.sql.gz
    date_str="${date_str%%_*}"              # YYYY-MM-DD
    ts=$(date -d "$date_str" +%s 2>/dev/null) || continue

    local keep=false
    local days_ago=$(( (now - ts) / 86400 ))

    # Last 7 days
    if [ "$days_ago" -le 7 ]; then
      keep=true
    fi

    # Monday within last 28 days
    local dow
    dow=$(date -d "@$ts" +%u 2>/dev/null)  # 1=Mon..7=Sun
    if [ "$dow" = "1" ] && [ "$days_ago" -le 28 ]; then
      keep=true
    fi

    # 1st of the month within last 365 days
    local dom
    dom=$(date -d "@$ts" +%d 2>/dev/null)  # day of month
    if [ "$dom" = "01" ] && [ "$days_ago" -le 365 ]; then
      keep=true
    fi

    if ! $keep; then
      echo "Removing old backup: $name"
      rm -f "$f"
    fi
  done
}

usage() {
  cat <<'EOF'
Usage:
  ./backup.sh
  ./backup.sh restore <backup_file>

Defaults:
  Creates a compressed backup in /mnt/config/q-jamarr/backup.
  Cleans up old backups keeping: last 7 days, Mondays for 4 weeks,
  and 1st of each month for 12 months.
EOF
}

if [[ -z "${DB_CONTAINER}" ]] || [[ "$(docker inspect -f '{{.State.Running}}' "${DB_CONTAINER}")" != "true" ]]; then
  echo "Database container not running; aborting." >&2
  exit 1
fi

MODE="${1:-}"
if [[ -z "${MODE}" ]]; then
  mkdir -p "${BACKUP_DIR}"
  BACKUP_PATH="${BACKUP_DIR}/${BACKUP_PREFIX}$(date +%F_%H%M%S).sql.gz"
  if ! docker exec -i jamarr_db pg_dump -h 127.0.0.1 -p 8110 -U jamarr -d jamarr --no-owner --no-privileges \
    | gzip -c > "${BACKUP_PATH}"; then
    echo "Database backup failed; aborting." >&2
    exit 1
  fi
  echo "Database backup created at ${BACKUP_PATH}"
  cleanup_old_backups
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
