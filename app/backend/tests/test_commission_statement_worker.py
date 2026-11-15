import asyncio
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from dependencies.auth import get_current_user
from core.database import get_db
from models.commissions import CommissionStatement, CommissionStatementCycle
from routers.commissions import router
from schemas.auth import UserResponse
from services import commission_statement_worker as worker


@pytest.mark.asyncio
async def test_worker_retries_after_failure_claims_once_and_rolls_at_beijing_midnight(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'cycle.sqlite'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        for table in (CommissionStatement.__table__, CommissionStatementCycle.__table__):
            await conn.run_sync(table.create)
    executions = []

    async def scan(session, *, commit):
        assert commit is False

    async def reconcile(session, *, now):
        executions.append(now)
        if len(executions) == 1:
            raise RuntimeError("interrupted before commit")

    monkeypatch.setattr(worker, "scan_commissions", scan)
    monkeypatch.setattr(worker, "reconcile_statements", reconcile)

    async def tick(when):
        async with sessions.begin() as session:
            return await worker.run_due_cycle(session, when)

    before = datetime(2026, 11, 14, 15, 59, tzinfo=timezone.utc)
    after = datetime(2026, 11, 14, 16, 0, tzinfo=timezone.utc)
    try:
        with pytest.raises(RuntimeError):
            await tick(before)
        async with sessions() as session:
            assert (await worker.scheduler_status(session))["last_completed_date"] is None
        assert sorted(await asyncio.gather(tick(before), tick(before))) == [False, True]
        assert await tick(after)
        assert executions == [before, before, after]
        async with sessions() as session:
            assert await worker.scheduler_status(session) == {
                "timezone": "Asia/Shanghai", "issue_day": 1, "reminder_day": 15, "last_completed_date": "2026-11-15",
            }
    finally:
        await engine.dispose()


@pytest.mark.parametrize("role", ["admin", "sales", "sales_partner"])
def test_monthly_statement_routes_require_owner(role):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: UserResponse(id="1", role=role, email="staff@example.test")
    app.dependency_overrides[get_db] = lambda: None
    with TestClient(app) as client:
        root = "/api/v1/commissions/statements"
        assert client.get(root, params={"month": "2026-10"}).status_code == 403
        assert client.get(root + "/1").status_code == 403
        assert client.get(root + "/reminders").status_code == 403
        assert client.post(root + "/1/settle", json={}).status_code == 403
