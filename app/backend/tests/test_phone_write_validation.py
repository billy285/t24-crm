import json
import pytest
import pytest_asyncio
from sqlalchemy import func, select, text

from models.customer_contacts import Customer_contacts
from models.customers import Customers
from models.employees import Employees
from test_customer_interaction_permissions import interaction_api, _headers

ADMIN = _headers("admin", 1, "Admin")
SALES = _headers("sales", 11, "Sales One")
OPS = _headers("ops", 21, "Ops One")


@pytest_asyncio.fixture
async def phone_api(interaction_api):
    client, db = interaction_api
    permissions = json.loads(await db.scalar(text("SELECT value_json FROM app_settings WHERE config_key='role_permissions'")))
    permissions["admin"]["buttons"].append("customer_create")
    await db.execute(text("UPDATE app_settings SET value_json=:value WHERE config_key='role_permissions'"), {"value": json.dumps(permissions)})
    await db.commit()
    yield client, db


@pytest.mark.asyncio
async def test_customer_phone_write_validation_preserves_raw_and_unchanged_history(phone_api):
    client, db = phone_api
    missing_country = await client.post("/api/v1/entities/customers", headers=ADMIN, json={"business_name": "New", "contact_name": "Owner", "phone": "2025550123"})
    assert missing_country.status_code == 400
    assert "国家" in missing_country.json()["detail"]
    original = await client.put("/api/v1/entities/customers/101", headers=ADMIN, json={"phone": "101", "notes": "Unchanged legacy phone"})
    assert original.status_code == 200
    assert original.json()["phone"] == "101"
    invalid_change = await client.put("/api/v1/entities/customers/101", headers=ADMIN, json={"phone": "2025550123 / 2125550123", "country": "US"})
    assert invalid_change.status_code == 400
    assert (await db.get(Customers, 101)).phone == "101"
    changed = await client.put("/api/v1/entities/customers/101", headers=ADMIN, json={"phone": " 202-555-0123 ext 009 ", "country": "US"})
    assert changed.status_code == 200
    assert changed.json()["phone"] == " 202-555-0123 ext 009 "
    forbidden = await client.put("/api/v1/entities/customers/103", headers=OPS, json={"phone": "+12025550123"})
    assert forbidden.status_code == 404, forbidden.text


@pytest.mark.asyncio
async def test_batch_customer_phone_errors_preflight_before_any_write(phone_api):
    client, db = phone_api
    before = await db.scalar(select(func.count()).select_from(Customers))
    response = await client.post("/api/v1/entities/customers/batch", headers=ADMIN, json={"items": [
        {"business_name": "Valid", "contact_name": "Owner", "phone": "+12025550123"},
        {"business_name": "Invalid", "contact_name": "Owner", "phone": "2025550123"},
    ]})
    assert response.status_code == 400
    assert await db.scalar(select(func.count()).select_from(Customers)) == before
    response = await client.put("/api/v1/entities/customers/batch", headers=ADMIN, json={"items": [
        {"id": 101, "updates": {"notes": "Should not save"}},
        {"id": 102, "updates": {"phone": "multiple +12025550123 +12125550123"}},
    ]})
    assert response.status_code == 400
    assert (await db.get(Customers, 101)).notes is None


@pytest.mark.asyncio
async def test_contact_country_comes_from_authorized_customer_and_batch_is_preflighted(phone_api):
    client, db = phone_api
    customer = await db.get(Customers, 104)
    customer.country = "US"
    legacy = await db.get(Customer_contacts, 401)
    legacy.contact_phone = "old phone"
    await db.commit()
    saved = await client.post("/api/v1/entities/customer_contacts", headers=OPS, json={"customer_id": 104, "contact_name": "Manager", "contact_phone": "2025550123 ext 9"})
    assert saved.status_code == 201, saved.text
    assert saved.json()["contact_phone"] == "2025550123 ext 9"
    unchanged = await client.put("/api/v1/entities/customer_contacts/401", headers=OPS, json={"contact_phone": "old phone", "notes": "Still editable"})
    assert unchanged.status_code == 200
    before = await db.scalar(select(func.count()).select_from(Customer_contacts))
    invalid = await client.post("/api/v1/entities/customer_contacts/batch", headers=OPS, json={"items": [
        {"customer_id": 104, "contact_name": "Valid", "contact_phone": "2025550123"},
        {"customer_id": 104, "contact_name": "Invalid", "contact_phone": "123"},
    ]})
    assert invalid.status_code == 400
    assert await db.scalar(select(func.count()).select_from(Customer_contacts)) == before
    forbidden = await client.post("/api/v1/entities/customer_contacts", headers=OPS, json={"customer_id": 103, "contact_name": "Hidden", "contact_phone": "+12025550123"})
    assert forbidden.status_code == 404, forbidden.text


@pytest.mark.asyncio
async def test_employee_no_country_is_not_guessed_and_history_is_preserved(phone_api):
    client, db = phone_api
    legacy = await db.get(Employees, 11)
    legacy.phone = "old phone"
    await db.commit()
    unchanged = await client.put("/api/v1/entities/employees/11", headers=ADMIN, json={"phone": "old phone", "notes": "Still editable"})
    assert unchanged.status_code == 200
    invalid = await client.put("/api/v1/entities/employees/11", headers=ADMIN, json={"phone": "2025550123"})
    assert invalid.status_code == 400
    assert "国家" in invalid.json()["detail"]
    assert (await db.get(Employees, 11)).phone == "old phone"
    valid = await client.put("/api/v1/entities/employees/11", headers=ADMIN, json={"phone": "+44 20 7946 0018"})
    assert valid.status_code == 200
    assert valid.json()["phone"] == "+44 20 7946 0018"
