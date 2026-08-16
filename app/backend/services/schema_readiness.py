"""Read-only helpers for checking runtime database schema readiness.

Runtime request handlers must never create or repair database objects.  These
helpers let callers choose an explicit fallback for reads and fail closed for
writes while Alembic remains the only production schema owner.
"""

from collections.abc import Iterable

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession


APP_SETTINGS_TABLE = "app_settings"
MONTHLY_DEDUCTION_TABLES = frozenset(
    {
        "monthly_deduction_rates",
        "monthly_deduction_defaults",
        "monthly_deduction_audits",
    }
)
RUNTIME_REQUIRED_TABLE_COLUMNS = {
    APP_SETTINGS_TABLE: frozenset({"config_key", "value_json", "updated_at"}),
    "monthly_deduction_rates": frozenset({"id", "year_month", "rate", "created_at", "updated_at"}),
    "monthly_deduction_defaults": frozenset({"id", "rate", "updated_at"}),
    "monthly_deduction_audits": frozenset(
        {"id", "action", "actor_id", "before_json", "after_json", "at"}
    ),
}


class SchemaUnavailableError(RuntimeError):
    """Raised when a required migrated table is not available."""

    def __init__(self, missing_tables: Iterable[str]):
        self.missing_tables = tuple(sorted(set(missing_tables)))
        joined = ", ".join(self.missing_tables)
        super().__init__(f"Required database tables are unavailable: {joined}")


async def get_database_table_names(session: AsyncSession) -> set[str]:
    """Return current table names without mutating or committing the schema."""

    connection = await session.connection()
    names = await connection.run_sync(lambda sync_connection: inspect(sync_connection).get_table_names())
    return set(names)


async def missing_tables(session: AsyncSession, required_tables: Iterable[str]) -> set[str]:
    required = set(required_tables)
    if not required:
        return set()
    available = await get_database_table_names(session)
    return required - available


async def tables_available(session: AsyncSession, required_tables: Iterable[str]) -> bool:
    return not await missing_tables(session, required_tables)


async def require_tables(session: AsyncSession, required_tables: Iterable[str]) -> None:
    missing = await missing_tables(session, required_tables)
    if missing:
        raise SchemaUnavailableError(missing)
