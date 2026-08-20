import json
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.main import app
from backend.routers import customer_callbacks as callbacks_router
from backend.routers import customer_contacts as contacts_router
from backend.routers import follow_ups as follow_ups_router
from core.database import Base
from models.customer_access_grants import CustomerAccessGrant
from models.customer_callbacks import Customer_callbacks
from models.customer_contacts import Customer_contacts
from models.customers import Customers
from models.employees import Employees
from models.follow_ups import Follow_ups
from services.emp_auth import create_access_token


def _headers(role: str, employee_id: int, name: str) -> dict[str, str]:
    token = create_access_token({
        "emp_id": employee_id,
        "email": f"interaction-{employee_id}@example.com",
        "role": role,
        "name": name,
    })
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def interaction_api():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        session.add_all([
            Employees(id=1, user_id="1", name="Admin", role="admin", status="active", email="interaction-1@example.com"),
            Employees(id=11, user_id="11", name="Sales One", role="sales", status="active", email="interaction-11@example.com"),
            Employees(id=12, user_id="12", name="Sales Manager", role="sales_manager", status="active", email="interaction-12@example.com", department="Sales East"),
            Employees(id=13, user_id="13", name="Sales One", role="sales", status="active", email="interaction-13@example.com"),
            Employees(id=14, user_id="14", name="East Report", role="sales", status="probation", email="interaction-14@example.com", department="Sales East"),
            Employees(id=15, user_id="15", name="West Report", role="sales", status="active", email="interaction-15@example.com", department="Sales West"),
            Employees(id=16, user_id="16", name="Inactive East", role="sales", status="inactive", email="interaction-16@example.com", department="Sales East"),
            Employees(id=21, user_id="21", name="Ops One", role="ops", status="active", email="interaction-21@example.com"),
            Employees(id=31, user_id="31", name="Designer", role="design", status="active", email="interaction-31@example.com"),
            Employees(id=41, user_id="41", name="Finance", role="finance", status="active", email="interaction-41@example.com"),
            Customers(id=101, business_name="Sales Owned", contact_name="Owner", phone="101", sales_employee_id=11, sales_person="Sales One"),
            Customers(id=102, business_name="Sales Granted", contact_name="Owner", phone="102"),
            Customers(id=103, business_name="Hidden", contact_name="Owner", phone="103"),
            Customers(id=104, business_name="Ops Granted", contact_name="Owner", phone="104"),
            Customers(id=105, business_name="Same Name Strong Owner", contact_name="Owner", phone="105", sales_employee_id=13, sales_person="Sales One"),
            Customers(id=106, business_name="Manager Department", contact_name="Owner", phone="106", sales_employee_id=14, sales_person="East Report"),
            Customers(id=107, business_name="Manager Other Department", contact_name="Owner", phone="107", sales_employee_id=15, sales_person="West Report"),
            Customers(id=108, business_name="Manager Inactive Department", contact_name="Owner", phone="108", sales_employee_id=16, sales_person="Inactive East"),
            Customers(id=109, business_name="Read-only Operations", contact_name="Owner", phone="109"),
            CustomerAccessGrant(customer_id=102, employee_id=11, granted_by_name="Admin"),
            CustomerAccessGrant(customer_id=104, employee_id=21, granted_by_name="Admin"),
            CustomerAccessGrant(customer_id=109, employee_id=21, access_level="read_only", granted_by_name="Admin"),
            Customer_callbacks(id=201, customer_id=101, employee_id=11, employee_name="Sales One", callback_date=datetime(2026, 8, 16, tzinfo=timezone.utc), status="pending", content="owned"),
            Customer_callbacks(id=202, customer_id=102, employee_id=11, employee_name="Sales One", callback_date=datetime(2026, 8, 16, tzinfo=timezone.utc), status="pending", content="granted"),
            Customer_callbacks(id=203, customer_id=103, employee_id=1, employee_name="Admin", callback_date=datetime(2026, 8, 16, tzinfo=timezone.utc), status="pending", content="hidden"),
            Customer_callbacks(id=204, customer_id=104, employee_id=21, employee_name="Ops One", created_by_employee_id=1, created_by_employee_name="Original Admin", callback_date=datetime(2026, 8, 16, tzinfo=timezone.utc), status="pending", content="ops", created_at=datetime(2026, 8, 1, tzinfo=timezone.utc), updated_at=datetime(2026, 8, 2, tzinfo=timezone.utc)),
            Customer_callbacks(id=205, customer_id=105, employee_id=13, employee_name="Sales One", callback_date=datetime(2026, 8, 16, tzinfo=timezone.utc), status="pending", content="same-name strong owner"),
            Customer_callbacks(id=206, customer_id=106, employee_id=14, employee_name="East Report", callback_date=datetime(2026, 8, 16, tzinfo=timezone.utc), status="pending", content="manager department"),
            Customer_callbacks(id=207, customer_id=107, employee_id=15, employee_name="West Report", callback_date=datetime(2026, 8, 16, tzinfo=timezone.utc), status="pending", content="manager other department"),
            Customer_callbacks(id=208, customer_id=108, employee_id=16, employee_name="Inactive East", callback_date=datetime(2026, 8, 16, tzinfo=timezone.utc), status="pending", content="manager inactive department"),
            Customer_callbacks(id=209, customer_id=109, employee_id=21, employee_name="Ops One", callback_date=datetime(2026, 8, 16, tzinfo=timezone.utc), status="pending", content="read only"),
            Follow_ups(id=301, customer_id=104, employee_id=21, employee_name="Ops One", content="ops follow"),
            Follow_ups(id=302, customer_id=101, employee_id=11, employee_name="Sales One", content="sales follow"),
            Customer_contacts(id=401, customer_id=104, contact_name="Ops Contact"),
            Customer_contacts(id=402, customer_id=101, contact_name="Sales Contact"),
        ])
        await session.execute(text(
            "CREATE TABLE IF NOT EXISTS app_settings "
            "(config_key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TIMESTAMP)"
        ))
        role_permissions = {
            "admin": {
                "pages": ["/customers", "/callbacks"],
                "buttons": ["customer_edit"],
                "dataScope": "all",
            },
            "sales": {
                "pages": ["/customers"],
                "buttons": ["follow_up_create", "follow_up_edit"],
                "dataScope": "self",
            },
            "sales_manager": {
                "pages": ["/customers"],
                "buttons": ["follow_up_create", "follow_up_edit"],
                "dataScope": "department",
            },
            "ops": {
                "pages": ["/customers", "/callbacks"],
                "buttons": ["customer_edit", "follow_up_create", "follow_up_edit"],
                "dataScope": "all",
            },
            "design": {"pages": ["/tasks"], "buttons": ["task_edit"], "dataScope": "self"},
            "finance": {"pages": ["/customers"], "buttons": [], "dataScope": "all"},
        }
        await session.execute(
            text("INSERT INTO app_settings (config_key, value_json) VALUES ('role_permissions', :value)"),
            {"value": json.dumps(role_permissions)},
        )
        await session.commit()

        async def override_db():
            yield session

        for dependency in (callbacks_router.get_db, contacts_router.get_db, follow_ups_router.get_db):
            app.dependency_overrides[dependency] = override_db

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client, session

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_callback_list_all_and_id_are_server_scoped(interaction_api):
    client, _ = interaction_api
    sales = _headers("sales", 11, "Sales One")
    ops = _headers("ops", 21, "Ops One")
    admin = _headers("admin", 1, "Admin")

    sales_list = await client.get("/api/v1/entities/customer_callbacks?limit=100", headers=sales)
    sales_all = await client.get("/api/v1/entities/customer_callbacks/all?limit=100", headers=sales)
    hidden_direct = await client.get("/api/v1/entities/customer_callbacks/203", headers=sales)
    same_name_direct = await client.get("/api/v1/entities/customer_callbacks/205", headers=sales)
    ops_list = await client.get("/api/v1/entities/customer_callbacks?limit=100", headers=ops)
    admin_list = await client.get("/api/v1/entities/customer_callbacks?limit=100", headers=admin)
    strong_owner_list = await client.get(
        "/api/v1/entities/customer_callbacks?limit=100",
        headers=_headers("sales", 13, "Sales One"),
    )
    manager_list = await client.get(
        "/api/v1/entities/customer_callbacks?limit=100",
        headers=_headers("sales_manager", 12, "Sales Manager"),
    )
    manager_cross_department = await client.get(
        "/api/v1/entities/customer_callbacks/207",
        headers=_headers("sales_manager", 12, "Sales Manager"),
    )
    manager_inactive_department = await client.get(
        "/api/v1/entities/customer_callbacks/208",
        headers=_headers("sales_manager", 12, "Sales Manager"),
    )

    assert sales_list.status_code == 200
    assert {row["id"] for row in sales_list.json()["items"]} == {201, 202}
    assert {row["id"] for row in sales_all.json()["items"]} == {201, 202}
    assert hidden_direct.status_code == 404
    assert same_name_direct.status_code == 404
    assert {row["id"] for row in strong_owner_list.json()["items"]} == {205}
    assert {row["id"] for row in manager_list.json()["items"]} == {206}
    assert manager_cross_department.status_code == 404
    assert manager_inactive_department.status_code == 404
    assert {row["id"] for row in ops_list.json()["items"]} == {204, 209}
    assert {row["id"] for row in admin_list.json()["items"]} == {201, 202, 203, 204, 205, 206, 207, 208, 209}


