import json

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.main import app
from backend.routers import tasks as tasks_router
from core.database import Base
from models.employees import Employees
from models.tasks import Tasks
from services.emp_auth import create_access_token


def _headers(role: str, employee_id: int, name: str) -> dict[str, str]:
    token = create_access_token({
        "emp_id": employee_id,
        "email": f"employee-{employee_id}@example.com",
        "role": role,
        "name": name,
    })
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def task_api():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        session.add_all([
            Employees(id=1, user_id="admin-1", name="Admin", role="admin", status="active", email="employee-1@example.com"),
            Employees(id=10, user_id="manager-10", name="Manager A", role="ops", status="active", email="employee-10@example.com", department="Operations"),
            Employees(id=11, user_id="report-11", name="Report A", role="ops", status="active", email="employee-11@example.com", department="Operations", supervisor="Manager A"),
            Employees(id=12, user_id="outsider-12", name="Outsider", role="ops", status="active", email="employee-12@example.com", department="Other", supervisor="Manager B"),
            Employees(id=20, user_id="designer-20", name="Designer A", role="design", status="active", email="employee-20@example.com", department="Design"),
            Employees(id=30, user_id="finance-30", name="Finance", role="finance", status="active", email="employee-30@example.com"),
        ])
        session.add_all([
            Tasks(id=101, title="Manager task", assignee_id=10, assignee_name="Manager A", status="pending"),
            Tasks(id=102, title="Report task", assignee_id=11, assignee_name="Report A", status="pending"),
            Tasks(id=103, title="Outsider task", assignee_id=12, assignee_name="Outsider", status="pending"),
            Tasks(id=104, title="Designer task", assignee_id=20, assignee_name="Designer A", status="pending"),
            Tasks(id=105, title="Designer collaboration", assignee_id=12, assignee_name="Outsider", collaborator_names="Designer A, Report A", status="pending"),
            Tasks(id=106, title="Similar collaborator must stay hidden", assignee_id=12, assignee_name="Outsider", collaborator_names="Designer Anna", status="pending"),
        ])
        await session.execute(text(
            "CREATE TABLE app_settings (config_key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TIMESTAMP)"
        ))
        role_permissions = {
            "admin": {
                "pages": ["/tasks"],
                "buttons": ["task_create", "task_edit", "task_delete"],
                "dataScope": "all",
            },
            "ops": {
                "pages": ["/tasks"],
                "buttons": ["task_create", "task_edit"],
                "dataScope": "team",
            },
            "design": {
                "pages": ["/tasks"],
                "buttons": ["task_edit"],
                "dataScope": "self",
            },
            "finance": {
                "pages": [],
                "buttons": [],
                "dataScope": "all",
            },
        }
        await session.execute(
            text("INSERT INTO app_settings (config_key, value_json) VALUES ('role_permissions', :value)"),
            {"value": json.dumps(role_permissions)},
        )
        await session.commit()

        async def override_db():
            yield session

        app.dependency_overrides[tasks_router.get_db] = override_db
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_self_scope_applies_to_list_all_alias_and_direct_task_id(task_api: AsyncClient):
    headers = _headers("design", 20, "Designer A")

    regular = await task_api.get("/api/v1/entities/tasks?limit=100", headers=headers)
    all_alias = await task_api.get("/api/v1/entities/tasks/all?limit=100", headers=headers)
    hidden_direct = await task_api.get("/api/v1/entities/tasks/103", headers=headers)

    assert regular.status_code == 200
    assert {item["id"] for item in regular.json()["items"]} == {104, 105}
    assert {item["id"] for item in all_alias.json()["items"]} == {104, 105}
    assert hidden_direct.status_code == 403


@pytest.mark.asyncio
async def test_team_scope_includes_direct_reports_but_not_other_teams(task_api: AsyncClient):
    headers = _headers("ops", 10, "Manager A")

    response = await task_api.get("/api/v1/entities/tasks?limit=100", headers=headers)
    report_direct = await task_api.get("/api/v1/entities/tasks/102", headers=headers)
    outsider_direct = await task_api.get("/api/v1/entities/tasks/103", headers=headers)
    assignee_options = await task_api.get("/api/v1/entities/tasks/assignee-options", headers=headers)

    assert response.status_code == 200
    assert {item["id"] for item in response.json()["items"]} == {101, 102, 105}
    assert report_direct.status_code == 200
    assert outsider_direct.status_code == 403
    assert assignee_options.status_code == 200
    assert {item["id"] for item in assignee_options.json()["items"]} == {10, 11}
    assert all(set(item) == {"id", "name", "department", "supervisor"} for item in assignee_options.json()["items"])


