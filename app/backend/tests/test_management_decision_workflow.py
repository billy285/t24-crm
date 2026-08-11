from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.main import app
from backend.services.emp_auth import create_access_token
from core.database import Base, get_db
from models.customer_lifecycles import CustomerLifecycleCycle
from models.customers import Customers
from models.customer_callbacks import Customer_callbacks
from models.management_decisions import (
    BusinessLine,
    ClassificationReviewDecision,
    CustomerEngagement,
    EngagementLifecycleEvent,
    EngagementSourceLink,
    ProductCatalog,
)
from models.payments import Payments
from models.subscriptions import Subscriptions
from models.service_tasks import Service_tasks
from models.automation import DataQualityIssue
from models.tasks import Tasks
from models.ad_fund_settlements import AdFundSettlement
from models.employees import Employees
from models.expenses import Expenses
from models.payroll import PayrollItems, PayrollSheets
from services.automation_monitor import automation_overview, run_automation_scan
from services.tasks import TasksService


def auth_headers(role: str, employee_id: int) -> dict[str, str]:
    token = create_access_token({
        "emp_id": employee_id,
        "email": f"{employee_id}@test.local",
        "role": role,
        "name": role,
    })
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def workflow_context():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    now = datetime(2026, 8, 3, tzinfo=timezone.utc)
    async with sessions() as session:
        managed = BusinessLine(id=1, code="managed_service", name="代运营", is_recurring=True, is_active=True)
        product = ProductCatalog(
            id=1,
            business_line_id=1,
            code="managed_service_legacy",
            name="代运营历史套餐",
            billing_kind="recurring",
            default_currency="USD",
            is_active=True,
        )
        session.add_all([
            managed,
            product,
            Customers(
                id=11,
                customer_code="C-0011",
                business_name="Ocean Buffet",
                contact_name="Owner",
                phone="555-0011",
                industry="restaurant",
                status="closed",
            ),
            Customers(
                id=12,
                customer_code="C-0012",
                business_name="Other Customer",
                contact_name="Owner",
                phone="555-0012",
                industry="restaurant",
                status="closed",
            ),
            Payments(
                id=101,
                customer_id=11,
                customer_name="Ocean Buffet",
                income_type="ads_fee",
                product_name="投流充值",
                amount_due=2000,
                amount_paid=2000,
                currency="USD",
                payment_date=datetime(2026, 1, 10, tzinfo=timezone.utc),
                user_id="1",
            ),
            Payments(
                id=102,
                customer_id=11,
                customer_name="Ocean Buffet",
                income_type="management_fee",
                product_name="基础套餐",
                amount_due=198,
                amount_paid=198,
                currency="USD",
                billing_cycle="月付",
                payment_date=datetime(2026, 2, 10, tzinfo=timezone.utc),
                user_id="1",
            ),
            Payments(
                id=201,
                customer_id=12,
                customer_name="Other Customer",
                income_type="management_fee",
                product_name="基础套餐",
                amount_due=198,
                amount_paid=198,
                currency="USD",
                payment_date=datetime(2026, 2, 11, tzinfo=timezone.utc),
                user_id="1",
            ),
            CustomerLifecycleCycle(
                id=301,
                customer_id=11,
                cycle_number=1,
                first_payment_id=101,
                started_at=datetime(2026, 1, 10, tzinfo=timezone.utc),
                status="active",
                start_source="payment",
                start_locked=False,
                created_at=now,
                updated_at=now,
            ),
        ])
        await session.commit()

    async def override_db():
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, sessions
    app.dependency_overrides.pop(get_db, None)
    await engine.dispose()


