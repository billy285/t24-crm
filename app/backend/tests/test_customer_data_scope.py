from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.main import app
from backend.services.emp_auth import create_access_token
from core.database import Base
from services.customers import CustomersService


def _auth_headers(role: str, emp_id: int = 6001, name: str | None = None) -> dict[str, str]:
    token = create_access_token({
        "emp_id": emp_id,
        "email": f"{role}@example.com",
        "role": role,
        "name": name or role,
    })
    return {"Authorization": f"Bearer {token}"}


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
async def test_customer_service_scopes_sales_to_assigned_customers(db_session):
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

    alice_user = SimpleNamespace(id="101", role="sales", name="Alice")
    scoped = await service.get_list(limit=10, scope_user=alice_user)
    scoped_names = {item.business_name for item in scoped["items"]}

    assert scoped["total"] == 2
    assert scoped_names == {"Alice Cafe", "Alice Bakery"}
    assert await service.get_by_id(own_by_id.id, scope_user=alice_user) is not None
    assert await service.get_by_id(own_by_name.id, scope_user=alice_user) is not None
    assert await service.get_by_id(other.id, scope_user=alice_user) is None


@pytest.mark.asyncio
async def test_customer_service_all_scope_roles_can_view_all_customers(db_session):
    service = CustomersService(db_session)
    await service.create({"business_name": "A", "contact_name": "A", "phone": "111", "sales_employee_id": 101})
    await service.create({"business_name": "B", "contact_name": "B", "phone": "222", "sales_employee_id": 202})

    finance_user = SimpleNamespace(id="303", role="finance", name="Finance")
    operations_user = SimpleNamespace(id="404", role="operations", name="Ops")
    finance_scoped = await service.get_list(limit=10, scope_user=finance_user)
    operations_scoped = await service.get_list(limit=10, scope_user=operations_user)

    assert finance_scoped["total"] == 2
    assert operations_scoped["total"] == 2


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
