import importlib
import logging
import os
import pkgutil
import time
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from core.database import Base, db_manager
from services.schema_readiness import RUNTIME_REQUIRED_TABLE_COLUMNS
from sqlalchemy import inspect, text

logger = logging.getLogger(__name__)

LEGACY_RUNTIME_SCHEMA_MODE = "legacy_runtime"
VERIFY_ONLY_SCHEMA_MODE = "verify_only"
CONNECT_ONLY_SCHEMA_MODE = "connect_only"
SUPPORTED_SCHEMA_MODES = {
    LEGACY_RUNTIME_SCHEMA_MODE,
    VERIFY_ONLY_SCHEMA_MODE,
    CONNECT_ONLY_SCHEMA_MODE,
}
PRODUCTION_ENVIRONMENTS = {"prod", "production"}


def is_production_runtime() -> bool:
    """Return whether schema mutation must be forbidden for this process."""

    environment_values = {
        (os.getenv("APP_ENV") or "").strip().lower(),
        (os.getenv("ENVIRONMENT") or "").strip().lower(),
        (os.getenv("ENV") or "").strip().lower(),
    }
    is_lambda = bool(
        os.getenv("AWS_LAMBDA_FUNCTION_NAME")
        or (os.getenv("IS_LAMBDA") or "").strip().lower() in {"1", "true", "yes"}
    )
    return bool(environment_values & PRODUCTION_ENVIRONMENTS) or is_lambda


def resolve_database_schema_mode() -> str:
    """Resolve the startup schema policy with production-safe defaults."""

    configured_mode = (os.getenv("DATABASE_SCHEMA_MODE") or "").strip().lower()
    production_runtime = is_production_runtime()

    if configured_mode and configured_mode not in SUPPORTED_SCHEMA_MODES:
        supported = ", ".join(sorted(SUPPORTED_SCHEMA_MODES))
        raise RuntimeError(f"Unsupported DATABASE_SCHEMA_MODE={configured_mode!r}; expected one of: {supported}")

    if production_runtime:
        if configured_mode and configured_mode != VERIFY_ONLY_SCHEMA_MODE:
            raise RuntimeError(
                "Production and Lambda runtimes require DATABASE_SCHEMA_MODE=verify_only; "
                "runtime schema creation and repair are forbidden"
            )
        if "MGX_IGNORE_INIT_DB" in os.environ:
            logger.warning(
                "MGX_IGNORE_INIT_DB is deprecated and cannot disable production database initialization; "
                "using verify_only"
            )
        return VERIFY_ONLY_SCHEMA_MODE

    if configured_mode:
        return configured_mode

    if "MGX_IGNORE_INIT_DB" in os.environ:
        logger.warning(
            "MGX_IGNORE_INIT_DB is deprecated; the database connection will still be initialized "
            "and schema handling will use connect_only"
        )
        return CONNECT_ONLY_SCHEMA_MODE

    return LEGACY_RUNTIME_SCHEMA_MODE


def _load_all_models() -> None:
    models_package = importlib.import_module("models")
    for module_info in pkgutil.iter_modules(models_package.__path__, models_package.__name__ + "."):
        importlib.import_module(module_info.name)


def _alembic_heads() -> set[str]:
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    return set(ScriptDirectory.from_config(config).get_heads())


