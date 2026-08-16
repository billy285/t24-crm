from datetime import date

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.main import app
from backend.routers import employees as employees_router
from core.database import Base
from models.commissions import CustomerCommissionAttribution, SalesPartner
from models.customers import Customers
from models.employees import Employees
from models.service_progresses import Service_progresses
from models.service_tasks import Service_tasks
from models.tasks import Tasks
from backend.services.emp_auth import create_access_token


def _auth_headers(role: str) -> dict[str, str]:
    token = create_access_token({
        "emp_id": 2001,
        "email": f"{role}@example.com",
        "role": role,
        "name": role,
    })
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def employee_read_api():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        session.add(Employees(
            id=1,
            user_id="employee-1",
            name="Sensitive Employee",
            role="ops",
            phone="+1-555-0100",
            email="sensitive@example.com",
            status="active",
            employee_code="EMP-001",
            department="Operations",
            position="Specialist",
            login_username="sensitive-login",
            hire_date="2026-01-01",
            supervisor="Operations Lead",
            notes="private employee note",
        ))
        await session.commit()

        async def override_db():
            yield session

        app.dependency_overrides[employees_router.get_db] = override_db
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client

    app.dependency_overrides.pop(employees_router.get_db, None)
    await engine.dispose()


@pytest_asyncio.fixture
async def employee_integrity_api():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        session.add_all([
            Employees(id=2001, user_id="admin-2001", name="Admin Actor", role="admin", status="active"),
            Employees(id=2002, user_id="owner-2002", name="Only Owner", role="super_admin", status="active"),
            Employees(id=2003, user_id="safe-2003", name="Safe Employee", role="ops", status="active"),
            Employees(id=2010, user_id="customer-2010", name="Customer Owner", role="sales", status="active"),
            Employees(id=2011, user_id="task-2011", name="Task Owner", role="ops", status="active"),
            Employees(id=2012, user_id="service-2012", name="Service Owner", role="ops", status="active"),
            Employees(id=2020, user_id="partner-2020", name="External Partner", role="sales_partner", status="active"),
            Employees(id=2021, user_id="partner-2021", name="Batch Partner", role="sales_partner", status="active"),
            Customers(
                id=301,
                business_name="Assigned Customer",
                contact_name="Owner",
                phone="301",
                sales_person="Customer Owner",
                sales_employee_id=2010,
            ),
            Customers(id=302, business_name="Commission Customer", contact_name="Owner", phone="302"),
            Tasks(
                id=401,
                title="Open employee task",
                assignee_id=2011,
                assignee_name="Task Owner",
                status="pending",
            ),
            Tasks(
                id=402,
                title="Historical employee task",
                assignee_id=2003,
                assignee_name="Safe Employee",
                status="completed",
            ),
            Service_progresses(
                id=501,
                customer_id=302,
                customer_name="Commission Customer",
                service_stage="active",
                ops_person="Service Owner",
                user_id="seed",
            ),
            Service_tasks(
                id=502,
                service_progress_id=501,
                customer_id=302,
                customer_name="Commission Customer",
                task_name="Open delivery task",
                assignee_name="Service Owner",
                status="in_progress",
                user_id="seed",
            ),
            SalesPartner(
                id=601,
                partner_code="PARTNER-2020",
                name="External Partner",
                partner_type="partner",
                employee_id=2020,
                status="active",
                joined_at=date(2026, 1, 1),
            ),
            SalesPartner(
                id=602,
                partner_code="PARTNER-2021",
                name="Batch Partner",
                partner_type="partner",
                employee_id=2021,
                status="active",
                joined_at=date(2026, 1, 1),
            ),
            CustomerCommissionAttribution(
                id=701,
                customer_id=302,
                partner_id=601,
                attribution_role="primary",
                effective_from=date(2026, 1, 1),
                is_active=True,
            ),
        ])
        await session.commit()

        async def override_db():
            yield session

        app.dependency_overrides[employees_router.get_db] = override_db
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client, session

    app.dependency_overrides.pop(employees_router.get_db, None)
    await engine.dispose()


@pytest.mark.asyncio
async def test_employee_write_endpoints_require_admin_role():
    transport = ASGITransport(app=app)
    headers = _auth_headers("sales")
    employee_payload = {
        "name": "Test Employee",
        "role": "sales",
        "email": "test.employee@example.com",
        "status": "active",
    }

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        responses = [
            await ac.post("/api/v1/entities/employees", json=employee_payload, headers=headers),
            await ac.post("/api/v1/entities/employees/batch", json={"items": [employee_payload]}, headers=headers),
            await ac.put("/api/v1/entities/employees/1", json={"name": "Changed"}, headers=headers),
            await ac.put("/api/v1/entities/employees/batch", json={"items": [{"id": 1, "updates": {"name": "Changed"}}]}, headers=headers),
            await ac.delete("/api/v1/entities/employees/1", headers=headers),
            await ac.request("DELETE", "/api/v1/entities/employees/batch", json={"ids": [1]}, headers=headers),
        ]

    assert [response.status_code for response in responses] == [403, 403, 403, 403, 403, 403]


