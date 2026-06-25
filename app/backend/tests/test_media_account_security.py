from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from core.database import Base
from core.mask_crypto import key_prefix
from services.media_accounts import (
    Media_accountsService,
    decrypt_media_account_password,
)


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
async def test_media_account_password_is_encrypted_on_create(db_session):
    service = Media_accountsService(db_session)
    account = await service.create(
        {
            "customer_id": 1,
            "platform_name": "Facebook",
            "account_name": "demo-store",
            "login_email": "demo@example.com",
            "login_password": "secret-123",
            "created_at": datetime(2026, 6, 25, 10, 0, 0),
        },
        user_id="1",
    )

    assert account is not None
    assert account.login_password.startswith(key_prefix)
    assert decrypt_media_account_password(account.login_password) == "secret-123"


@pytest.mark.asyncio
async def test_media_account_blank_password_update_preserves_existing_secret(db_session):
    service = Media_accountsService(db_session)
    account = await service.create(
        {
            "customer_id": 1,
            "platform_name": "Instagram",
            "account_name": "demo-brand",
            "login_password": "old-password",
            "created_at": datetime(2026, 6, 25, 10, 0, 0),
        },
        user_id="2",
    )
    original_password = account.login_password

    updated = await service.update(
        account.id,
        {
            "login_password": "",
            "account_status": "active",
            "updated_at": datetime(2026, 6, 25, 11, 0, 0),
        },
        user_id="2",
    )

    assert updated is not None
    assert updated.login_password == original_password
    assert decrypt_media_account_password(updated.login_password) == "old-password"


@pytest.mark.asyncio
async def test_media_account_password_update_reencrypts_new_secret(db_session):
    service = Media_accountsService(db_session)
    account = await service.create(
        {
            "customer_id": 1,
            "platform_name": "Google Business",
            "account_name": "demo-business",
            "login_password": "old-secret",
            "created_at": datetime(2026, 6, 25, 10, 0, 0),
        },
        user_id="3",
    )

    updated = await service.update(
        account.id,
        {
            "login_password": "new-secret",
            "updated_at": datetime(2026, 6, 25, 12, 0, 0),
        },
        user_id="3",
    )

    assert updated is not None
    assert updated.login_password.startswith(key_prefix)
    assert decrypt_media_account_password(updated.login_password) == "new-secret"
