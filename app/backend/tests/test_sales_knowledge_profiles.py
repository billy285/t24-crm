import asyncio
import json

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from backend.main import app
from backend.tests.test_sales_lead_isolation import _auth_headers, sales_app_client
from core.database import get_db
from core.database import Base
from models.operation_logs import Operation_logs
from models.sales_knowledge_articles import SalesKnowledgeArticles
from routers import sales_knowledge as knowledge
from schemas.auth import UserResponse
from services.sales_knowledge_profiles import lock_knowledge


MANAGER = _auth_headers("sales_manager", 10, "Manager A")
SALES = _auth_headers("sales", 11, "Sales A")


def card(**changes):
    return {"category": "需求诊断", "title": "如何了解预约管理现状？", "customer_question": "我现在用微信登记预约。",
            "standard_answer": "先了解您现在的预约流程，再演示适合您门店的管理方式。",
            "phone_answer": "您现在预约主要通过微信，还是也会接电话登记？", "product_scope": "beautyos",
            "followup_question": "最容易漏掉的是哪一步？", "demo_steps": ["仅演示已确认的预约流程"],
            "next_action": "约定一次预约演示", "action_steps": ["内部核实当前门店权限"],
            "internal_notes": "内部测试标识，不可复制给客户", "store_types": ["美甲"],
            "availability": "ready", "high_frequency": True, **changes}


async def read_rows(model):
    context = app.dependency_overrides[get_db]()
    try:
        db = await anext(context)
        return (await db.scalars(select(model).order_by(model.id))).all()
    finally:
        await context.aclose()


@pytest.mark.asyncio
async def test_profiles_persist_and_published_draft_does_not_leak_into_staff_or_search(sales_app_client):
    created = await sales_app_client.post("/api/v1/sales-knowledge/articles?publish_now=true", headers=MANAGER, json=card())
    assert created.status_code == 201
    old = created.json()
    assert old["revision"] == old["published_revision"] == 1
    assert old["legacy_profile"] is False
    assert old["reviewed_by_name"] == "Manager A"

    updated = await sales_app_client.put(f"/api/v1/sales-knowledge/articles/{old['id']}", headers=MANAGER,
        json=card(title="未审批独有新标题", standard_answer="尚未审批的新答复", phone_answer="尚未审批的新电话版",
                  product_scope="managed_service", expected_revision=1))
    assert updated.status_code == 200
    draft = updated.json()
    assert draft["status"] == "draft" and draft["revision"] == 2 and draft["published_revision"] == 1

    staff = (await sales_app_client.get("/api/v1/sales-knowledge/articles?product_scope=beautyos&include_general=false", headers=SALES)).json()["items"]
    assert len(staff) == 1 and staff[0]["title"] == old["title"] and staff[0]["phone_answer"] == old["phone_answer"]
    assert staff[0]["revision"] == 1 and staff[0]["product_scope"] == "beautyos"
    hidden = await sales_app_client.get("/api/v1/sales-knowledge/articles?query=未审批独有", headers=SALES)
    assert hidden.json()["items"] == []
    manager = await sales_app_client.get("/api/v1/sales-knowledge/articles?include_all=true&product_scope=managed_service&include_general=false", headers=MANAGER)
    assert manager.json()["items"][0]["title"] == "未审批独有新标题"

    published = await sales_app_client.post(f"/api/v1/sales-knowledge/articles/{old['id']}/publish", headers=MANAGER, json={"expected_revision": 2})
    assert published.status_code == 200 and published.json()["revision"] == published.json()["published_revision"] == 3
    staff = await sales_app_client.get("/api/v1/sales-knowledge/articles?product_scope=managed_service&include_general=false", headers=SALES)
    assert staff.json()["items"][0]["phone_answer"] == "尚未审批的新电话版"
    history = [json.loads(row.action_detail) for row in await read_rows(Operation_logs) if row.action_type.startswith("sales_knowledge_profile:")]
    assert [row["revision"] for row in history] == [1, 2, 3]
    assert history[1]["before"]["phone_answer"] == old["phone_answer"]
    assert history[1]["snapshot"]["phone_answer"] == "尚未审批的新电话版"


