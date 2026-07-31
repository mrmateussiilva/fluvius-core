#!/usr/bin/env bash
set -euo pipefail

CONFIG_FILE=${FLUVIUS_BACKUP_CONFIG:-/etc/fluvius/backup.conf}
if [[ ! -f "$CONFIG_FILE" ]]; then
  echo "Configuração de backup não encontrada em $CONFIG_FILE." >&2
  exit 1
fi
source "$CONFIG_FILE"
if [[ ! -f "$FLUVIUS_ENV_FILE" ]]; then
  echo "Ambiente de produção não encontrado em $FLUVIUS_ENV_FILE." >&2
  exit 1
fi
set -a
source "$FLUVIUS_ENV_FILE"
set +a

COMPOSE=(
  docker compose
  --env-file "$FLUVIUS_ENV_FILE"
  -f "$FLUVIUS_PROJECT_DIR/docker-compose.prod.yml"
)
STAGING_ROOT="$FLUVIUS_DATA_DIR/backups/staging"
mkdir -p "$STAGING_ROOT"
STAGING_DIR=$(mktemp -d "$STAGING_ROOT/backup.XXXXXX")
cleanup() {
  rm -rf -- "$STAGING_DIR"
}
trap cleanup EXIT INT TERM

TIMESTAMP=$(date -u +%Y%m%dT%H%M%SZ)
DATABASE_DUMP="$STAGING_DIR/postgresql-$TIMESTAMP.sql.gz"
EVOGO_AUTH_DUMP="$STAGING_DIR/evogo_auth-$TIMESTAMP.sql.gz"
EVOGO_USERS_DUMP="$STAGING_DIR/evogo_users-$TIMESTAMP.sql.gz"
"${COMPOSE[@]}" exec -T postgres \
  pg_dumpall --clean --if-exists -U "$POSTGRES_USER" |
  gzip -9 > "$DATABASE_DUMP"
# Dumps dedicados da Evolution (licença + instâncias) para restore seletivo.
"${COMPOSE[@]}" exec -T postgres \
  pg_dump --clean --if-exists -U "$POSTGRES_USER" -d evogo_auth |
  gzip -9 > "$EVOGO_AUTH_DUMP"
"${COMPOSE[@]}" exec -T postgres \
  pg_dump --clean --if-exists -U "$POSTGRES_USER" -d evogo_users |
  gzip -9 > "$EVOGO_USERS_DUMP"

export RESTIC_REPOSITORY="$FLUVIUS_DATA_DIR/backups/restic"
export RESTIC_PASSWORD_FILE
if ! restic snapshots >/dev/null 2>&1; then
  restic init
fi
restic backup \
  "$DATABASE_DUMP" \
  "$EVOGO_AUTH_DUMP" \
  "$EVOGO_USERS_DUMP" \
  "$FLUVIUS_DATA_DIR/media" \
  --tag fluvius-production
restic forget \
  --keep-daily 7 \
  --keep-weekly 4 \
  --keep-monthly 3 \
  --prune

echo "Backup concluído em $TIMESTAMP."
