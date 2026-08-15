import json

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.main import app
from backend.routers import service_progresses as service_progresses_router
from backend.routers import service_tasks as service_tasks_router
from core.database import Base
from models.customer_access_grants import CustomerAccessGrant
from models.customers import Customers
from models.employees import Employees
from models.service_progresses import Service_progresses
from models.service_tasks import Service_tasks
from services.emp_auth import create_access_token


def _headers(role: str, employee_id: int) -> dict[str, str]:
    token = create_access_token({
        "emp_id": employee_id,
        "email": f"service-{employee_id}@example.com",
        "role": role,
        "name": f"Service {role}",
    })
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def service_board_api():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        session.add_all([
            Employees(id=71, user_id="71", name="Ops", role="ops", status="active", email="service-71@example.com"),
            Employees(id=72, user_id="72", name="Sales", role="sales", status="active", email="service-72@example.com"),
            Employees(id=73, user_id="73", name="Admin", role="admin", status="active", email="service-73@example.com"),
            Customers(id=9901, business_name="Scoped Service Customer", contact_name="Owner", phone="555-9901"),
            Customers(id=9902, business_name="Other Service Customer", contact_name="Other", phone="555-9902"),
            CustomerAccessGrant(customer_id=9901, employee_id=71, granted_by_name="Admin"),
            CustomerAccessGrant(customer_id=9902, employee_id=71, granted_by_name="Admin"),
            CustomerAccessGrant(customer_id=9901, employee_id=72, granted_by_name="Admin"),
            Service_progresses(
                id=9911,
                customer_id=9901,
                customer_name="Scoped Service Customer",
                service_type="social_media",
                service_stage="deal_handover",
                progress_percent=10,
                user_id="73",
            ),
            Service_progresses(
                id=9912,
                customer_id=9902,
                customer_name="Other Service Customer",
                service_type="social_media",
                service_stage="deal_handover",
                progress_percent=10,
                user_id="73",
            ),
            Service_tasks(
                id=9921,
                service_progress_id=9911,
                customer_id=9901,
                customer_name="Scoped Service Customer",
                task_name="Create service group",
                task_type="setup_group",
                status="pending",
                priority="medium",
                user_id="73",
            ),
            Service_tasks(
                id=9922,
                service_progress_id=9911,
                customer_id=9901,
                customer_name="Scoped Service Customer",
                task_name="Collect assets",
                task_type="collect_images",
                status="pending",
                priority="medium",
                user_id="73",
            ),
        ])
        await session.execute(text(
            "CREATE TABLE IF NOT EXISTS app_settings "
            "(config_key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TIMESTAMP)"
        ))
        permissions = {
            "admin": {
                "pages": ["/service-board"],
                "buttons": ["task_create", "task_edit", "task_delete"],
                "dataScope": "all",
            },
            "ops": {
                "pages": ["/service-board"],
                "buttons": ["task_create", "task_edit"],
                "dataScope": "all",
            },
            # Even when an administrator explicitly exposes the page, sales
            # still cannot mutate it without the relevant task button.
            "sales": {
                "pages": ["/customers"],
                "buttons": [],
                "dataScope": "self",
            },
        }
        await session.execute(
            text("INSERT INTO app_settings (config_key, value_json) VALUES ('role_permissions', :value)"),
            {"value": json.dumps(permissions)},
        )
        await session.commit()

        async def override_db():
            yield session

        app.dependency_overrides[service_progresses_router.get_db] = override_db
        app.dependency_overrides[service_tasks_router.get_db] = override_db
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_ops_can_edit_and_complete_but_cannot_delete_service_board_records(service_board_api: AsyncClient):
    headers = _headers("ops", 71)

    progress_edit = await service_board_api.put(
        "/api/v1/entities/service_progresses/9911",
        json={"progress_percent": 55, "last_work_summary": "Ops updated progress"},
        headers=headers,
    )
    task_edit = await service_board_api.put(
        "/api/v1/entities/service_tasks/9921",
        json={"status": "in_progress"},
        headers=headers,
    )
    task_complete = await service_board_api.post(
        "/api/v1/entities/service_tasks/9921/complete",
        json={"completion_note": "Finished by operations"},
        headers=headers,
    )
    task_delete = await service_board_api.delete(
        "/api/v1/entities/service_tasks/9921",
        headers=headers,
    )
    progress_delete = await service_board_api.delete(
        "/api/v1/entities/service_progresses/9911",
        headers=headers,
    )

    assert progress_edit.status_code == 200
    assert progress_edit.json()["progress_percent"] == 55
    assert task_edit.status_code == 200
    assert task_complete.status_code == 200
    assert task_complete.json()["status"] == "completed"
    assert task_delete.status_code == 403
    assert progress_delete.status_code == 403


