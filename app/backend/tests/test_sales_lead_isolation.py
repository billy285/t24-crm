import io

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from openpyxl import Workbook
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.main import app
from backend.services.emp_auth import create_access_token
from core.database import Base, get_db
from models.employees import Employees


def _auth_headers(role: str, emp_id: int, name: str) -> dict[str, str]:
    token = create_access_token({
        "emp_id": emp_id,
        "email": f"{emp_id}@example.com",
        "role": role,
        "name": name,
    })
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def sales_app_client():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
    )
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_maker() as session:
        session.add_all([
            Employees(id=10, user_id="manager", name="Manager A", role="sales_manager", status="active"),
            Employees(id=11, user_id="sales-a", name="Sales A", role="sales", status="active", supervisor="Manager A"),
            Employees(id=12, user_id="sales-b", name="Sales B", role="sales", status="active", supervisor="Manager B"),
        ])
        await session.commit()

    async def override_get_db():
        async with session_maker() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.pop(get_db, None)
    await engine.dispose()


@pytest.mark.asyncio
async def test_sales_only_sees_assigned_leads_and_not_customer_api(sales_app_client):
    admin = _auth_headers("admin", 1, "Admin")
    sales_a = _auth_headers("sales", 11, "Sales A")
    sales_b = _auth_headers("sales", 12, "Sales B")

    own = await sales_app_client.post(
        "/api/v1/sales-leads",
        headers=admin,
        json={"business_name": "Own Cafe", "phone": "111", "assigned_sales_id": 11},
    )
    other = await sales_app_client.post(
        "/api/v1/sales-leads",
        headers=admin,
        json={"business_name": "Other Cafe", "phone": "222", "assigned_sales_id": 12},
    )
    assert own.status_code == 201
    assert other.status_code == 201

    own_list = await sales_app_client.get("/api/v1/sales-leads", headers=sales_a)
    other_list = await sales_app_client.get("/api/v1/sales-leads", headers=sales_b)
    blocked_customers = await sales_app_client.get("/api/v1/entities/customers", headers=sales_a)

    assert [item["business_name"] for item in own_list.json()["items"]] == ["Own Cafe"]
    assert [item["business_name"] for item in other_list.json()["items"]] == ["Other Cafe"]
    assert blocked_customers.status_code == 403
    assert blocked_customers.json()["detail"] == "电话销售账号只能访问电话销售中心"


@pytest.mark.asyncio
async def test_manager_only_sees_and_assigns_direct_team(sales_app_client):
    admin = _auth_headers("admin", 1, "Admin")
    manager = _auth_headers("sales_manager", 10, "Manager A")

    await sales_app_client.post(
        "/api/v1/sales-leads",
        headers=admin,
        json={"business_name": "Team Cafe", "phone": "333", "assigned_sales_id": 11},
    )
    await sales_app_client.post(
        "/api/v1/sales-leads",
        headers=admin,
        json={"business_name": "Outside Cafe", "phone": "444", "assigned_sales_id": 12},
    )
    manager_created = await sales_app_client.post(
        "/api/v1/sales-leads",
        headers=manager,
        json={"business_name": "Manager Lead", "phone": "555", "assigned_sales_id": 11},
    )
    forbidden_assignment = await sales_app_client.post(
        "/api/v1/sales-leads",
        headers=manager,
        json={"business_name": "Wrong Team", "phone": "666", "assigned_sales_id": 12},
    )
    manager_list = await sales_app_client.get("/api/v1/sales-leads", headers=manager)
    blocked_finance = await sales_app_client.get("/api/v1/entities/payments", headers=manager)

    assert manager_created.status_code == 201
    assert forbidden_assignment.status_code == 403
    assert {item["business_name"] for item in manager_list.json()["items"]} == {"Team Cafe", "Manager Lead"}
    assert blocked_finance.status_code == 403