@pytest.mark.asyncio
async def test_missing_or_stale_revision_does_not_change_wording_publish_or_archive(sales_app_client):
    created = (await sales_app_client.post("/api/v1/sales-knowledge/articles?publish_now=true", headers=MANAGER, json=card())).json()
    path = f"/api/v1/sales-knowledge/articles/{created['id']}"
    for body in [card(title="不应保存"), card(title="不应保存", expected_revision=0)]:
        assert (await sales_app_client.put(path, headers=MANAGER, json=body)).status_code == 409
    assert (await sales_app_client.post(path + "/publish", headers=MANAGER)).status_code == 409
    assert (await sales_app_client.delete(path, headers=MANAGER)).status_code == 409
    current = (await sales_app_client.get("/api/v1/sales-knowledge/articles?include_all=true", headers=MANAGER)).json()["items"][0]
    assert current["revision"] == 1 and current["title"] == created["title"] and current["status"] == "published"
    assert len(await read_rows(Operation_logs)) == 1


@pytest.mark.asyncio
async def test_legacy_metadata_is_inferred_read_only_and_does_not_clear_when_old_fields_are_saved(sales_app_client):
    seeded = (await sales_app_client.get("/api/v1/sales-knowledge/articles", headers=SALES)).json()["items"]
    managed = next(row for row in seeded if row["title"] == "代运营套餐怎么选？")
    assert managed["product_scope"] == "managed_service" and managed["legacy_profile"] and managed["revision"] == 0
    assert not await read_rows(Operation_logs)
    async for db in app.dependency_overrides[get_db]():
        row = await db.get(SalesKnowledgeArticles, managed["id"])
        row.title = "付款链接｜基础版｜月付"
        row.tags = "[]"
        await db.commit()
    scoped = (await sales_app_client.get("/api/v1/sales-knowledge/articles?product_scope=beautyos&include_general=false", headers=SALES)).json()
    assert scoped["items"] == [] and scoped["categories"] == []
    all_rows = (await sales_app_client.get("/api/v1/sales-knowledge/articles", headers=SALES)).json()["items"]
    assert next(row for row in all_rows if row["id"] == managed["id"])["product_scope"] == "managed_service"

    new = (await sales_app_client.post("/api/v1/sales-knowledge/articles?publish_now=true", headers=MANAGER, json=card())).json()
    old_client_payload = {key: value for key, value in card().items() if key in {"category", "title", "standard_answer", "customer_question", "action_steps"}}
    old_client_payload["expected_revision"] = 1
    saved = (await sales_app_client.put(f"/api/v1/sales-knowledge/articles/{new['id']}", headers=MANAGER, json=old_client_payload)).json()
    assert saved["phone_answer"] == new["phone_answer"] and saved["internal_notes"] == new["internal_notes"] and saved["product_scope"] == "beautyos"


@pytest.mark.asyncio
async def test_category_facets_and_store_frequency_filters_match_visible_product_scope(sales_app_client):
    for value in [card(), card(title="美发团队诊断", category="产品与服务", store_types=["美发"], high_frequency=False),
                  card(title="通用美业开场", category="销售准备与开场", store_types=["通用"]),
                  card(title="代运营专用", category="收款与付款", product_scope="managed_service")]:
        assert (await sales_app_client.post("/api/v1/sales-knowledge/articles?publish_now=true", headers=MANAGER, json=value)).status_code == 201
    response = await sales_app_client.get("/api/v1/sales-knowledge/articles?product_scope=beautyos&include_general=false&store_type=美甲&high_frequency=true&category=需求诊断", headers=SALES)
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1
    assert set(response.json()["categories"]) == {"需求诊断", "销售准备与开场"}


