#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "Execute este script como root." >&2
  exit 1
fi

PROJECT_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
DATA_DIR=${FLUVIUS_DATA_DIR:-/srv/fluvius}
ENABLE_FIREWALL=${1:-}

source /etc/os-release
if [[ ${ID:-} != "ubuntu" ]]; then
  echo "Este instalador foi preparado para Ubuntu." >&2
  exit 1
fi

apt-get update
apt-get install -y ca-certificates curl gnupg openssl restic rsync ufw
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y \
  containerd.io \
  docker-buildx-plugin \
  docker-ce \
  docker-ce-cli \
  docker-compose-plugin
systemctl enable --now docker

install -d -m 0750 \
  "$DATA_DIR/postgres" \
  "$DATA_DIR/redis" \
  "$DATA_DIR/media" \
  "$DATA_DIR/backups"
chown -R 999:999 "$DATA_DIR/postgres" "$DATA_DIR/redis"
chown -R 10001:10001 "$DATA_DIR/media"

install -d -m 0700 /etc/fluvius
if [[ ! -f /etc/fluvius/restic-password ]]; then
  openssl rand -hex 32 > /etc/fluvius/restic-password
  chmod 600 /etc/fluvius/restic-password
fi
{
  echo "FLUVIUS_PROJECT_DIR=$PROJECT_ROOT"
  echo "FLUVIUS_ENV_FILE=$PROJECT_ROOT/.env.production"
  echo "FLUVIUS_DATA_DIR=$DATA_DIR"
  echo "RESTIC_PASSWORD_FILE=/etc/fluvius/restic-password"
} > /etc/fluvius/backup.conf
chmod 600 /etc/fluvius/backup.conf

ln -sfn "$PROJECT_ROOT/deploy/scripts/backup.sh" /usr/local/sbin/fluvius-backup
ln -sfn "$PROJECT_ROOT/deploy/scripts/verify-backup.sh" /usr/local/sbin/fluvius-verify-backup
install -m 0644 \
  "$PROJECT_ROOT/deploy/systemd/fluvius-backup.service" \
  /etc/systemd/system/fluvius-backup.service
install -m 0644 \
  "$PROJECT_ROOT/deploy/systemd/fluvius-backup.timer" \
  /etc/systemd/system/fluvius-backup.timer
systemctl daemon-reload
systemctl enable --now fluvius-backup.timer

if ! command -v caddy >/dev/null 2>&1; then
  echo "Caddy não encontrado no host. Instale-o antes do deploy público."
fi

if [[ "$ENABLE_FIREWALL" == "--enable-firewall" ]]; then
  ufw default deny incoming
  ufw default allow outgoing
  ufw allow "${SSH_PORT:-22}/tcp"
  ufw allow 80/tcp
  ufw allow 443/tcp
  ufw allow 443/udp
  ufw --force enable
else
  echo "Firewall não alterado. Rode novamente com --enable-firewall após confirmar a porta SSH."
fi

echo "Ubuntu preparado. Próximo passo: gere .env.production e execute production-deploy.sh vX.Y.Z."