@pytest.mark.asyncio
async def test_sales_recovery_requires_manager_confirmation_and_keeps_protected_leads(sales_app_client):
    admin = _auth_headers("admin", 1, "Admin")
    manager = _auth_headers("sales_manager", 10, "Manager A")
    sales_a = _auth_headers("sales", 11, "Sales A")

    created = await sales_app_client.post(
        "/api/v1/sales-leads",
        headers=admin,
        json={"business_name": "Recovery Cafe", "phone": "555-2000", "assigned_sales_id": 11},
    )
    assert created.status_code == 201
    lead_id = created.json()["id"]

    sales_alerts = await sales_app_client.get("/api/v1/sales-leads/recovery/my-alerts", headers=sales_a)
    assert sales_alerts.status_code == 200
    assert sales_alerts.json()["items"][0]["state"] == "watch"

    requested = await sales_app_client.post(
        f"/api/v1/sales-leads/{lead_id}/recovery/request-extension",
        headers=sales_a,
        json={"reason": "商家约定下周回电，需要继续跟进", "requested_days": 3},
    )
    assert requested.status_code == 200

    overview = await sales_app_client.get("/api/v1/sales-leads/recovery/overview", headers=manager)
    assert overview.status_code == 200
    assert overview.json()["summary"]["extension_requests"] == 1

    approved = await sales_app_client.post(
        f"/api/v1/sales-leads/{lead_id}/recovery/approve-extension",
        headers=manager,
        json={"reason": "已核实回访计划，批准保护期"},
    )
    assert approved.status_code == 200

    updated = await sales_app_client.get("/api/v1/sales-leads/recovery/overview", headers=manager)
    item = next(item for item in updated.json()["items"] if item["lead_id"] == lead_id)
    assert item["state"] == "extended"
    assert item["extension_request"] is None

    protected = await sales_app_client.put(
        f"/api/v1/sales-leads/{lead_id}",
        headers=manager,
        json={"status": "interested"},
    )
    assert protected.status_code == 200
    no_transfer = await sales_app_client.post(
        f"/api/v1/sales-leads/{lead_id}/recovery/reassign",
        headers=admin,
        json={"assigned_sales_id": 12, "reason": "主管交接", "confirm_protected_transfer": False},
    )
    assert no_transfer.status_code == 400
    confirmed_transfer = await sales_app_client.post(
        f"/api/v1/sales-leads/{lead_id}/recovery/reassign",
        headers=admin,
        json={"assigned_sales_id": 12, "reason": "原销售离职，主管确认交接", "confirm_protected_transfer": True},
    )
    assert confirmed_transfer.status_code == 200


@pytest.mark.asyncio
async def test_explainable_sales_performance_is_scoped_to_phone_sales_data(sales_app_client):
    admin = _auth_headers("admin", 1, "Admin")
    manager = _auth_headers("sales_manager", 10, "Manager A")
    sales_a = _auth_headers("sales", 11, "Sales A")
    created = await sales_app_client.post(
        "/api/v1/sales-leads",
        headers=admin,
        json={"business_name": "Performance Cafe", "phone": "555-3000", "assigned_sales_id": 11},
    )
    assert created.status_code == 201

    workbench = await sales_app_client.get("/api/v1/sales-leads/workbench/today", headers=sales_a)
    assert workbench.status_code == 200
    task_id = workbench.json()["items"][0]["task_id"]
    recorded = await sales_app_client.post(
        f"/api/v1/sales-leads/workbench/tasks/{task_id}/result",
        headers=sales_a,
        json={"outcome": "interested", "notes": "商家希望了解本地推广方案，并约定明天下午继续沟通。"},
    )
    assert recorded.status_code == 200

    manager_dashboard = await sales_app_client.get("/api/v1/sales-leads/dashboard/performance?days=30", headers=manager)
    assert manager_dashboard.status_code == 200
    item = manager_dashboard.json()["items"][0]
    assert item["salesperson"] == "Sales A"
    assert item["score"] > 0
    assert item["metrics"]["interested"] == 1
    assert set(item["score_breakdown"]) == {"results", "execution", "discipline", "documentation", "compliance"}

    personal_dashboard = await sales_app_client.get("/api/v1/sales-leads/dashboard/performance?days=30", headers=sales_a)
    assert personal_dashboard.status_code == 200
    assert [item["salesperson"] for item in personal_dashboard.json()["items"]] == ["Sales A"]


@pytest.mark.asyncio
async def test_sales_can_mark_do_not_contact_but_cannot_reassign(sales_app_client):
    admin = _auth_headers("admin", 1, "Admin")
    sales_a = _auth_headers("sales", 11, "Sales A")
    created = await sales_app_client.post(
        "/api/v1/sales-leads",
        headers=admin,
        json={"business_name": "Protected Cafe", "phone": "777", "assigned_sales_id": 11},
    )
    lead_id = created.json()["id"]

    protected = await sales_app_client.put(
        f"/api/v1/sales-leads/{lead_id}",
        headers=sales_a,
        json={"do_not_contact": True, "do_not_contact_reason": "商家明确拒绝"},
    )
    forbidden_reassign = await sales_app_client.put(
        f"/api/v1/sales-leads/{lead_id}",
        headers=sales_a,
        json={"assigned_sales_id": 12},
    )

    assert protected.status_code == 200
    assert protected.json()["do_not_contact"] is True
    assert protected.json()["status"] == "blocked"
    assert forbidden_reassign.status_code == 403


