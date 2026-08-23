import importlib
import os
import pkgutil
import sqlite3
import subprocess
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
HEAD_REVISION = "d8a4f2c6b901"
BRIDGE_PARENT_REVISION = "e4c7a1b9d305"
PRE_ALIGNMENT_HEAD_REVISION = "f3a7c9d2e611"

PRODUCTION_ALIGNMENT_INDEXES = {
    "ix_ad_fund_settlements_id": ("ad_fund_settlements", ("id",)),
    "ix_customer_lifecycle_cycles_id": ("customer_lifecycle_cycles", ("id",)),
    "ix_customer_lifecycle_events_id": ("customer_lifecycle_events", ("id",)),
    "ix_customers_sales_lead_id": ("customers", ("sales_lead_id",)),
    "ix_finance_refunds_id": ("finance_refunds", ("id",)),
    "ix_opportunities_id": ("opportunities", ("id",)),
}

BRIDGE_ORM_TABLES = {
    "users",
    "oidc_states",
    "customer_ai_copies",
    "customer_callbacks",
    "customer_materials",
    "customer_menu_items",
    "merchant_ai_analyses",
    "merchant_pool",
    "ringcentral_connections",
    "sales_call_activities",
    "sales_call_ai_analyses",
    "sales_daily_dial_tasks",
    "sales_daily_quotas",
    "sales_quote_requests",
    "sales_handoff_checklists",
    "sales_knowledge_articles",
    "sales_knowledge_questions",
    "sales_lead_assignment_logs",
    "sales_lead_conversion_logs",
    "sales_leads",
}

NON_ORM_PERSISTENT_TABLES = {
    "app_settings",
    "monthly_deduction_rates",
    "monthly_deduction_defaults",
    "monthly_deduction_audits",
}


def _run_alembic(database: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(
        {
            "APP_ENV": "test",
            "DATABASE_URL": f"sqlite:///{database}",
        }
    )
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", *arguments],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, (
        f"alembic {' '.join(arguments)} failed\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    return result


def _run_alembic_expect_failure(
    database: Path,
    *arguments: str,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(
        {
            "APP_ENV": "test",
            "DATABASE_URL": f"sqlite:///{database}",
        }
    )
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", *arguments],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode != 0, f"alembic {' '.join(arguments)} unexpectedly succeeded"
    return result


def _run_production_verify_only(database: Path) -> None:
    environment = os.environ.copy()
    environment.update(
        {
            "APP_ENV": "production",
            "DATABASE_SCHEMA_MODE": "verify_only",
            "DATABASE_URL": f"sqlite:///{database}",
            "PYTHONPATH": str(BACKEND_ROOT),
        }
    )
    program = """
import asyncio
from services.database import close_database, initialize_database

async def main():
    await initialize_database()
    await close_database()

asyncio.run(main())
"""
    result = subprocess.run(
        [sys.executable, "-c", program],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, (
        f"production verify_only failed\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


def _orm_table_names() -> set[str]:
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))
    import models
    from core.database import Base

    for _, module_name, _ in pkgutil.iter_modules(models.__path__):
        importlib.import_module(f"models.{module_name}")
    return set(Base.metadata.tables)


def _database_table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }


def _schema_signature(connection: sqlite3.Connection) -> tuple[tuple[object, ...], ...]:
    objects = connection.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
    ).fetchall()
    version = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    return tuple(objects) + (("alembic_version_value", *version),)


def _copy_bridge_tables(reference: Path, destination: Path) -> None:
    source_connection = sqlite3.connect(reference)
    destination_connection = sqlite3.connect(destination)
    try:
        destination_connection.execute("PRAGMA foreign_keys = OFF")
        for table in sorted(BRIDGE_ORM_TABLES | NON_ORM_PERSISTENT_TABLES):
            create_sql = source_connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()
            assert create_sql and create_sql[0], f"reference table missing: {table}"
            destination_connection.execute(create_sql[0])

            indexes = source_connection.execute(
                "SELECT sql FROM sqlite_master "
                "WHERE type = 'index' AND tbl_name = ? AND sql IS NOT NULL "
                "ORDER BY name",
                (table,),
            ).fetchall()
            for (index_sql,) in indexes:
                destination_connection.execute(index_sql)
        destination_connection.commit()
    finally:
        source_connection.close()
        destination_connection.close()


