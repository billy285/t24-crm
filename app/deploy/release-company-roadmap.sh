#!/bin/bash

set -euo pipefail

cd /opt/t24-crm/app

TARGET="${TARGET:?TARGET is required}"
EXPECTED_PRE_MIGRATION="d5a9f7b2c604"
EXPECTED_POST_MIGRATION="e2c6b8d4a105"

test "$(git rev-parse HEAD)" = "$TARGET"
test "$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' t24-crm)" = healthy

python3 - <<'PY'
import sqlite3

connection = sqlite3.connect("data/crm_prod.db")
try:
    quick_check = connection.execute("pragma quick_check").fetchone()[0]
    revision = connection.execute("select version_num from alembic_version").fetchone()[0]
    counts = {
        table: connection.execute(f"select count(*) from {table}").fetchone()[0]
        for table in ("customers", "payments", "subscriptions", "deals", "employees")
    }
    print(f"PRE_DB_CHECK={quick_check}")
    print(f"PRE_ALEMBIC={revision}")
    print(f"PRE_COUNTS={counts}")
    assert quick_check == "ok"
    assert revision == "d5a9f7b2c604"
finally:
    connection.close()
PY

APP_DIR=/opt/t24-crm/app bash ./deploy/backup-sqlite.sh
LATEST="$(ls -1t backups/crm_prod_*.db.gz | head -1)"
gzip -t "$LATEST"
APP_DIR=/opt/t24-crm/app \
  BACKUP_FILE="/opt/t24-crm/app/$LATEST" \
  bash ./deploy/verify-backup-restore.sh

OLD_IMAGE="$(docker inspect -f '{{.Image}}' t24-crm)"
IMAGE_NAME="$(docker inspect -f '{{.Config.Image}}' t24-crm)"

docker compose --env-file .env.production build crm
docker compose --env-file .env.production run --rm crm alembic upgrade head

python3 - <<'PY'
import sqlite3

connection = sqlite3.connect("data/crm_prod.db")
try:
    quick_check = connection.execute("pragma quick_check").fetchone()[0]
    revision = connection.execute("select version_num from alembic_version").fetchone()[0]
    required = {
        "company_strategy_settings", "cash_accounts", "cash_periods",
        "cash_account_balances", "cash_restrictions", "cash_audit_logs",
        "strategy_recommendation_decisions",
    }
    actual = {row[0] for row in connection.execute(
        "select name from sqlite_master where type='table'"
    )}
    missing = sorted(required - actual)
    print(f"MIGRATION_DB_CHECK={quick_check}")
    print(f"MIGRATION_ALEMBIC={revision}")
    print(f"MISSING_TABLES={missing}")
    assert quick_check == "ok"
    assert revision == "e2c6b8d4a105"
    assert not missing
finally:
    connection.close()
PY

docker compose --env-file .env.production up -d --no-build --force-recreate crm

READY=0
for _ in $(seq 1 60); do
  HEALTH="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' t24-crm 2>/dev/null || true)"
  if [ "$HEALTH" = healthy ]; then
    READY=1
    break
  fi
  if [ "$HEALTH" = unhealthy ]; then
    break
  fi
  sleep 2
done

if [ "$READY" -ne 1 ]; then
  docker logs --tail 180 t24-crm || true
  docker tag "$OLD_IMAGE" "$IMAGE_NAME"
  docker compose --env-file .env.production up -d --no-build --force-recreate crm
  exit 91
fi

curl -fsS --max-time 20 http://127.0.0.1:8000/health
curl -fsS --max-time 20 http://127.0.0.1:8000/ready
docker exec t24-crm sh -lc 'grep -Rqs "公司战略与里程碑" /app/frontend/dist/assets'

python3 - <<'PY'
import sqlite3

connection = sqlite3.connect("data/crm_prod.db")
try:
    quick_check = connection.execute("pragma quick_check").fetchone()[0]
    revision = connection.execute("select version_num from alembic_version").fetchone()[0]
    counts = {
        table: connection.execute(f"select count(*) from {table}").fetchone()[0]
        for table in ("customers", "payments", "subscriptions", "deals", "employees")
    }
    print(f"POST_DB_CHECK={quick_check}")
    print(f"POST_ALEMBIC={revision}")
    print(f"POST_COUNTS={counts}")
    assert quick_check == "ok"
    assert revision == "e2c6b8d4a105"
finally:
    connection.close()
PY

curl -fsS --max-time 25 https://t24-crm.com/health
HOME_CODE="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 25 https://t24-crm.com/)"
ROADMAP_CODE="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 25 https://t24-crm.com/company-roadmap)"
UNAUTH_ROADMAP_CODE="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 20 http://127.0.0.1:8000/api/v1/company-roadmap/overview)"

echo "STATUS=home:$HOME_CODE,roadmap:$ROADMAP_CODE,unauth_roadmap:$UNAUTH_ROADMAP_CODE"
test "$HOME_CODE" = 200
test "$ROADMAP_CODE" = 200
test "$UNAUTH_ROADMAP_CODE" = 401

ERROR_LINES="$(docker logs --since 8m --tail 350 t24-crm 2>&1 | grep -Ei 'exception|traceback|critical' | tail -50 || true)"
test -z "$ERROR_LINES" || {
  echo "$ERROR_LINES"
  exit 92
}

echo "BACKUP=$LATEST"
echo "TARGET=$TARGET"
echo "MIGRATION=$EXPECTED_POST_MIGRATION"
echo "DEPLOY=PASS"