@pytest.mark.asyncio
async def test_read_only_team_member_can_view_callback_but_cannot_mutate_it(interaction_api):
    client, _ = interaction_api
    ops = _headers("ops", 21, "Ops One")
    visible = await client.get("/api/v1/entities/customer_callbacks/209", headers=ops)
    assert visible.status_code == 200

    created = await client.post(
        "/api/v1/entities/customer_callbacks",
        json={
            "customer_id": 109,
            "employee_id": 21,
            "employee_name": "Ops One",
            "callback_date": "2026-08-20T00:00:00Z",
            "status": "pending",
            "content": "must not create",
        },
        headers=ops,
    )
    updated = await client.put(
        "/api/v1/entities/customer_callbacks/209",
        json={"content": "must not update"},
        headers=ops,
    )
    assert created.status_code == 403
    assert updated.status_code == 403


@pytest.mark.asyncio
async def test_callback_create_and_update_ignore_forged_server_audit(interaction_api):
    client, session = interaction_api
    ops = _headers("ops", 21, "Ops One")
    forged_created_at = "2000-01-01T00:00:00Z"
    forged_updated_at = "2000-01-02T00:00:00Z"

    created = await client.post(
        "/api/v1/entities/customer_callbacks",
        json={
            "customer_id": 104,
            "employee_id": 21,
            "employee_name": "Ops One",
            "callback_date": "2026-08-17T00:00:00Z",
            "status": "pending",
            "content": "server audited",
            "created_by_employee_id": 999,
            "created_by_employee_name": "Forged Creator",
            "created_at": forged_created_at,
            "updated_at": forged_updated_at,
            "completed_by_employee_id": 999,
        },
        headers=ops,
    )
    assert created.status_code == 201
    created_body = created.json()
    assert created_body["created_by_employee_id"] == 21
    assert created_body["created_by_employee_name"] == "Ops One"
    assert not created_body["created_at"].startswith("2000-01-01")
    assert not created_body["updated_at"].startswith("2000-01-02")
    assert created_body["completed_by_employee_id"] is None

    updated = await client.put(
        "/api/v1/entities/customer_callbacks/204",
        json={
            "content": "legitimate edit",
            "created_by_employee_id": 999,
            "created_by_employee_name": "Forged Editor",
            "created_at": forged_created_at,
            "updated_at": forged_updated_at,
            "completed_by_employee_id": 999,
            "completed_by_employee_name": "Forged Completer",
            "completed_at": forged_updated_at,
        },
        headers=ops,
    )
    assert updated.status_code == 200
    session.expire_all()
    callback = (await session.execute(
        select(Customer_callbacks).where(Customer_callbacks.id == 204)
    )).scalar_one()
    assert callback.content == "legitimate edit"
    assert callback.created_by_employee_id == 1
    assert callback.created_by_employee_name == "Original Admin"
    assert callback.created_at.year == 2026
    assert callback.updated_at.year != 2000
    assert callback.completed_by_employee_id is None
    assert callback.completed_by_employee_name is None
    assert callback.completed_at is None


