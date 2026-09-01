#!/usr/bin/env bash
set -Eeuo pipefail

VERSION="${1:?Informe a versão para deploy}"
PROJECT_ROOT=${FLUVIUS_PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}
ENV_FILE=${FLUVIUS_ENV_FILE:-"$PROJECT_ROOT/.env.production"}
EXPECTED_DEPLOY_SHA=${FLUVIUS_EXPECTED_DEPLOY_SHA:-}
STATE_DIR="$PROJECT_ROOT/.deploy-state"
ACTIVE_SLOT_FILE="$STATE_DIR/active-slot"
UPSTREAMS_FILE=${FLUVIUS_UPSTREAMS_FILE:-"$STATE_DIR/active-upstreams.caddy"}
CADDY_CONFIG=${FLUVIUS_CADDY_CONFIG:-/etc/caddy/Caddyfile}
DRAIN_SECONDS=${FLUVIUS_DRAIN_SECONDS:-30}

if [[ ! "$VERSION" =~ ^v[0-9]+[.][0-9]+[.][0-9]+([-][0-9A-Za-z][0-9A-Za-z.-]*)?$ ]]; then
  echo "Tag inválida: $VERSION. Use formato semver, exemplo v0.1.0." >&2
  exit 1
fi
if ! [[ "$DRAIN_SECONDS" =~ ^[0-9]+$ ]]; then
  echo "FLUVIUS_DRAIN_SECONDS deve ser um número inteiro." >&2
  exit 1
fi

mkdir -p "$STATE_DIR"
exec 9>"$STATE_DIR/deploy.lock"
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
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

SLOT_COMPOSE_FILE="$PROJECT_ROOT/docker-compose.prod.slot.yml"
if [[ ! -f "$SLOT_COMPOSE_FILE" ]]; then
  echo "Arquivo de Compose dos slots não encontrado: $SLOT_COMPOSE_FILE" >&2
  exit 1
fi

LEGACY_PROJECT_NAME=${COMPOSE_PROJECT_NAME:-fluvius-core-prod}
BACKEND_NETWORK=${FLUVIUS_BACKEND_NETWORK:-fluvius-core-prod_backend}
FRONTEND_NETWORK=${FLUVIUS_FRONTEND_NETWORK:-fluvius-core-prod_frontend}
BLUE_API_PORT=${FLUVIUS_BLUE_API_PORT:-18100}
BLUE_WEB_PORT=${FLUVIUS_BLUE_WEB_PORT:-18180}
GREEN_API_PORT=${FLUVIUS_GREEN_API_PORT:-18200}
GREEN_WEB_PORT=${FLUVIUS_GREEN_WEB_PORT:-18280}

LEGACY_COMPOSE=(
  docker compose
  --project-name "$LEGACY_PROJECT_NAME"
  --env-file "$ENV_FILE"
  -f "$PROJECT_ROOT/docker-compose.prod.yml"
)

slot_values() {
  local slot=$1
  case "$slot" in
    blue)
      SLOT_API_PORT="$BLUE_API_PORT"
      SLOT_WEB_PORT="$BLUE_WEB_PORT"
      SLOT_PROJECT="fluvius-blue"
      ;;
    green)
      SLOT_API_PORT="$GREEN_API_PORT"
      SLOT_WEB_PORT="$GREEN_WEB_PORT"
      SLOT_PROJECT="fluvius-green"
      ;;
    *)
      echo "Slot inválido: $slot" >&2
      return 1
      ;;
  esac
}

slot_compose() {
  local slot=$1
  shift
  slot_values "$slot"
  FLUVIUS_SLOT="$slot" \
    FLUVIUS_SLOT_API_PORT="$SLOT_API_PORT" \
    FLUVIUS_SLOT_WEB_PORT="$SLOT_WEB_PORT" \
    FLUVIUS_BACKEND_NETWORK="$BACKEND_NETWORK" \
    FLUVIUS_FRONTEND_NETWORK="$FRONTEND_NETWORK" \
    docker compose \
      --project-name "$SLOT_PROJECT" \
      --env-file "$ENV_FILE" \
      -f "$SLOT_COMPOSE_FILE" \
      "$@"
}