@pytest.mark.asyncio
async def test_pack_preview_is_read_only_install_is_hashed_authorized_and_idempotent_without_reviving_archive(sales_app_client):
    initial = (await sales_app_client.get("/api/v1/sales-knowledge/articles", headers=SALES)).json()["items"]
    assert len(initial) == 11
    preview = await sales_app_client.post("/api/v1/sales-knowledge/beautyos-pack/preview", headers=MANAGER, json={})
    assert preview.status_code == 200
    summary = preview.json()
    assert summary["total"] == 60 and summary["high_frequency_count"] == 20 and summary["new_count"] == 60
    assert len(await read_rows(SalesKnowledgeArticles)) == 11 and not await read_rows(Operation_logs)
    assert (await sales_app_client.post("/api/v1/sales-knowledge/beautyos-pack/preview", headers=SALES, json={})).status_code == 403
    assert (await sales_app_client.post("/api/v1/sales-knowledge/beautyos-pack/install", headers=SALES, json={"manifest_hash": summary["manifest_hash"], "publish_now": True})).status_code == 403
    assert (await sales_app_client.post("/api/v1/sales-knowledge/beautyos-pack/install", headers=MANAGER, json={"manifest_hash": "0" * 64, "publish_now": True})).status_code == 409
    assert len(await read_rows(SalesKnowledgeArticles)) == 11

    installed = await sales_app_client.post("/api/v1/sales-knowledge/beautyos-pack/install", headers=MANAGER, json={"manifest_hash": summary["manifest_hash"], "publish_now": True})
    assert installed.status_code == 200
    assert installed.json()["installed_count"] == 60 and installed.json()["skipped_count"] == 0
    assert len(await read_rows(SalesKnowledgeArticles)) == 71
    first = installed.json()["items"][0]
    assert (await sales_app_client.delete(f"/api/v1/sales-knowledge/articles/{first['id']}?expected_revision=1", headers=MANAGER)).status_code == 200
    second = await sales_app_client.post("/api/v1/sales-knowledge/beautyos-pack/install", headers=MANAGER, json={"manifest_hash": summary["manifest_hash"], "publish_now": True})
    assert second.status_code == 200 and second.json()["installed_count"] == 0 and second.json()["skipped_count"] == 60
    rows = await read_rows(SalesKnowledgeArticles)
    assert next(row for row in rows if row.id == first["id"]).status == "archived" and len(rows) == 71
    for old in initial:
        row = next(row for row in rows if row.id == old["id"])
        assert row.title == old["title"] and row.standard_answer == old["standard_answer"]


@pytest.mark.asyncio
async def test_manager_permissions_validation_and_corrupt_ledger_fail_closed(sales_app_client):
    assert (await sales_app_client.post("/api/v1/sales-knowledge/articles", headers=SALES, json=card())).status_code == 403
    for value in [card(title="  "), card(product_scope="unknown"), card(availability="live_for_everyone")]:
        assert (await sales_app_client.post("/api/v1/sales-knowledge/articles", headers=MANAGER, json=value)).status_code == 422
    created = (await sales_app_client.post("/api/v1/sales-knowledge/articles?publish_now=true", headers=MANAGER, json=card())).json()
    forged = await sales_app_client.post("/api/v1/entities/operation_logs", headers=SALES, json={
        "action_type": f"sales_knowledge_profile:{created['id']}", "user_id": "10",
        "action_detail": json.dumps({"revision": 99, "after": {"phone_answer": "伪造话术"}}),
    })
    assert forged.status_code in {403, 422} and len(await read_rows(Operation_logs)) == 1
    async for db in app.dependency_overrides[get_db]():
        db.add(Operation_logs(user_id="10", action_type=f"sales_knowledge_profile:{created['id']}", action_detail="not-json"))
        await db.commit()
    ledger = await read_rows(Operation_logs)
    assert len(ledger) == 2 and ledger[-1].action_detail == "not-json"
    rejected = await sales_app_client.get("/api/v1/sales-knowledge/articles", headers=SALES)
    assert rejected.status_code == 503, rejected.json()
    assert (await sales_app_client.put(f"/api/v1/sales-knowledge/articles/{created['id']}", headers=MANAGER, json=card(expected_revision=1))).status_code == 503


@pytest.mark.asyncio
async def test_two_real_sqlite_connections_serialize_revision_checks_and_keep_only_one_winner(tmp_path, monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///" + str(tmp_path / "knowledge.sqlite"), poolclass=NullPool, connect_args={"timeout": 0.08})
    async with engine.begin() as connection:
        await connection.execute(text("PRAGMA journal_mode=WAL"))
        await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=[SalesKnowledgeArticles.__table__, Operation_logs.__table__]))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    actor = UserResponse(id="10", name="Manager A", email="manager@example.test", role="sales_manager")
    async with sessions() as db:
        created = await knowledge.create_article(knowledge.KnowledgeArticlePayload(**card()), publish_now=True, current_user=actor, db=db)
    held, release = asyncio.Event(), asyncio.Event()
    original = knowledge.append_profile

    async def hold_first(*args, **kwargs):
        if kwargs.get("action") == "edit_draft" and not held.is_set():
            held.set()
            await release.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(knowledge, "append_profile", hold_first)
    async with sessions() as first, sessions() as second:
        task = asyncio.create_task(knowledge.update_article(created["id"], knowledge.KnowledgeArticlePayload(**card(title="首位主管的草稿", expected_revision=1)), current_user=actor, db=first))
        await asyncio.wait_for(held.wait(), 2)
        with pytest.raises(HTTPException) as locked:
            await knowledge.update_article(created["id"], knowledge.KnowledgeArticlePayload(**card(title="不应覆盖", expected_revision=1)), current_user=actor, db=second)
        assert locked.value.status_code == 409
        release.set()
        assert (await task)["revision"] == 2
        with pytest.raises(HTTPException) as stale:
            await knowledge.update_article(created["id"], knowledge.KnowledgeArticlePayload(**card(title="仍不应覆盖", expected_revision=1)), current_user=actor, db=second)
        assert stale.value.status_code == 409
    async with sessions() as db:
        row = await db.get(SalesKnowledgeArticles, created["id"])
        assert row.title == "首位主管的草稿"
        assert len((await db.scalars(select(Operation_logs))).all()) == 2
    await engine.dispose()


