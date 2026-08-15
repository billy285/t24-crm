import json
import logging

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.main import app
from backend.routers import media_accounts as media_accounts_router
from core.database import Base
from models.customer_access_grants import CustomerAccessGrant
from models.customers import Customers
from models.employees import Employees
from models.media_accounts import Media_accounts
from services.emp_auth import create_access_token
from services.media_accounts import encrypt_media_account_password


def _headers(role: str, employee_id: int = 61) -> dict[str, str]:
    token = create_access_token({
        "emp_id": employee_id,
        "email": f"media-{employee_id}@example.com",
        "role": role,
        "name": f"Media {role}",
    })
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def media_account_api():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        session.add_all([
            Employees(id=61, user_id="61", name="Ops Creator", role="ops", status="active", email="media-61@example.com"),
            Employees(id=62, user_id="62", name="Ops Handoff", role="ops", status="active", email="media-62@example.com"),
            Employees(id=63, user_id="63", name="Ops Hidden", role="ops", status="active", email="media-63@example.com"),
            Employees(id=64, user_id="64", name="Admin", role="admin", status="active", email="media-64@example.com"),
            Employees(id=65, user_id="65", name="Designer", role="design", status="active", email="media-65@example.com"),
            Customers(id=901, business_name="Shared Customer", contact_name="Owner", phone="555-0901"),
            Customers(id=902, business_name="Hidden Customer", contact_name="Owner", phone="555-0902"),
            CustomerAccessGrant(customer_id=901, employee_id=61, granted_by_name="Admin"),
            CustomerAccessGrant(customer_id=901, employee_id=62, granted_by_name="Admin"),
        ])
        await session.execute(text(
            "CREATE TABLE IF NOT EXISTS app_settings "
            "(config_key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TIMESTAMP)"
        ))
        role_permissions = {
            "admin": {
                "pages": ["/customers"],
                "buttons": ["media_account_create", "media_account_edit", "media_account_delete"],
                "dataScope": "all",
                "sensitiveFields": {"viewPassword": True},
            },
            "ops": {
                "pages": ["/customers"],
                "buttons": ["media_account_create", "media_account_edit"],
                "dataScope": "all",
                "sensitiveFields": {"viewPassword": False},
            },
            "design": {
                "pages": ["/tasks"],
                "buttons": ["task_edit"],
                "dataScope": "self",
            },
        }
        await session.execute(
            text("INSERT INTO app_settings (config_key, value_json) VALUES ('role_permissions', :value)"),
            {"value": json.dumps(role_permissions)},
        )
        await session.commit()

        async def override_db():
            yield session

        app.dependency_overrides[media_accounts_router.get_db] = override_db
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_media_account_access_follows_customer_grants_not_creator_ownership(media_account_api: AsyncClient):
    creator_headers = _headers("ops", 61)
    handoff_headers = _headers("ops", 62)
    admin_headers = _headers("admin", 64)

    created = await media_account_api.post(
        "/api/v1/entities/media_accounts",
        json={
            "customer_id": 901,
            "platform_name": "Facebook",
            "account_name": "race-safe-store",
            "login_password": "shared-secret",
        },
        headers=creator_headers,
    )
    assert created.status_code == 201
    account_id = created.json()["id"]

    read = await media_account_api.get(
        f"/api/v1/entities/media_accounts/{account_id}",
        headers=handoff_headers,
    )
    updated = await media_account_api.put(
        f"/api/v1/entities/media_accounts/{account_id}",
        json={"notes": "accepted by the next operations owner"},
        headers=handoff_headers,
    )
    forbidden_password = await media_account_api.get(
        f"/api/v1/entities/media_accounts/{account_id}/password",
        headers=handoff_headers,
    )
    admin_password = await media_account_api.get(
        f"/api/v1/entities/media_accounts/{account_id}/password",
        headers=admin_headers,
    )
    missing_password = await media_account_api.get(
        "/api/v1/entities/media_accounts/999999/password",
        headers=admin_headers,
    )
    password_audits = await media_account_api.get(
        "/api/v1/entities/operation_logs/all",
        params={"query": json.dumps({"action_type": "view_password", "customer_id": 901})},
        headers=admin_headers,
    )
    forbidden_delete = await media_account_api.delete(
        f"/api/v1/entities/media_accounts/{account_id}",
        headers=handoff_headers,
    )
    forbidden_batch_delete = await media_account_api.request(
        "DELETE",
        "/api/v1/entities/media_accounts/batch",
        json={"ids": [account_id]},
        headers=handoff_headers,
    )
    admin_delete = await media_account_api.delete(
        f"/api/v1/entities/media_accounts/{account_id}",
        headers=admin_headers,
    )

    assert read.status_code == 200
    assert read.json()["account_name"] == "race-safe-store"
    assert read.json()["user_id"] == "61"
    assert updated.status_code == 200
    assert updated.json()["notes"] == "accepted by the next operations owner"
    assert forbidden_password.status_code == 403
    assert admin_password.status_code == 200
    assert admin_password.json()["login_password"] == "shared-secret"
    assert missing_password.status_code == 404
    assert password_audits.status_code == 200
    assert password_audits.json()["total"] == 1
    password_audit = password_audits.json()["items"][0]
    assert password_audit["user_id"] == "64"
    assert password_audit["operator_name"] == "Media admin"
    assert password_audit["ip_address"] == "127.0.0.1"
    assert password_audit["customer_id"] == 901
    assert password_audit["action_type"] == "view_password"
    assert f"account_id={account_id}" in password_audit["action_detail"]
    assert forbidden_delete.status_code == 403
    assert forbidden_batch_delete.status_code == 403
    assert admin_delete.status_code == 200


