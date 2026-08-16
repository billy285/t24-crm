import re
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from core.database import Base, DatabaseManager, db_manager
from services import database as database_service


RUNTIME_ENV_KEYS = (
    "APP_ENV",
    "ENVIRONMENT",
    "ENV",
    "AWS_LAMBDA_FUNCTION_NAME",
    "IS_LAMBDA",
    "DATABASE_SCHEMA_MODE",
    "MGX_IGNORE_INIT_DB",
)


def test_runtime_source_has_no_request_time_table_ddl_literals():
    backend_dir = Path(__file__).resolve().parents[1]
    create_table_offenders: list[str] = []
    request_ddl_offenders: list[str] = []

    for source_path in backend_dir.rglob("*.py"):
        relative_path = source_path.relative_to(backend_dir)
        if relative_path.parts[0] in {"alembic", "tests"}:
            continue
        source = source_path.read_text(encoding="utf-8").upper()
        if re.search(r"\bCREATE\s+TABLE\b", source):
            create_table_offenders.append(str(relative_path))
        request_has_ddl = bool(
            re.search(r"\b(?:CREATE|ALTER|DROP)\s+TABLE\b", source)
            or "METADATA.CREATE_ALL" in source
        )
        if relative_path.parts[0] in {"routers", "services"} and request_has_ddl:
            request_ddl_offenders.append(str(relative_path))

    assert create_table_offenders == []
    assert request_ddl_offenders == []


def clear_runtime_environment(monkeypatch) -> None:
    for key in RUNTIME_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


@pytest.mark.asyncio
async def test_development_default_keeps_legacy_runtime_schema_handling(monkeypatch):
    clear_runtime_environment(monkeypatch)
    monkeypatch.setenv("APP_ENV", "development")
    init_db = AsyncMock()
    create_tables = AsyncMock()
    verify_schema = AsyncMock()
    monkeypatch.setattr(db_manager, "init_db", init_db)
    monkeypatch.setattr(db_manager, "create_tables", create_tables)
    monkeypatch.setattr(database_service, "verify_database_schema", verify_schema)

    await database_service.initialize_database()

    init_db.assert_awaited_once()
    create_tables.assert_awaited_once()
    verify_schema.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_ignore_flag_still_initializes_connection_without_schema_mutation(monkeypatch):
    clear_runtime_environment(monkeypatch)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("MGX_IGNORE_INIT_DB", "1")
    init_db = AsyncMock()
    create_tables = AsyncMock()
    verify_schema = AsyncMock()
    monkeypatch.setattr(db_manager, "init_db", init_db)
    monkeypatch.setattr(db_manager, "create_tables", create_tables)
    monkeypatch.setattr(database_service, "verify_database_schema", verify_schema)

    await database_service.initialize_database()

    init_db.assert_awaited_once()
    create_tables.assert_not_awaited()
    verify_schema.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("environment_key", "environment_value"),
    (("APP_ENV", "production"), ("AWS_LAMBDA_FUNCTION_NAME", "crm-handler")),
)
async def test_production_and_lambda_default_to_verify_only(
    monkeypatch,
    environment_key,
    environment_value,
):
    clear_runtime_environment(monkeypatch)
    monkeypatch.setenv(environment_key, environment_value)
    init_db = AsyncMock()
    create_tables = AsyncMock()
    verify_schema = AsyncMock()
    monkeypatch.setattr(db_manager, "init_db", init_db)
    monkeypatch.setattr(db_manager, "create_tables", create_tables)
    monkeypatch.setattr(database_service, "verify_database_schema", verify_schema)

    await database_service.initialize_database()

    init_db.assert_awaited_once()
    verify_schema.assert_awaited_once()
    create_tables.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("unsafe_mode", ("legacy_runtime", "connect_only"))
async def test_production_rejects_non_verifying_schema_modes_before_connect(monkeypatch, unsafe_mode):
    clear_runtime_environment(monkeypatch)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_SCHEMA_MODE", unsafe_mode)
    init_db = AsyncMock()
    create_tables = AsyncMock()
    monkeypatch.setattr(db_manager, "init_db", init_db)
    monkeypatch.setattr(db_manager, "create_tables", create_tables)

    with pytest.raises(RuntimeError, match="require DATABASE_SCHEMA_MODE=verify_only"):
        await database_service.initialize_database()

    init_db.assert_not_awaited()
    create_tables.assert_not_awaited()


@pytest.mark.asyncio
async def test_database_manager_hard_blocks_creation_and_repair_in_production(monkeypatch):
    clear_runtime_environment(monkeypatch)
    monkeypatch.setenv("APP_ENV", "production")
    manager = DatabaseManager()

    with pytest.raises(RuntimeError, match="schema creation is disabled"):
        await manager.create_tables()
    with pytest.raises(RuntimeError, match="schema repair is disabled"):
        await manager.check_and_repair_existing_tables()