@pytest.mark.asyncio
async def test_merchant_pool_isolates_bad_records_before_sales_leads(sales_app_client):
    admin = _auth_headers("admin", 1, "Admin")
    manager = _auth_headers("sales_manager", 10, "Manager A")
    sales_a = _auth_headers("sales", 11, "Sales A")

    formal_customer = await sales_app_client.post(
        "/api/v1/entities/customers",
        headers=admin,
        json={"business_name": "Formal Cafe", "contact_name": "Owner", "phone": "555-1000", "address": "1 Main St"},
    )
    assert formal_customer.status_code in {200, 201}

    imported = await sales_app_client.post(
        "/api/v1/merchant-pool/import",
        headers=manager,
        json={
            "data_source": "api",
            "records": [
                {"business_name": "No Phone Cafe"},
                {"business_name": "Closed Cafe", "phone": "555-2000", "business_status": "closed"},
                {"business_name": "Formal Cafe Copy", "phone": "555-1000"},
                {"business_name": "Clean Cafe", "phone": "555-3000", "address": "3 Main St"},
                {"business_name": "Clean Cafe Again", "phone": "555-3000"},
            ],
        },
    )
    assert imported.status_code == 200
    assert imported.json()["counts"] == {
        "pending": 1,
        "no_phone": 1,
        "duplicate": 1,
        "existing_customer": 1,
        "closed": 1,
    }

    pool = await sales_app_client.get("/api/v1/merchant-pool", headers=manager)
    records = {item["business_name"]: item for item in pool.json()["items"]}
    assert records["No Phone Cafe"]["pool_status"] == "no_phone"
    assert records["Closed Cafe"]["pool_status"] == "closed"
    assert records["Formal Cafe Copy"]["pool_status"] == "existing_customer"
    assert records["Clean Cafe Again"]["pool_status"] == "duplicate"

    converted = await sales_app_client.post(
        f"/api/v1/merchant-pool/{records['Clean Cafe']['id']}/convert-to-lead",
        headers=manager,
        json={"assigned_sales_id": 11},
    )
    assert converted.status_code == 200
    sales_leads = await sales_app_client.get("/api/v1/sales-leads", headers=sales_a)
    assert [item["business_name"] for item in sales_leads.json()["items"]] == ["Clean Cafe"]

    # A phone-sales account cannot read raw pool data or formal customers.
    assert (await sales_app_client.get("/api/v1/merchant-pool", headers=sales_a)).status_code == 403
    assert (await sales_app_client.get("/api/v1/entities/customers", headers=sales_a)).status_code == 403


@pytest.mark.asyncio
async def test_manager_can_bulk_assign_clean_merchants_to_one_salesperson(sales_app_client):
    manager = _auth_headers("sales_manager", 10, "Manager A")
    sales_a = _auth_headers("sales", 11, "Sales A")

    imported = await sales_app_client.post(
        "/api/v1/merchant-pool/import",
        headers=manager,
        json={
            "data_source": "bulk",
            "records": [
                {"business_name": "Bulk Cafe One", "phone": "555-8101"},
                {"business_name": "Bulk Cafe Two", "phone": "555-8102"},
                {"business_name": "Bulk Cafe Three", "phone": "555-8103"},
            ],
        },
    )
    assert imported.status_code == 200
    merchant_ids = [item["id"] for item in imported.json()["items"]]

    assigned = await sales_app_client.post(
        "/api/v1/merchant-pool/bulk-convert-to-lead",
        headers=manager,
        json={"merchant_ids": merchant_ids, "assigned_sales_id": 11},
    )
    assert assigned.status_code == 200
    assert assigned.json()["converted_count"] == 3
    assert assigned.json()["assigned_sales_name"] == "Sales A"

    leads = await sales_app_client.get("/api/v1/sales-leads", headers=sales_a)
    assert {item["business_name"] for item in leads.json()["items"]} == {
        "Bulk Cafe One", "Bulk Cafe Two", "Bulk Cafe Three",
    }

    repeated = await sales_app_client.post(
        "/api/v1/merchant-pool/bulk-convert-to-lead",
        headers=manager,
        json={"merchant_ids": merchant_ids, "assigned_sales_id": 11},
    )
    assert repeated.status_code == 400


