#!/usr/bin/env bash
set -Eeuo pipefail

VERSION="${1:?Informe a versão para deploy}"
PROJECT_ROOT=${FLUVIUS_PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}
ENV_FILE=${FLUVIUS_ENV_FILE:-"$PROJECT_ROOT/.env.production"}
EXPECTED_DEPLOY_SHA=${FLUVIUS_EXPECTED_DEPLOY_SHA:-}

if [[ ! "$VERSION" =~ ^v[0-9]+[.][0-9]+[.][0-9]+([-][0-9A-Za-z][0-9A-Za-z.-]*)?$ ]]; then
  echo "Tag inválida: $VERSION. Use formato semver, exemplo v0.1.0." >&2
  exit 1
fi

mkdir -p "$PROJECT_ROOT/.deploy-state"
exec 9>"$PROJECT_ROOT/.deploy-state/deploy.lock"
if ! flock -n 9; then
  echo "Outro deploy já está em execução." >&2
  exit 1
fi

cd "$PROJECT_ROOT"
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "A VPS possui alterações rastreadas; deploy interrompido." >&2
  git status --short
  exit 1
fi

if ! git ls-remote --exit-code --tags origin "refs/tags/$VERSION" >/dev/null; then
  echo "Tag não encontrada no origin: $VERSION" >&2
  exit 1
fi
git fetch origin --tags --force
if ! git rev-parse -q --verify "refs/tags/$VERSION^{commit}" >/dev/null; then
  echo "Tag não encontrada no origin: $VERSION" >&2
  exit 1
fi
DEPLOY_SHA=$(git rev-parse "refs/tags/$VERSION^{commit}")
if [[ -n "$EXPECTED_DEPLOY_SHA" && "$DEPLOY_SHA" != "$EXPECTED_DEPLOY_SHA" ]]; then
  echo "Tag $VERSION aponta para $DEPLOY_SHA, esperado $EXPECTED_DEPLOY_SHA." >&2
  exit 1
fi
git checkout --detach "$VERSION"
git reset --hard "$VERSION"
CURRENT_SHA=$(git rev-parse HEAD)
if [[ "$CURRENT_SHA" != "$DEPLOY_SHA" ]]; then
  echo "Checkout terminou em $CURRENT_SHA, esperado $DEPLOY_SHA." >&2
  exit 1
fi
echo "Implantando Fluvius $VERSION ($DEPLOY_SHA)."

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

verify_services_running() {
  local service
  local status
  local expected_services=(
    postgres
    redis
    evolution-go
    api
    worker
    delivery-worker
    web
  )

  for service in "${expected_services[@]}"; do
    status=$("${COMPOSE[@]}" ps --status running --services "$service" 2>/dev/null || true)
    if [[ "$status" != "$service" ]]; then
      echo "Container esperado não está running: $service" >&2
      "${COMPOSE[@]}" ps
      return 1
    fi
  done
}

verify_datastores_ready() {
  "${COMPOSE[@]}" exec -T postgres \
    pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null
  "${COMPOSE[@]}" exec -T redis \
    redis-cli -a "$REDIS_PASSWORD" --no-auth-warning ping >/dev/null
}

"${COMPOSE[@]}" config --quiet
"${COMPOSE[@]}" build

"${COMPOSE[@]}" up -d --remove-orphans --wait --wait-timeout 300 \
  postgres redis
verify_datastores_ready
"${COMPOSE[@]}" up -d --no-deps --wait --wait-timeout 300 evolution-go
"${COMPOSE[@]}" run --rm --no-deps api alembic upgrade head
"${COMPOSE[@]}" up -d --no-deps --wait --wait-timeout 300 api
"${COMPOSE[@]}" exec -T api alembic current
"${COMPOSE[@]}" up -d --no-deps --wait --wait-timeout 300 \
  worker delivery-worker
"${COMPOSE[@]}" up -d --no-deps --wait --wait-timeout 300 web
"${COMPOSE[@]}" ps
verify_services_running

wait_for_url \
  "http://127.0.0.1:${FLUVIUS_API_PORT:-18000}/health/ready" \
  "API interna"
wait_for_url \
  "http://127.0.0.1:${FLUVIUS_WEB_PORT:-18080}/" \
  "Frontend interno"
wait_for_url "https://$APP_DOMAIN/health/ready" "Domínio público"

printf '%s\n' "$VERSION" \
  > "$PROJECT_ROOT/.deploy-state/last-successful-tag"
printf '%s\n' "$DEPLOY_SHA" \
  > "$PROJECT_ROOT/.deploy-state/last-successful-sha"

echo "Deploy concluído: https://$APP_DOMAIN ($VERSION $DEPLOY_SHA)"