@pytest.mark.asyncio
async def test_write_lock_alone_does_not_change_article_fields_or_updated_time(tmp_path):
    engine = create_async_engine("sqlite+aiosqlite:///" + str(tmp_path / "knowledge-lock.sqlite"))
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=[SalesKnowledgeArticles.__table__]))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        db.add(SalesKnowledgeArticles(category="其他", title="原资料", standard_answer="原答复", status="published"))
        await db.commit()
        before = dict((await db.execute(text("SELECT * FROM sales_knowledge_articles"))).mappings().one())
        await db.rollback()
        await lock_knowledge(db)
        await db.commit()
        after = dict((await db.execute(text("SELECT * FROM sales_knowledge_articles"))).mappings().one())
        assert before == after
    await engine.dispose()


@pytest.mark.asyncio
async def test_spoken_search_aliases_use_actual_pack_public_approved_scope_and_keep_exact_first(sales_app_client):
    preview = (await sales_app_client.post("/api/v1/sales-knowledge/beautyos-pack/preview", headers=MANAGER, json={})).json()
    installed = await sales_app_client.post("/api/v1/sales-knowledge/beautyos-pack/install", headers=MANAGER,
        json={"manifest_hash": preview["manifest_hash"], "publish_now": True})
    assert installed.status_code == 200 and installed.json()["installed_count"] == 60
    await sales_app_client.post("/api/v1/sales-knowledge/articles?publish_now=true", headers=MANAGER,
        json=card(title="其他产品完全相同的搜索词", product_scope="managed_service", standard_answer="我已经有系统了", tags=["已有系统"]))
    await sales_app_client.post("/api/v1/sales-knowledge/articles?publish_now=false", headers=MANAGER,
        json=card(title="未发布异议草稿", tags=["已有系统"]))
    internal = await sales_app_client.post("/api/v1/sales-knowledge/articles?publish_now=true", headers=MANAGER,
        json=card(title="公开演示安排", internal_notes="内部独有政策索引A7", tags=[]))
    assert internal.status_code == 201

    async def search(query):
        response = await sales_app_client.get("/api/v1/sales-knowledge/articles", headers=SALES,
            params={"product_scope": "beautyos", "include_general": "false", "query": query, "include_all": "true"})
        assert response.status_code == 200
        return response.json()["items"]

    existing = await search("我已经有系统了")
    assert len(existing) == 1 and existing[0]["title"] == "客户已经在用别的系统"
    trial = await search("免费30天是真的吗")
    assert len(trial) == 1 and trial[0]["title"] == "客户问能试多久、是否收费"
    assert trial[0]["availability"] == "pending_confirmation"
    assert "30" not in trial[0]["phone_answer"] and "60" not in trial[0]["standard_answer"]
    for spoken, title in [
        ("价格太高怎么办", "客户说太贵，先问什么？"),
        ("我现在很忙晚点联系", "老板正在忙，怎样约回拨？"),
        ("给份介绍资料吧", "客户说先发资料，怎样形成下一步？"),
        ("我不想用了怎么取消", "试用结束、续费和取消怎样回复？"),
        ("短信怎么开通发送", "能给客户发短信吗？"),
    ]:
        assert title in [row["title"] for row in await search(spoken)]
    assert await search("内部独有政策索引A7") == []
    assert await search("火星咖啡机联机问题") == []

    exact = await sales_app_client.post("/api/v1/sales-knowledge/articles?publish_now=true", headers=MANAGER,
        json=card(title="精确客户原话", standard_answer="我已经有系统了", phone_answer="先确认实际现状。", tags=[]))
    assert exact.status_code == 201
    assert [row["id"] for row in await search("我已经有系统了")] == [exact.json()["id"]]
