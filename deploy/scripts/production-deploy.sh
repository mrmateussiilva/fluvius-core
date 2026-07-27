#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
ENV_FILE=${FLUVIUS_ENV_FILE:-"$PROJECT_ROOT/.env.production"}
if [[ ! -f "$ENV_FILE" ]]; then
  echo "Crie $ENV_FILE antes do deploy." >&2
  exit 1
fi
set -a
source "$ENV_FILE"
set +a
COMPOSE=(
  docker compose
  --env-file "$ENV_FILE"
  -f "$PROJECT_ROOT/docker-compose.prod.yml"
)

"${COMPOSE[@]}" config --quiet
"${COMPOSE[@]}" build
"${COMPOSE[@]}" up -d --remove-orphans
"${COMPOSE[@]}" exec -T api alembic current
"${COMPOSE[@]}" ps

for attempt in {1..30}; do
  if curl -fsS "https://$APP_DOMAIN/health/ready" >/dev/null; then
    echo "Deploy concluído: https://$APP_DOMAIN"
    exit 0
  fi
  sleep 2
done

echo "A aplicação não ficou pronta. Consulte docker compose logs." >&2
exit 1
