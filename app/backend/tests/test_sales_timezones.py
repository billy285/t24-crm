"""Address-derived calling zones must match SQL filtering without changing proof."""

import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, literal, select

from backend.tests.test_merchant_industries import auth, industry_client
from models.merchant_pool import MerchantPool
from models.sales_intelligence import SalesLeadProfiles
from models.sales_leads import SalesLeads
from services.sales_timezones import resolve_contact_timezone, sql_contact_timezone


CASES = [
    ({"country": "US", "state": "CA", "city": "Los Angeles"}, "America/Los_Angeles", "pacific"),
    ({"country": "USA", "state": "Washington", "city": "Seattle"}, "America/Los_Angeles", "pacific"),
    ({"country": "美国", "state": "OR", "city": "Beaverton"}, "America/Los_Angeles", "pacific"),
    ({"country": "US", "state": "OR", "city": "Ontario"}, "America/Boise", "mountain"),
    ({"country": "US", "state": "OR", "city": "Unreviewed City"}, None, "unknown"),
    ({"country": "US", "state": "NV", "city": "Las Vegas"}, "America/Los_Angeles", "pacific"),
    ({"country": "US", "state": "NV", "city": "West Wendover"}, "America/Denver", "mountain"),
    ({"country": "US", "state": "NV", "city": "Unreviewed City"}, None, "unknown"),
    ({"country": "US", "state": "Idaho", "city": "Boise"}, "America/Boise", "mountain"),
    ({"country": "US", "state": "ID", "city": "Coeur d'Alene"}, "America/Los_Angeles", "pacific"),
    ({"country": "US", "state": "Arizona", "city": "Mesa"}, "America/Phoenix", "mountain"),
    ({"country": "US", "state": "AZ", "city": "Window Rock"}, None, "unknown"),
    ({"country": "US", "state": "AZ", "city": "Phoenix", "address": "Navajo Nation Reservation"}, None, "unknown"),
    ({"country": "US", "state": "AZ", "city": "Phoenix", "address": "1 Navajo Way"}, "America/Phoenix", "mountain"),
    ({"country": "US", "state": "AZ", "city": "Chinle", "profile_timezone": "America/Denver"}, "America/Denver", "mountain"),
    ({"country": "US", "state": "UT", "city": "South Salt Lake"}, "America/Denver", "mountain"),
    ({"country": "US", "state": "CO", "city": "Denver"}, "America/Denver", "mountain"),
    ({"country": "US", "state": "HI", "city": "Honolulu"}, "Pacific/Honolulu", "hawaii"),
    ({"country": "US", "state": "AK", "city": "Anchorage"}, "America/Anchorage", "alaska"),
    ({"country": "US", "state": "AK", "city": "Adak"}, "America/Adak", "alaska"),
    ({"country": "US", "state": "AK", "city": "Unknown village"}, None, "unknown"),
    ({"country": "US", "state": "IL", "city": "Chicago"}, "America/Chicago", "central"),
    ({"country": "US", "state": "NY", "city": "New York"}, "America/New_York", "eastern"),
    ({"country": "US", "state": "TX", "city": "Houston"}, "America/Chicago", "central"),
    ({"country": "US", "state": "TX", "city": "El Paso"}, "America/Denver", "mountain"),
    ({"country": "US", "state": "FL", "city": "Pensacola"}, "America/Chicago", "central"),
    ({"country": "US", "state": "IN", "city": "Indianapolis"}, "America/Indiana/Indianapolis", "eastern"),
    ({"country": "US", "state": "CA", "city": "LA", "profile_timezone": " America/New_York "}, "America/New_York", "eastern"),
    ({"country": "CA", "state": "CA", "city": "Los Angeles"}, None, "unknown"),
    ({"country": "CN", "state": "WA", "city": "Seattle"}, None, "unknown"),
    ({"country": None, "state": "CA", "city": "Los Angeles"}, None, "unknown"),
    ({"country": "Canada", "state": "ON", "city": "Toronto", "profile_timezone": "America/Toronto"}, "America/Toronto", "unknown"),
    ({"country": "US", "state": "CA", "city": "LA", "profile_timezone": "Not/A_Zone"}, "America/Los_Angeles", "pacific"),
    ({"country": " U.S.A. ", "state": " california ", "city": "LA"}, "America/Los_Angeles", "pacific"),
    ({"country": "\tUS\n", "state": "\u00a0Arizona\u00a0", "city": "\tMesa\n"}, "America/Phoenix", "mountain"),
    ({"country": "US", "state": "CA", "city": "LA", "profile_timezone": "\tAmerica/New_York\n"}, "America/New_York", "eastern"),
]


