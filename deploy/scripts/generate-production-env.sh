#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
TARGET_FILE=${1:-"$PROJECT_ROOT/.env.production"}
APP_DOMAIN=${APP_DOMAIN:-fluvius.finderbit.com.br}

if [[ -e "$TARGET_FILE" ]]; then
  echo "O arquivo $TARGET_FILE já existe; nenhum segredo foi sobrescrito." >&2
  exit 1
fi
if ! command -v openssl >/dev/null 2>&1; then
  echo "Instale openssl antes de gerar o ambiente." >&2
  exit 1
fi

random_secret() {
  openssl rand -hex 32
}

umask 077
{
  echo "COMPOSE_PROJECT_NAME=fluvius-core-prod"
  echo "APP_DOMAIN=$APP_DOMAIN"
  echo "EVOLUTION_GO_WEBHOOK_BASE_URL=https://$APP_DOMAIN"
  echo "FLUVIUS_DATA_DIR=/srv/fluvius"
  echo "FLUVIUS_API_PORT=18000"
  echo "FLUVIUS_WEB_PORT=18080"
  echo "FLUVIUS_BLUE_API_PORT=18100"
  echo "FLUVIUS_BLUE_WEB_PORT=18180"
  echo "FLUVIUS_GREEN_API_PORT=18200"
  echo "FLUVIUS_GREEN_WEB_PORT=18280"
  echo "FLUVIUS_DRAIN_SECONDS=30"
  echo "FLUVIUS_FRONTEND_NETWORK=fluvius-core-prod_frontend"
  echo "FLUVIUS_BACKEND_NETWORK=fluvius-core-prod_backend"
  echo "EVOLUTION_GO_MANAGER_PORT=18081"
  echo "UVICORN_WORKERS=4"
  echo "UVICORN_LIMIT_CONCURRENCY=200"
  echo "UVICORN_BACKLOG=2048"
  echo "DELIVERY_WORKER_PROCESSES=4"
  echo "WEBHOOK_WORKER_PROCESSES=3"
  echo
  echo "POSTGRES_DB=fluvius"
  echo "POSTGRES_USER=fluvius"
  echo "POSTGRES_PASSWORD=$(random_secret)"
  echo "REDIS_PASSWORD=$(random_secret)"
  echo
  echo "SECRET_KEY=$(random_secret)"
  echo "PROVIDER_CREDENTIALS_KEY=$(random_secret)"
  echo "WEBHOOK_SECRET=$(random_secret)"
  echo "EVOLUTION_GO_GLOBAL_API_KEY=$(random_secret)"
  echo
  echo "EVOLUTION_GO_API_KEY="
  echo "EVOLUTION_GO_INSTANCE_TOKENS={}"
  echo "EVOLUTION_OPERATOR_EMAIL="
  echo "EVOLUTION_GO_SOURCE_REF=9337afc47e10b86cc896a6f432240e40fee95dd1"
  echo "EVOLUTION_GO_IMAGE=fluvius/evolution-go:0.7.2-connection-pool-fix.3"
} > "$TARGET_FILE"

chmod 600 "$TARGET_FILE"
echo "Ambiente de produção criado em $TARGET_FILE."
echo "Guarde uma cópia segura dos segredos antes do deploy."
