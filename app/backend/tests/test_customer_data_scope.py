from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy import select

from backend.main import app
from backend.routers.customers import CustomersData
from backend.services.emp_auth import create_access_token
from core.database import Base
from models.customer_access_grants import CustomerAccessGrant
from models.employees import Employees
from models.deals import Deals
from models.follow_ups import Follow_ups
from models.customer_contacts import Customer_contacts
from models.service_progresses import Service_progresses
from models.service_tasks import Service_tasks
from models.subscriptions import Subscriptions
from services.customer_contacts import Customer_contactsService
from services.customers import CustomersService
from services.follow_ups import Follow_upsService
from services.service_progresses import Service_progressesService
from services.service_tasks import Service_tasksService


def _auth_headers(role: str, emp_id: int = 6001, name: str | None = None) -> dict[str, str]:
    token = create_access_token({
        "emp_id": emp_id,
        "email": f"{role}@example.com",
        "role": role,
        "name": name or role,
    })
    return {"Authorization": f"Bearer {token}"}


def test_customer_payload_accepts_blank_optional_numeric_fields():
    payload = CustomersData(
        business_name="Blank Owner Cafe",
        contact_name="Owner",
        phone="555",
        sales_employee_id="",
        monthly_orders="",
        interested_packages="google_business_management",
    )

    assert payload.sales_employee_id is None
    assert payload.monthly_orders is None
    assert payload.interested_packages == "google_business_management"


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_customer_service_scopes_sales_to_explicitly_visible_customers(db_session):
    service = CustomersService(db_session)
    own_by_id = await service.create({
        "business_name": "Alice Cafe",
        "contact_name": "Alice",
        "phone": "111",
        "sales_employee_id": 101,
        "sales_person": "Someone Else",
    })
    own_by_name = await service.create({
        "business_name": "Alice Bakery",
        "contact_name": "Alice",
        "phone": "222",
        "sales_person": "Alice",
    })
    other = await service.create({
        "business_name": "Bob Shop",
        "contact_name": "Bob",
        "phone": "333",
        "sales_employee_id": 202,
        "sales_person": "Bob",
    })
    same_name_other_owner = await service.create({
        "business_name": "Other Alice Owner",
        "contact_name": "Other Alice",
        "phone": "444",
        "sales_employee_id": 202,
        "sales_person": "Alice",
    })
    db_session.add_all([
        CustomerAccessGrant(customer_id=own_by_id.id, employee_id=101, granted_by_name="Admin"),
        CustomerAccessGrant(customer_id=own_by_name.id, employee_id=101, granted_by_name="Admin"),
    ])
    await db_session.commit()

    alice_user = SimpleNamespace(id="101", role="sales", name="Alice")
    scoped = await service.get_list(limit=10, scope_user=alice_user)
    scoped_names = {item.business_name for item in scoped["items"]}

    assert scoped["total"] == 2
    assert scoped_names == {"Alice Cafe", "Alice Bakery"}
    assert await service.get_by_id(own_by_id.id, scope_user=alice_user) is not None
    assert await service.get_by_id(own_by_name.id, scope_user=alice_user) is not None
    assert await service.get_by_id(other.id, scope_user=alice_user) is None
    # A populated owner id takes precedence over the legacy, non-unique name.
    assert await service.get_by_id(same_name_other_owner.id, scope_user=alice_user) is None

    grant = (await db_session.execute(
        select(CustomerAccessGrant).where(
            CustomerAccessGrant.customer_id == own_by_id.id,
            CustomerAccessGrant.employee_id == 101,
        )
    )).scalar_one()
    await db_session.delete(grant)
    await db_session.commit()
    # Removing an explicit grant must not hide a customer that is still owned
    # by the same sales employee.
    assert await service.get_by_id(own_by_id.id, scope_user=alice_user) is not None
    assert own_by_id.sales_employee_id == 101


