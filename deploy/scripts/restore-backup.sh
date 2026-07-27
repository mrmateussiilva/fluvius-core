#!/usr/bin/env bash
set -euo pipefail

if [[ ${CONFIRM_RESTORE:-} != "YES" ]]; then
  echo "Restauração altera banco e mídias. Execute com CONFIRM_RESTORE=YES." >&2
  exit 1
fi
CONFIG_FILE=${FLUVIUS_BACKUP_CONFIG:-/etc/fluvius/backup.conf}
source "$CONFIG_FILE"
set -a
source "$FLUVIUS_ENV_FILE"
set +a

SNAPSHOT=${1:-latest}
RESTORE_ROOT=$(mktemp -d "$FLUVIUS_DATA_DIR/backups/restore.XXXXXX")
cleanup() {
  rm -rf -- "$RESTORE_ROOT"
}
trap cleanup EXIT INT TERM
export RESTIC_REPOSITORY="$FLUVIUS_DATA_DIR/backups/restic"
export RESTIC_PASSWORD_FILE
COMPOSE=(
  docker compose
  --env-file "$FLUVIUS_ENV_FILE"
  -f "$FLUVIUS_PROJECT_DIR/docker-compose.prod.yml"
)

restic restore "$SNAPSHOT" --target "$RESTORE_ROOT"
DATABASE_DUMP=$(find "$RESTORE_ROOT" -type f -name 'postgresql-*.sql.gz' | head -n 1)
MEDIA_SOURCE="$RESTORE_ROOT$FLUVIUS_DATA_DIR/media"
if [[ -z "$DATABASE_DUMP" || ! -d "$MEDIA_SOURCE" ]]; then
  echo "Snapshot não contém banco e mídias esperados." >&2
  exit 1
fi

"${COMPOSE[@]}" stop api worker delivery-worker evolution-go caddy
"${COMPOSE[@]}" up -d postgres redis
gunzip -c "$DATABASE_DUMP" |
  "${COMPOSE[@]}" exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres
rsync -a --delete "$MEDIA_SOURCE/" "$FLUVIUS_DATA_DIR/media/"
"${COMPOSE[@]}" up -d

echo "Snapshot $SNAPSHOT restaurado. Valide healthcheck, login, canais e mensagens."
