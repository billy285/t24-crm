"""Connection health is separate from observed official call counts."""
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.database import Base
from models.employees import Employees
from models.operation_logs import Operation_logs
from models.ringcentral_connections import RingCentralConnections
from models.ringcentral_call_records import RingCentralCallRecords
from models.sales_call_activities import SalesCallActivities
from models.sales_daily_dial_tasks import SalesDailyDialTasks
from models.sales_leads import SalesLeads
from models.sales_lead_conversion_logs import SalesLeadConversionLogs
from routers.sales_leads import sales_call_report
from schemas.auth import UserResponse


@pytest_asyncio.fixture
async def report_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    tables = [Operation_logs.__table__, Employees.__table__, RingCentralConnections.__table__, RingCentralCallRecords.__table__,
              SalesCallActivities.__table__, SalesDailyDialTasks.__table__, SalesLeads.__table__,
              SalesLeadConversionLogs.__table__]
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync: Base.metadata.create_all(sync, tables=tables))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        db.add_all([
            Employees(id=11, user_id="11", name="Sales A", role="sales", status="active", supervisor="Manager A"),
            Employees(id=12, user_id="12", name="PRIVATE_OTHER_TEAM", role="sales", status="active", supervisor="Manager B"),
            Employees(id=13, user_id="13", name="Sales C", role="sales", status="probation", supervisor="Manager A"),
        ])
        await db.commit()
        yield db
    await engine.dispose()


def user(role="admin", name="Owner", id="1"):
    return UserResponse(id=id, name=name, role=role, email="synthetic@report.test")


def connection(employee_id, **overrides):
    now = datetime.now(timezone.utc)
    values = dict(employee_id=employee_id, access_token_encrypted="PRIVATE_ACCESS_TOKEN",
                  refresh_token_encrypted="PRIVATE_REFRESH_TOKEN", is_active=True,
                  ringcentral_account_id="account", ringcentral_extension_id=str(employee_id),
                  extension_number=str(employee_id), token_expires_at=now+timedelta(hours=1),
                  webhook_subscription_status="active", webhook_expires_at=now+timedelta(days=1),
                  last_synced_at=now)
    values.update(overrides)
    return RingCentralConnections(**values)


@pytest.mark.asyncio
async def test_missing_connections_do_not_turn_zero_observed_records_into_zero_actual_calls(report_db):
    report = await sales_call_report(days=30, current_user=user(), db=report_db)
    assert report["summary"]["provider_calls"] == 0
    assert report["source"]["data_complete"] is False
    assert report["source"]["coverage_status"] == "unknown"
    assert report["source"]["counts_observed"] is True
    assert report["connection_health"]["not_connected"] == 3
    assert report["connection_health"]["needs_attention"] == 3
    assert all(row["needs_attention"] for row in report["employees"])
    assert "实际拨打总量" in report["source"]["message"]


@pytest.mark.asyncio
async def test_verified_calls_are_preserved_even_when_connection_now_expired(report_db):
    report_db.add(connection(11, is_active=False, last_error="Token is expired"))
    report_db.add(RingCentralCallRecords(provider_key="observed", sales_employee_id=11,
        direction="outbound", connected=True, duration_seconds=125,
        started_at=datetime.now(timezone.utc), sync_status="verified"))
    await report_db.commit()
    report = await sales_call_report(days=7, current_user=user("sales", "Sales A", "11"), db=report_db)
    assert report["source"]["status"] == "verified"
    assert report["source"]["data_complete"] is False
    assert report["summary"]["provider_calls"] == 1
    assert report["summary"]["total_talk_seconds"] == 125
    assert report["employees"][0]["needs_attention"] is True
    assert report["employees"][0]["extension_number"] == "11"
    assert "PRIVATE_ACCESS_TOKEN" not in str(report) and "PRIVATE_REFRESH_TOKEN" not in str(report)


@pytest.mark.asyncio
async def test_manager_report_health_only_contains_direct_reports(report_db):
    report_db.add(connection(12, extension_number="PRIVATE_OTHER_EXTENSION"))
    report_db.add(connection(11))
    await report_db.commit()
    report = await sales_call_report(days=7, current_user=user("sales_manager", "Manager A", "10"), db=report_db)
    assert {row["sales_employee_id"] for row in report["employees"]} == {11, 13}
    assert report["connection_health"]["total"] == 2
    assert report["connection_health"]["ready"] == 1
    assert "PRIVATE_OTHER" not in str(report)


@pytest.mark.asyncio
async def test_live_connection_does_not_prove_historical_coverage_and_never_synced_needs_attention(report_db):
    report_db.add(connection(11))
    report_db.add(connection(13, last_synced_at=None))
    await report_db.commit()
    report = await sales_call_report(days=30, current_user=user("sales_manager", "Manager A", "10"), db=report_db)
    assert report["source"]["data_complete"] is False
    assert report["connection_health"]["ready"] == 1
    assert report["connection_health"]["attention"] == 1
    rows = {row["sales_employee_id"]: row for row in report["employees"]}
    assert rows[11]["needs_attention"] is False
    assert rows[13]["needs_attention"] is True
    assert all(row["coverage_status"] == "unknown" for row in rows.values())
