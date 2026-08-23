from datetime import date, datetime, timezone

import pytest
from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.requests import Request

from core.database import Base
from models.employees import Employees
from models.ringcentral_call_records import RingCentralCallRecords
from models.ringcentral_connections import RingCentralConnections
from models.sales_call_activities import SalesCallActivities
from models.sales_daily_dial_tasks import SalesDailyDialTasks
from models.sales_leads import SalesLeads
from routers import ringcentral as ringcentral_router
from routers.ringcentral import ringcentral_webhook
from schemas.auth import UserResponse
from services.ringcentral_sync import process_telephony_event, upsert_call_log_record


@pytest.mark.asyncio
async def test_webhook_validation_echoes_ringcentral_token():
    request = Request({"type": "http", "method": "POST", "path": "/api/ringcentral/webhook", "headers": []})
    response = await ringcentral_webhook(
        request,
        BackgroundTasks(),
        validation_token="ringcentral-validation-token",
        verification_token=None,
    )
    assert response.status_code == 200
    assert response.headers["Validation-Token"] == "ringcentral-validation-token"
    assert len(response.body) < 1024


@pytest.mark.asyncio
async def test_event_and_call_log_are_idempotent_and_match_employee_lead_task():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    tables = [
        Employees.__table__,
        RingCentralConnections.__table__,
        SalesLeads.__table__,
        SalesDailyDialTasks.__table__,
        SalesCallActivities.__table__,
        RingCentralCallRecords.__table__,
    ]
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync_connection: Base.metadata.create_all(sync_connection, tables=tables))
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_maker() as db:
        employee = Employees(id=11, user_id="11", name="Billy Li", role="sales", status="active")
        connection = RingCentralConnections(
            employee_id=11,
            employee_name="Billy Li",
            ringcentral_account_id="acct-1",
            ringcentral_extension_id="4001",
            access_token_encrypted="test-token",
            is_active=True,
        )
        lead = SalesLeads(
            business_name="Test Salon",
            phone="+1 (555) 222-3333",
            status="new",
            assigned_sales_id=11,
            assigned_sales_name="Billy Li",
        )
        db.add_all([employee, connection, lead])
        await db.flush()
        task = SalesDailyDialTasks(
            sales_employee_id=11,
            task_date=date.today(),
            lead_id=lead.id,
            status="pending",
            dial_started_at=datetime(2026, 8, 23, 7, 59, tzinfo=timezone.utc),
        )
        db.add(task)
        await db.commit()

        payload = {
            "uuid": "event-1",
            "body": {
                "telephonySessionId": "telephony-1",
                "eventTime": "2026-08-23T08:00:00Z",
                "sequence": 1,
                "parties": [{
                    "extensionId": "4001",
                    "sessionId": "session-1",
                    "direction": "Outbound",
                    "status": {"code": "Answered"},
                    "from": {"phoneNumber": "+15550001111"},
                    "to": {"phoneNumber": "+15552223333"},
                }],
            },
        }
        provider_call, terminal = await process_telephony_event(db, payload, event_uuid="event-1")
        assert provider_call is not None
        assert terminal is False
        assert provider_call.connected is True
        assert provider_call.sales_employee_id == 11
        assert provider_call.lead_id == lead.id
        assert provider_call.task_id == task.id
        await db.commit()

        verified = await upsert_call_log_record(db, connection, {
            "id": "call-1",
            "telephonySessionId": "telephony-1",
            "sessionId": "session-1",
            "direction": "Outbound",
            "from": {"phoneNumber": "+15550001111"},
            "to": {"phoneNumber": "+15552223333"},
            "result": "Call connected",
            "duration": 86,
            "startTime": "2026-08-23T08:00:00Z",
        })
        assert verified is not None
        assert verified.id == provider_call.id
        assert verified.ringcentral_call_id == "call-1"
        assert verified.duration_seconds == 86
        assert verified.sync_status == "verified"
        await db.commit()

        duplicate = await upsert_call_log_record(db, connection, {
            "id": "call-1",
            "telephonySessionId": "telephony-1",
            "result": "Call connected",
            "duration": 86,
        })
        assert duplicate is not None
        assert duplicate.id == provider_call.id

        stale_lead = SalesLeads(
            business_name="Old Dial Salon",
            phone="+1 555 444 5555",
            status="new",
            assigned_sales_id=11,
            assigned_sales_name="Billy Li",
        )
        db.add(stale_lead)
        await db.flush()
        stale_task = SalesDailyDialTasks(
            sales_employee_id=11,
            task_date=date(2026, 8, 20),
            lead_id=stale_lead.id,
            status="pending",
            dial_started_at=datetime(2026, 8, 20, 8, 0, tzinfo=timezone.utc),
        )
        db.add(stale_task)
        await db.commit()

        stale_call = await upsert_call_log_record(db, connection, {
            "id": "call-stale-task",
            "direction": "Outbound",
            "from": {"phoneNumber": "+15550001111"},
            "to": {"phoneNumber": "+15554445555"},
            "result": "Call connected",
            "duration": 42,
            "startTime": "2026-08-23T08:00:00Z",
        })
        assert stale_call is not None
        assert stale_call.lead_id == stale_lead.id
        assert stale_call.task_id is None

    await engine.dispose()


@pytest.mark.asyncio
async def test_manual_call_log_sync_keeps_realtime_subscription_error(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    tables = [RingCentralConnections.__table__, RingCentralCallRecords.__table__]
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync_connection: Base.metadata.create_all(sync_connection, tables=tables))
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_maker() as db:
        connection = RingCentralConnections(
            employee_id=11,
            access_token_encrypted="test-token",
            is_active=True,
            webhook_subscription_status="error",
            last_error="实时订阅权限不足",
        )
        db.add(connection)
        await db.commit()

        async def keep_connection(_employee_id, current, _db):
            return current

        async def no_records(_access_token, *, date_from, telephony_session_id=None):
            return []

        monkeypatch.setattr(ringcentral_router, "_refresh_connection_if_needed", keep_connection)
        monkeypatch.setattr(ringcentral_router, "_access_token", lambda _connection: "access-token")
        monkeypatch.setattr(ringcentral_router, "fetch_extension_call_log", no_records)

        result = await ringcentral_router.sync_ringcentral_call_log(
            days=2,
            current_user=UserResponse(id="11", email="sales@example.com", role="sales"),
            db=db,
        )
        await db.refresh(connection)

        assert connection.last_error == "实时订阅权限不足"
        assert result["connected"] is True
        assert result["realtime_sync_enabled"] is False
        assert result["sync_health"] == "attention"

    await engine.dispose()