@pytest.mark.asyncio
async def test_callback_design_and_finance_are_denied_on_direct_apis(interaction_api):
    client, _ = interaction_api
    design = _headers("design", 31, "Designer")
    finance = _headers("finance", 41, "Finance")

    for headers in (design, finance):
        assert (await client.get("/api/v1/entities/customer_callbacks", headers=headers)).status_code == 403
        assert (await client.get("/api/v1/entities/customer_callbacks/201", headers=headers)).status_code == 403
        assert (await client.delete("/api/v1/entities/customer_callbacks/201", headers=headers)).status_code == 403


@pytest.mark.asyncio
async def test_callback_writes_require_permission_and_visible_customer(interaction_api):
    client, session = interaction_api
    sales = _headers("sales", 11, "Sales One")
    ops = _headers("ops", 21, "Ops One")
    admin = _headers("admin", 1, "Admin")
    payload = {
        "customer_id": 104,
        "employee_id": 21,
        "employee_name": "Ops One",
        "callback_date": "2026-08-17T00:00:00Z",
        "status": "pending",
        "content": "new callback",
    }

    assert (await client.post("/api/v1/entities/customer_callbacks", json=payload, headers=ops)).status_code == 201
    assert (await client.post("/api/v1/entities/customer_callbacks", json=payload, headers=sales)).status_code == 403
    assert (await client.post(
        "/api/v1/entities/customer_callbacks",
        json={**payload, "customer_id": 103},
        headers=ops,
    )).status_code == 404
    admin_created = await client.post(
        "/api/v1/entities/customer_callbacks",
        json={**payload, "customer_id": 103, "employee_id": 1, "employee_name": "Admin"},
        headers=admin,
    )
    assert admin_created.status_code == 201
    assert (await client.put(
        f"/api/v1/entities/customer_callbacks/{admin_created.json()['id']}",
        json={"content": "admin override edit"},
        headers=admin,
    )).status_code == 200
    assert (await client.put(
        "/api/v1/entities/customer_callbacks/204",
        json={"customer_id": 103, "content": "must not move"},
        headers=ops,
    )).status_code == 404
    await session.refresh((await session.execute(select(Customer_callbacks).where(Customer_callbacks.id == 204))).scalar_one())
    callback = (await session.execute(select(Customer_callbacks).where(Customer_callbacks.id == 204))).scalar_one()
    assert callback.customer_id == 104
    assert callback.content == "ops"

    assert (await client.delete("/api/v1/entities/customer_callbacks/201", headers=sales)).status_code == 403
    assert (await client.delete("/api/v1/entities/customer_callbacks/204", headers=ops)).status_code == 403
    assert (await client.delete("/api/v1/entities/customer_callbacks/203", headers=admin)).status_code == 200


