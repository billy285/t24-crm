"""Serialize merchant references and undo without rewriting historical fields."""

from collections.abc import Iterable

from fastapi import HTTPException
from sqlalchemy import bindparam, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from models.merchant_pool import MerchantPool


def _retryable_lock_error(error: DBAPIError) -> bool:
    original = error.orig
    sqlite_code = getattr(original, "sqlite_errorcode", None)
    if isinstance(sqlite_code, int) and sqlite_code & 255 in {5, 6}:
        return True
    sqlstate = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    cause = getattr(original, "__cause__", None)
    sqlstate = sqlstate or getattr(cause, "sqlstate", None)
    if sqlstate in {"40P01", "55P03", "40001"}:
        return True
    message = str(original).lower()
    return "database is locked" in message or "database table is locked" in message


async def lock_merchant_rows(db: AsyncSession, ids: Iterable[int]) -> list[MerchantPool]:
    """Hold locks through commit/rollback; empty IDs start SQLite's write txn.

    SQLite ignores FOR UPDATE. The raw no-op UPDATE deliberately avoids ORM
    onupdate defaults, so even updated_at and every historical field stay exact.
    Call before the business read/recheck, and never commit between this guard
    and the protected write. PostgreSQL locks rows in deterministic ID order.
    """
    merchant_ids = sorted(set(ids))
    try:
        with db.no_autoflush:
            if db.get_bind().dialect.name == "sqlite":
                if merchant_ids:
                    statement = text("UPDATE merchant_pool SET id = id WHERE id IN :merchant_ids").bindparams(bindparam("merchant_ids", expanding=True))
                    await db.execute(statement, {"merchant_ids": merchant_ids})
                else:
                    await db.execute(text("UPDATE merchant_pool SET id = id WHERE 0"))
            if not merchant_ids:
                return []
            return list((await db.execute(
                select(MerchantPool).where(MerchantPool.id.in_(merchant_ids))
                .order_by(MerchantPool.id).with_for_update()
                .execution_options(populate_existing=True)
            )).scalars().all())
    except DBAPIError as error:
        if not _retryable_lock_error(error):
            raise
        await db.rollback()
        raise HTTPException(status_code=409, detail="商家数据正在被其他操作处理，本次操作尚未写入，请稍后重试") from error