@pytest.mark.asyncio
async def test_employee_write_endpoints_require_login():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/api/v1/entities/employees",
            json={"name": "No Auth", "role": "sales"},
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_non_admin_roles_cannot_read_full_employee_records(employee_read_api: AsyncClient):
    for role in ("sales", "design"):
        headers = _auth_headers(role)
        responses = [
            await employee_read_api.get("/api/v1/entities/employees", headers=headers),
            await employee_read_api.get("/api/v1/entities/employees/all", headers=headers),
            await employee_read_api.get("/api/v1/entities/employees/1", headers=headers),
        ]
        assert [response.status_code for response in responses] == [403, 403, 403]


@pytest.mark.asyncio
async def test_ops_employee_directory_excludes_sensitive_fields(employee_read_api: AsyncClient):
    response = await employee_read_api.get(
        "/api/v1/entities/employees/directory",
        params={"query": '{"status":"active"}', "sort": "name", "limit": 100},
        headers=_auth_headers("ops"),
    )
    sensitive_filter = await employee_read_api.get(
        "/api/v1/entities/employees/directory",
        params={"query": '{"email":"sensitive@example.com"}'},
        headers=_auth_headers("ops"),
    )

    assert response.status_code == 200
    assert response.json()["items"] == [{
        "id": 1,
        "name": "Sensitive Employee",
        "department": "Operations",
        "role": "ops",
        "supervisor": "Operations Lead",
        "status": "active",
    }]
    assert sensitive_filter.status_code == 400


@pytest.mark.asyncio
async def test_admin_can_read_full_employee_records(employee_read_api: AsyncClient):
    headers = _auth_headers("admin")
    regular = await employee_read_api.get("/api/v1/entities/employees", headers=headers)
    all_alias = await employee_read_api.get("/api/v1/entities/employees/all", headers=headers)
    direct = await employee_read_api.get("/api/v1/entities/employees/1", headers=headers)

    assert [regular.status_code, all_alias.status_code, direct.status_code] == [200, 200, 200]
    for item in (regular.json()["items"][0], all_alias.json()["items"][0], direct.json()):
        assert item["phone"] == "+1-555-0100"
        assert item["email"] == "sensitive@example.com"
        assert item["login_username"] == "sensitive-login"
        assert item["notes"] == "private employee note"


@pytest.mark.asyncio
async def test_direct_delete_blocks_self_last_super_admin_and_unhanded_ownership(employee_integrity_api):
    client, db = employee_integrity_api
    headers = _auth_headers("admin")

    self_delete = await client.delete("/api/v1/entities/employees/2001", headers=headers)
    last_owner = await client.delete("/api/v1/entities/employees/2002", headers=headers)
    customer_owner = await client.delete("/api/v1/entities/employees/2010", headers=headers)
    task_owner = await client.delete("/api/v1/entities/employees/2011", headers=headers)
    service_owner = await client.delete("/api/v1/entities/employees/2012", headers=headers)

    assert [
        self_delete.status_code,
        last_owner.status_code,
        customer_owner.status_code,
        task_owner.status_code,
        service_owner.status_code,
    ] == [409, 409, 409, 409, 409]
    assert "当前登录账号" in self_delete.json()["detail"]
    assert "最后一个超级管理员" in last_owner.json()["detail"]
    assert "客户" in customer_owner.json()["detail"]
    assert "待办任务" in task_owner.json()["detail"]
    assert "交付任务" in service_owner.json()["detail"]
    for employee_id in (2001, 2002, 2010, 2011, 2012):
        assert await db.get(Employees, employee_id) is not None


@pytest.mark.asyncio
async def test_single_update_cannot_offboard_owner_or_disable_last_super_admin(employee_integrity_api):
    client, db = employee_integrity_api
    headers = _auth_headers("admin")

    owner_response = await client.put(
        "/api/v1/entities/employees/2010",
        json={"status": "resigned"},
        headers=headers,
    )
    super_admin_response = await client.put(
        "/api/v1/entities/employees/2002",
        json={"status": "disabled"},
        headers=headers,
    )

    assert owner_response.status_code == 409
    assert super_admin_response.status_code == 409
    assert (await db.get(Employees, 2010)).status == "active"
    assert (await db.get(Employees, 2002)).status == "active"