@pytest.mark.asyncio
async def test_customer_service_finance_sees_all_but_operations_requires_invitation(db_session):
    service = CustomersService(db_session)
    invited = await service.create({"business_name": "A", "contact_name": "A", "phone": "111", "sales_employee_id": 101})
    await service.create({"business_name": "B", "contact_name": "B", "phone": "222", "sales_employee_id": 202})
    db_session.add(CustomerAccessGrant(customer_id=invited.id, employee_id=404, granted_by_name="Admin"))
    await db_session.commit()

    finance_user = SimpleNamespace(id="303", role="finance", name="Finance")
    operations_user = SimpleNamespace(id="404", role="operations", name="Ops")
    finance_scoped = await service.get_list(limit=10, scope_user=finance_user)
    operations_scoped = await service.get_list(limit=10, scope_user=operations_user)

    assert finance_scoped["total"] == 2
    assert operations_scoped["total"] == 1
    assert operations_scoped["items"][0].business_name == "A"


@pytest.mark.asyncio
async def test_customer_access_endpoint_replaces_invited_employees(db_session, monkeypatch):
    customer = await CustomersService(db_session).create({"business_name": "Private Cafe", "contact_name": "Owner", "phone": "555"})
    second_customer = await CustomersService(db_session).create({"business_name": "Second Cafe", "contact_name": "Owner", "phone": "556"})
    customer_id = customer.id
    second_customer_id = second_customer.id
    db_session.add_all([
        Employees(id=801, user_id="801", name="Ops One", role="ops", status="active"),
        Employees(id=802, user_id="802", name="Sales Two", role="sales", status="active"),
    ])
    await db_session.commit()

    from backend.routers import customers as customers_router
    async def override_db():
        yield db_session
    app.dependency_overrides[customers_router.get_db] = override_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.put(
                f"/api/v1/entities/customers/{customer_id}/access",
                json={"members": [
                    {"employee_id": 801, "access_level": "read_only"},
                    {"employee_id": 802, "access_level": "read_write"},
                ]},
                headers=_auth_headers("admin", emp_id=9001, name="Admin"),
            )
            assert response.status_code == 200
            assert {row["employee_id"] for row in response.json()["members"]} == {801, 802}
            assert {row["employee_id"]: row["access_level"] for row in response.json()["members"]} == {
                801: "read_only", 802: "read_write",
            }

            read_only_update = await ac.put(
                f"/api/v1/entities/customers/{customer_id}",
                json={"business_name": "Read-only edit must fail"},
                headers=_auth_headers("ops", emp_id=801, name="Ops One"),
            )
            assert read_only_update.status_code == 403

            bulk_add = await ac.post(
                "/api/v1/entities/customers/access/bulk-update",
                json={
                    "customer_ids": [customer_id, second_customer_id],
                    "operation": "upsert",
                    "members": [{"employee_id": 801, "access_level": "read_write"}],
                },
                headers=_auth_headers("admin", emp_id=9001, name="Admin"),
            )
            assert bulk_add.status_code == 200
            assert bulk_add.json()["updated_grants"] == 2

            read_write_update = await ac.put(
                f"/api/v1/entities/customers/{customer_id}",
                json={"business_name": "Writable Team Customer"},
                headers=_auth_headers("ops", emp_id=801, name="Ops One"),
            )
            assert read_write_update.status_code == 200
            assert read_write_update.json()["business_name"] == "Writable Team Customer"

            bulk_remove = await ac.post(
                "/api/v1/entities/customers/access/bulk-update",
                json={
                    "customer_ids": [customer_id, second_customer_id],
                    "operation": "remove",
                    "members": [{"employee_id": 801, "access_level": "read_only"}],
                },
                headers=_auth_headers("admin", emp_id=9001, name="Admin"),
            )
            assert bulk_remove.status_code == 200
            assert bulk_remove.json()["updated_grants"] == 2

            replacement = await ac.put(
                f"/api/v1/entities/customers/{customer_id}/access",
                json={"employee_ids": [801]},
                headers=_auth_headers("admin", emp_id=9001, name="Admin"),
            )
            assert replacement.status_code == 200
            assert [row["employee_id"] for row in replacement.json()["members"]] == [801]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_non_finance_customer_records_are_scoped_and_amounts_redacted(db_session):
    visible = await CustomersService(db_session).create({"business_name": "Visible", "contact_name": "V", "phone": "111"})
    hidden = await CustomersService(db_session).create({"business_name": "Hidden", "contact_name": "H", "phone": "222"})
    db_session.add_all([
        CustomerAccessGrant(customer_id=visible.id, employee_id=404, granted_by_name="Admin"),
        Deals(customer_id=visible.id, product_type="service", deal_amount=999, is_paid=True),
        Deals(customer_id=hidden.id, product_type="service", deal_amount=888, is_paid=True),
        Subscriptions(customer_id=visible.id, package_name="Visible Plan", package_price=249, status="active"),
        Subscriptions(customer_id=hidden.id, package_name="Hidden Plan", package_price=399, status="active"),
    ])
    await db_session.commit()

    from backend.routers import deals as deals_router
    from backend.routers import subscriptions as subscriptions_router
    async def override_db():
        yield db_session
    app.dependency_overrides[deals_router.get_db] = override_db
    app.dependency_overrides[subscriptions_router.get_db] = override_db
    try:
        transport = ASGITransport(app=app)
        headers = _auth_headers("ops", emp_id=404, name="Ops")
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            deals_response = await ac.get("/api/v1/entities/deals?limit=20", headers=headers)
            subscriptions_response = await ac.get("/api/v1/entities/subscriptions?limit=20", headers=headers)

        assert deals_response.status_code == 200
        assert [row["customer_id"] for row in deals_response.json()["items"]] == [visible.id]
        assert deals_response.json()["items"][0]["deal_amount"] is None
        assert deals_response.json()["items"][0]["is_paid"] is None
        assert subscriptions_response.status_code == 200
        assert [row["customer_id"] for row in subscriptions_response.json()["items"]] == [visible.id]
        assert subscriptions_response.json()["items"][0]["package_price"] is None
        assert subscriptions_response.json()["items"][0]["last_payment_date"] is None
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_customer_access_removal_hides_linked_operational_records(db_session):
    visible = await CustomersService(db_session).create({"business_name": "Visible Ops", "contact_name": "V", "phone": "111"})
    hidden = await CustomersService(db_session).create({"business_name": "Hidden Ops", "contact_name": "H", "phone": "222"})
    db_session.add_all([
        CustomerAccessGrant(customer_id=visible.id, employee_id=404, granted_by_name="Admin"),
        Follow_ups(customer_id=visible.id, content="visible follow-up"),
        Follow_ups(customer_id=hidden.id, content="hidden follow-up"),
        Customer_contacts(customer_id=visible.id, contact_name="Visible Contact"),
        Customer_contacts(customer_id=hidden.id, contact_name="Hidden Contact"),
        Service_progresses(customer_id=visible.id, service_stage="active", user_id="admin"),
        Service_progresses(customer_id=hidden.id, service_stage="active", user_id="admin"),
        Service_tasks(customer_id=visible.id, task_name="Visible Task", status="pending", user_id="admin"),
        Service_tasks(customer_id=hidden.id, task_name="Hidden Task", status="pending", user_id="admin"),
    ])
    await db_session.commit()

    operations_user = SimpleNamespace(id="404", role="ops", name="Ops")
    assert (await Follow_upsService(db_session).get_list(limit=20, scope_user=operations_user))["total"] == 1
    assert (await Customer_contactsService(db_session).get_list(limit=20, scope_user=operations_user))["total"] == 1
    assert (await Service_progressesService(db_session).get_list(limit=20, scope_user=operations_user))["total"] == 1
    assert (await Service_tasksService(db_session).get_list(limit=20, scope_user=operations_user))["total"] == 1

    grant = (await db_session.execute(
        select(CustomerAccessGrant).where(
            CustomerAccessGrant.customer_id == visible.id,
            CustomerAccessGrant.employee_id == 404,
        )
    )).scalar_one()
    await db_session.delete(grant)
    await db_session.commit()
    assert (await Follow_upsService(db_session).get_list(limit=20, scope_user=operations_user))["total"] == 0
    assert (await Customer_contactsService(db_session).get_list(limit=20, scope_user=operations_user))["total"] == 0
    assert (await Service_progressesService(db_session).get_list(limit=20, scope_user=operations_user))["total"] == 0
    assert (await Service_tasksService(db_session).get_list(limit=20, scope_user=operations_user))["total"] == 0


