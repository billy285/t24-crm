import logging
import os
import time
from pathlib import Path

from core.database import db_manager
from core.config import settings
from sqlalchemy import text

logger = logging.getLogger(__name__)

SQLITE_FALLBACK_PATH = Path(os.environ.get("SQLITE_FALLBACK_PATH", "/tmp/t24-crm-demo.db"))


def _set_database_url(url: str) -> None:
    """Update both os.environ and the cached settings attribute."""
    os.environ["DATABASE_URL"] = url
    settings.__dict__["database_url"] = url


def _should_use_sqlite_fallback(exc: Exception) -> bool:
    """Allow Render demo deployments to recover from broken Postgres credentials."""
    if os.environ.get("DISABLE_SQLITE_STARTUP_FALLBACK", "").lower() in ("1", "true", "yes"):
        return False

    current_url = os.environ.get("DATABASE_URL", "")
    if current_url.startswith("sqlite"):
        return False

    msg = str(exc).lower()
    render_hint = bool(
        os.environ.get("RENDER")
        or os.environ.get("RENDER_SERVICE_ID")
        or os.environ.get("RENDER_EXTERNAL_URL")
    )
    known_db_connection_errors = (
        "password authentication failed",
        "invalidpassworderror",
        "could not translate host name",
        "temporary failure in name resolution",
        "connection refused",
        "connect call failed",
        "database_url environment variable is required",
    )
    return render_hint or any(marker in msg for marker in known_db_connection_errors)


async def _retry_with_sqlite_fallback():
    """Boot the app with an ephemeral SQLite database for demo deployments."""
    SQLITE_FALLBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    fallback_url = f"sqlite:///{SQLITE_FALLBACK_PATH}"

    logger.warning(
        "Falling back to local SQLite demo database at %s because PostgreSQL startup failed. "
        "Data on this fallback database is ephemeral and may reset on redeploy or restart.",
        SQLITE_FALLBACK_PATH,
    )

    await db_manager.close_db()
    _set_database_url(fallback_url)
    await db_manager.init_db()
    await db_manager.create_tables()
    logger.warning("SQLite fallback database initialized successfully")


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


async def initialize_database():
    """Initialize database and create tables"""
    if "MGX_IGNORE_INIT_DB" in os.environ:
        logger.info("Ignore creating tables")
        return
    start_time = time.time()
    logger.debug("[DB_OP] Starting database initialization")
    try:
        logger.info("🔧 Starting database initialization...")
        await db_manager.init_db()
        logger.info("🔧 Database connection initialized, now creating tables if tables not exist...")
        await db_manager.create_tables()
        logger.info("🔧 Table creation completed")
        logger.info("Database initialized successfully")
        logger.debug(f"[DB_OP] Database initialization completed in {time.time() - start_time:.4f}s")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        if _should_use_sqlite_fallback(e):
            await _retry_with_sqlite_fallback()
            logger.debug(
                f"[DB_OP] Database initialization completed via SQLite fallback in {time.time() - start_time:.4f}s"
            )
            return
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
