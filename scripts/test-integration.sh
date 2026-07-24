#!/bin/sh
set -eu

PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
COMPOSE_FILE="$PROJECT_ROOT/docker-compose.test.yml"

cleanup() {
  docker compose -f "$COMPOSE_FILE" down -v --remove-orphans
}

trap cleanup EXIT INT TERM

docker compose -f "$COMPOSE_FILE" up \
  --build \
  --abort-on-container-exit \
  --exit-code-from api-test
