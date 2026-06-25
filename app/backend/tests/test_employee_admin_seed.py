import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.services.emp_auth import EmpAuthService, hash_password, verify_password


@pytest.fixture
def admin_env(monkeypatch):
    for key in (
        "DEFAULT_ADMIN_EMAIL",
        "DEFAULT_ADMIN_PASSWORD",
        "DEFAULT_ADMIN_NAME",
        "ALLOW_WEAK_DEFAULT_ADMIN",
    ):
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


async def _session_maker():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE employees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id VARCHAR NOT NULL,
                name VARCHAR NOT NULL,
                role VARCHAR NOT NULL,
                phone VARCHAR,
                email VARCHAR,
                password VARCHAR,
                status VARCHAR,
                created_at DATETIME
            )
        """))
    return engine, async_sessionmaker(engine, expire_on_commit=False)


@pytest.mark.asyncio
async def test_default_admin_seed_skips_when_password_is_not_configured(admin_env):
    engine, session_maker = await _session_maker()
    try:
        async with session_maker() as db:
            await EmpAuthService(db).ensure_default_admin()
            count = (await db.execute(text("SELECT COUNT(*) FROM employees"))).scalar()

        assert count == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_default_admin_seed_refuses_historical_weak_password(admin_env):
    admin_env.setenv("DEFAULT_ADMIN_PASSWORD", "admin123")
    engine, session_maker = await _session_maker()
    try:
        async with session_maker() as db:
            await EmpAuthService(db).ensure_default_admin()
            count = (await db.execute(text("SELECT COUNT(*) FROM employees"))).scalar()

        assert count == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_default_admin_seed_creates_configured_strong_admin(admin_env):
    admin_env.setenv("DEFAULT_ADMIN_EMAIL", "owner@example.com")
    admin_env.setenv("DEFAULT_ADMIN_PASSWORD", "StrongPass123!")
    admin_env.setenv("DEFAULT_ADMIN_NAME", "Owner")
    engine, session_maker = await _session_maker()
    try:
        async with session_maker() as db:
            await EmpAuthService(db).ensure_default_admin()
            row = (
                await db.execute(text("SELECT user_id, name, role, email, password, status FROM employees"))
            ).fetchone()

        assert row is not None
        assert row[0] == "admin:owner@example.com"
        assert row[1] == "Owner"
        assert row[2] == "admin"
        assert row[3] == "owner@example.com"
        assert verify_password("StrongPass123!", row[4])
        assert row[5] == "active"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_default_admin_seed_does_not_overwrite_existing_password(admin_env):
    admin_env.setenv("DEFAULT_ADMIN_EMAIL", "owner@example.com")
    admin_env.setenv("DEFAULT_ADMIN_PASSWORD", "NewStrongPass123!")
    original_hash = hash_password("OriginalStrongPass123!")
    engine, session_maker = await _session_maker()
    try:
        async with session_maker() as db:
            await db.execute(
                text("""
                    INSERT INTO employees (user_id, name, role, email, password, status)
                    VALUES ('admin:owner@example.com', 'Owner', 'admin', 'owner@example.com', :pwd, 'active')
                """),
                {"pwd": original_hash},
            )
            await db.commit()

            await EmpAuthService(db).ensure_default_admin()
            stored_hash = (
                await db.execute(text("SELECT password FROM employees WHERE email = 'owner@example.com'"))
            ).scalar()

        assert verify_password("OriginalStrongPass123!", stored_hash)
        assert not verify_password("NewStrongPass123!", stored_hash)
    finally:
        await engine.dispose()
