import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.main import app
from backend.routers import customer_ai_copies as copies_router
from backend.routers import customer_materials as materials_router
from backend.routers import customer_menu_items as items_router
from backend.routers import customers as customers_router
from core.database import Base
from models.customer_access_grants import CustomerAccessGrant
from models.customer_ai_copies import Customer_ai_copies
from models.customer_materials import Customer_materials
from models.customer_menu_items import Customer_menu_items
from models.customers import Customers
from models.employees import Employees
from services.emp_auth import create_access_token
from services.role_permissions import load_role_permission_config
from routers import customer_materials as runtime_materials_router


def _headers(role: str, employee_id: int, name: str) -> dict[str, str]:
    token = create_access_token({
        "emp_id": employee_id,
        "email": f"content-{employee_id}@example.com",
        "role": role,
        "name": name,
    })
    return {"Authorization": f"Bearer {token}"}


def _query(customer_id: int) -> dict[str, str]:
    return {"query": json.dumps({"customer_id": customer_id})}


@pytest_asyncio.fixture
async def content_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    materials_root = tmp_path / "materials"
    visible_file = materials_root / "501" / "visible.txt"
    visible_file.parent.mkdir(parents=True)
    visible_file.write_text("private customer material", encoding="utf-8")
    monkeypatch.setattr(materials_router, "MATERIALS_ROOT", materials_root)
    monkeypatch.setattr(runtime_materials_router, "MATERIALS_ROOT", materials_root)

    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        session.add_all([
            Employees(id=1, user_id="1", name="Admin", role="admin", status="active", email="content-1@example.com"),
            Employees(id=21, user_id="21", name="Ops", role="ops", status="active", email="content-21@example.com"),
            Employees(id=31, user_id="31", name="Designer", role="design", status="active", email="content-31@example.com"),
            Employees(id=41, user_id="41", name="Finance", role="finance", status="active", email="content-41@example.com"),
            Customers(id=501, business_name="Visible Content", contact_name="Owner", phone="501"),
            Customers(id=502, business_name="Hidden Content", contact_name="Owner", phone="502"),
            CustomerAccessGrant(customer_id=501, employee_id=21, granted_by_name="Admin"),
            Customer_materials(id=601, user_id="1", customer_id=501, title="Visible File", material_type="document", source_type="upload", file_name="visible.txt", file_path="501/visible.txt"),
            Customer_materials(id=602, user_id="1", customer_id=502, title="Hidden File", material_type="document", source_type="external_link", file_url="https://example.com/hidden"),
            Customer_ai_copies(id=701, user_id="1", customer_id=501, platform="facebook", content_type="weekly_update", title="Visible Copy", content="visible"),
            Customer_ai_copies(id=702, user_id="1", customer_id=502, platform="facebook", content_type="weekly_update", title="Hidden Copy", content="hidden"),
            Customer_menu_items(id=801, user_id="1", customer_id=501, name="Visible Item", item_type="dish"),
            Customer_menu_items(id=802, user_id="1", customer_id=502, name="Hidden Item", item_type="dish"),
        ])
        await session.execute(text(
            "CREATE TABLE IF NOT EXISTS app_settings "
            "(config_key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TIMESTAMP)"
        ))
        permissions = {
            "admin": {
                "pages": ["/customers", "/service-board"],
                "buttons": ["task_create", "task_edit", "task_delete"],
                "dataScope": "all",
            },
            "ops": {
                "pages": ["/customers", "/service-board"],
                "buttons": ["task_create", "task_edit"],
                "dataScope": "all",
            },
            "finance": {
                "pages": ["/customers", "/service-board"],
                "buttons": [],
                "dataScope": "all",
            },
            "design": {
                "pages": ["/tasks"],
                "buttons": ["task_edit"],
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

        for dependency in (materials_router.get_db, copies_router.get_db, items_router.get_db):
            app.dependency_overrides[dependency] = override_db

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client, visible_file

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_content_reads_require_workspace_page_and_customer_scope(content_api):
    client, _ = content_api
    ops = _headers("ops", 21, "Ops")
    finance = _headers("finance", 41, "Finance")
    design = _headers("design", 31, "Designer")
    admin = _headers("admin", 1, "Admin")
    endpoints = (
        "/api/v1/entities/customer_materials",
        "/api/v1/entities/customer_ai_copies",
        "/api/v1/entities/customer_menu_items",
    )

    for endpoint in endpoints:
        visible = await client.get(endpoint, params=_query(501), headers=ops)
        hidden = await client.get(endpoint, params=_query(502), headers=ops)
        no_scope = await client.get(endpoint, headers=ops)
        finance_read = await client.get(endpoint, params=_query(501), headers=finance)
        design_read = await client.get(endpoint, params=_query(501), headers=design)
        admin_all = await client.get(endpoint, headers=admin)

        assert visible.status_code == 200
        assert visible.json()["total"] == 1
        assert hidden.status_code == 404
        assert no_scope.status_code == 400
        assert finance_read.status_code == 200
        assert design_read.status_code == 403
        assert admin_all.status_code == 200
        assert admin_all.json()["total"] == 2


@pytest.mark.asyncio
async def test_ops_can_create_and_edit_visible_content_but_not_cross_customer_or_delete(content_api):
    client, visible_file = content_api
    ops = _headers("ops", 21, "Ops")
    material = await client.post(
        "/api/v1/entities/customer_materials",
        json={
            "customer_id": 501,
            "title": "New Link",
            "material_type": "image",
            "source_type": "external_link",
            "file_url": "https://example.com/new",
        },
        headers=ops,
    )
    assert material.status_code == 201
    assert (await client.put(
        "/api/v1/entities/customer_materials/601",
        json={"title": "Visible Edited"},
        headers=ops,
    )).status_code == 200
    assert (await client.put(
        "/api/v1/entities/customer_materials/602",
        json={"title": "Cross customer"},
        headers=ops,
    )).status_code == 404
    assert (await client.post(
        "/api/v1/entities/customer_materials/601/duplicate",
        headers=ops,
    )).status_code == 201
    assert (await client.delete("/api/v1/entities/customer_materials/601", headers=ops)).status_code == 403
    assert visible_file.exists()

    copy = await client.post(
        "/api/v1/entities/customer_ai_copies",
        json={"customer_id": 501, "platform": "facebook", "content_type": "weekly_update", "content": "new copy"},
        headers=ops,
    )
    assert copy.status_code == 201
    assert (await client.put(
        "/api/v1/entities/customer_ai_copies/701",
        json={"content": "edited"},
        headers=ops,
    )).status_code == 200
    assert (await client.put(
        "/api/v1/entities/customer_ai_copies/702",
        json={"content": "cross customer"},
        headers=ops,
    )).status_code == 404
    assert (await client.delete("/api/v1/entities/customer_ai_copies/701", headers=ops)).status_code == 403

    menu_item = await client.post(
        "/api/v1/entities/customer_menu_items",
        json={"customer_id": 501, "name": "New Item", "item_type": "dish"},
        headers=ops,
    )
    assert menu_item.status_code == 201
    assert (await client.put(
        "/api/v1/entities/customer_menu_items/801",
        json={"name": "Visible Item Edited"},
        headers=ops,
    )).status_code == 200
    assert (await client.put(
        "/api/v1/entities/customer_menu_items/802",
        json={"name": "Cross customer"},
        headers=ops,
    )).status_code == 404
    assert (await client.delete("/api/v1/entities/customer_menu_items/801", headers=ops)).status_code == 403


@pytest.mark.asyncio
async def test_finance_and_design_cannot_write_or_trigger_ai(content_api):
    client, _ = content_api
    finance = _headers("finance", 41, "Finance")
    design = _headers("design", 31, "Designer")
    material_payload = {"customer_id": 501, "title": "Blocked", "material_type": "image", "file_url": "https://example.com/x"}
    copy_payload = {"customer_id": 501, "platform": "facebook", "content_type": "weekly_update", "content": "blocked"}
    item_payload = {"customer_id": 501, "name": "Blocked Item"}

    for headers in (finance, design):
        assert (await client.post("/api/v1/entities/customer_materials", json=material_payload, headers=headers)).status_code == 403
        assert (await client.post("/api/v1/entities/customer_ai_copies", json=copy_payload, headers=headers)).status_code == 403
        assert (await client.post("/api/v1/entities/customer_menu_items", json=item_payload, headers=headers)).status_code == 403
        assert (await client.post(
            "/api/v1/entities/customer_materials/ai-match",
            json={"customer_id": 501, "target_platforms": []},
            headers=headers,
        )).status_code == 403
        assert (await client.post(
            "/api/v1/entities/customer_ai_copies/generate",
            json={"customer_id": 501, "platform": "facebook", "content_type": "weekly_update", "variants": 1},
            headers=headers,
        )).status_code == 403


@pytest.mark.asyncio
async def test_admin_delete_removes_private_file_and_linked_records(content_api):
    client, visible_file = content_api
    admin = _headers("admin", 1, "Admin")

    assert visible_file.exists()
    assert (await client.delete("/api/v1/entities/customer_materials/601", headers=admin)).status_code == 204
    assert not visible_file.exists()
    assert (await client.delete("/api/v1/entities/customer_ai_copies/701", headers=admin)).status_code == 204
    assert (await client.delete("/api/v1/entities/customer_menu_items/801", headers=admin)).status_code == 204


@pytest.mark.asyncio
async def test_fresh_database_sales_defaults_keep_owned_and_manager_scoped_customer_reads():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        session.add_all([
            Employees(id=51, user_id="51", name="Sales Owner", role="sales", status="active", email="content-51@example.com", department="Sales West"),
            Employees(id=52, user_id="52", name="Sales Manager", role="sales_manager", status="active", email="content-52@example.com", department="Sales East"),
            Employees(id=53, user_id="53", name="East Sales", role="sales", status="probation", email="content-53@example.com", department="Sales East"),
            Employees(id=54, user_id="54", name="West Sales", role="sales", status="active", email="content-54@example.com", department="Sales West"),
            Employees(id=55, user_id="55", name="Inactive East", role="sales", status="inactive", email="content-55@example.com", department="Sales East"),
            Customers(id=901, business_name="Sales Owned", contact_name="Owner", phone="901", sales_employee_id=51, sales_person="Sales Owner"),
            Customers(id=902, business_name="Other Sales", contact_name="Owner", phone="902", sales_employee_id=99, sales_person="Other"),
            Customers(id=903, business_name="Manager Owned", contact_name="Owner", phone="903", sales_employee_id=52, sales_person="Sales Manager"),
            Customers(id=904, business_name="East Department", contact_name="Owner", phone="904", sales_employee_id=53, sales_person="East Sales"),
            Customers(id=905, business_name="West Department", contact_name="Owner", phone="905", sales_employee_id=54, sales_person="West Sales"),
            Customers(id=906, business_name="Inactive Department Member", contact_name="Owner", phone="906", sales_employee_id=55, sales_person="Inactive East"),
            CustomerAccessGrant(customer_id=901, employee_id=52, granted_by_name="Admin"),
            Customer_materials(id=911, user_id="1", customer_id=901, title="Sales Material", material_type="image", source_type="external_link", file_url="https://example.com/901"),
            Customer_materials(id=912, user_id="1", customer_id=902, title="Hidden Material", material_type="image", source_type="external_link", file_url="https://example.com/902"),
            Customer_materials(id=913, user_id="1", customer_id=903, title="Manager Material", material_type="image", source_type="external_link", file_url="https://example.com/903"),
            Customer_materials(id=914, user_id="1", customer_id=904, title="East Material", material_type="image", source_type="external_link", file_url="https://example.com/904"),
            Customer_materials(id=915, user_id="1", customer_id=905, title="West Material", material_type="image", source_type="external_link", file_url="https://example.com/905"),
            Customer_materials(id=916, user_id="1", customer_id=906, title="Inactive Material", material_type="image", source_type="external_link", file_url="https://example.com/906"),
        ])
        await session.commit()

        async def override_db():
            yield session

        for dependency in (materials_router.get_db, copies_router.get_db, items_router.get_db, customers_router.get_db):
            app.dependency_overrides[dependency] = override_db

        transport = ASGITransport(app=app)
        try:
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                sales = _headers("sales", 51, "Sales Owner")
                manager = _headers("sales_manager", 52, "Sales Manager")

                sales_customer = await client.get(
                    "/api/v1/entities/customers/901",
                    headers=sales,
                )
                sales_cannot_read_department_peer = await client.get(
                    "/api/v1/entities/customers/904",
                    headers=sales,
                )
                sales_material = await client.get(
                    "/api/v1/entities/customer_materials",
                    params=_query(901),
                    headers=sales,
                )
                sales_hidden = await client.get(
                    "/api/v1/entities/customer_materials",
                    params=_query(902),
                    headers=sales,
                )
                manager_granted = await client.get(
                    "/api/v1/entities/customer_materials",
                    params=_query(901),
                    headers=manager,
                )
                manager_owned = await client.get(
                    "/api/v1/entities/customer_materials",
                    params=_query(903),
                    headers=manager,
                )
                manager_hidden = await client.get(
                    "/api/v1/entities/customer_materials",
                    params=_query(902),
                    headers=manager,
                )
                manager_department_customer = await client.get(
                    "/api/v1/entities/customers/904",
                    headers=manager,
                )
                manager_department_material = await client.get(
                    "/api/v1/entities/customer_materials",
                    params=_query(904),
                    headers=manager,
                )
                manager_cross_department = await client.get(
                    "/api/v1/entities/customer_materials",
                    params=_query(905),
                    headers=manager,
                )
                manager_inactive_department = await client.get(
                    "/api/v1/entities/customer_materials",
                    params=_query(906),
                    headers=manager,
                )

            app_settings = (await session.execute(text(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'app_settings'"
            ))).first()

            assert sales_customer.status_code == 200
            assert sales_customer.json()["id"] == 901
            assert sales_cannot_read_department_peer.status_code == 404
            assert sales_material.status_code == 200
            assert [item["id"] for item in sales_material.json()["items"]] == [911]
            assert sales_hidden.status_code == 404
            assert manager_granted.status_code == 200
            assert manager_owned.status_code == 200
            assert manager_hidden.status_code == 404
            assert manager_department_customer.status_code == 200
            assert [item["id"] for item in manager_department_material.json()["items"]] == [914]
            assert manager_cross_department.status_code == 404
            assert manager_inactive_department.status_code == 404
            assert app_settings is None
        finally:
            app.dependency_overrides.clear()

    await engine.dispose()


@pytest.mark.asyncio
async def test_stored_sales_role_config_cannot_remove_fixed_customer_pages():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        await session.execute(text(
            "CREATE TABLE app_settings "
            "(config_key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TIMESTAMP)"
        ))
        await session.execute(
            text("INSERT INTO app_settings (config_key, value_json) VALUES ('role_permissions', :value)"),
            {"value": json.dumps({
                "sales": {"pages": [], "buttons": [], "dataScope": "self"},
                "sales_manager": {"pages": ["/sales-leads"], "buttons": [], "dataScope": "department"},
            })},
        )
        await session.commit()

        sales = await load_role_permission_config(session, SimpleNamespace(role="sales"))
        manager = await load_role_permission_config(session, SimpleNamespace(role="sales_manager"))

        assert {"/customers", "/sales-leads"}.issubset(set(sales["pages"]))
        assert {"/customers", "/merchant-pool", "/sales-leads"}.issubset(set(manager["pages"]))

    await engine.dispose()
