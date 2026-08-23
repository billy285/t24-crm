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
from models.sales_lead_conversion_logs import SalesLeadConversionLogs
from models.sales_leads import SalesLeads
from routers import ringcentral as ringcentral_router
from routers.ringcentral import ringcentral_webhook
from routers.sales_leads import sales_call_report
from schemas.auth import UserResponse
from services import ringcentral as ringcentral_service
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
async def test_subscription_payload_does_not_send_unsupported_verification_token(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("RINGCENTRAL_WEBHOOK_URL", "https://t24-crm.com/api/ringcentral/webhook")
    monkeypatch.setenv("RINGCENTRAL_WEBHOOK_VERIFICATION_TOKEN", "configured-in-developer-console")
    captured = {}

    async def capture_request(method, path, access_token, *, params=None, payload=None):
        captured.update(
            method=method,
            path=path,
            access_token=access_token,
            params=params,
            payload=payload,
        )
        return {"id": "subscription-1", "status": "Active"}

    monkeypatch.setattr(ringcentral_service, "_authorized_json_request", capture_request)

    result = await ringcentral_service.create_telephony_subscription(
        "access-token",
        account_id="account-1",
        extension_id="extension-1",
    )

    assert result["id"] == "subscription-1"
    assert captured["method"] == "POST"
    assert captured["path"] == "/restapi/v1.0/subscription"
    assert captured["payload"]["deliveryMode"] == {
        "transportType": "WebHook",
        "address": "https://t24-crm.com/api/ringcentral/webhook",
    }


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


@pytest.mark.asyncio
async def test_sales_call_report_uses_verified_provider_calls_for_connection_metrics():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    tables = [
        Employees.__table__, SalesLeads.__table__, SalesDailyDialTasks.__table__,
        SalesCallActivities.__table__, RingCentralCallRecords.__table__, SalesLeadConversionLogs.__table__,
    ]
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync_connection: Base.metadata.create_all(sync_connection, tables=tables))
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_maker() as db:
        employee = Employees(id=21, user_id="21", name="Report Sales", role="sales", status="active")
        lead = SalesLeads(
            business_name="Report Salon", phone="+15551112222", status="interested",
            assigned_sales_id=21, assigned_sales_name="Report Sales",
        )
        db.add_all([employee, lead])
        await db.flush()
        activity = SalesCallActivities(
            lead_id=lead.id, sales_employee_id=21, sales_employee_name="Report Sales",
            outcome="interested", notes="客户希望明天继续确认套餐", called_at=datetime.now(timezone.utc),
        )
        db.add(activity)
        await db.flush()
        task = SalesDailyDialTasks(
            sales_employee_id=21, task_date=date.today(), lead_id=lead.id,
            status="completed", completed_activity_id=activity.id,
        )
        db.add(task)
        db.add_all([
            RingCentralCallRecords(
                provider_key="report-connected", sales_employee_id=21, sales_employee_name="Report Sales",
                lead_id=lead.id, activity_id=activity.id, direction="outbound", provider_status="completed",
                provider_result="Call connected", connected=True, duration_seconds=125,
                started_at=datetime.now(timezone.utc), sync_status="verified",
            ),
            RingCentralCallRecords(
                provider_key="report-no-answer", sales_employee_id=21, sales_employee_name="Report Sales",
                lead_id=lead.id, direction="outbound", provider_status="completed", provider_result="No Answer",
                connected=False, duration_seconds=20, started_at=datetime.now(timezone.utc), sync_status="verified",
            ),
            RingCentralCallRecords(
                provider_key="report-busy", sales_employee_id=21, sales_employee_name="Report Sales",
                lead_id=lead.id, direction="outbound", provider_status="completed", provider_result="Busy",
                connected=False, duration_seconds=8, started_at=datetime.now(timezone.utc), sync_status="verified",
            ),
        ])
        await db.commit()

        report = await sales_call_report(
            days=7,
            current_user=UserResponse(id="1", email="admin@example.com", role="admin", name="Admin"),
            db=db,
        )

        assert report["source"]["status"] == "verified"
        assert report["summary"]["provider_calls"] == 3
        assert report["summary"]["connected"] == 1
        assert report["summary"]["not_connected"] == 2
        assert report["summary"]["connection_rate"] == 33.3
        assert report["summary"]["total_talk_seconds"] == 125
        assert report["summary"]["average_talk_seconds"] == 125
        assert report["summary"]["crm_records"] == 1
        assert report["summary"]["linked_records"] == 1
        assert report["employees"][0]["provider_calls"] == 3
        assert {item["label"] for item in report["result_breakdown"]} == {"已接通", "无人接听", "忙线"}

    await engine.dispose()