@pytest.mark.asyncio
async def test_review_queue_is_readable_by_finance_and_writable_only_by_admin(workflow_context):
    client, _ = workflow_context
    finance = await client.get(
        "/api/v1/management-decisions/classification-review",
        headers=auth_headers("finance", 2),
    )
    admin = await client.get(
        "/api/v1/management-decisions/classification-review",
        headers=auth_headers("admin", 1),
    )
    denied = await client.get(
        "/api/v1/management-decisions/classification-review",
        headers=auth_headers("sales", 3),
    )

    assert finance.status_code == 200
    assert finance.json()["write_enabled"] is False
    assert admin.status_code == 200
    assert admin.json()["write_enabled"] is True
    assert denied.status_code == 403
    ocean = next(row for row in admin.json()["items"] if row["customer_id"] == 11)
    assert ocean["review_status"] == "pending"
    assert ocean["customer_lifecycle"]["status"] == "active"
    assert {row["business_line"] for row in ocean["suggestions"]} == {"managed_service"}


@pytest.mark.asyncio
async def test_automatic_risk_reminder_never_changes_project_status(workflow_context):
    client, sessions = workflow_context
    async with sessions() as session:
        session.add(CustomerEngagement(
            id=401,
            customer_id=11,
            business_line_id=1,
            product_id=1,
            engagement_code="ENG-RISK-401",
            package_name="待上线套餐",
            status="pending_setup",
            currency="USD",
            created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        ))
        await session.commit()

    response = await client.get(
        "/api/v1/management-decisions/classification-review",
        headers=auth_headers("admin", 1),
    )
    assert response.status_code == 200
    payload = response.json()
    reminder = next(row for row in payload["anomalies"] if row["code"] == "automatic_project_risk_reminder")
    assert reminder["category"] == "risk"
    assert "待开通" in reminder["message"]
    assert payload["summary"]["risk_reminder_count"] == 1

    async with sessions() as session:
        engagement = (await session.execute(
            select(CustomerEngagement).where(CustomerEngagement.id == 401)
        )).scalar_one()
    assert engagement.status == "pending_setup"


