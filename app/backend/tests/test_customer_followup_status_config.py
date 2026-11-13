"""Isolated SQLite contracts; no production database, accounts or providers."""
import asyncio
import json
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.database import get_db
from dependencies.auth import get_current_user
from routers import app_config as config

PATH = "/api/v1/app-config/dict_config/customer-followup-statuses"
DICT_PATH = "/api/v1/app-config/dict_config"
ACTIVE = config.CUSTOMER_FOLLOWUP_ACTIVE
ARCHIVE = config.CUSTOMER_FOLLOWUP_ARCHIVE


@pytest_asyncio.fixture
async def env(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'config-only.sqlite'}")
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE app_settings (config_key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TIMESTAMP)"))
        await conn.execute(text("CREATE TABLE untouched_customers (id INTEGER PRIMARY KEY, stage TEXT)"))
        await conn.execute(text("INSERT INTO untouched_customers VALUES (1, 'old_follow_later')"))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    identity = {"role": "super_admin"}
    app = FastAPI()
    app.include_router(config.router)

    async def db_override():
        async with maker() as db:
            yield db

    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(role=identity["role"])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, maker, identity
    await engine.dispose()


async def stored(maker):
    async with maker() as db:
        raw = await db.scalar(text("SELECT value_json FROM app_settings WHERE config_key='dict_config'"))
        return json.loads(raw) if raw else None


async def seed(maker, value):
    async with maker() as db:
        await db.execute(text("INSERT INTO app_settings (config_key,value_json) VALUES ('dict_config',:value)"), {"value": json.dumps(value)})
        await db.commit()


def patch_value(current, **changes):
    return {"active": current["active"], "archive": current["archive"], "expected_revision": current["revision"], **changes}


@pytest.mark.asyncio
async def test_default_get_is_readonly_and_presales_history_is_separate(env):
    client, maker, _ = env
    response = await client.get(PATH)
    assert response.status_code == 200
    value = response.json()
    assert len(value["active"].split(",")) == 8 and value["archive"] == ""
    assert "service_follow_later:后续跟进" in value["active"]
    assert all(not item.startswith("follow_later:") for item in value["active"].split(","))
    assert len(value["revision"]) == 64 and await stored(maker) is None
    generic = (await client.get(DICT_PATH)).json()["value"]
    assert generic["followUpStages"] == config.DEFAULT_APP_CONFIGS["dict_config"]["followUpStages"]
    async with maker() as db:
        assert await db.scalar(text("SELECT stage FROM untouched_customers WHERE id=1")) == "old_follow_later"


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["admin", "super_admin"])
async def test_add_rename_reorder_archive_restore_keeps_keys_and_other_dictionary(env, role):
    client, maker, identity = env
    identity["role"] = role
    original = {"followUpStages": "old_follow_later:历史售前标签", "industries": "nail:美甲", "opaque": {"keep": [1, 2]}}
    await seed(maker, original)
    current = (await client.get(PATH)).json()
    entries = current["active"].split(",")
    archived = entries.pop(1)
    active = ",".join(reversed(entries)).replace("in_service:正常服务", "in_service:正常服务中") + ",custom_123:自定义阶段"
    response = await client.patch(PATH, json=patch_value(current, active=active, archive=archived))
    assert response.status_code == 200
    changed = response.json()
    assert changed["active"] == active and changed["archive"] == archived and changed["revision"] != current["revision"]
    assert {key: value for key, value in (await stored(maker)).items() if key not in (ACTIVE, ARCHIVE)} == original
    restored = await client.patch(PATH, json=patch_value(changed, active=changed["active"] + "," + archived, archive=""))
    assert restored.status_code == 200 and restored.json()["archive"] == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["ops", "operations", "sales", "sales_manager", "finance", "sales_partner"])
async def test_only_admin_roles_can_patch_service_dictionary(env, role):
    client, maker, identity = env
    current = (await client.get(PATH)).json()
    identity["role"] = role
    response = await client.patch(PATH, json=patch_value(current, active=current["active"].replace("正常服务", "新服务名称")))
    assert response.status_code == 403 and await stored(maker) is None


@pytest.mark.asyncio
async def test_legacy_ops_put_preserves_service_fields_and_explicit_changes_rejected(env):
    client, maker, identity = env
    custom = {ACTIVE: config.DEFAULT_CUSTOMER_FOLLOWUP_STATUSES.replace("正常服务", "稳定服务"), ARCHIVE: "old_service:旧阶段", "followUpStages": "legacy:历史售前"}
    await seed(maker, custom)
    identity["role"] = "ops"
    response = await client.put(DICT_PATH, json={"value": {"followUpStages": "legacy:修改售前名称", "industries": "nail:美甲"}})
    assert response.status_code == 200
    saved = await stored(maker)
    assert saved[ACTIVE] == custom[ACTIVE] and saved[ARCHIVE] == custom[ARCHIVE]
    assert saved["followUpStages"] == "legacy:修改售前名称"
    for role, expected in (("ops", 403), ("admin", 409), ("super_admin", 409)):
        identity["role"] = role
        response = await client.put(DICT_PATH, json={"value": {**saved, ACTIVE: "replacement:替换全部"}})
        assert response.status_code == expected and await stored(maker) == saved
    identity["role"] = "ops"
    assert (await client.put(DICT_PATH, json={"value": saved})).status_code == 200


