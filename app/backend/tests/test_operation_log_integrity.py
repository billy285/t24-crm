from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.main import app
from backend.routers import customers as customers_router
from backend.routers import operation_logs as operation_logs_router
from core.database import Base
from models.customer_access_grants import CustomerAccessGrant
from models.customers import Customers
from models.operation_logs import Operation_logs
from services.emp_auth import create_access_token
from services.operation_logs import MAX_OPERATION_BATCH_SIZE, MAX_OPERATION_DETAIL_LENGTH


def _headers(role: str, employee_id: int, name: str) -> dict[str, str]:
    token = create_access_token({
        "emp_id": employee_id,
        "email": f"audit-{employee_id}@example.com",
        "role": role,
        "name": name,
    })
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def audit_api():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        session.add_all([
            Customers(id=701, business_name="Visible", contact_name="Owner", phone="701"),
            Customers(id=702, business_name="Hidden", contact_name="Owner", phone="702"),
            Customers(id=703, business_name="Delete Me", contact_name="Owner", phone="703"),
            CustomerAccessGrant(customer_id=701, employee_id=11, granted_by_name="Admin"),
        ])
        await session.commit()

        async def override_db():
            yield session

        app.dependency_overrides[operation_logs_router.get_db] = override_db
        app.dependency_overrides[customers_router.get_db] = override_db
        transport = ASGITransport(app=app, client=("198.51.100.27", 4321))
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client, session

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_single_create_overwrites_forged_attribution_with_server_values(audit_api):
    client, session = audit_api
    response = await client.post(
        "/api/v1/entities/operation_logs",
        headers={
            **_headers("ops", 11, "Ops One"),
            "x-forwarded-for": "203.0.113.250",
        },
        json={
            "customer_id": 701,
            "action_type": "user_note",
            "action_detail": "Manual context about the visible customer",
            "user_id": "forged-user",
            "operator_name": "Forged Boss",
            "ip_address": "203.0.113.99",
            "created_at": "2000-01-01T00:00:00Z",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["user_id"] == "11"
    assert body["action_type"] == "user_note"
    assert body["operator_name"] == "Ops One"
    assert body["ip_address"] == "198.51.100.27"
    created_at = datetime.fromisoformat(body["created_at"].replace("Z", "+00:00"))
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    assert abs((datetime.now(timezone.utc) - created_at).total_seconds()) < 10

    stored = (await session.execute(
        select(Operation_logs).where(Operation_logs.id == body["id"])
    )).scalar_one()
    assert stored.user_id == "11"
    assert stored.operator_name == "Ops One"
    assert stored.ip_address == "198.51.100.27"


@pytest.mark.asyncio
async def test_customer_reference_must_exist_and_be_in_the_actor_scope(audit_api):
    client, session = audit_api
    staff = _headers("ops", 11, "Ops One")

    hidden = await client.post(
        "/api/v1/entities/operation_logs",
        headers=staff,
        json={"customer_id": 702, "action_type": "user_note", "action_detail": "forged scope"},
    )
    missing = await client.post(
        "/api/v1/entities/operation_logs",
        headers=staff,
        json={"customer_id": 99999, "action_type": "user_note", "action_detail": "missing"},
    )

    assert hidden.status_code == 404
    assert missing.status_code == 404
    assert (await session.execute(select(Operation_logs))).scalars().all() == []


@pytest.mark.asyncio
async def test_action_type_and_detail_length_are_bounded(audit_api):
    client, session = audit_api
    headers = _headers("ops", 11, "Ops One")

    forged_actions = [
        "edit_customer",
        "create_payment",
        "change_subscription_package",
        "close_finance_month",
        "edit_company_expense",
        "export_data",
        "edit_employee",
        "edit_permissions",
        "complete_service_task",
        "view_password",
        "other",
        "pretend_to_be_admin",
    ]
    forged_responses = [
        await client.post(
            "/api/v1/entities/operation_logs",
            headers=headers,
            json={"customer_id": 701, "action_type": action, "action_detail": "forged critical event"},
        )
        for action in forged_actions
    ]
    oversized_detail = await client.post(
        "/api/v1/entities/operation_logs",
        headers=headers,
        json={"action_type": "user_note", "action_detail": "x" * (MAX_OPERATION_DETAIL_LENGTH + 1)},
    )

    assert [response.status_code for response in forged_responses] == [422] * len(forged_actions)
    assert oversized_detail.status_code == 422
    assert (await session.execute(select(Operation_logs))).scalars().all() == []


@pytest.mark.asyncio
async def test_batch_is_admin_only_bounded_and_uses_server_attribution(audit_api):
    client, _ = audit_api
    item = {
        "customer_id": 701,
        "action_type": "user_note",
        "action_detail": "bounded batch audit",
        "user_id": "forged-user",
        "operator_name": "Forged Boss",
        "ip_address": "203.0.113.99",
        "created_at": "2000-01-01T00:00:00Z",
    }

    forbidden = await client.post(
        "/api/v1/entities/operation_logs/batch",
        headers=_headers("ops", 11, "Ops One"),
        json={"items": [item]},
    )
    created = await client.post(
        "/api/v1/entities/operation_logs/batch",
        headers=_headers("admin", 1, "Trusted Admin"),
        json={"items": [item]},
    )
    oversized = await client.post(
        "/api/v1/entities/operation_logs/batch",
        headers=_headers("admin", 1, "Trusted Admin"),
        json={"items": [item] * (MAX_OPERATION_BATCH_SIZE + 1)},
    )

    assert forbidden.status_code == 403
    assert created.status_code == 201
    assert len(created.json()) == 1
    assert created.json()[0]["user_id"] == "1"
    assert created.json()[0]["operator_name"] == "Trusted Admin"
    assert created.json()[0]["ip_address"] == "198.51.100.27"
    assert not created.json()[0]["created_at"].startswith("2000-")
    assert oversized.status_code == 422


@pytest.mark.asyncio
async def test_operation_logs_are_append_only_and_all_update_delete_methods_are_unavailable(audit_api):
    client, session = audit_api
    admin = _headers("admin", 1, "Trusted Admin")
    created = await client.post(
        "/api/v1/entities/operation_logs",
        headers=admin,
        json={"customer_id": 701, "action_type": "user_note", "action_detail": "immutable note"},
    )
    assert created.status_code == 201
    log_id = created.json()["id"]

    attempts = [
        await client.put(
            f"/api/v1/entities/operation_logs/{log_id}",
            headers=admin,
            json={"action_detail": "tampered"},
        ),
        await client.put(
            "/api/v1/entities/operation_logs/batch",
            headers=admin,
            json={"items": [{"id": log_id, "updates": {"action_detail": "tampered"}}]},
        ),
        await client.delete(f"/api/v1/entities/operation_logs/{log_id}", headers=admin),
        await client.request(
            "DELETE",
            "/api/v1/entities/operation_logs/batch",
            headers=admin,
            json={"ids": [log_id]},
        ),
    ]

    assert [response.status_code for response in attempts] == [405, 405, 405, 405]
    rows = (await session.execute(select(Operation_logs))).scalars().all()
    assert len(rows) == 1
    assert rows[0].id == log_id
    assert rows[0].action_type == "user_note"
    assert rows[0].action_detail == "immutable note"


@pytest.mark.asyncio
async def test_customer_delete_writes_durable_server_audit_in_the_same_transaction(audit_api):
    client, session = audit_api
    response = await client.delete(
        "/api/v1/entities/customers/703",
        headers=_headers("admin", 1, "Trusted Admin"),
    )

    assert response.status_code == 200
    assert await session.get(Customers, 703) is None
    audit_rows = (await session.execute(
        select(Operation_logs).where(
            Operation_logs.customer_id == 703,
            Operation_logs.action_type == "delete_customer",
        )
    )).scalars().all()
    assert len(audit_rows) == 1
    assert audit_rows[0].user_id == "1"
    assert audit_rows[0].operator_name == "Trusted Admin"
    assert audit_rows[0].ip_address == "198.51.100.27"
    assert audit_rows[0].action_detail == "删除客户: Delete Me"
