"""Transaction locks for explicit sales assignment and call-result mutations."""
from collections.abc import Iterable

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from models.employees import Employees
from models.sales_leads import SalesLeads

# Stable, positive signed-bigint namespace; never use Python's randomized hash.
SALES_WORKFLOW_ADVISORY_KEY = int.from_bytes(b"T24SALES", byteorder="big")


def _retryable_lock_error(error: DBAPIError) -> bool:
    original = error.orig
    sqlite_code = getattr(original, "sqlite_errorcode", None)
    if isinstance(sqlite_code, int) and (sqlite_code & 255) in {5, 6}:
        return True
    sqlstate = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    cause = getattr(original, "__cause__", None)
    sqlstate = sqlstate or getattr(cause, "sqlstate", None)
    if sqlstate in {"40P01", "55P03", "40001"}:
        return True
    message = str(original).lower()
    return "database is locked" in message or "database table is locked" in message


async def lock_sales_workflow(
    db: AsyncSession,
    lead_ids: Iterable[int] = (),
    employee_ids: Iterable[int] = (),
) -> None:
    """Acquire before business reads; hold until the caller commits or rolls back.

    SQLite ignores row locks, so a raw zero-row UPDATE starts its write
    transaction without touching id, updated_at, or any historical field.
    PostgreSQL first serializes sales mutations with one transaction advisory
    lock, including empty IDs and competing preparations for a shared pool.
    It then locks employees first, then leads, in deterministic ID order.
    Callers must include all employee/lead IDs involved in the mutation and
    must never call this guard from a GET or commit before the protected write.
    """
    employees = sorted(set(employee_ids))
    leads = sorted(set(lead_ids))
    try:
        with db.no_autoflush:
            dialect = db.get_bind().dialect.name
            if dialect == "sqlite":
                await db.execute(text("UPDATE sales_leads SET id = id WHERE 0"))
                return
            if dialect == "postgresql":
                await db.execute(
                    text("SELECT pg_advisory_xact_lock(:namespace_key)"),
                    {"namespace_key": SALES_WORKFLOW_ADVISORY_KEY},
                )
            if employees:
                await db.execute(
                    select(Employees).where(Employees.id.in_(employees))
                    .order_by(Employees.id).with_for_update()
                    .execution_options(populate_existing=True)
                )
            if leads:
                await db.execute(
                    select(SalesLeads).where(SalesLeads.id.in_(leads))
                    .order_by(SalesLeads.id).with_for_update()
                    .execution_options(populate_existing=True)
                )
    except DBAPIError as error:
        if not _retryable_lock_error(error):
            raise
        await db.rollback()
        raise HTTPException(status_code=409, detail="销售任务正在被其他操作处理，本次操作尚未写入，请刷新后重试") from error