@pytest.mark.asyncio
async def test_unknown_employee_status_is_rejected_before_single_or_batch_mutation(employee_integrity_api):
    client, db = employee_integrity_api
    headers = _auth_headers("admin")

    single = await client.put(
        "/api/v1/entities/employees/2003",
        json={"status": "temporarily-gone"},
        headers=headers,
    )
    batch = await client.put(
        "/api/v1/entities/employees/batch",
        json={
            "items": [
                {"id": 2003, "updates": {"name": "Must Not Persist"}},
                {"id": 2010, "updates": {"status": "typo-disabled"}},
            ]
        },
        headers=headers,
    )

    assert single.status_code == 422
    assert batch.status_code == 422
    assert (await db.get(Employees, 2003)).name == "Safe Employee"
    assert (await db.get(Employees, 2010)).status == "active"


@pytest.mark.asyncio
async def test_batch_update_and_delete_preflight_prevents_partial_writes(employee_integrity_api):
    client, db = employee_integrity_api
    headers = _auth_headers("admin")

    update_response = await client.put(
        "/api/v1/entities/employees/batch",
        json={
            "items": [
                {"id": 2003, "updates": {"name": "Must Not Persist"}},
                {"id": 2002, "updates": {"role": "ops"}},
            ]
        },
        headers=headers,
    )
    delete_response = await client.request(
        "DELETE",
        "/api/v1/entities/employees/batch",
        json={"ids": [2003, 2010]},
        headers=headers,
    )

    assert update_response.status_code == 409
    assert delete_response.status_code == 409
    safe_employee = await db.get(Employees, 2003)
    assert safe_employee is not None
    assert safe_employee.name == "Safe Employee"
    assert await db.get(Employees, 2010) is not None


@pytest.mark.asyncio
async def test_safe_employee_can_be_physically_deleted_after_preflight(employee_integrity_api):
    client, db = employee_integrity_api

    response = await client.delete(
        "/api/v1/entities/employees/2003",
        headers=_auth_headers("admin"),
    )

    assert response.status_code == 200
    assert await db.get(Employees, 2003) is None


@pytest.mark.asyncio
async def test_sales_partner_delete_deactivates_login_and_transfers_attribution(employee_integrity_api):
    client, db = employee_integrity_api

    response = await client.delete(
        "/api/v1/entities/employees/2020",
        headers=_auth_headers("admin"),
    )

    assert response.status_code == 200
    assert response.json()["deactivated"] is True
    employee = await db.get(Employees, 2020)
    partner = await db.get(SalesPartner, 601)
    original_attribution = await db.get(CustomerCommissionAttribution, 701)
    await db.refresh(employee)
    await db.refresh(partner)
    await db.refresh(original_attribution)
    assert employee.status == "disabled"
    assert partner.status == "terminated"
    assert partner.stopped_at == date.today()
    assert original_attribution.is_active is False

    direct_partner = await db.scalar(select(SalesPartner).where(SalesPartner.partner_type == "direct"))
    assert direct_partner is not None
    replacement = await db.scalar(select(CustomerCommissionAttribution).where(
        CustomerCommissionAttribution.customer_id == 302,
        CustomerCommissionAttribution.partner_id == direct_partner.id,
        CustomerCommissionAttribution.is_active.is_(True),
    ))
    assert replacement is not None


@pytest.mark.asyncio
async def test_batch_update_syncs_existing_sales_partner_when_role_is_omitted(employee_integrity_api):
    client, db = employee_integrity_api

    response = await client.put(
        "/api/v1/entities/employees/batch",
        json={
            "items": [
                {"id": 2003, "updates": {"name": "Updated Internal"}},
                {"id": 2021, "updates": {"name": "Updated Partner", "status": "disabled"}},
            ]
        },
        headers=_auth_headers("admin"),
    )

    assert response.status_code == 200
    internal = await db.get(Employees, 2003)
    employee = await db.get(Employees, 2021)
    partner = await db.get(SalesPartner, 602)
    await db.refresh(internal)
    await db.refresh(employee)
    await db.refresh(partner)
    assert internal.name == "Updated Internal"
    assert employee.name == "Updated Partner"
    assert employee.status == "disabled"
    assert partner.name == "Updated Partner"
    assert partner.status == "terminated"
    assert partner.stopped_at == date.today()


@pytest.mark.asyncio
async def test_batch_rejects_sales_partner_role_change_before_any_write(employee_integrity_api):
    client, db = employee_integrity_api

    response = await client.put(
        "/api/v1/entities/employees/batch",
        json={
            "items": [
                {"id": 2003, "updates": {"name": "Must Not Persist"}},
                {"id": 2021, "updates": {"role": "sales"}},
            ]
        },
        headers=_auth_headers("admin"),
    )

    assert response.status_code == 409
    assert (await db.get(Employees, 2003)).name == "Safe Employee"
    assert (await db.get(Employees, 2021)).role == "sales_partner"
    assert (await db.get(SalesPartner, 602)).status == "active"
