#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/t24-crm/app}"
BACKUP_DIR="${BACKUP_DIR:-$APP_DIR/backups}"
BACKUP_FILE="${BACKUP_FILE:-}"

if [ -z "$BACKUP_FILE" ]; then
  BACKUP_FILE="$(find "$BACKUP_DIR" -maxdepth 1 -type f -name 'crm_prod_*.db.gz' -print | sort | tail -n 1)"
fi

if [ -z "$BACKUP_FILE" ] || [ ! -f "$BACKUP_FILE" ]; then
  echo "No SQLite backup archive found in $BACKUP_DIR" >&2
  exit 1
fi

umask 077
restore_dir="$(mktemp -d "${TMPDIR:-/tmp}/t24-crm-restore.XXXXXX")"
restored_db="$restore_dir/restored.db"
cleanup() {
  rm -rf "$restore_dir"
}
trap cleanup EXIT

if [ -f "${BACKUP_FILE}.sha256" ]; then
  if command -v sha256sum >/dev/null 2>&1; then
    (cd "$(dirname "$BACKUP_FILE")" && sha256sum -c "$(basename "${BACKUP_FILE}.sha256")")
  elif command -v shasum >/dev/null 2>&1; then
    expected="$(awk '{print $1}' "${BACKUP_FILE}.sha256")"
    actual="$(shasum -a 256 "$BACKUP_FILE" | awk '{print $1}')"
    [ "$expected" = "$actual" ] || { echo "Backup checksum mismatch" >&2; exit 1; }
  else
    echo "No SHA-256 utility available" >&2
    exit 1
  fi
else
  echo "Backup checksum file is missing: ${BACKUP_FILE}.sha256" >&2
  exit 1
fi

gzip -t "$BACKUP_FILE"
gzip -dc "$BACKUP_FILE" > "$restored_db"

python_bin=""
if command -v python3 >/dev/null 2>&1; then
  python_bin="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  python_bin="$(command -v python)"
fi

if [ -n "$python_bin" ]; then
  "$python_bin" - "$restored_db" <<'PY'
import sqlite3
import sys

database_path = sys.argv[1]
connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
try:
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        raise SystemExit(f"Restored database integrity check failed: {integrity}")
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    required = {"customers", "deals", "payments", "employees"}
    missing = sorted(required - tables)
    if missing:
        raise SystemExit(f"Restored database is missing required tables: {', '.join(missing)}")
    counts = {
        table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        for table in sorted(required)
    }
    print("Restore drill verified:", ", ".join(f"{key}={value}" for key, value in counts.items()))
finally:
    connection.close()
PY
elif command -v sqlite3 >/dev/null 2>&1; then
  integrity="$(sqlite3 "$restored_db" "PRAGMA integrity_check;")"
  [ "$integrity" = "ok" ] || { echo "Restored database integrity check failed: $integrity" >&2; exit 1; }
  echo "Restore drill verified: SQLite integrity is ok"
else
  echo "Restore verification failed: neither Python nor sqlite3 is available" >&2
  exit 1
fi

echo "Source archive: $BACKUP_FILE"