@pytest.mark.parametrize("values,expected_zone,expected_group", CASES)
def test_python_and_sql_resolve_same_reviewed_address(values, expected_zone, expected_group):
    expected = resolve_contact_timezone(**values)
    assert expected["timezone"] == expected_zone
    assert expected["timezone_group"] == expected_group
    fields = {name: literal(values.get(name)) for name in ("country", "state", "city", "address")}
    expressions = sql_contact_timezone(fields, literal(json.dumps({"timezone": values.get("profile_timezone")})))
    engine = create_engine("sqlite://")
    with engine.connect() as connection:
        actual = dict(connection.execute(select(*(value.label(key) for key, value in expressions.items()))).mappings().one())
    engine.dispose()
    assert actual == expected
    assert actual["timezone_needs_confirmation"] == (actual["timezone_basis"] != "confirmed_profile")


@pytest.mark.parametrize("payload", [None, "not-json", "[]", '{"timezone":123}', '{"timezone":false}'])
def test_malformed_legacy_profile_cannot_break_sql_or_override_address(payload):
    expressions = sql_contact_timezone({"country": literal("US"), "state": literal("CA"), "city": literal("LA"), "address": literal(None)}, literal(payload))
    engine = create_engine("sqlite://")
    with engine.connect() as connection:
        actual = dict(connection.execute(select(*(value.label(key) for key, value in expressions.items()))).mappings().one())
    engine.dispose()
    assert actual == resolve_contact_timezone(country="US", state="CA", city="LA")


def test_arizona_and_hawaii_keep_iana_dst_rules():
    summer = datetime(2026, 7, 1, 12, tzinfo=timezone.utc)
    winter = datetime(2026, 12, 1, 12, tzinfo=timezone.utc)
    phoenix = resolve_contact_timezone(country="US", state="AZ", city="Mesa")["timezone"]
    denver = resolve_contact_timezone(country="US", state="CO", city="Denver")["timezone"]
    hawaii = resolve_contact_timezone(country="US", state="HI", city="Honolulu")["timezone"]
    assert summer.astimezone(ZoneInfo(phoenix)).hour == 5
    assert summer.astimezone(ZoneInfo(denver)).hour == 6
    assert winter.astimezone(ZoneInfo(phoenix)).hour == winter.astimezone(ZoneInfo(denver)).hour == 5
    assert summer.astimezone(ZoneInfo(hawaii)).hour == winter.astimezone(ZoneInfo(hawaii)).hour == 2


@pytest.mark.asyncio
async def test_timezone_filter_is_scoped_and_applied_before_counts_facets_and_pages(industry_client):
    client, maker = industry_client
    async with maker() as db:
        for number, (state, city, industry, creator) in enumerate([
            ("CA", "Los Angeles", "美业", 10), ("CA", "San Diego", "餐厅", 10),
            ("AZ", "Mesa", "美业", 10), ("NY", "New York", "美业", 10),
            ("CA", "San Francisco", "美业", 20),
        ]):
            db.add(MerchantPool(business_name=f"Synthetic zone {number}", phone=f"+12125550{number:03d}",
                country="US", state=state, city=city, industry=industry, data_source="zone-test", created_by_id=creator,
                raw_payload='{"timezone":"Asia/Shanghai","source":"unchanged"}'))
        await db.commit()
    params = {"timezone_group": "pacific", "limit": 1, "industry": "美业"}
    response = await client.get("/api/v1/merchant-pool", headers=auth(), params=params)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1 and body["facet_total"] == 2
    assert {row["value"]: row["count"] for row in body["industry_facets"]} == {"餐厅": 1, "美业": 1}
    assert body["items"][0]["timezone"] == "America/Los_Angeles"
    assert body["items"][0]["timezone_basis"] == "address_state"
    assert body["items"][0]["timezone_needs_confirmation"] is True
    pages = []
    for skip in (0, 1):
        page = await client.get("/api/v1/merchant-pool", headers=auth(), params={"timezone_group": "pacific", "limit": 1, "skip": skip})
        assert page.json()["total"] == 2
        pages.extend(row["id"] for row in page.json()["items"])
    assert len(set(pages)) == 2
    invalid = await client.get("/api/v1/merchant-pool", headers=auth(), params={"timezone_group": "west"})
    assert invalid.status_code == 422
    denied = await client.get("/api/v1/merchant-pool", headers=auth("sales", 11), params={"timezone_group": "pacific"})
    assert denied.status_code == 403
    async with maker() as db:
        rows = (await db.scalars(select(MerchantPool))).all()
        assert {row.raw_payload for row in rows} == {'{"timezone":"Asia/Shanghai","source":"unchanged"}'}