@pytest.mark.asyncio
async def test_read_only_customer_member_can_view_but_cannot_modify_linked_records(db_session):
    customer = await CustomersService(db_session).create({"business_name": "Read Only Ops", "contact_name": "Owner", "phone": "111"})
    follow_up = Follow_ups(customer_id=customer.id, content="visible but protected")
    grant = CustomerAccessGrant(
        customer_id=customer.id,
        employee_id=404,
        access_level="read_only",
        granted_by_name="Admin",
    )
    db_session.add_all([follow_up, grant])
    await db_session.commit()
    follow_up_id = follow_up.id
    grant_id = grant.id

    operations_user = SimpleNamespace(id="404", role="ops", name="Ops")
    service = Follow_upsService(db_session)
    assert (await service.get_list(limit=20, scope_user=operations_user))["total"] == 1
    with pytest.raises(HTTPException) as exc_info:
        await service.update(follow_up_id, {"content": "forbidden"}, scope_user=operations_user)
    assert exc_info.value.status_code == 403

    grant = await db_session.get(CustomerAccessGrant, grant_id)
    grant.access_level = "read_write"
    await db_session.commit()
    updated = await service.update(follow_up_id, {"content": "allowed"}, scope_user=operations_user)
    assert updated.content == "allowed"


@pytest.mark.asyncio
async def test_customer_write_permissions_reject_finance_and_sales_delete():
    transport = ASGITransport(app=app)
    customer_payload = {
        "business_name": "Protected Cafe",
        "contact_name": "Owner",
        "phone": "555",
    }

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        finance_create = await ac.post(
            "/api/v1/entities/customers",
            json=customer_payload,
            headers=_auth_headers("finance", emp_id=7001, name="Finance"),
        )
        sales_delete = await ac.delete(
            "/api/v1/entities/customers/1",
            headers=_auth_headers("sales", emp_id=7002, name="Sales"),
        )

    assert finance_create.status_code == 403
    assert sales_delete.status_code == 403


