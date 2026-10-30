#!/usr/bin/env bash
# Optional upgrade helper for an image install of Jamarr.
#
# Run it in the directory that holds docker-compose.yml, .env and config.yaml
# (no repo checkout needed; it is attached to every release). It does what
#
#   docker compose pull && docker compose up -d
#
# does, with a database dump first and old images pruned before the pull so a
# full disk cannot block the download. Migrations apply when the app starts;
# the explicit run here only makes a failing one visible before the restart.
#
#   BACKUP_DIR   where dumps go        (default: ./backups)
#   BACKUP_KEEP  dumps to keep         (default: 5; 0 keeps none)
set -euo pipefail

COMPOSE="docker compose"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
BACKUP_KEEP="${BACKUP_KEEP:-5}"

for f in docker-compose.yml .env config.yaml; do
    if [[ ! -f "$f" ]]; then
        echo "Missing $f in $(pwd). Run this where the stack's files live." >&2
        exit 1
    fi
done

# The database name and user the dump needs, as the stack sees them.
set -a
# shellcheck disable=SC1091
. ./.env
set +a
DB_USER="${DB_USER:-jamarr}"
DB_NAME="${DB_NAME:-jamarr}"

echo "[1/6] Pruning unused images (so the pull has room)..."
docker image prune -f >/dev/null

echo "[2/6] Pulling the application image..."
# Before anything stops: if this fails, the old version keeps running.
${COMPOSE} pull jamarr

echo "[3/6] Ensuring the database is up..."
${COMPOSE} up -d jamarr_db
for _ in $(seq 1 30); do
    if ${COMPOSE} exec -T jamarr_db pg_isready -U "${DB_USER}" -d "${DB_NAME}" >/dev/null 2>&1; then
        DB_READY=true
        break
    fi
    sleep 1
done
if [[ "${DB_READY:-false}" != "true" ]]; then
    echo "Database did not become ready; aborting." >&2
    exit 1
fi

echo "[4/6] Dumping the database to ${BACKUP_DIR}..."
mkdir -p "${BACKUP_DIR}"
BACKUP_PATH="${BACKUP_DIR}/jamarr_$(date +%F_%H%M%S).sql.gz"
# -T: no tty, so the compressed stream is not mangled.
if ${COMPOSE} exec -T jamarr_db pg_dump -U "${DB_USER}" -d "${DB_NAME}" --no-owner --no-privileges | gzip -c > "${BACKUP_PATH}"; then
    echo "Backup: ${BACKUP_PATH}"
else
    rm -f "${BACKUP_PATH}"
    echo "Database backup failed; aborting." >&2
    exit 1
fi
if [[ "${BACKUP_KEEP}" =~ ^[0-9]+$ ]]; then
    # Newest first; drop everything past BACKUP_KEEP.
    ls -1t "${BACKUP_DIR}"/jamarr_*.sql.gz 2>/dev/null | tail -n +"$((BACKUP_KEEP + 1))" | xargs -r rm -f
fi

echo "[5/6] Applying database migrations..."
${COMPOSE} run --rm --no-deps jamarr python migrations/apply_migrations.py

echo "[6/6] Restarting the app..."
${COMPOSE} up -d jamarr

echo "Done. $(${COMPOSE} ps --format '{{.Name}} {{.Status}}' jamarr 2>/dev/null || true)"
