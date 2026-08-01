#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/t24-crm/app}"
DB_FILE="${DB_FILE:-$APP_DIR/data/crm_prod.db}"
BACKUP_DIR="${BACKUP_DIR:-$APP_DIR/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

umask 077

mkdir -p "$BACKUP_DIR"

if [ ! -f "$DB_FILE" ]; then
  echo "Database file not found: $DB_FILE" >&2
  exit 1
fi

timestamp="$(date +%Y%m%d_%H%M%S)"
backup_file="$BACKUP_DIR/crm_prod_${timestamp}.db"
partial_file="$BACKUP_DIR/.crm_prod_${timestamp}.db.partial"
archive_file="${backup_file}.gz"

cleanup_incomplete_backup() {
  rm -f "$partial_file" "$backup_file" "$archive_file" "${archive_file}.sha256"
}
trap cleanup_incomplete_backup EXIT

python_bin=""
if command -v python3 >/dev/null 2>&1; then
  python_bin="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  python_bin="$(command -v python)"
fi

if [ "${BACKUP_FORCE_PYTHON:-false}" != "true" ] && command -v sqlite3 >/dev/null 2>&1; then
  sqlite3 "$DB_FILE" ".backup '$partial_file'"
elif [ -n "$python_bin" ]; then
  "$python_bin" - "$DB_FILE" "$partial_file" <<'PY'
import sqlite3
import sys

source = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
target = sqlite3.connect(sys.argv[2])
try:
    source.backup(target)
finally:
    target.close()
    source.close()
PY
else
  echo "Backup failed: neither sqlite3 nor Python with sqlite3 support is available" >&2
  exit 1
fi

if [ -n "$python_bin" ]; then
  integrity_result="$($python_bin - "$partial_file" <<'PY'
import sqlite3
import sys

connection = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
try:
    print(connection.execute("PRAGMA integrity_check").fetchone()[0])
finally:
    connection.close()
PY
)"
else
  integrity_result="$(sqlite3 "$partial_file" "PRAGMA integrity_check;")"
fi

if [ "$integrity_result" != "ok" ]; then
  echo "Backup integrity check failed: $integrity_result" >&2
  exit 1
fi

mv "$partial_file" "$backup_file"
gzip "$backup_file"
gzip -t "$archive_file"
chmod 600 "$archive_file"

if command -v sha256sum >/dev/null 2>&1; then
  sha256sum "$archive_file" > "${archive_file}.sha256"
elif command -v shasum >/dev/null 2>&1; then
  shasum -a 256 "$archive_file" > "${archive_file}.sha256"
fi

find "$BACKUP_DIR" -name "crm_prod_*.db.gz" -mtime +"$RETENTION_DAYS" -delete
find "$BACKUP_DIR" -name "crm_prod_*.db.gz.sha256" -mtime +"$RETENTION_DAYS" -delete

trap - EXIT
echo "Backup verified: $archive_file"
