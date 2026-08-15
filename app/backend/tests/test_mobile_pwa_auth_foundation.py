from datetime import date, datetime, timedelta, timezone

import pytest
from cryptography.fernet import InvalidToken
from fastapi import HTTPException, Request
from httpx import ASGITransport, AsyncClient
from jose import jwt
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend import main as main_module
from core.database import get_db
from core.mask_crypto import decrypt_text, encrypt_text, validate_mask_crypto_config
from dependencies.auth import get_current_user, normalize_system_role
from models.commissions import SalesPartner
from routers.app_config import DEFAULT_APP_CONFIGS
from routers.commissions import _portal_partner_scope
from routers.emp_auth_tokens import (
    TokenResponse,
    _secure_cookie_enabled,
)
from schemas.auth import UserResponse
from backend.services import security_tokens
from services.emp_auth import (
    ACCESS_TOKEN_EXPIRE_HOURS,
    create_access_token as create_employee_access_token,
    validate_employee_auth_security_config,
    validate_runtime_security_config,
)


@pytest.mark.asyncio
async def test_pwa_static_files_have_safe_types_and_missing_reserved_file_is_not_spa(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<h1>SPA shell</h1>", encoding="utf-8")
    (dist / "manifest.webmanifest").write_text('{"name":"T24 OS"}', encoding="utf-8")
    (dist / "sw.js").write_text("self.addEventListener('fetch', () => {});", encoding="utf-8")
    (dist / "offline.html").write_text("<h1>Offline</h1>", encoding="utf-8")
    (dist / "robots.txt").write_text("User-agent: *\nDisallow: /\n", encoding="utf-8")
    for icon_name in ("apple-touch-icon.png", "pwa-icon-192.png", "pwa-icon-512.png"):
        (dist / icon_name).write_bytes(b"test-png")
    monkeypatch.setattr(main_module, "FRONTEND_DIST_DIR", dist)

    transport = ASGITransport(app=main_module.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        manifest = await client.get("/manifest.webmanifest")
        worker = await client.get("/sw.js")
        offline = await client.get("/offline.html")
        robots = await client.get("/robots.txt")
        icons = [
            await client.get("/apple-touch-icon.png"),
            await client.get("/pwa-icon-192.png"),
            await client.get("/pwa-icon-512.png"),
        ]
        spa_route = await client.get("/customers")
        missing_icon = await client.get("/pwa-icon-maskable-512.png")

    assert manifest.status_code == 200
    assert manifest.headers["content-type"].startswith("application/manifest+json")
    assert manifest.headers["cache-control"].startswith("no-store")
    assert worker.headers["content-type"].startswith("application/javascript")
    assert worker.headers["service-worker-allowed"] == "/"
    assert worker.headers["cache-control"].startswith("no-store")
    assert offline.headers["cache-control"].startswith("no-store")
    assert robots.headers["content-type"].startswith("text/plain")
    assert robots.headers["cache-control"].startswith("no-store")
    assert "Disallow: /" in robots.text
    for icon in icons:
        assert icon.status_code == 200
        assert icon.headers["content-type"].startswith("image/png")
        assert "no-cache" in icon.headers["cache-control"]
        assert "must-revalidate" in icon.headers["cache-control"]
        assert "immutable" not in icon.headers["cache-control"]
        assert "etag" in icon.headers
    assert spa_route.status_code == 200
    assert "SPA shell" in spa_route.text
    assert missing_icon.status_code == 404
    assert "SPA shell" not in missing_icon.text


def test_deduction_and_owner_portal_default_permissions_are_registered():
    permissions = DEFAULT_APP_CONFIGS["role_permissions"]
    for role in ("super_admin", "admin", "finance"):
        assert "/settings/deduction" in permissions[role]["pages"]
    assert "/partner-portal" in permissions["super_admin"]["pages"]
    assert "/partner-portal" not in permissions["admin"]["pages"]
    assert "/partner-portal" not in permissions["finance"]["pages"]


def test_refresh_cookie_defaults_to_secure_in_production(monkeypatch):
    monkeypatch.delenv("COOKIE_SECURE", raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    assert _secure_cookie_enabled() is True

    monkeypatch.setenv("COOKIE_SECURE", "false")
    assert _secure_cookie_enabled() is False


@pytest.mark.asyncio
async def test_set_refresh_rejects_malformed_and_expired_employee_tokens_as_401():
    expired = create_employee_access_token(
        {"emp_id": 1, "email": "expired@example.com", "role": "admin"},
        expires_delta=timedelta(seconds=-1),
    )
    async def no_database_needed_for_invalid_token():
        yield None

    main_module.app.dependency_overrides[get_db] = no_database_needed_for_invalid_token
    try:
        transport = ASGITransport(app=main_module.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            responses = [
                await client.post(
                    "/api/v1/emp-auth/set_refresh",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"remember_me": True},
                )
                for token in ("not-a-jwt", expired)
            ]
    finally:
        main_module.app.dependency_overrides.pop(get_db, None)

    assert [response.status_code for response in responses] == [401, 401]
    assert all("token" in response.json()["detail"].lower() for response in responses)


def test_refresh_response_expiry_matches_employee_access_token_contract():
    assert ACCESS_TOKEN_EXPIRE_HOURS == 24
    assert TokenResponse(access_token="token").expires_in == ACCESS_TOKEN_EXPIRE_HOURS * 60 * 60


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy_role", ["boss", "owner", "superadmin", "超级管理员", "老板"])
async def test_auth_boundary_canonicalizes_legacy_owner_roles(legacy_role, monkeypatch):
    monkeypatch.setenv("ENFORCE_EMPLOYEE_STATUS", "false")
    token = create_employee_access_token({
        "emp_id": 9,
        "email": "owner@example.com",
        "role": legacy_role,
        "name": "Owner",
    })
    request = Request({
        "type": "http",
        "method": "GET",
        "scheme": "https",
        "path": "/api/v1/commissions/my-dashboard",
        "raw_path": b"/api/v1/commissions/my-dashboard",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 1),
        "server": ("test", 443),
    })

    user = await get_current_user(request=request, token=token, db=None)  # type: ignore[arg-type]

    assert user.role == "super_admin"


def test_public_default_cannot_forge_employee_refresh_cookie():
    forged = jwt.encode(
        {
            "sub": "1",
            "iat": int(datetime.now(timezone.utc).timestamp()),
            "exp": datetime.now(timezone.utc) + timedelta(days=1),
        },
        "change-me-refresh",
        algorithm=security_tokens.ALGORITHM,
    )
    with pytest.raises(Exception):
        security_tokens.verify_refresh_token(forged)


def test_refresh_secret_fails_closed_in_production_and_derives_from_strong_jwt(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("REFRESH_TOKEN_SECRET", raising=False)
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    monkeypatch.delenv("T24_EPHEMERAL_REFRESH_TOKEN_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="Production refresh tokens require"):
        security_tokens._resolve_refresh_token_secret()

    monkeypatch.setenv("JWT_SECRET_KEY", "a-strong-production-jwt-secret-value-0123456789")
    derived = security_tokens._resolve_refresh_token_secret()
    assert len(derived) == 64
    assert derived != "a-strong-production-jwt-secret-value-0123456789"


def test_refresh_secret_rejects_placeholder_or_short_values(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("REFRESH_TOKEN_SECRET", "change-me-refresh")
    monkeypatch.setenv("JWT_SECRET_KEY", "a-strong-production-jwt-secret-value-0123456789")
    with pytest.raises(RuntimeError, match="REFRESH_TOKEN_SECRET"):
        security_tokens._resolve_refresh_token_secret()


@pytest.mark.parametrize(
    "weak_jwt_secret",
    [
        "short-secret",
        "crm-employee-auth-secret-key-2024",
        "replace-with-a-long-random-secret",
        "replace-with-a-different-public-placeholder-value-123456789",
    ],
)
def test_production_rejects_weak_employee_jwt_even_with_strong_refresh_secret(monkeypatch, weak_jwt_secret):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("REFRESH_TOKEN_SECRET", "independent-strong-refresh-secret-value-0123456789")
    monkeypatch.setenv("JWT_SECRET_KEY", weak_jwt_secret)

    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        validate_employee_auth_security_config()


def test_production_accepts_independently_strong_employee_jwt_and_refresh_secrets(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("REFRESH_TOKEN_SECRET", "independent-strong-refresh-secret-value-0123456789")
    monkeypatch.setenv("JWT_SECRET_KEY", "independent-strong-employee-jwt-value-0123456789")

    validate_employee_auth_security_config()


@pytest.mark.parametrize("mask_key", [None, "short-mask-key", "Mgx@FunctionSea", "replace-with-a-long-random-mask-key"])
def test_production_rejects_missing_weak_or_placeholder_mask_key(monkeypatch, mask_key):
    monkeypatch.setenv("APP_ENV", "production")
    if mask_key is None:
        monkeypatch.delenv("MASK_KEY", raising=False)
    else:
        monkeypatch.setenv("MASK_KEY", mask_key)

    with pytest.raises(RuntimeError, match="MASK_KEY"):
        validate_mask_crypto_config()


def test_strong_mask_key_round_trip_and_wrong_key_failure(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("MASK_KEY", "stable-production-mask-key-value-0123456789")
    encrypted = encrypt_text("sensitive-test-value")
    assert encrypted != "sensitive-test-value"
    assert decrypt_text(encrypted) == "sensitive-test-value"

    monkeypatch.setenv("MASK_KEY", "different-production-mask-key-9876543210")
    with pytest.raises(InvalidToken):
        decrypt_text(encrypted)


def test_production_rejects_legacy_placeholder_auth_even_with_strong_keys(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", "independent-strong-employee-jwt-value-0123456789")
    monkeypatch.setenv("REFRESH_TOKEN_SECRET", "independent-strong-refresh-secret-value-0123456789")
    monkeypatch.setenv("MASK_KEY", "stable-production-mask-key-value-0123456789")
    monkeypatch.setenv("ENABLE_LEGACY_AUTH", "true")

    with pytest.raises(RuntimeError, match="ENABLE_LEGACY_AUTH"):
        validate_runtime_security_config()


@pytest.mark.asyncio
async def test_owner_partner_portal_scope_is_read_only_and_explicit():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(SalesPartner.__table__.create)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as db:
        db.add_all([
            SalesPartner(
                id=1,
                partner_code="P001",
                name="A Partner",
                partner_type="partner",
                status="suspended",
                joined_at=date(2026, 1, 1),
            ),
            SalesPartner(
                id=2,
                partner_code="P002",
                name="B Partner",
                partner_type="agency",
                status="active",
                joined_at=date(2026, 2, 1),
            ),
        ])
        await db.commit()

        owner = UserResponse(id="9", email="owner@example.com", role="super_admin")
        selected, available, owner_readonly = await _portal_partner_scope(owner, db, None)
        explicit, _, explicit_readonly = await _portal_partner_scope(owner, db, 1)

        assert selected.id == 2
        assert [row.id for row in available] == [1, 2]
        assert owner_readonly is True
        assert explicit.id == 1
        assert explicit_readonly is True

        for legacy_role in ("boss", "owner", "superadmin", "超级管理员", "老板"):
            legacy_selected, _, legacy_readonly = await _portal_partner_scope(
                UserResponse(id="9", email="owner@example.com", role=legacy_role),
                db,
                None,
            )
            assert normalize_system_role(legacy_role) == "super_admin"
            assert legacy_selected.id == 2
            assert legacy_readonly is True

        with pytest.raises(HTTPException) as admin_error:
            await _portal_partner_scope(
                UserResponse(id="8", email="admin@example.com", role="admin"),
                db,
                None,
            )
        assert admin_error.value.status_code == 403

    await engine.dispose()
