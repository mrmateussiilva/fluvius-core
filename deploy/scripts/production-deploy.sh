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

wait_for_url() {
  local url=$1
  local label=$2
  local attempts=${3:-30}

  for ((attempt = 1; attempt <= attempts; attempt++)); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done

  echo "$label não respondeu após $((attempts * 2)) segundos: $url" >&2
  return 1
}

"${COMPOSE[@]}" config --quiet
"${COMPOSE[@]}" build

"${COMPOSE[@]}" up -d --remove-orphans --wait --wait-timeout 300 \
  postgres redis evolution-go
"${COMPOSE[@]}" run --rm --no-deps api alembic upgrade head
"${COMPOSE[@]}" up -d --no-deps --wait --wait-timeout 300 api
"${COMPOSE[@]}" exec -T api alembic current
"${COMPOSE[@]}" up -d --no-deps --wait --wait-timeout 300 \
  worker delivery-worker
"${COMPOSE[@]}" up -d --no-deps --wait --wait-timeout 300 web
"${COMPOSE[@]}" ps

wait_for_url \
  "http://127.0.0.1:${FLUVIUS_API_PORT:-18000}/health/ready" \
  "API interna"
wait_for_url \
  "http://127.0.0.1:${FLUVIUS_WEB_PORT:-18080}/" \
  "Frontend interno"
wait_for_url "https://$APP_DOMAIN/health/ready" "Domínio público"

DEPLOY_SHA=${FLUVIUS_DEPLOY_SHA:-}
if [[ -z "$DEPLOY_SHA" ]] && git -C "$PROJECT_ROOT" rev-parse HEAD >/dev/null 2>&1; then
  DEPLOY_SHA=$(git -C "$PROJECT_ROOT" rev-parse HEAD)
fi
if [[ -n "$DEPLOY_SHA" ]]; then
  mkdir -p "$PROJECT_ROOT/.deploy-state"
  printf '%s\n' "$DEPLOY_SHA" \
    > "$PROJECT_ROOT/.deploy-state/last-successful-sha"
fi

echo "Deploy concluído: https://$APP_DOMAIN (${DEPLOY_SHA:-sha desconhecido})"