@pytest.mark.asyncio
async def test_customer_routes_enforce_page_and_button_contracts(db_session):
    """A customer grant never bypasses the page contract or write buttons."""
    service = CustomersService(db_session)
    design_customer = await service.create({
        "business_name": "Design Hidden Profile",
        "contact_name": "Private Owner",
        "phone": "555-1000",
    })
    sales_customer = await service.create({
        "business_name": "Sales Owned Profile",
        "contact_name": "Sales Owner",
        "phone": "555-2000",
        "sales_employee_id": 9102,
        "sales_person": "Sales User",
    })
    ops_customer = await service.create({
        "business_name": "Operations Profile",
        "contact_name": "Ops Owner",
        "phone": "555-3000",
    })
    db_session.add_all([
        CustomerAccessGrant(customer_id=design_customer.id, employee_id=9101, granted_by_name="Admin"),
        CustomerAccessGrant(customer_id=ops_customer.id, employee_id=9103, granted_by_name="Admin"),
    ])
    await db_session.commit()
    design_customer_id = design_customer.id
    sales_customer_id = sales_customer.id
    ops_customer_id = ops_customer.id

    from backend.routers import customers as customers_router

    async def override_db():
        yield db_session

    app.dependency_overrides[customers_router.get_db] = override_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            design_headers = _auth_headers("design", emp_id=9101, name="Designer")
            for path in (
                "/api/v1/entities/customers?limit=20",
                "/api/v1/entities/customers/all?limit=20",
                f"/api/v1/entities/customers/{design_customer_id}",
                f"/api/v1/entities/customers/{design_customer_id}/projects",
            ):
                response = await ac.get(path, headers=design_headers)
                assert response.status_code == 403

            payload = {
                "business_name": "Direct Write Attempt",
                "contact_name": "Owner",
                "phone": "555-4000",
            }
            sales_headers = _auth_headers("sales", emp_id=9102, name="Sales User")
            assert (await ac.post(
                "/api/v1/entities/customers",
                json=payload,
                headers=sales_headers,
            )).status_code == 403
            assert (await ac.put(
                f"/api/v1/entities/customers/{sales_customer_id}",
                json={"business_name": "Sales Direct Edit"},
                headers=sales_headers,
            )).status_code == 403

            ops_headers = _auth_headers("ops", emp_id=9103, name="Ops User")
            assert (await ac.post(
                "/api/v1/entities/customers",
                json=payload,
                headers=ops_headers,
            )).status_code == 403
            ops_update = await ac.put(
                f"/api/v1/entities/customers/{ops_customer_id}",
                json={"business_name": "Operations Updated Profile"},
                headers=ops_headers,
            )
            assert ops_update.status_code == 200
            assert ops_update.json()["business_name"] == "Operations Updated Profile"
    finally:
        app.dependency_overrides.clear()
