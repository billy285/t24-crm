"""Industry grouping must never widen scope, overwrite raw proof or undo conversion."""

import csv
import io
import json

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.main import app
from backend.services.emp_auth import create_access_token
from core.database import Base, get_db
from models.merchant_pool import MerchantPool
from models.sales_leads import SalesLeads
from services.merchant_industries import normalize_merchant_industry


def auth(role="sales_manager", employee_id=10):
    token = create_access_token({"emp_id": employee_id, "email": f"{employee_id}@example.com",
                                 "role": role, "name": f"Manager {employee_id}"})
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def industry_client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async def override_db():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test") as client:
        yield client, maker
    app.dependency_overrides.pop(get_db, None)
    await engine.dispose()


async def seed(maker, records):
    async with maker() as session:
        rows = []
        for index, record in enumerate(records):
            merchant = MerchantPool(business_name=record.pop("business_name", f"Example {index}"),
                                    phone=f"+1212555{index:04}", country="US", state="CA",
                                    data_source="reviewed", created_by_id=10, raw_payload='{"original":"proof"}')
            for key, value in record.items():
                setattr(merchant, key, value)
            session.add(merchant)
            rows.append(merchant)
        await session.commit()
        return [row.id for row in rows]


def facets(body):
    return {item["value"]: item["count"] for item in body["industry_facets"]}


@pytest.mark.parametrize("raw,expected", [
    ("餐饮", "餐厅"), (" Chinese Restaurants ", "餐厅"), ("BEAUTY / SALON", "美业"),
    ("美甲", "美业"), ("水疗", "美业"), ("按摩", "美业"), ("理发", "美业"), ("massage", "美业"),
    ("unknown", None), ("__unclassified__", None), (" ", None),
    ("Restaurant Software", "Restaurant Software"), ("零售", "零售"),
])
def test_only_explicit_industries_are_normalized(raw, expected):
    assert normalize_merchant_industry(raw) == expected


@pytest.mark.asyncio
async def test_alias_filter_and_facets_are_exact_scoped_and_do_not_backfill(industry_client):
    client, maker = industry_client
    ids = await seed(maker, [
        {"industry": "餐饮"}, {"industry": " Chinese Restaurants "}, {"industry": "BEAUTY / SALON"},
        {"industry": None, "business_name": "Chinese Restaurant Without Reviewed Industry"},
        {"industry": "Restaurant Software"}, {"industry": "餐饮", "created_by_id": 20},
        {"industry": "餐饮", "pool_status": "archived"},
    ])
    response = await client.get("/api/v1/merchant-pool", headers=auth(), params={"industry": "餐厅", "limit": 1})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 2 and len(body["items"]) == 1
    assert body["items"][0]["industry"] == "餐厅"
    assert body["facet_total"] == 5
    assert facets(body) == {"餐厅": 2, "美业": 1, "__unclassified__": 1, "Restaurant Software": 1}
    alias = await client.get("/api/v1/merchant-pool", headers=auth(), params={"industry": "restaurants"})
    assert {item["id"] for item in alias.json()["items"]} == set(ids[:2])
    unclassified = await client.get("/api/v1/merchant-pool", headers=auth(), params={"industry": "__unclassified__"})
    assert [item["id"] for item in unclassified.json()["items"]] == [ids[3]]
    assert unclassified.json()["items"][0]["industry"] is None
    assert next(item for item in body["industry_facets"] if item["value"] == "__unclassified__")["label"] == "待分类"
    assert (await client.get("/api/v1/merchant-pool", headers=auth("sales", 11))).status_code == 403
    admin = await client.get("/api/v1/merchant-pool", headers=auth("admin", 1), params={"industry": "餐厅"})
    assert admin.json()["total"] == 3
    async with maker() as session:
        original = await session.get(MerchantPool, ids[0])
        assert original.industry == "餐饮" and json.loads(original.raw_payload) == {"original": "proof"}


@pytest.mark.asyncio
async def test_facets_honor_view_search_source_region_rating_before_industry(industry_client):
    client, maker = industry_client
    await seed(maker, [
        {"business_name": "Target Restaurant", "industry": "餐饮", "rating": 4.6},
        {"business_name": "Target Beauty", "industry": "美甲", "rating": 4.6},
        {"business_name": "Target Lower Rated", "industry": "餐厅", "rating": 3},
        {"business_name": "Target New York", "industry": "餐厅", "rating": 4.6, "state": "NY"},
        {"business_name": "Target Other Source", "industry": "餐厅", "rating": 4.6, "data_source": "other"},
        {"business_name": "Target Converted", "industry": "餐厅", "rating": 4.6, "pool_status": "converted"},
        {"business_name": "No Match", "industry": "餐厅", "rating": 4.6},
    ])
    response = await client.get("/api/v1/merchant-pool", headers=auth(), params={
        "industry": "餐厅", "pool_status": "pending", "search": "Target", "source": "reviewed", "region": "CA", "rating_min": 4,
    })
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1
    assert response.json()["facet_total"] == 2 and facets(response.json()) == {"餐厅": 1, "美业": 1}