@pytest.mark.asyncio
async def test_growth_dashboard_separates_ad_funds_and_drives_owner_decisions(workflow_context):
    client, sessions = workflow_context
    now = datetime(2026, 8, 3, tzinfo=timezone.utc)
    async with sessions() as session:
        session.add_all([
            Employees(id=7, user_id="7", name="Ops Owner", role="operations", status="active"),
            CustomerEngagement(
                id=410, customer_id=11, business_line_id=1, product_id=1,
                engagement_code="ENG-GROWTH-410", package_name="代运营套餐", status="active_paid",
                owner_employee_id=7, currency="USD", paid_started_at=datetime(2026, 1, 10, tzinfo=timezone.utc),
                created_at=now, updated_at=now,
            ),
            AdFundSettlement(
                id=501, customer_id=11, customer_name="Ocean Buffet", year_month="2026-07", currency="USD",
                opening_balance=0, funds_received=2000, actual_ad_spend=1800, customer_refund_amount=0,
                recognized_spread_amount=200, adjustment_amount=0, closing_balance=0, status="closed",
                created_at=now, updated_at=now, user_id="1",
            ),
            Expenses(
                id=601, customer_id=11, customer_name="Ocean Buffet", expense_category="website",
                expense_type="domain", amount=50, currency="USD", expense_date=now, user_id="1",
            ),
            Subscriptions(
                id=701, customer_id=11, customer_name="Ocean Buffet", engagement_id=410,
                business_line_id=1, product_id=1, package_name="代运营套餐", package_price=198,
                start_date=datetime(2026, 7, 1, tzinfo=timezone.utc), end_date=datetime(2026, 8, 1, tzinfo=timezone.utc),
                auto_renew=False, status="active",
            ),
            Tasks(
                id=801, title="逾期客户任务", customer_id=11, customer_name="Ocean Buffet",
                assignee_id=7, assignee_name="Ops Owner", status="pending",
                due_date=datetime(2026, 7, 20, tzinfo=timezone.utc), created_at=now, updated_at=now,
            ),
            PayrollSheets(id=901, month="2026-02", status="paid", currency="CNY", paid_at=now),
            PayrollItems(
                id=902, sheet_id=901, employee_id=7, employee_name="Ops Owner",
                base_salary=1000, payment_status="paid", payment_date="2026-02-28",
            ),
        ])
        payment = await session.get(Payments, 102)
        payment.engagement_id = 410
        payment.management_amount = 198
        payment.outstanding_amount = 198
        ad_payment = await session.get(Payments, 101)
        ad_payment.engagement_id = 410
        ad_payment.ads_recharge_amount = 2000
        await session.commit()

    response = await client.get(
        "/api/v1/management-decisions/growth-dashboard?start_date=2026-01-01&end_date=2026-08-03&project_capacity_target=1",
        headers=auth_headers("admin", 1),
    )
    assert response.status_code == 200
    payload = response.json()
    usd = payload["unit_economics"]["totals"]["USD"]
    assert usd["service_revenue"] == 198
    assert usd["ad_spread"] == 200
    assert usd["customer_cost"] == 50
    assert usd["contribution_profit"] == 348
    managed_line = next(row for row in payload["unit_economics"]["business_lines"] if row["business_line_code"] == "managed_service")
    assert managed_line["average_project_contribution"] == 348
    health = next(row for row in payload["customer_health"]["items"] if row["project_id"] == 410)
    assert health["level"] in {"risk", "critical"}
    assert health["project_status"] == "active_paid"
    owner = next(row for row in payload["team_capacity"]["employees"] if row["employee_id"] == 7)
    assert owner["utilization"] == 1
    assert payload["team_capacity"]["summary"]["near_or_over_capacity"] == 1

    rate_saved = await client.put(
        "/api/v1/management-decisions/exchange-rates/2026-02",
        headers=auth_headers("admin", 1),
        json={"average_rate": 7.2, "source": "月度平均中间价", "status": "locked"},
    )
    assert rate_saved.status_code == 200
    refreshed = await client.get(
        "/api/v1/management-decisions/growth-dashboard?start_date=2026-01-01&end_date=2026-08-03&project_capacity_target=1",
        headers=auth_headers("admin", 1),
    )
    february = next(row for row in refreshed.json()["formal_monthly_profit"]["rows"] if row["year_month"] == "2026-02")
    assert february["exchange_rate"] == 7.2
    assert february["payroll_cost_cny"] == 1000
    assert february["payroll_source"] == "paid_payroll"
    assert february["formal_profit_cny"] == 425.6

    denied = await client.get(
        "/api/v1/management-decisions/growth-dashboard",
        headers=auth_headers("finance", 2),
    )
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_daily_scan_is_idempotent_and_task_completion_closes_issue(workflow_context):
    _, sessions = workflow_context
    async with sessions() as session:
        session.add(CustomerEngagement(
            id=402,
            customer_id=11,
            business_line_id=1,
            product_id=1,
            engagement_code="ENG-AUTO-402",
            package_name="待上线自动扫描套餐",
            status="pending_setup",
            currency="USD",
            created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        ))
        await session.commit()

    async with sessions() as session:
        first = await run_automation_scan(session, trigger="scheduled", run_key="scheduled:2026-08-03")
    assert first["status"] == "completed"
    assert first["task_created_count"] >= 1

    async with sessions() as session:
        second = await run_automation_scan(session, trigger="scheduled", run_key="scheduled:2026-08-03")
    assert second["skipped"] is True

    async with sessions() as session:
        issue = (await session.execute(
            select(DataQualityIssue).where(
                DataQualityIssue.code == "automatic_project_risk_reminder",
                DataQualityIssue.project_id == 402,
            )
        )).scalar_one()
        task = (await session.execute(
            select(Tasks).where(Tasks.automation_issue_id == issue.id)
        )).scalar_one()
        assert issue.status == "open"
        assert task.source_type == "system"
        assert task.status == "pending"
        await TasksService(session).update(task.id, {
            "status": "completed",
            "completion_result": "已联系客户，确认周五完成上线",
            "updated_at": datetime.now(timezone.utc),
        })

    async with sessions() as session:
        overview = await automation_overview(session)
        issue_payload = next(row for row in overview["items"] if row["project_id"] == 402 and row["code"] == "automatic_project_risk_reminder")
        project = (await session.execute(
            select(CustomerEngagement).where(CustomerEngagement.id == 402)
        )).scalar_one()
    assert issue_payload["status"] == "resolved"
    assert issue_payload["resolution_note"] == "已联系客户，确认周五完成上线"
    assert issue_payload["task"]["status"] == "completed"
    assert project.status == "pending_setup"


