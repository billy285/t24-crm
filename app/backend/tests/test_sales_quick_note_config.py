from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.database import get_db
from dependencies.auth import get_current_user
from routers.app_config import SALES_QUICK_NOTE_CONFIG, router

PATH = "/api/v1/app-config/sales/quick-note-templates"
GENERAL_PATH = f"/api/v1/app-config/{SALES_QUICK_NOTE_CONFIG}"


@pytest_asyncio.fixture
async def env(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'quick-notes.sqlite'}")
    async with engine.begin() as connection:
        await connection.execute(text(
            "CREATE TABLE app_settings (config_key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TIMESTAMP)"
        ))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    identity = SimpleNamespace(role="super_admin")
    app = FastAPI()
    app.include_router(router)

    async def db_override():
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[get_current_user] = lambda: identity
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client, identity
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_owner_configuration_preserves_defaults_and_checks_revision(env):
    client, identity = env
    initial = (await client.get(PATH)).json()
    assert len(initial["templates"]) == 8
    assert initial["templates"][-1]["remind_do_not_contact"] is True
    restaurant = {
        "id": "restaurant_contract", "label": " 合同到期 ", "text": "现用系统：___；\n到期时间：___",
        "industry": "restaurant", "enabled": True, "remind_do_not_contact": False,
    }
    templates = [restaurant, *initial["templates"]]
    templates[2] = {**templates[2], "enabled": False}
    request = {"expected_revision": initial["revision"], "templates": templates}

    result = await client.patch(PATH, json=request)
    assert result.status_code == 200, result.text
    saved = result.json()
    assert saved["revision"] != initial["revision"]
    assert saved["templates"][0] == {**restaurant, "label": "合同到期"}
    assert saved["templates"][2]["enabled"] is False
    assert (await client.patch(PATH, json=request)).status_code == 409
    for role in ("sales", "sales_manager", "admin"):
        identity.role = role
        assert (await client.get(PATH)).json() == {
            **saved, "templates": [template for template in saved["templates"] if template["enabled"]],
        }
        assert (await client.get(GENERAL_PATH)).status_code == 403
        assert (await client.patch(PATH, json={**request, "expected_revision": saved["revision"]})).status_code == 403
        assert (await client.put(GENERAL_PATH, json={"value": {"templates": []}})).status_code == 403
    identity.role = "sales_partner"
    assert (await client.get(PATH)).status_code == 403


@pytest.mark.asyncio
async def test_validation_prevents_silent_deletion_and_ambiguous_enabled_names(env):
    client, _ = env
    current = (await client.get(PATH)).json()
    templates = current["templates"]
    revision = current["revision"]
    assert (await client.patch(PATH, json={"expected_revision": revision, "templates": templates[:-1]})).status_code == 422
    repeated = {**templates[0], "id": "repeated", "industry": "beauty"}
    assert (await client.patch(PATH, json={"expected_revision": revision, "templates": [*templates, repeated]})).status_code == 422
    blank = {**repeated, "id": "blank", "label": "   "}
    assert (await client.patch(PATH, json={"expected_revision": revision, "templates": [*templates, blank]})).status_code == 422
    assert (await client.put(GENERAL_PATH, json={"value": {"templates": []}})).status_code == 403
    assert (await client.get(PATH)).json() == current