@pytest.mark.asyncio
async def test_batch_facets_only_count_authorized_committed_members(industry_client):
    client, maker = industry_client
    await seed(maker, [{"industry": "餐厅"}, {"industry": "美业"}])
    document = io.StringIO(newline="")
    writer = csv.writer(document)
    writer.writerow(["商家名称", "商家电话", "商家位置", "地区", "来源"])
    writer.writerow(["Reviewed Import", "+13105550123", "1 Main St", "Los Angeles, CA, US", "Official Site"])
    preview = await client.post("/api/v1/merchant-imports/preview", headers=auth(),
        files={"file": ("batch.csv", document.getvalue().encode("utf-8-sig"), "text/csv")})
    assert preview.status_code == 200, preview.text
    batch_id = preview.json()["id"]
    before_commit = await client.get("/api/v1/merchant-pool", headers=auth(), params={"batch_id": batch_id})
    assert before_commit.status_code == 409
    confirm = await client.post(f"/api/v1/merchant-imports/{batch_id}/confirm", headers=auth())
    assert confirm.status_code == 200, confirm.text
    filtered = await client.get("/api/v1/merchant-pool", headers=auth(), params={"batch_id": batch_id})
    assert filtered.status_code == 200, filtered.text
    assert filtered.json()["facet_total"] == 1 and facets(filtered.json()) == {"__unclassified__": 1}
    assert len(filtered.json()["items"]) == 1
    unauthorized = await client.get("/api/v1/merchant-pool", headers=auth(employee_id=20), params={"batch_id": batch_id})
    assert unauthorized.status_code == 404


@pytest.mark.asyncio
async def test_import_and_update_normalize_without_changing_original_payload(industry_client):
    client, maker = industry_client
    raw = {"business_name": "New Business", "phone": "+12125550123", "country": "US", "industry": "餐饮"}
    response = await client.post("/api/v1/merchant-pool/import", headers=auth(), json={"records": [raw]})
    assert response.status_code == 200, response.text
    merchant_id = response.json()["items"][0]["id"]
    assert response.json()["items"][0]["industry"] == "餐厅"
    update = await client.put(f"/api/v1/merchant-pool/{merchant_id}", headers=auth(), json={"industry": "nail salon"})
    assert update.status_code == 200 and update.json()["industry"] == "美业"
    async with maker() as session:
        merchant = await session.get(MerchantPool, merchant_id)
        assert merchant.industry == "美业" and json.loads(merchant.raw_payload) == raw


@pytest.mark.asyncio
async def test_bulk_classification_is_scoped_atomic_and_retry_is_noop(industry_client):
    client, maker = industry_client
    ids = await seed(maker, [{"industry": None}, {"industry": "餐饮"}, {"industry": None, "created_by_id": 20}])
    endpoint = "/api/v1/merchant-pool/bulk-update-industry"
    payload = {"merchant_ids": ids, "industry": "餐厅"}
    assert (await client.post(endpoint, headers=auth("sales", 11), json=payload)).status_code == 403
    assert (await client.post(endpoint, headers=auth(), json=payload)).status_code == 404
    async with maker() as session:
        assert (await session.get(MerchantPool, ids[0])).industry is None
    response = await client.post(endpoint, headers=auth(), json={"merchant_ids": [ids[0], ids[1], ids[0]], "industry": "restaurants"})
    assert response.status_code == 200, response.text
    assert response.json()["industry"] == "餐厅" and response.json()["updated_count"] == 2
    assert response.json()["selected_count"] == 2
    async with maker() as session:
        before = [(row.id, row.updated_at, row.raw_payload, row.pool_status) for row in
                  (await session.execute(select(MerchantPool).order_by(MerchantPool.id))).scalars()]
    retry = await client.post(endpoint, headers=auth(), json={"merchant_ids": ids[:2], "industry": "餐饮"})
    assert retry.status_code == 200 and retry.json()["updated_count"] == 0
    async with maker() as session:
        after = [(row.id, row.updated_at, row.raw_payload, row.pool_status) for row in
                 (await session.execute(select(MerchantPool).order_by(MerchantPool.id))).scalars()]
        assert before == after and (await session.get(MerchantPool, ids[2])).industry is None
        assert (await session.execute(select(SalesLeads))).scalars().all() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("final_state", [{"pool_status": "converted"}, {"pool_status": "archived"}, {"converted_lead_id": 999}])
async def test_final_records_reject_single_or_bulk_reclassification(industry_client, final_state):
    client, maker = industry_client
    ids = await seed(maker, [{"industry": None}, {"industry": "餐饮", **final_state}])
    response = await client.post("/api/v1/merchant-pool/bulk-update-industry", headers=auth(), json={"merchant_ids": ids, "industry": "美业"})
    assert response.status_code == 409, response.text
    single = await client.put(f"/api/v1/merchant-pool/{ids[1]}", headers=auth(), json={"industry": "美业"})
    assert single.status_code == 409
    async with maker() as session:
        assert (await session.get(MerchantPool, ids[0])).industry is None
        final = await session.get(MerchantPool, ids[1])
        assert final.industry == "餐饮" and final.converted_lead_id == final_state.get("converted_lead_id")


@pytest.mark.asyncio
async def test_lead_conversion_copies_normalized_industry_without_rewriting_pool_history(industry_client):
    client, maker = industry_client
    ids = await seed(maker, [{"industry": "美甲"}])
    response = await client.post(f"/api/v1/merchant-pool/{ids[0]}/convert-to-lead", headers=auth(), json={})
    assert response.status_code == 200, response.text
    async with maker() as session:
        lead = await session.get(SalesLeads, response.json()["lead_id"])
        assert lead.industry == "美业"
        merchant = await session.get(MerchantPool, ids[0])
        assert merchant.industry == "美甲" and merchant.pool_status == "converted"