@pytest.mark.asyncio
async def test_automation_overview_is_finance_readable_and_scan_is_admin_only(workflow_context):
    client, _ = workflow_context
    finance_overview = await client.get(
        "/api/v1/management-decisions/automation/overview",
        headers=auth_headers("finance", 2),
    )
    denied_scan = await client.post(
        "/api/v1/management-decisions/automation/scan",
        headers=auth_headers("finance", 2),
    )
    admin_scan = await client.post(
        "/api/v1/management-decisions/automation/scan",
        headers=auth_headers("admin", 1),
    )

    assert finance_overview.status_code == 200
    assert finance_overview.json()["schedule"]["auto_stop_enabled"] is False
    assert denied_scan.status_code == 403
    assert admin_scan.status_code == 200
    assert admin_scan.json()["scan"]["status"] == "completed"


@pytest.mark.asyncio
async def test_daily_scan_covers_finance_customer_success_and_delivery(workflow_context):
    _, sessions = workflow_context
    async with sessions() as session:
        session.add_all([
            Payments(
                id=301,
                customer_id=12,
                customer_name="Other Customer",
                income_type="management_fee",
                product_name="基础套餐",
                amount_due=300,
                amount_paid=100,
                outstanding_amount=200,
                currency="USD",
                payment_date=datetime(2026, 7, 1, tzinfo=timezone.utc),
                user_id="1",
            ),
            Customer_callbacks(
                id=401,
                customer_id=12,
                employee_id=9,
                employee_name="Billy Li",
                callback_date=datetime(2026, 7, 1, tzinfo=timezone.utc),
                status="pending",
                content="确认续费意向",
            ),
            Service_tasks(
                id=501,
                customer_id=12,
                customer_name="Other Customer",
                task_name="完成网站上线",
                assignee_name="Billy Li",
                status="pending",
                due_date="2026-07-01",
                user_id="1",
            ),
        ])
        await session.commit()

    async with sessions() as session:
        result = await run_automation_scan(session, trigger="manual", run_key="manual:cross-functional")
        overview = await automation_overview(session)

    assert result["status"] == "completed"
    codes = {item["code"] for item in overview["items"] if item["status"] != "resolved"}
    assert "finance_receivable_open" in codes
    assert "customer_callback_overdue" in codes
    assert "delivery_task_overdue" in codes
    assert overview["summary"]["category_counts"]["finance"] >= 1
    assert overview["summary"]["category_counts"]["customer_success"] >= 1
    assert overview["summary"]["category_counts"]["delivery"] >= 1