@pytest.mark.asyncio
async def test_callback_batch_preflight_prevents_partial_cross_scope_update(interaction_api):
    client, session = interaction_api
    ops = _headers("ops", 21, "Ops One")
    response = await client.put(
        "/api/v1/entities/customer_callbacks/batch",
        json={"items": [
            {"id": 204, "updates": {"content": "would be first"}},
            {"id": 203, "updates": {"content": "hidden"}},
        ]},
        headers=ops,
    )
    assert response.status_code == 404
    session.expire_all()
    callback = (await session.execute(select(Customer_callbacks).where(Customer_callbacks.id == 204))).scalar_one()
    assert callback.content == "ops"


@pytest.mark.asyncio
async def test_follow_up_and_contact_mutations_use_configured_buttons(interaction_api):
    client, session = interaction_api
    sales = _headers("sales", 11, "Sales One")
    ops = _headers("ops", 21, "Ops One")
    admin = _headers("admin", 1, "Admin")
    finance = _headers("finance", 41, "Finance")

    follow_created = await client.post(
        "/api/v1/entities/follow_ups",
        json={"customer_id": 104, "content": "ops created"},
        headers=ops,
    )
    assert follow_created.status_code == 201
    assert (await client.put(
        "/api/v1/entities/follow_ups/301",
        json={"content": "ops edited"},
        headers=ops,
    )).status_code == 200
    assert (await client.delete("/api/v1/entities/follow_ups/301", headers=ops)).status_code == 403
    assert (await client.delete("/api/v1/entities/follow_ups/302", headers=sales)).status_code == 403
    assert (await client.delete("/api/v1/entities/follow_ups/301", headers=admin)).status_code == 200

    contact_created = await client.post(
        "/api/v1/entities/customer_contacts",
        json={"customer_id": 104, "contact_name": "New Ops Contact"},
        headers=ops,
    )
    assert contact_created.status_code == 201
    assert (await client.put(
        "/api/v1/entities/customer_contacts/401",
        json={"contact_name": "Ops Edited"},
        headers=ops,
    )).status_code == 200
    assert (await client.put(
        "/api/v1/entities/customer_contacts/401",
        json={"customer_id": 103},
        headers=ops,
    )).status_code == 404
    assert (await client.delete("/api/v1/entities/customer_contacts/401", headers=ops)).status_code == 403
    assert (await client.delete("/api/v1/entities/customer_contacts/402", headers=sales)).status_code == 403
    assert (await client.put(
        "/api/v1/entities/customer_contacts/401",
        json={"contact_name": "Finance bypass"},
        headers=finance,
    )).status_code == 403

    session.expire_all()
    contact = (await session.execute(select(Customer_contacts).where(Customer_contacts.id == 401))).scalar_one()
    assert contact.customer_id == 104
    assert contact.contact_name == "Ops Edited"
    assert (await client.delete("/api/v1/entities/customer_contacts/401", headers=admin)).status_code == 200
