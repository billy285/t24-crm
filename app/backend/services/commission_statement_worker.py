"""Generate closed-month commission statements on the Beijing business calendar."""
import asyncio
import contextlib
import logging
import os
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from core.database import db_manager
from models.commissions import CommissionStatementCycle
from services.commissions import scan_commissions
from services.commission_statements import lock_statements, reconcile_statements


BEIJING = ZoneInfo("Asia/Shanghai")
logger = logging.getLogger(__name__)


async def run_due_cycle(db, now=None):
    at = now or datetime.now(timezone.utc)
    day = at.astimezone(BEIJING).date()
    await lock_statements(db)
    if await db.get(CommissionStatementCycle, day):
        return False
    insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    # This claim, candidate scan and all statement lines commit together. A crashed
    # worker leaves the date available to its successor.
    claim = insert(CommissionStatementCycle).values(business_date=day, completed_at=at)
    claimed = await db.execute(claim.on_conflict_do_nothing(index_elements=["business_date"]))
    if not claimed.rowcount:
        return False
    await scan_commissions(db, commit=False)
    await reconcile_statements(db, now=at)
    return True


async def scheduler_status(db):
    last = await db.scalar(select(CommissionStatementCycle).order_by(
        CommissionStatementCycle.business_date.desc()).limit(1))
    return {
        "timezone": "Asia/Shanghai", "issue_day": 1, "reminder_day": 15,
        "last_completed_date": last.business_date.isoformat() if last else None,
    }


async def _run():
    while True:
        try:
            async with db_manager.async_session_maker() as db, db.begin():
                await run_due_cycle(db)
            local = datetime.now(BEIJING)
            midnight = datetime.combine(local.date() + timedelta(days=1), time.min, BEIJING)
            delay = max(1.0, (midnight - local).total_seconds())
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Commission statement generation will retry (%s)", type(exc).__name__)
            delay = 60
        await asyncio.sleep(delay)


def start_worker():
    if os.getenv("IS_LAMBDA") != "true":
        return asyncio.create_task(_run(), name="commission-monthly-statements")


async def stop_worker(task):
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