def test_empty_sqlite_upgrade_head_is_complete_repeatable_and_clean(tmp_path: Path) -> None:
    database = tmp_path / "fresh.sqlite"

    _run_alembic(database, "upgrade", "head")

    connection = sqlite3.connect(database)
    try:
        orm_tables = _orm_table_names()
        database_tables = _database_table_names(connection)

        assert len(orm_tables) == 68
        assert orm_tables <= database_tables
        assert BRIDGE_ORM_TABLES <= database_tables
        assert NON_ORM_PERSISTENT_TABLES <= database_tables
        assert database_tables == orm_tables | NON_ORM_PERSISTENT_TABLES | {"alembic_version"}
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            HEAD_REVISION,
        )
        signature_before_repeat = _schema_signature(connection)
    finally:
        connection.close()

    _run_alembic(database, "upgrade", "head")

    connection = sqlite3.connect(database)
    try:
        assert _schema_signature(connection) == signature_before_repeat
    finally:
        connection.close()

    check = _run_alembic(database, "check")
    assert "No new upgrade operations detected" in check.stdout + check.stderr
    _run_production_verify_only(database)


def test_e4_runtime_bootstrap_reentry_preserves_existing_business_values(tmp_path: Path) -> None:
    reference = tmp_path / "reference-head.sqlite"
    legacy = tmp_path / "runtime-repaired-e4.sqlite"
    _run_alembic(reference, "upgrade", "head")
    _run_alembic(legacy, "upgrade", BRIDGE_PARENT_REVISION)
    _copy_bridge_tables(reference, legacy)

    connection = sqlite3.connect(legacy)
    try:
        connection.execute(
            "INSERT INTO sales_quote_requests ("
            "lead_id, package_name, billing_mode, billing_cycle, payment_method, "
            "currency, list_amount, discount_amount, final_amount, status, submitted_by_id"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (1, "Quarterly plan", "subscription", "quarterly", "stripe", "USD", 249.0, 0.0, 249.0, "submitted", 9),
        )
        connection.execute(
            "INSERT INTO sales_leads ("
            "business_name, phone, status, is_blacklisted, do_not_contact, "
            "automation_state, contact_attempt_count, rotation_count"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("Preserved merchant", "5550100", "new", 0, 0, "manual_hold", 3, 2),
        )
        connection.execute(
            "INSERT INTO app_settings (config_key, value_json) VALUES (?, ?)",
            ("preserved_setting", '{"enabled": true}'),
        )
        connection.commit()
    finally:
        connection.close()

    _run_alembic(legacy, "upgrade", "head")

    connection = sqlite3.connect(legacy)
    try:
        assert connection.execute(
            "SELECT billing_cycle FROM sales_quote_requests WHERE lead_id = 1"
        ).fetchone() == ("quarterly",)
        assert connection.execute(
            "SELECT automation_state, contact_attempt_count, rotation_count "
            "FROM sales_leads WHERE phone = '5550100'"
        ).fetchone() == ("manual_hold", 3, 2)
        assert connection.execute(
            "SELECT value_json FROM app_settings WHERE config_key = 'preserved_setting'"
        ).fetchone() == ('{"enabled": true}',)
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            HEAD_REVISION,
        )
    finally:
        connection.close()

    check = _run_alembic(legacy, "check")
    assert "No new upgrade operations detected" in check.stdout + check.stderr