@pytest.mark.asyncio
async def test_sales_direct_service_board_deletes_are_forbidden(service_board_api: AsyncClient):
    headers = _headers("sales", 72)

    task_read = await service_board_api.get(
        "/api/v1/entities/service_tasks/9921",
        headers=headers,
    )
    progress_read = await service_board_api.get(
        "/api/v1/entities/service_progresses/9911",
        headers=headers,
    )
    task_edit = await service_board_api.put(
        "/api/v1/entities/service_tasks/9921",
        json={"notes": "must not update"},
        headers=headers,
    )

    task_delete = await service_board_api.delete(
        "/api/v1/entities/service_tasks/9921",
        headers=headers,
    )
    progress_delete = await service_board_api.delete(
        "/api/v1/entities/service_progresses/9911",
        headers=headers,
    )

    assert task_read.status_code == 200
    assert progress_read.status_code == 200
    assert task_edit.status_code == 403
    assert task_delete.status_code == 403
    assert progress_delete.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_delete_service_task_and_progress(service_board_api: AsyncClient):
    headers = _headers("admin", 73)

    first_task_delete = await service_board_api.delete(
        "/api/v1/entities/service_tasks/9921",
        headers=headers,
    )
    second_task_delete = await service_board_api.delete(
        "/api/v1/entities/service_tasks/9922",
        headers=headers,
    )
    progress_delete = await service_board_api.delete(
        "/api/v1/entities/service_progresses/9911",
        headers=headers,
    )

    assert first_task_delete.status_code == 200
    assert second_task_delete.status_code == 200
    assert progress_delete.status_code == 200


@pytest.mark.asyncio
async def test_generic_task_writes_cannot_forge_completion_or_cross_customer_links(
    service_board_api: AsyncClient,
):
    headers = _headers("ops", 71)

    completed_create = await service_board_api.post(
        "/api/v1/entities/service_tasks",
        json={
            "service_progress_id": 9911,
            "customer_id": 9901,
            "customer_name": "Spoofed customer",
            "task_name": "Forged complete task",
            "status": "completed",
            "completed_by": "Boss",
        },
        headers=headers,
    )
    cross_customer_create = await service_board_api.post(
        "/api/v1/entities/service_tasks",
        json={
            "service_progress_id": 9912,
            "customer_id": 9901,
            "task_name": "Cross customer task",
            "status": "pending",
        },
        headers=headers,
    )
    safe_create = await service_board_api.post(
        "/api/v1/entities/service_tasks",
        json={
            "service_progress_id": 9911,
            "customer_id": 9901,
            "customer_name": "Spoofed customer",
            "task_name": "Safe task",
            "status": "pending",
            "completed_at": "2020-01-01T00:00:00",
            "completed_by": "Boss",
            "selected_copy_title": "Forged copy",
            "completion_quality": "perfect",
            "created_at": "2020-01-01T00:00:00",
            "user_id": "999",
        },
        headers=headers,
    )
    forged_update = await service_board_api.put(
        "/api/v1/entities/service_tasks/9921",
        json={
            "status": "completed",
            "completed_at": "2020-01-01T00:00:00",
            "completed_by": "Boss",
            "selected_material_title": "Forged material",
        },
        headers=headers,
    )
    cross_customer_update = await service_board_api.put(
        "/api/v1/entities/service_tasks/9921",
        json={"service_progress_id": 9912},
        headers=headers,
    )
    task_after_rejections = await service_board_api.get(
        "/api/v1/entities/service_tasks/9921",
        headers=headers,
    )

    assert completed_create.status_code == 400
    assert cross_customer_create.status_code == 400
    assert safe_create.status_code == 201
    safe_payload = safe_create.json()
    assert safe_payload["customer_name"] == "Scoped Service Customer"
    assert safe_payload["completed_at"] is None
    assert safe_payload["completed_by"] is None
    assert safe_payload["selected_copy_title"] is None
    assert safe_payload["completion_quality"] is None
    assert safe_payload["created_at"] != "2020-01-01T00:00:00"
    assert safe_payload["user_id"] == "71"
    assert forged_update.status_code == 400
    assert cross_customer_update.status_code == 400
    assert task_after_rejections.status_code == 200
    assert task_after_rejections.json()["status"] == "pending"
    assert task_after_rejections.json()["completed_by"] is None