@pytest.mark.asyncio
async def test_media_account_create_and_update_logs_never_include_plaintext_password(
    media_account_api: AsyncClient,
    caplog: pytest.LogCaptureFixture,
):
    caplog.set_level(logging.DEBUG, logger=media_accounts_router.logger.name)
    create_secret = "create-secret-must-not-enter-logs"
    update_secret = "update-secret-must-not-enter-logs"
    headers = _headers("admin", 64)

    created = await media_account_api.post(
        "/api/v1/entities/media_accounts",
        json={
            "customer_id": 901,
            "platform_name": "Google",
            "account_name": "safe-logging-account",
            "login_password": create_secret,
        },
        headers=headers,
    )
    assert created.status_code == 201
    updated = await media_account_api.put(
        f"/api/v1/entities/media_accounts/{created.json()['id']}",
        json={"login_password": update_secret, "notes": "safe metadata"},
        headers=headers,
    )

    assert updated.status_code == 200
    assert create_secret not in caplog.text
    assert update_secret not in caplog.text


@pytest.mark.asyncio
async def test_password_plaintext_is_not_returned_when_trusted_audit_write_fails(
    media_account_api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    headers = _headers("admin", 64)
    created = await media_account_api.post(
        "/api/v1/entities/media_accounts",
        json={
            "customer_id": 901,
            "platform_name": "Yelp",
            "account_name": "audit-required-account",
            "login_password": "must-not-return-without-audit",
        },
        headers=headers,
    )
    assert created.status_code == 201

    async def fail_audit(*_args, **_kwargs):
        raise RuntimeError("simulated audit storage failure")

    monkeypatch.setattr(media_accounts_router.Operation_logsService, "create", fail_audit)
    revealed = await media_account_api.get(
        f"/api/v1/entities/media_accounts/{created.json()['id']}/password",
        headers=headers,
    )

    assert revealed.status_code == 500
    assert "must-not-return-without-audit" not in revealed.text


@pytest.mark.asyncio
async def test_explicit_sensitive_field_false_revokes_password_access_despite_legacy_allowlist(
    media_account_api: AsyncClient,
):
    headers = _headers("admin", 64)
    created = await media_account_api.post(
        "/api/v1/entities/media_accounts",
        json={
            "customer_id": 901,
            "platform_name": "Facebook",
            "account_name": "revoked-password-account",
            "login_password": "revoked-secret",
        },
        headers=headers,
    )
    assert created.status_code == 201

    permissions_updated = await media_account_api.put(
        "/api/v1/app-config/role_permissions",
        json={
            "value": {
                "admin": {
                    "sensitiveFields": {"viewPassword": False},
                },
            },
        },
        headers=headers,
    )
    legacy_allowlist_updated = await media_account_api.put(
        "/api/v1/app-config/security_config",
        json={"value": {"passwordViewRoles": ["admin", "super_admin"]}},
        headers=headers,
    )
    revealed = await media_account_api.get(
        f"/api/v1/entities/media_accounts/{created.json()['id']}/password",
        headers=headers,
    )
    audits = await media_account_api.get(
        "/api/v1/entities/operation_logs/all",
        params={"query": json.dumps({"action_type": "view_password", "customer_id": 901})},
        headers=headers,
    )

    assert permissions_updated.status_code == 200
    assert legacy_allowlist_updated.status_code == 200
    assert revealed.status_code == 403
    assert audits.status_code == 200
    assert audits.json()["total"] == 0


@pytest.mark.asyncio
async def test_role_without_media_permissions_cannot_bypass_ui_with_direct_api(media_account_api: AsyncClient):
    design_headers = _headers("design", 65)

    create = await media_account_api.post(
        "/api/v1/entities/media_accounts",
        json={
            "customer_id": 902,
            "platform_name": "Instagram",
            "account_name": "must-not-create",
        },
        headers=design_headers,
    )
    update = await media_account_api.put(
        "/api/v1/entities/media_accounts/999",
        json={"notes": "must-not-update"},
        headers=design_headers,
    )
    delete = await media_account_api.delete(
        "/api/v1/entities/media_accounts/999",
        headers=design_headers,
    )
    read = await media_account_api.get(
        "/api/v1/entities/media_accounts/999",
        headers=design_headers,
    )

    assert create.status_code == 403
    assert read.status_code == 403
    assert update.status_code == 403
    assert delete.status_code == 403


@pytest.mark.asyncio
async def test_ops_without_customer_grant_cannot_probe_or_modify_media_account(media_account_api: AsyncClient):
    creator_headers = _headers("ops", 61)
    hidden_headers = _headers("ops", 63)

    created = await media_account_api.post(
        "/api/v1/entities/media_accounts",
        json={
            "customer_id": 901,
            "platform_name": "Instagram",
            "account_name": "grant-protected",
        },
        headers=creator_headers,
    )
    account_id = created.json()["id"]

    hidden_read = await media_account_api.get(
        f"/api/v1/entities/media_accounts/{account_id}",
        headers=hidden_headers,
    )
    hidden_update = await media_account_api.put(
        f"/api/v1/entities/media_accounts/{account_id}",
        json={"notes": "must stay unchanged"},
        headers=hidden_headers,
    )
    hidden_create = await media_account_api.post(
        "/api/v1/entities/media_accounts",
        json={
            "customer_id": 901,
            "platform_name": "TikTok",
            "account_name": "must-not-create",
        },
        headers=hidden_headers,
    )

    # Customer-scoped lookups intentionally use 404 to avoid revealing that a
    # hidden customer's media account exists.
    assert hidden_read.status_code == 404
    assert hidden_update.status_code == 404
    assert hidden_create.status_code == 404


@pytest.mark.asyncio
async def test_fresh_database_permission_reads_fall_back_without_creating_app_settings():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        session.add_all([
            Employees(
                id=64,
                user_id="64",
                name="Fresh Admin",
                role="admin",
                status="active",
                email="media-64@example.com",
            ),
            Customers(
                id=903,
                business_name="Fresh Database Customer",
                contact_name="Owner",
                phone="555-0903",
            ),
            Media_accounts(
                id=904,
                user_id="64",
                customer_id=903,
                platform_name="Google",
                account_name="fresh-database-account",
                login_password=encrypt_media_account_password("fresh-secret"),
            ),
        ])
        await session.commit()

        async def override_db():
            yield session

        app.dependency_overrides[media_accounts_router.get_db] = override_db
        transport = ASGITransport(app=app)
        try:
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                listed = await client.get(
                    '/api/v1/entities/media_accounts?query={"customer_id":903}',
                    headers=_headers("admin", 64),
                )
                revealed = await client.get(
                    "/api/v1/entities/media_accounts/904/password",
                    headers=_headers("admin", 64),
                )

            table = (await session.execute(text(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name = 'app_settings'"
            ))).first()

            assert listed.status_code == 200
            assert [item["id"] for item in listed.json()["items"]] == [904]
            assert revealed.status_code == 200
            assert revealed.json()["login_password"] == "fresh-secret"
            assert table is None
        finally:
            app.dependency_overrides.clear()

    await engine.dispose()