async def verify_database_schema() -> None:
    """Verify Alembic revision and ORM table presence without writing to the DB."""

    if db_manager.engine is None:
        raise RuntimeError("Database engine is not initialized")

    _load_all_models()
    expected_heads = _alembic_heads()
    if not expected_heads:
        raise RuntimeError("Alembic has no configured head revision")

    expected_columns = {
        table.name: {column.name for column in table.columns}
        for table in Base.metadata.tables.values()
    }
    expected_columns.update(
        {table_name: set(columns) for table_name, columns in RUNTIME_REQUIRED_TABLE_COLUMNS.items()}
    )
    expected_tables = set(expected_columns)

    async with db_manager.engine.connect() as connection:
        def inspect_schema(sync_connection):
            inspector = inspect(sync_connection)
            table_names = set(inspector.get_table_names())
            actual_columns = {
                table_name: {column["name"] for column in inspector.get_columns(table_name)}
                for table_name in expected_tables & table_names
            }
            if "alembic_version" not in table_names:
                return table_names, actual_columns, set()
            revisions = set(sync_connection.execute(text("SELECT version_num FROM alembic_version")).scalars())
            return table_names, actual_columns, revisions

        actual_tables, actual_columns, actual_revisions = await connection.run_sync(inspect_schema)

    if "alembic_version" not in actual_tables:
        raise RuntimeError(
            "Database schema verification failed: alembic_version is missing; "
            "run Alembic migrations before starting the application"
        )

    if actual_revisions != expected_heads:
        expected = ", ".join(sorted(expected_heads))
        actual = ", ".join(sorted(actual_revisions)) or "none"
        raise RuntimeError(
            f"Database schema verification failed: Alembic revision is {actual}; expected {expected}"
        )

    missing_tables = expected_tables - actual_tables
    if missing_tables:
        missing = ", ".join(sorted(missing_tables))
        raise RuntimeError(f"Database schema verification failed: missing required tables: {missing}")

    missing_columns = {
        table_name: required_columns - actual_columns.get(table_name, set())
        for table_name, required_columns in expected_columns.items()
        if required_columns - actual_columns.get(table_name, set())
    }
    if missing_columns:
        rendered = "; ".join(
            f"{table_name}({', '.join(sorted(columns))})"
            for table_name, columns in sorted(missing_columns.items())
        )
        raise RuntimeError(f"Database schema verification failed: missing required columns: {rendered}")

    logger.info(
        "Database schema verified at Alembic head %s with %d required tables",
        ", ".join(sorted(expected_heads)),
        len(expected_tables),
    )


async def check_database_health() -> bool:
    """Check if database is healthy"""
    start_time = time.time()
    logger.debug("[DB_OP] Starting database health check")
    try:
        if not db_manager.async_session_maker:
            return False

        async with db_manager.async_session_maker() as session:
            await session.execute(text("SELECT 1"))
            logger.debug(f"[DB_OP] Database health check completed in {time.time() - start_time:.4f}s - healthy: True")
            return True
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        logger.debug(f"[DB_OP] Database health check failed in {time.time() - start_time:.4f}s - healthy: False")
        return False


async def initialize_database_connection() -> None:
    """Initialize only the engine and session factory."""

    await db_manager.init_db()


async def prepare_runtime_schema(schema_mode: str | None = None) -> str:
    """Apply the selected startup schema policy after a connection exists."""

    resolved_mode = schema_mode or resolve_database_schema_mode()
    if resolved_mode not in SUPPORTED_SCHEMA_MODES:
        raise RuntimeError(f"Unsupported database schema mode: {resolved_mode}")
    if is_production_runtime() and resolved_mode != VERIFY_ONLY_SCHEMA_MODE:
        raise RuntimeError("Production and Lambda runtimes forbid runtime schema creation and repair")

    if resolved_mode == LEGACY_RUNTIME_SCHEMA_MODE:
        await db_manager.create_tables()
    elif resolved_mode == VERIFY_ONLY_SCHEMA_MODE:
        await verify_database_schema()
    else:
        logger.warning("Database schema handling is disabled by connect_only mode")
    return resolved_mode


async def initialize_database() -> None:
    """Initialize the connection, then enforce the configured schema policy."""

    start_time = time.time()
    logger.debug("[DB_OP] Starting database initialization")
    try:
        logger.info("🔧 Starting database initialization...")
        schema_mode = resolve_database_schema_mode()
        await initialize_database_connection()
        await prepare_runtime_schema(schema_mode)
        logger.info("Database initialized successfully")
        logger.info("Database schema startup mode: %s", schema_mode)
        logger.debug(f"[DB_OP] Database initialization completed in {time.time() - start_time:.4f}s")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise


async def close_database():
    """Close database connections"""
    start_time = time.time()
    logger.debug("[DB_OP] Starting database close")
    try:
        await db_manager.close_db()
        logger.info("Database connections closed")
        logger.debug(f"[DB_OP] Database close completed in {time.time() - start_time:.4f}s")
    except Exception as e:
        logger.error(f"Error closing database: {e}")
        logger.debug(f"[DB_OP] Database close failed in {time.time() - start_time:.4f}s")