@pytest.mark.asyncio
async def test_task_edit_and_delete_require_button_permission_and_scope(task_api: AsyncClient):
    designer_headers = _headers("design", 20, "Designer A")
    manager_headers = _headers("ops", 10, "Manager A")

    own_edit = await task_api.put(
        "/api/v1/entities/tasks/104",
        json={"title": "Designer task updated"},
        headers=designer_headers,
    )
    hidden_edit = await task_api.put(
        "/api/v1/entities/tasks/103",
        json={"title": "Must not change"},
        headers=designer_headers,
    )
    forbidden_delete = await task_api.delete("/api/v1/entities/tasks/104", headers=designer_headers)
    out_of_scope_delete = await task_api.delete("/api/v1/entities/tasks/103", headers=manager_headers)

    assert own_edit.status_code == 200
    assert own_edit.json()["title"] == "Designer task updated"
    assert hidden_edit.status_code == 403
    assert forbidden_delete.status_code == 403
    # Missing delete permission is checked before record scope, so direct IDs
    # cannot be used to probe or delete other teams' records.
    assert out_of_scope_delete.status_code == 403


@pytest.mark.asyncio
async def test_scoped_create_and_reassignment_cannot_grant_out_of_scope_access(task_api: AsyncClient):
    manager_headers = _headers("ops", 10, "Manager A")
    designer_headers = _headers("design", 20, "Designer A")

    no_create_permission = await task_api.post(
        "/api/v1/entities/tasks",
        json={"title": "Designer should not create", "assignee_id": 20, "assignee_name": "Designer A"},
        headers=designer_headers,
    )
    team_create = await task_api.post(
        "/api/v1/entities/tasks",
        json={"title": "Team task", "assignee_id": 11, "assignee_name": "Report A", "status": "pending"},
        headers=manager_headers,
    )
    outsider_create = await task_api.post(
        "/api/v1/entities/tasks",
        json={"title": "Other team task", "assignee_id": 12, "assignee_name": "Outsider"},
        headers=manager_headers,
    )
    outsider_collaborator = await task_api.put(
        "/api/v1/entities/tasks/102",
        json={"collaborator_names": "Outsider"},
        headers=manager_headers,
    )

    assert no_create_permission.status_code == 403
    assert team_create.status_code == 201
    assert outsider_create.status_code == 403
    assert outsider_collaborator.status_code == 403


@pytest.mark.asyncio
async def test_batch_preflight_prevents_partial_cross_scope_update(task_api: AsyncClient):
    manager_headers = _headers("ops", 10, "Manager A")
    admin_headers = _headers("admin", 1, "Admin")

    response = await task_api.put(
        "/api/v1/entities/tasks/batch",
        json={"items": [
            {"id": 102, "updates": {"title": "Should roll back before write"}},
            {"id": 103, "updates": {"title": "Forbidden outsider write"}},
        ]},
        headers=manager_headers,
    )
    unchanged = await task_api.get("/api/v1/entities/tasks/102", headers=admin_headers)

    assert response.status_code == 403
    assert unchanged.status_code == 200
    assert unchanged.json()["title"] == "Report task"


@pytest.mark.asyncio
async def test_all_scope_can_manage_any_manual_task(task_api: AsyncClient):
    headers = _headers("admin", 1, "Admin")

    task_list = await task_api.get("/api/v1/entities/tasks?limit=100", headers=headers)
    outsider_edit = await task_api.put(
        "/api/v1/entities/tasks/103",
        json={"title": "Admin updated outsider task"},
        headers=headers,
    )
    delete_response = await task_api.delete("/api/v1/entities/tasks/106", headers=headers)

    assert task_list.status_code == 200
    assert {item["id"] for item in task_list.json()["items"]} == {101, 102, 103, 104, 105, 106}
    assert outsider_edit.status_code == 200
    assert delete_response.status_code == 200


@pytest.mark.asyncio
async def test_page_permission_is_enforced_by_task_api(task_api: AsyncClient):
    response = await task_api.get(
        "/api/v1/entities/tasks?limit=100",
        headers=_headers("finance", 30, "Finance"),
    )

    assert response.status_code == 403
