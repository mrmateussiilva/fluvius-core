#!/usr/bin/env bash
set -euo pipefail

CONFIG_FILE=${FLUVIUS_BACKUP_CONFIG:-/etc/fluvius/backup.conf}
source "$CONFIG_FILE"
export RESTIC_REPOSITORY="$FLUVIUS_DATA_DIR/backups/restic"
export RESTIC_PASSWORD_FILE

restic snapshots --latest 1
restic check --read-data-subset=5%