@pytest.mark.asyncio
async def test_owner_cockpit_uses_separate_currency_policy_and_workflow_counts(workflow_context):
    client, _ = workflow_context
    response = await client.get(
        "/api/v1/management-decisions/owner-cockpit",
        headers=auth_headers("admin", 1),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["finance"]["currency_policy"].startswith("USD 与 CNY 独立统计")
    assert payload["finance"]["USD"]["ads_client_funds"] >= 0
    assert payload["customers"]["active_projects"] >= 0
    assert payload["execution"]["open_tasks"] >= 0
    assert payload["automation"]["schedule"]["auto_stop_enabled"] is False


@pytest.mark.asyncio
async def test_customer_create_with_projects_is_atomic_and_admin_can_read_projects(workflow_context):
    client, sessions = workflow_context
    payload = {
        "customer": {
            "customer_code": "C-NEW",
            "business_name": "New Multi Service Customer",
            "contact_name": "Owner",
            "phone": "555-9000",
            "industry": "restaurant",
            "status": "closed",
        },
        "projects": [{
            "business_line_code": "managed_service",
            "product_code": "managed_service_legacy",
            "product_name": "代运营服务",
            "package_name": "代运营基础套餐",
            "status": "active_paid",
            "billing_cycle": "monthly",
            "collection_method": "bank_transfer",
            "currency": "USD",
            "paid_started_at": "2026-08-01T00:00:00Z",
        }],
    }
    created = await client.post(
        "/api/v1/entities/customers/with-projects",
        headers=auth_headers("admin", 33),
        json=payload,
    )
    assert created.status_code == 201, created.text
    customer_id = created.json()["id"]

    projects = await client.get(
        f"/api/v1/entities/customers/{customer_id}/projects",
        headers=auth_headers("admin", 33),
    )
    assert projects.status_code == 200
    assert projects.json()["items"][0]["package_name"] == "代运营基础套餐"

    async with sessions() as session:
        engagement = (await session.execute(
            select(CustomerEngagement).where(CustomerEngagement.customer_id == customer_id)
        )).scalar_one()
        decision = (await session.execute(
            select(ClassificationReviewDecision).where(ClassificationReviewDecision.customer_id == customer_id)
        )).scalar_one()
        linked_subscription = Subscriptions(
            customer_id=customer_id,
            customer_name="New Multi Service Customer",
            engagement_id=engagement.id,
            package_name="代运营基础套餐",
            package_price=499,
            auto_renew=True,
            next_payment_date=datetime(2026, 9, 1, tzinfo=timezone.utc),
            status="active",
        )
        session.add(linked_subscription)
        await session.commit()
        subscription_id = linked_subscription.id
    assert engagement.package_name == "代运营基础套餐"
    assert decision.decision == "confirmed"

    inconsistent = await client.put(
        f"/api/v1/entities/customers/{customer_id}/with-projects",
        headers=auth_headers("admin", 33),
        json={"customer": {"status": "lost"}, "projects": [{**payload["projects"][0], "engagement_id": engagement.id}]},
    )
    assert inconsistent.status_code == 400
    assert "成交和收款历史无需删除" in inconsistent.json()["detail"]

    updated = await client.put(
        f"/api/v1/entities/customers/{customer_id}/with-projects",
        headers=auth_headers("admin", 33),
        json={
            "customer": {"business_name": "Atomic Customer"},
            "projects": [{
                **payload["projects"][0],
                "engagement_id": engagement.id,
                "status": "stopped",
                "stopped_at": "2026-08-03T00:00:00Z",
                "stop_reason_code": "customer_choice",
            }],
        },
    )
    assert updated.status_code == 200, updated.text
    async with sessions() as session:
        status_events = (await session.execute(
            select(EngagementLifecycleEvent)
            .where(EngagementLifecycleEvent.engagement_id == engagement.id)
            .order_by(EngagementLifecycleEvent.id.asc())
        )).scalars().all()
        linked_subscription = await session.get(Subscriptions, subscription_id)
    assert [event.event_type for event in status_events] == ["classification_confirmed", "status_changed"]
    assert "active_paid -> stopped" in status_events[-1].note
    assert linked_subscription.status == "stopped"
    assert linked_subscription.auto_renew is False
    assert linked_subscription.next_payment_date is None

    invalid_payload = {
        **payload,
        "customer": {**payload["customer"], "customer_code": "C-BAD", "business_name": "Should Roll Back"},
        "projects": [{**payload["projects"][0], "paid_started_at": None}],
    }
    invalid = await client.post(
        "/api/v1/entities/customers/with-projects",
        headers=auth_headers("admin", 33),
        json=invalid_payload,
    )
    assert invalid.status_code == 400
    async with sessions() as session:
        rolled_back = (await session.execute(
            select(Customers).where(Customers.customer_code == "C-BAD")
        )).scalar_one_or_none()
    assert rolled_back is None


@pytest.mark.asyncio
async def test_confirming_project_is_idempotent_and_does_not_change_customer_lifecycle(workflow_context):
    client, sessions = workflow_context
    payload = {
        "decision": "confirmed",
        "note": "确认仍在合作，只建立代运营项目",
        "projects": [{
            "business_line_code": "managed_service",
            "product_code": "managed_service_legacy",
            "product_name": "代运营历史套餐",
            "status": "active_paid",
            "billing_cycle": "monthly",
            "collection_method": "bank_transfer",
            "currency": "USD",
            "paid_started_at": "2026-02-10T00:00:00Z",
            "source_payment_ids": [102],
            "source_subscription_ids": [],
        }],
    }
    first = await client.post(
        "/api/v1/management-decisions/classification-review/customers/11",
        headers=auth_headers("admin", 1),
        json=payload,
    )
    second = await client.post(
        "/api/v1/management-decisions/classification-review/customers/11",
        headers=auth_headers("admin", 1),
        json=payload,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    async with sessions() as session:
        counts = {
            model.__tablename__: (await session.execute(select(func.count()).select_from(model))).scalar_one()
            for model in (CustomerEngagement, EngagementSourceLink, EngagementLifecycleEvent, ClassificationReviewDecision)
        }
        customer = (await session.execute(select(Customers).where(Customers.id == 11))).scalar_one()
        lifecycle = (await session.execute(
            select(CustomerLifecycleCycle).where(CustomerLifecycleCycle.id == 301)
        )).scalar_one()
        engagement = (await session.execute(select(CustomerEngagement))).scalar_one()

    assert counts == {
        "customer_engagements": 1,
        "engagement_source_links": 1,
        "engagement_lifecycle_events": 1,
        "classification_review_decisions": 1,
    }
    assert customer.status == "closed"
    assert lifecycle.status == "active"
    assert lifecycle.first_payment_id == 101
    assert engagement.status == "active_paid"
    assert engagement.paid_started_at.date().isoformat() == "2026-02-10"


@pytest.mark.asyncio
async def test_confirmation_rejects_another_customers_payment(workflow_context):
    client, sessions = workflow_context
    response = await client.post(
        "/api/v1/management-decisions/classification-review/customers/11",
        headers=auth_headers("admin", 1),
        json={
            "decision": "confirmed",
            "projects": [{
                "business_line_code": "managed_service",
                "status": "active_paid",
                "billing_cycle": "monthly",
                "collection_method": "other",
                "currency": "USD",
                "paid_started_at": "2026-02-10T00:00:00Z",
                "source_payment_ids": [201],
            }],
        },
    )
    assert response.status_code == 400
    assert "不属于该客户" in response.json()["detail"]
    async with sessions() as session:
        assert (await session.execute(select(func.count()).select_from(CustomerEngagement))).scalar_one() == 0


@pytest.mark.asyncio
async def test_project_stop_does_not_stop_customer(workflow_context):
    client, sessions = workflow_context
    create = await client.post(
        "/api/v1/management-decisions/classification-review/customers/11",
        headers=auth_headers("admin", 1),
        json={
            "decision": "confirmed",
            "projects": [{
                "business_line_code": "managed_service",
                "status": "active_paid",
                "billing_cycle": "monthly",
                "collection_method": "other",
                "currency": "USD",
                "paid_started_at": "2026-02-10T00:00:00Z",
                "source_payment_ids": [102],
            }],
        },
    )
    project_id = create.json()["projects"][0]["id"]
    stopped = await client.patch(
        f"/api/v1/management-decisions/engagements/{project_id}/status",
        headers=auth_headers("admin", 1),
        json={"status": "stopped", "effective_date": "2026-08-03", "note": "仅停止该项目"},
    )

    assert stopped.status_code == 200
    async with sessions() as session:
        customer = (await session.execute(select(Customers).where(Customers.id == 11))).scalar_one()
        lifecycle = (await session.execute(select(CustomerLifecycleCycle).where(CustomerLifecycleCycle.id == 301))).scalar_one()
        engagement = (await session.execute(select(CustomerEngagement).where(CustomerEngagement.id == project_id))).scalar_one()
    assert customer.status == "closed"
    assert lifecycle.status == "active"
    assert engagement.status == "stopped"