wait_for_url() {
  local url=$1
  local label=$2
  local attempts=${3:-60}

  for ((attempt = 1; attempt <= attempts; attempt++)); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done

  echo "$label não respondeu após $((attempts * 2)) segundos: $url" >&2
  return 1
}

wait_for_slot() {
  local slot=$1
  local api_port=$2
  local attempts=${3:-60}
  local response

  for ((attempt = 1; attempt <= attempts; attempt++)); do
    response=$(curl -fsS "http://127.0.0.1:$api_port/health/version" 2>/dev/null || true)
    if [[ "$response" =~ \"slot\"[[:space:]]*:[[:space:]]*\"$slot\" ]]; then
      return 0
    fi
    sleep 2
  done

  echo "API do slot $slot não confirmou sua identidade após $((attempts * 2)) segundos." >&2
  return 1
}

verify_datastores_ready() {
  "${LEGACY_COMPOSE[@]}" exec -T postgres \
    pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null </dev/null
  "${LEGACY_COMPOSE[@]}" exec -T redis \
    redis-cli -a "$REDIS_PASSWORD" --no-auth-warning ping >/dev/null </dev/null
}

verify_networks() {
  docker network inspect "$BACKEND_NETWORK" >/dev/null
  docker network inspect "$FRONTEND_NETWORK" >/dev/null
}

verify_slot_services() {
  local slot=$1
  local service
  local status
  for service in api web worker delivery-worker webhook-worker; do
    status=$(slot_compose "$slot" ps --status running --services "$service" 2>/dev/null || true)
    if [[ "$status" != "$service" ]]; then
      echo "Container esperado não está running no slot $slot: $service" >&2
      slot_compose "$slot" ps
      return 1
    fi
  done
}

slot_has_running_app() {
  local slot=$1
  local service=${2:-api}
  local status
  if [[ "$slot" == "legacy" ]]; then
    status=$("${LEGACY_COMPOSE[@]}" ps --status running --services "$service" 2>/dev/null || true)
  else
    status=$(slot_compose "$slot" ps --status running --services "$service" 2>/dev/null || true)
  fi
  [[ "$status" == "$service" ]]
}

start_slot_app() {
  local slot=$1
  if [[ "$slot" == "legacy" ]]; then
    "${LEGACY_COMPOSE[@]}" start api web worker delivery-worker webhook-worker >/dev/null 2>&1 || \
      "${LEGACY_COMPOSE[@]}" up -d --no-deps api web worker delivery-worker webhook-worker
  else
    slot_compose "$slot" start api web worker delivery-worker webhook-worker >/dev/null 2>&1 || \
      slot_compose "$slot" up -d --no-deps api web worker delivery-worker webhook-worker
  fi
}

stop_slot_services() {
  local slot=$1
  shift
  if [[ "$slot" == "legacy" ]]; then
    "${LEGACY_COMPOSE[@]}" stop "$@"
  else
    slot_compose "$slot" stop "$@"
  fi
}

write_upstreams() {
  local api_port=$1
  local web_port=$2
  local temporary_file="${UPSTREAMS_FILE}.tmp.$$"
  {
    echo "# Generated by production-deploy.sh. Do not edit manually."
    echo "@backend path /api/* /health /health/* /ws"
    echo "handle @backend {"
    printf '\treverse_proxy 127.0.0.1:%s\n' "$api_port"
    echo "}"
    echo
    echo "handle {"
    printf '\treverse_proxy 127.0.0.1:%s\n' "$web_port"
    echo "}"
  } > "$temporary_file"
  mv -f "$temporary_file" "$UPSTREAMS_FILE"
  chmod 0644 "$UPSTREAMS_FILE"
}

reload_caddy() {
  sudo -n caddy validate --config "$CADDY_CONFIG"
  sudo -n systemctl reload caddy
}

ensure_caddy_ready() {
  if [[ ! -r "$CADDY_CONFIG" ]]; then
    echo "A configuração do Caddy não está legível: $CADDY_CONFIG" >&2
    return 1
  fi
  if ! grep -R -F -q "$UPSTREAMS_FILE" /etc/caddy; then
    echo "O Caddy ainda não importa $UPSTREAMS_FILE." >&2
    echo "Instale deploy/Caddyfile.host uma vez e recarregue o Caddy antes do próximo deploy." >&2
    return 1
  fi
  if [[ ! -f "$UPSTREAMS_FILE" ]]; then
    cp "$PROJECT_ROOT/deploy/Caddyfile.upstreams" "$UPSTREAMS_FILE"
  fi
  sudo -n caddy validate --config "$CADDY_CONFIG"
}

rollback_traffic() {
  local old_slot=$1
  local old_api_port=$2
  local old_web_port=$3
  echo "Tentando restaurar o tráfego para $old_slot..." >&2
  if [[ "$old_app_available" == true ]]; then
    start_slot_app "$old_slot" || true
  fi
  write_upstreams "$old_api_port" "$old_web_port"
  reload_caddy || true
  stop_slot_services "$target_slot" api web worker delivery-worker webhook-worker || true
}

probe_active_slot() {
  local slot=$1
  local api_port=$2
  local response
  if [[ "$slot" == legacy ]]; then
    curl -fsS --max-time 2 "http://127.0.0.1:$api_port/health/ready" >/dev/null 2>&1
    return
  fi
  response=$(curl -fsS --max-time 2 "http://127.0.0.1:$api_port/health/version" 2>/dev/null || true)
  [[ "$response" =~ \"slot\"[[:space:]]*:[[:space:]]*\"$slot\" ]]
}

read_active_slot() {
  if [[ -f "$ACTIVE_SLOT_FILE" ]]; then
    local value
    value=$(tr -d '[:space:]' < "$ACTIVE_SLOT_FILE")
    case "$value" in
      blue|green|legacy)
        printf '%s\n' "$value"
        return 0
        ;;
      *)
        echo "Slot ativo inválido em $ACTIVE_SLOT_FILE: $value" >&2
        return 1
        ;;
    esac
  fi
  local candidates=()
  if probe_active_slot legacy "${FLUVIUS_API_PORT:-18000}"; then
    candidates+=(legacy)
  fi
  if probe_active_slot blue "$BLUE_API_PORT"; then
    candidates+=(blue)
  fi
  if probe_active_slot green "$GREEN_API_PORT"; then
    candidates+=(green)
  fi
  if (( ${#candidates[@]} == 1 )); then
    printf '%s\n' "${candidates[0]}"
    return 0
  fi
  if (( ${#candidates[@]} > 1 )); then
    echo "Mais de um slot responde sem um estado ativo confiável: ${candidates[*]}" >&2
    return 1
  fi
  printf '%s\n' legacy
}

active_ports() {
  case "$1" in
    legacy)
      printf '%s %s\n' "${FLUVIUS_API_PORT:-18000}" "${FLUVIUS_WEB_PORT:-18080}"
      ;;
    blue)
      printf '%s %s\n' "$BLUE_API_PORT" "$BLUE_WEB_PORT"
      ;;
    green)
      printf '%s %s\n' "$GREEN_API_PORT" "$GREEN_WEB_PORT"
      ;;
    *)
      echo "Não foi possível resolver as portas do slot $1." >&2
      return 1
      ;;
  esac
}

active_slot=$(read_active_slot)
if [[ "$active_slot" == "legacy" ]]; then
  target_slot=blue
else
  target_slot=green
  [[ "$active_slot" == green ]] && target_slot=blue
fi
read -r old_api_port old_web_port < <(active_ports "$active_slot")
slot_values "$target_slot"
target_api_port="$SLOT_API_PORT"
target_web_port="$SLOT_WEB_PORT"
old_app_available=false
if slot_has_running_app "$active_slot"; then
  old_app_available=true
fi

traffic_switched=false
upstreams_updated=false
old_workers_stopped=false

rollback_on_error() {
  local status=$?
  trap - ERR
  set +e
  if [[ "$traffic_switched" == true || "$upstreams_updated" == true ]]; then
    rollback_traffic "$active_slot" "$old_api_port" "$old_web_port"
  else
    stop_slot_services "$target_slot" api web worker delivery-worker webhook-worker || true
    if [[ "$old_workers_stopped" == true && "$old_app_available" == true ]]; then
      start_slot_app "$active_slot" || true
    fi
  fi
  exit "$status"
}

# A failed rollout may leave the inactive slot consuming database connections.
# Clean it before building the next candidate while the active slot keeps serving.
stop_slot_services "$target_slot" api web worker delivery-worker webhook-worker || true
trap rollback_on_error ERR

ensure_caddy_ready
"${LEGACY_COMPOSE[@]}" config --quiet
slot_compose "$target_slot" config --quiet
"${LEGACY_COMPOSE[@]}" up -d --remove-orphans --wait --wait-timeout 300 postgres redis evolution-go
verify_datastores_ready
verify_networks

slot_compose "$target_slot" build api web worker delivery-worker webhook-worker
slot_compose "$target_slot" run --rm --no-deps api alembic upgrade head </dev/null
slot_compose "$target_slot" up -d --no-deps --wait --wait-timeout 300 api web
wait_for_slot "$target_slot" "$target_api_port"
wait_for_url "http://127.0.0.1:$target_api_port/health/ready" "API do slot $target_slot"
wait_for_url "http://127.0.0.1:$target_web_port/" "Frontend do slot $target_slot"

# Pause the old background fleet before the one-off job. The durable queues keep
# accepting work while this releases enough PostgreSQL connections for rollout.
if [[ "$old_app_available" == true ]]; then
  old_workers_stopped=true
  stop_slot_services "$active_slot" worker delivery-worker webhook-worker
fi

# Existing Evolution Go instances may still contain the legacy api:8000 URL.
# Reapply the public URL before switching traffic so no channel loses webhooks.
slot_compose "$target_slot" run --rm --no-deps api python -m app.jobs.reconfigure_webhooks </dev/null

write_upstreams "$target_api_port" "$target_web_port"
upstreams_updated=true
reload_caddy
traffic_switched=true

wait_for_slot "$target_slot" "$target_api_port"
wait_for_url "https://$APP_DOMAIN/health/ready" "Domínio público após a troca"
public_version=$(curl -fsS "https://$APP_DOMAIN/health/version")
if [[ ! "$public_version" =~ \"slot\"[[:space:]]*:[[:space:]]*\"$target_slot\" ]]; then
  echo "O domínio público não confirmou o slot $target_slot: $public_version" >&2
  exit 1
fi

slot_compose "$target_slot" up -d --no-deps --wait --wait-timeout 300 \
  worker delivery-worker webhook-worker
verify_slot_services "$target_slot"

# The old workers are already stopped. Keep only the old HTTP/WebSocket services
# during the short drain window so in-flight requests can finish.
if [[ "$old_app_available" == true ]]; then
  sleep "$DRAIN_SECONDS"
  stop_slot_services "$active_slot" api web
fi

traffic_switched=false
upstreams_updated=false
old_workers_stopped=false
trap - ERR
printf '%s\n' "$target_slot" > "$ACTIVE_SLOT_FILE"
printf '%s\n' "$VERSION" > "$STATE_DIR/last-successful-tag"
printf '%s\n' "$DEPLOY_SHA" > "$STATE_DIR/last-successful-sha"

echo "Deploy blue/green concluído: $active_slot -> $target_slot"
echo "https://$APP_DOMAIN ($VERSION $DEPLOY_SHA)"