@pytest.mark.asyncio
async def test_merchant_pool_import_recognizes_common_csv_and_excel_headers(sales_app_client):
    manager = _auth_headers("sales_manager", 10, "Manager A")
    csv_content = "Business Name,Phone Number,Full Address,Category,Google Rating\nCafe One,555-7000,1 Main St,Restaurant,4.6\n"
    csv_response = await sales_app_client.post(
        "/api/v1/merchant-pool/import-csv",
        headers=manager,
        files={"file": ("merchants.csv", csv_content.encode(), "text/csv")},
    )
    assert csv_response.status_code == 200
    assert csv_response.json()["total"] == 1
    assert {"business_name", "phone", "address", "industry", "google_rating"}.issubset(csv_response.json()["recognized_fields"])

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["商户名称", "联系电话", "详细地址", "类别", "官网"])
    sheet.append(["Cafe Two", "555-7001", "2 Main St", "餐厅", "https://example.com"])
    content = io.BytesIO()
    workbook.save(content)
    excel_response = await sales_app_client.post(
        "/api/v1/merchant-pool/import-csv",
        headers=manager,
        files={"file": ("merchants.xlsx", content.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert excel_response.status_code == 200
    assert excel_response.json()["total"] == 1


@pytest.mark.asyncio
async def test_admin_can_archive_and_delete_useless_pool_records(sales_app_client):
    admin = _auth_headers("admin", 1, "Admin")
    manager = _auth_headers("sales_manager", 10, "Manager A")

    imported = await sales_app_client.post(
        "/api/v1/merchant-pool/import",
        headers=manager,
        json={
            "data_source": "bulk",
            "records": [
                {"business_name": "No Phone Archive"},
                {"business_name": "Clean Archive", "phone": "555-9000"},
            ],
        },
    )
    assert imported.status_code == 200
    records = {item["business_name"]: item for item in imported.json()["items"]}

    manager_blocked = await sales_app_client.post(
        f"/api/v1/merchant-pool/{records['No Phone Archive']['id']}/archive",
        headers=manager,
    )
    assert manager_blocked.status_code == 403

    archived = await sales_app_client.post(
        f"/api/v1/merchant-pool/{records['No Phone Archive']['id']}/archive",
        headers=admin,
    )
    assert archived.status_code == 200
    assert archived.json()["pool_status"] == "archived"

    default_list = await sales_app_client.get("/api/v1/merchant-pool", headers=admin)
    assert "No Phone Archive" not in {item["business_name"] for item in default_list.json()["items"]}

    archive_list = await sales_app_client.get("/api/v1/merchant-pool?pool_status=archived", headers=admin)
    assert "No Phone Archive" in {item["business_name"] for item in archive_list.json()["items"]}

    deleted = await sales_app_client.delete(
        f"/api/v1/merchant-pool/{records['No Phone Archive']['id']}",
        headers=admin,
    )
    assert deleted.status_code == 200

    converted = await sales_app_client.post(
        f"/api/v1/merchant-pool/{records['Clean Archive']['id']}/convert-to-lead",
        headers=admin,
        json={"assigned_sales_id": 11},
    )
    assert converted.status_code == 200
    delete_converted = await sales_app_client.delete(
        f"/api/v1/merchant-pool/{records['Clean Archive']['id']}",
        headers=admin,
    )
    assert delete_converted.status_code == 409


@pytest.mark.asyncio
async def test_pool_supports_bulk_industry_update_and_delete(sales_app_client):
    admin = _auth_headers("admin", 1, "Admin")
    manager = _auth_headers("sales_manager", 10, "Manager A")

    imported = await sales_app_client.post(
        "/api/v1/merchant-pool/import",
        headers=manager,
        json={
            "data_source": "bulk",
            "records": [
                {"business_name": "Batch Industry One", "phone": "555-9101"},
                {"business_name": "Batch Industry Two", "phone": "555-9102"},
                {"business_name": "Batch Industry Three", "phone": "555-9103"},
            ],
        },
    )
    assert imported.status_code == 200
    merchant_ids = [item["id"] for item in imported.json()["items"]]

    updated = await sales_app_client.post(
        "/api/v1/merchant-pool/bulk-update-industry",
        headers=manager,
        json={"merchant_ids": merchant_ids, "industry": "美容院"},
    )
    assert updated.status_code == 200
    assert updated.json()["updated_count"] == 3

    listed = await sales_app_client.get("/api/v1/merchant-pool", headers=admin)
    matching = [item for item in listed.json()["items"] if item["id"] in merchant_ids]
    assert {item["industry"] for item in matching} == {"美容院"}

    deleted = await sales_app_client.post(
        "/api/v1/merchant-pool/bulk-delete",
        headers=admin,
        json={"merchant_ids": merchant_ids},
    )
    assert deleted.status_code == 200
    assert deleted.json()["deleted_count"] == 3