@pytest.mark.asyncio
async def test_converted_current_address_and_manual_override_match_lead_contact_context(industry_client):
    client, maker = industry_client
    original_payload = '{"timezone":"America/Chicago","country":"US","state":"CO"}'
    profile_payload = '{"timezone":"America/New_York","evidence":"manual confirmed","custom_fields":{}}'
    async with maker() as db:
        merchant = MerchantPool(business_name="Synthetic moved merchant", phone="+16465550101", country="US", state="CO", city="Denver",
            industry="美业", data_source="zone-test", created_by_id=10, pool_status="converted", raw_payload=original_payload)
        db.add(merchant)
        await db.flush()
        lead = SalesLeads(business_name="Synthetic current Mesa", phone=merchant.phone, country="US", state="AZ", city="Mesa",
            address="1 Main St", merchant_pool_id=merchant.id, team_manager_id=10, assigned_sales_id=11, industry="美业")
        db.add(lead)
        await db.flush()
        merchant.converted_lead_id = lead.id
        await db.commit()
        merchant_id, lead_id = merchant.id, lead.id
    result = await client.get("/api/v1/merchant-pool", headers=auth(), params={"timezone_group": "mountain"})
    assert result.status_code == 200, result.text
    item = result.json()["items"][0]
    assert item["id"] == merchant_id and item["state"] == "AZ" and item["timezone"] == "America/Phoenix"
    insight = await client.get(f"/api/v1/sales-intelligence/leads/{lead_id}", headers=auth())
    assert insight.status_code == 200, insight.text
    assert insight.json()["contact_timezone"]["timezone"] == "America/Phoenix"
    assert insight.json()["profile"] == {}
    async with maker() as db:
        db.add(SalesLeadProfiles(lead_id=lead_id, revision=1, payload_json=profile_payload))
        await db.commit()
    result = await client.get("/api/v1/merchant-pool", headers=auth(), params={"timezone_group": "eastern"})
    assert result.status_code == 200, result.text
    item = result.json()["items"][0]
    assert item["state"] == "AZ" and item["timezone"] == "America/New_York"
    assert item["timezone_basis"] == "confirmed_profile" and item["timezone_needs_confirmation"] is False
    assert (await client.get("/api/v1/merchant-pool", headers=auth(), params={"timezone_group": "mountain"})).json()["total"] == 0
    insight = (await client.get(f"/api/v1/sales-intelligence/leads/{lead_id}", headers=auth())).json()
    assert insight["contact_timezone"] == {key: item[key] for key in ("timezone", "timezone_group", "timezone_basis", "timezone_needs_confirmation")}
    assert insight["profile"]["timezone"] == "America/New_York"
    async with maker() as db:
        assert (await db.get(MerchantPool, merchant_id)).raw_payload == original_payload
        assert (await db.get(SalesLeadProfiles, lead_id)).payload_json == profile_payload


@pytest.mark.asyncio
async def test_former_manager_cannot_filter_on_current_private_lead_timezone(industry_client):
    client, maker = industry_client
    async with maker() as db:
        merchant = MerchantPool(business_name="Synthetic original", phone="+12125550105", country="US", state="CA", city="Los Angeles",
            industry="美业", data_source="zone-test", created_by_id=10, pool_status="converted")
        db.add(merchant)
        await db.flush()
        lead = SalesLeads(business_name="Private current", phone=merchant.phone, country="US", state="NY", city="New York",
            merchant_pool_id=merchant.id, team_manager_id=20, assigned_sales_id=21)
        db.add(lead)
        await db.flush()
        merchant.converted_lead_id = lead.id
        db.add(SalesLeadProfiles(lead_id=lead.id, payload_json='{"timezone":"Pacific/Honolulu"}'))
        await db.commit()
    for group in ("eastern", "hawaii"):
        response = await client.get("/api/v1/merchant-pool", headers=auth(), params={"timezone_group": group})
        assert response.status_code == 200 and response.json()["total"] == 0
    own_original = await client.get("/api/v1/merchant-pool", headers=auth(), params={"timezone_group": "pacific"})
    assert own_original.status_code == 200 and own_original.json()["total"] == 1
    assert own_original.json()["items"][0]["business_name"] == "Synthetic original"
    admin = await client.get("/api/v1/merchant-pool", headers=auth("admin", 1), params={"timezone_group": "hawaii"})
    assert admin.status_code == 200 and admin.json()["total"] == 1