async def _schema_test_engine(
    revision: str,
    *,
    create_orm_tables: bool,
    create_runtime_tables: bool = False,
):
    database_service._load_all_models()
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        if create_orm_tables:
            await connection.run_sync(Base.metadata.create_all)
        if create_runtime_tables:
            await connection.execute(
                text(
                    """
                    CREATE TABLE app_settings (
                      config_key TEXT PRIMARY KEY,
                      value_json TEXT NOT NULL,
                      updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    CREATE TABLE monthly_deduction_rates (
                      id INTEGER PRIMARY KEY,
                      year_month DATE UNIQUE NOT NULL,
                      rate NUMERIC(5,4) NOT NULL,
                      created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                      updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    CREATE TABLE monthly_deduction_defaults (
                      id INTEGER PRIMARY KEY,
                      rate NUMERIC(5,4) NOT NULL DEFAULT 0.15,
                      updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    CREATE TABLE monthly_deduction_audits (
                      id INTEGER PRIMARY KEY,
                      action TEXT NOT NULL,
                      actor_id BIGINT,
                      before_json TEXT,
                      after_json TEXT,
                      at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
        await connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        await connection.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
            {"revision": revision},
        )
    return engine


@pytest.mark.asyncio
async def test_verify_only_rejects_database_behind_alembic_head(monkeypatch):
    engine = await _schema_test_engine("old_revision", create_orm_tables=False)
    monkeypatch.setattr(db_manager, "engine", engine)
    monkeypatch.setattr(database_service, "_alembic_heads", lambda: {"expected_head"})
    try:
        with pytest.raises(RuntimeError, match="Alembic revision is old_revision; expected expected_head"):
            await database_service.verify_database_schema()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_verify_only_rejects_missing_orm_tables(monkeypatch):
    engine = await _schema_test_engine("expected_head", create_orm_tables=False)
    monkeypatch.setattr(db_manager, "engine", engine)
    monkeypatch.setattr(database_service, "_alembic_heads", lambda: {"expected_head"})
    try:
        with pytest.raises(RuntimeError, match="missing required tables"):
            await database_service.verify_database_schema()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_verify_only_accepts_current_complete_schema_without_writes(monkeypatch):
    engine = await _schema_test_engine(
        "expected_head",
        create_orm_tables=True,
        create_runtime_tables=True,
    )
    statements: list[str] = []

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def record_statement(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement.strip().upper())

    monkeypatch.setattr(db_manager, "engine", engine)
    monkeypatch.setattr(database_service, "_alembic_heads", lambda: {"expected_head"})
    try:
        await database_service.verify_database_schema()
    finally:
        await engine.dispose()

    forbidden_prefixes = ("CREATE ", "ALTER ", "DROP ", "INSERT ", "UPDATE ", "DELETE ")
    assert not any(statement.startswith(forbidden_prefixes) for statement in statements)


@pytest.mark.asyncio
async def test_verify_only_rejects_missing_non_orm_runtime_tables_without_writes(monkeypatch):
    engine = await _schema_test_engine("expected_head", create_orm_tables=True)
    statements: list[str] = []

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def record_statement(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement.strip().upper())

    monkeypatch.setattr(db_manager, "engine", engine)
    monkeypatch.setattr(database_service, "_alembic_heads", lambda: {"expected_head"})
    try:
        with pytest.raises(RuntimeError, match="missing required tables: app_settings"):
            await database_service.verify_database_schema()
    finally:
        await engine.dispose()

    forbidden_prefixes = ("CREATE ", "ALTER ", "DROP ", "INSERT ", "UPDATE ", "DELETE ")
    assert not any(statement.startswith(forbidden_prefixes) for statement in statements)


@pytest.mark.asyncio
async def test_verify_only_rejects_missing_required_column_without_writes(monkeypatch):
    engine = await _schema_test_engine(
        "expected_head",
        create_orm_tables=True,
        create_runtime_tables=True,
    )
    async with engine.begin() as connection:
        await connection.execute(text("ALTER TABLE customers DROP COLUMN notes"))

    statements: list[str] = []

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def record_statement(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement.strip().upper())

    monkeypatch.setattr(db_manager, "engine", engine)
    monkeypatch.setattr(database_service, "_alembic_heads", lambda: {"expected_head"})
    try:
        with pytest.raises(RuntimeError, match=r"missing required columns: customers\(notes\)"):
            await database_service.verify_database_schema()
    finally:
        await engine.dispose()

    forbidden_prefixes = ("CREATE ", "ALTER ", "DROP ", "INSERT ", "UPDATE ", "DELETE ")
    assert not any(statement.startswith(forbidden_prefixes) for statement in statements)


@pytest.mark.asyncio
async def test_verify_only_rejects_missing_non_orm_required_column_without_writes(monkeypatch):
    engine = await _schema_test_engine(
        "expected_head",
        create_orm_tables=True,
        create_runtime_tables=True,
    )
    async with engine.begin() as connection:
        await connection.execute(text("ALTER TABLE app_settings DROP COLUMN value_json"))

    statements: list[str] = []

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def record_statement(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement.strip().upper())

    monkeypatch.setattr(db_manager, "engine", engine)
    monkeypatch.setattr(database_service, "_alembic_heads", lambda: {"expected_head"})
    try:
        with pytest.raises(
            RuntimeError,
            match=r"missing required columns: app_settings\(value_json\)",
        ):
            await database_service.verify_database_schema()
    finally:
        await engine.dispose()

    forbidden_prefixes = ("CREATE ", "ALTER ", "DROP ", "INSERT ", "UPDATE ", "DELETE ")
    assert not any(statement.startswith(forbidden_prefixes) for statement in statements)