@pytest.mark.asyncio
async def test_validation_rejects_bad_types_keys_labels_duplicates_and_key_deletion(env):
    client, maker, _ = env
    current = (await client.get(PATH)).json()
    active = current["active"]
    invalid = [
        {"active": []}, {"archive": None}, {"active": ""},
        {"active": active + ",Upper:大写键"}, {"active": active + ",bad-key:非法键"},
        {"active": active + ",long_label:" + "字" * 41}, {"active": active + ",empty_label:"},
        {"active": active + ",colon:中文：冒号"}, {"active": active + ",comma:中文，逗号"},
        {"active": active + ",ascii:含:冒号"}, {"active": active + ",control:换\n行"},
        {"active": active + ",trailing_control:末尾制表\t"},
        {"active": active + ",in_service:另一个名称"}, {"archive": "other_key:正常服务"},
        {"archive": "in_service:重复键"}, {"active": ",".join(active.split(",")[1:])},
        {"expected_revision": "not-a-revision"}, {"unexpected": True},
    ]
    for change in invalid:
        response = await client.patch(PATH, json=patch_value(current, **change))
        assert response.status_code == 422, (change, response.text)
        assert await stored(maker) is None


@pytest.mark.asyncio
async def test_revision_only_tracks_service_fields_and_stale_patch_is_409(env):
    client, maker, _ = env
    current = (await client.get(PATH)).json()
    assert (await client.put(DICT_PATH, json={"value": {"industries": "new_industry:新行业"}})).status_code == 200
    assert (await client.get(PATH)).json()["revision"] == current["revision"]
    changed = current["active"].replace("正常服务", "服务正常")
    assert (await client.patch(PATH, json=patch_value(current, active=changed))).status_code == 200
    before = await stored(maker)
    assert (await client.patch(PATH, json=patch_value(current))).status_code == 409
    assert await stored(maker) == before and before["industries"] == "new_industry:新行业"


@pytest.mark.asyncio
@pytest.mark.parametrize("existing_row", [True, False])
async def test_two_real_sqlite_sessions_cannot_both_overwrite_same_revision(env, existing_row):
    client, maker, _ = env
    if existing_row:
        await seed(maker, {"other_dictionary": "must_survive"})
    current = (await client.get(PATH)).json()
    responses = await asyncio.gather(*[
        client.patch(PATH, json=patch_value(current, active=current["active"].replace("正常服务", label)))
        for label in ("同事甲服务", "同事乙服务")
    ])
    assert sorted(response.status_code for response in responses) == [200, 409]
    saved = await stored(maker)
    winner = next(response.json() for response in responses if response.status_code == 200)
    assert saved[ACTIVE] == winner["active"]
    if existing_row:
        assert saved["other_dictionary"] == "must_survive"


@pytest.mark.asyncio
async def test_interleaved_other_dictionary_write_is_merged_after_sql_cas_miss(env, monkeypatch):
    client, maker, _ = env
    await seed(maker, {"other_dictionary": "before"})
    current = (await client.get(PATH)).json()
    async with maker() as db:
        real_execute = db.execute
        raced = False

        async def execute(statement, params=None, **kwargs):
            nonlocal raced
            if not raced and str(statement).startswith("UPDATE app_settings SET value_json"):
                raced = True
                response = await client.put(DICT_PATH, json={"value": {"other_dictionary": "concurrent", "new_dictionary": ["kept"]}})
                assert response.status_code == 200
            return await real_execute(statement, params, **kwargs)

        monkeypatch.setattr(db, "execute", execute)
        result = await config.update_customer_followup_statuses(
            config.CustomerFollowUpStatusUpdate(**patch_value(current, active=current["active"].replace("正常服务", "并发后服务"))),
            SimpleNamespace(role="admin"), db,
        )
    saved = await stored(maker)
    assert raced and saved["other_dictionary"] == "concurrent" and saved["new_dictionary"] == ["kept"]
    assert saved[ACTIVE] == result["active"] and "并发后服务" in result["active"]


@pytest.mark.asyncio
async def test_interleaved_generic_put_keeps_new_service_snapshot(env, monkeypatch):
    client, maker, _ = env
    await seed(maker, {"other_dictionary": "before"})
    current = (await client.get(PATH)).json()
    old_payload = {"other_dictionary": "generic_edit", ACTIVE: current["active"], ARCHIVE: current["archive"]}
    async with maker() as db:
        real_execute = db.execute
        raced = False

        async def execute(statement, params=None, **kwargs):
            nonlocal raced
            if not raced and str(statement).startswith("UPDATE app_settings SET value_json"):
                raced = True
                response = await client.patch(PATH, json=patch_value(current, active=current["active"].replace("正常服务", "刚更新服务阶段")))
                assert response.status_code == 200
            return await real_execute(statement, params, **kwargs)

        monkeypatch.setattr(db, "execute", execute)
        await config.update_app_config("dict_config", config.AppConfigUpdate(value=old_payload), SimpleNamespace(role="ops"), db)
    saved = await stored(maker)
    assert raced and saved["other_dictionary"] == "generic_edit" and "刚更新服务阶段" in saved[ACTIVE]


@pytest.mark.asyncio
async def test_missing_schema_reads_defaults_but_patch_does_not_create_table(env):
    client, maker, _ = env
    async with maker() as db:
        await db.execute(text("DROP TABLE app_settings"))
        await db.commit()
    current = (await client.get(PATH)).json()
    assert (await client.patch(PATH, json=patch_value(current))).status_code == 503
    async with maker() as db:
        assert await db.scalar(text("SELECT COUNT(*) FROM sqlite_master WHERE name='app_settings'")) == 0
        assert await db.scalar(text("SELECT stage FROM untouched_customers WHERE id=1")) == "old_follow_later"
