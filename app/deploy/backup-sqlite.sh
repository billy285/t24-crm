#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/t24-crm/app}"
DB_FILE="${DB_FILE:-$APP_DIR/data/crm_prod.db}"
BACKUP_DIR="${BACKUP_DIR:-$APP_DIR/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

mkdir -p "$BACKUP_DIR"

if [ ! -f "$DB_FILE" ]; then
  echo "Database file not found: $DB_FILE" >&2
  exit 1
fi

timestamp="$(date +%Y%m%d_%H%M%S)"
backup_file="$BACKUP_DIR/crm_prod_${timestamp}.db"

sqlite3 "$DB_FILE" ".backup '$backup_file'"
gzip "$backup_file"

find "$BACKUP_DIR" -name "crm_prod_*.db.gz" -mtime +"$RETENTION_DAYS" -delete
echo "Backup written: ${backup_file}.gz"