@pytest.mark.asyncio
async def test_batch_update_preflights_every_task_before_mutating_any_record(
    service_board_api: AsyncClient,
):
    headers = _headers("ops", 71)

    response = await service_board_api.put(
        "/api/v1/entities/service_tasks/batch",
        json={
            "items": [
                {"id": 9921, "updates": {"notes": "must not be persisted"}},
                {"id": 9922, "updates": {"service_progress_id": 9912}},
            ]
        },
        headers=headers,
    )
    first_task = await service_board_api.get(
        "/api/v1/entities/service_tasks/9921",
        headers=headers,
    )

    assert response.status_code == 400
    assert first_task.status_code == 200
    assert first_task.json()["notes"] is None


@pytest.mark.asyncio
async def test_generic_update_can_detach_progress_without_changing_customer(
    service_board_api: AsyncClient,
):
    headers = _headers("ops", 71)

    response = await service_board_api.put(
        "/api/v1/entities/service_tasks/9921",
        json={"service_progress_id": None, "notes": "Standalone follow-up"},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["service_progress_id"] is None
    assert response.json()["customer_id"] == 9901
    assert response.json()["customer_name"] == "Scoped Service Customer"


@pytest.mark.asyncio
async def test_linked_progress_cannot_move_customer_or_be_deleted(
    service_board_api: AsyncClient,
):
    headers = _headers("admin", 73)

    move_response = await service_board_api.put(
        "/api/v1/entities/service_progresses/9911",
        json={
            "customer_id": 9902,
            "customer_name": "Spoofed",
            "user_id": "999",
            "created_at": "2020-01-01T00:00:00",
        },
        headers=headers,
    )
    delete_response = await service_board_api.delete(
        "/api/v1/entities/service_progresses/9911",
        headers=headers,
    )
    progress_after_rejections = await service_board_api.get(
        "/api/v1/entities/service_progresses/9911",
        headers=headers,
    )

    assert move_response.status_code == 409
    assert delete_response.status_code == 409
    assert progress_after_rejections.status_code == 200
    assert progress_after_rejections.json()["customer_id"] == 9901
    assert progress_after_rejections.json()["customer_name"] == "Scoped Service Customer"
    assert progress_after_rejections.json()["user_id"] == "73"


@pytest.mark.asyncio
async def test_progress_create_uses_server_customer_and_audit_fields(
    service_board_api: AsyncClient,
):
    headers = _headers("ops", 71)

    response = await service_board_api.post(
        "/api/v1/entities/service_progresses",
        json={
            "customer_id": 9902,
            "customer_name": "Spoofed",
            "service_type": "social_media",
            "service_stage": "deal_handover",
            "progress_percent": 10,
            "last_update_person": "Boss",
            "last_update_time": "2020-01-01T00:00:00",
            "created_at": "2020-01-01T00:00:00",
        },
        headers=headers,
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["customer_name"] == "Other Service Customer"
    assert payload["user_id"] == "71"
    assert payload["last_update_person"] == "Service ops"
    assert payload["last_update_time"] != "2020-01-01T00:00:00"
    assert payload["created_at"] != "2020-01-01T00:00:00"