def test_existing_f3_database_adds_only_expected_indexes_and_preserves_data(tmp_path: Path) -> None:
    database = tmp_path / "production-like-f3.sqlite"
    _run_alembic(database, "upgrade", PRE_ALIGNMENT_HEAD_REVISION)

    connection = sqlite3.connect(database)
    try:
        for index_name, (table_name, _) in PRODUCTION_ALIGNMENT_INDEXES.items():
            existing = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = ? AND tbl_name = ?",
                (index_name, table_name),
            ).fetchone()
            if existing:
                connection.execute(f'DROP INDEX "{index_name}"')
        connection.execute(
            "INSERT INTO app_settings (config_key, value_json) VALUES (?, ?)",
            ("phase0_alignment_sentinel", '{"preserved": true}'),
        )
        connection.commit()
        schema_before = {
            row
            for row in connection.execute(
                "SELECT type, name, tbl_name, sql FROM sqlite_master "
                "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
            ).fetchall()
            if row[1] not in PRODUCTION_ALIGNMENT_INDEXES
        }
        row_counts_before = {
            table_name: connection.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
            for table_name in _database_table_names(connection)
            if table_name != "alembic_version"
        }
    finally:
        connection.close()

    _run_alembic(database, "upgrade", "head")

    connection = sqlite3.connect(database)
    try:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            HEAD_REVISION,
        )
        assert connection.execute(
            "SELECT value_json FROM app_settings WHERE config_key = ?",
            ("phase0_alignment_sentinel",),
        ).fetchone() == ('{"preserved": true}',)

        schema_after = {
            row
            for row in connection.execute(
                "SELECT type, name, tbl_name, sql FROM sqlite_master "
                "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
            ).fetchall()
            if row[1] not in PRODUCTION_ALIGNMENT_INDEXES
        }
        assert len(schema_after) >= len(schema_before)
        assert {
            table_name: connection.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
            for table_name in row_counts_before
        } == row_counts_before
        assert "ringcentral_call_records" in _database_table_names(connection)

        for index_name, (table_name, expected_columns) in PRODUCTION_ALIGNMENT_INDEXES.items():
            index_rows = connection.execute(f'PRAGMA index_list("{table_name}")').fetchall()
            matched = [row for row in index_rows if row[1] == index_name]
            assert len(matched) == 1
            assert matched[0][2] == 0
            actual_columns = tuple(
                row[2]
                for row in connection.execute(f'PRAGMA index_info("{index_name}")').fetchall()
            )
            assert actual_columns == expected_columns

        for table_name, column_name in (
            ("deals", "opportunity_id"),
            ("opportunities", "opportunity_code"),
        ):
            assert any(
                row[2] == 1
                and tuple(
                    item[2]
                    for item in connection.execute(f'PRAGMA index_info("{row[1]}")').fetchall()
                ) == (column_name,)
                for row in connection.execute(f'PRAGMA index_list("{table_name}")').fetchall()
            )

        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()

    check = _run_alembic(database, "check")
    assert "No new upgrade operations detected" in check.stdout + check.stderr


def test_alignment_downgrade_is_rejected_before_any_schema_change(tmp_path: Path) -> None:
    database = tmp_path / "alignment-downgrade.sqlite"
    _run_alembic(database, "upgrade", "head")

    connection = sqlite3.connect(database)
    try:
        signature_before = _schema_signature(connection)
    finally:
        connection.close()

    failure = _run_alembic_expect_failure(
        database,
        "downgrade",
        PRE_ALIGNMENT_HEAD_REVISION,
    )
    assert "intentionally irreversible" in failure.stdout + failure.stderr

    connection = sqlite3.connect(database)
    try:
        assert _schema_signature(connection) == signature_before
    finally:
        connection.close()


def test_bridge_downgrade_is_rejected_before_any_schema_or_data_change(tmp_path: Path) -> None:
    database = tmp_path / "bridge-downgrade.sqlite"
    _run_alembic(database, "upgrade", "e5f8a1c3d702")

    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "INSERT INTO app_settings (config_key, value_json) VALUES (?, ?)",
            ("downgrade_sentinel", '{"preserved": true}'),
        )
        connection.commit()
        signature_before = _schema_signature(connection)
    finally:
        connection.close()

    failure = _run_alembic_expect_failure(database, "downgrade", BRIDGE_PARENT_REVISION)
    assert "intentionally irreversible" in failure.stdout + failure.stderr

    connection = sqlite3.connect(database)
    try:
        assert _schema_signature(connection) == signature_before
        assert connection.execute(
            "SELECT value_json FROM app_settings WHERE config_key = 'downgrade_sentinel'"
        ).fetchone() == ('{"preserved": true}',)
    finally:
        connection.close()
