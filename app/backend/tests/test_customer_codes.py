import asyncio
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select, text

from backend.tests.test_sales_catalog_handoffs import headers, registered, sale_api
from models.customers import Customers


PREFIX = "/api/v1/entities/customers"


def merchant(name, **fields):
    return {"business_name": name, "contact_name": "", "phone": "+12125550123", **fields}


@pytest.mark.asyncio
async def test_global_allocation_across_hidden_customers_threads_and_handoffs(sale_api):
    client, sessions = sale_api
    async with sessions() as db:
        await db.execute(text("CREATE TABLE app_settings (config_key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TIMESTAMP)"))
        settings = {"useIndustryPrefix": True, "includeYear": False, "defaultPrefix": "BUS",
                    "industryPrefixes": [{"industry": "beauty", "prefix": "BE"}], "separator": "-", "digitCount": 3}
        roles = {"ops": {"pages": ["/customers"], "buttons": ["customer_create"]}}
        await db.execute(text("INSERT INTO app_settings(config_key,value_json) VALUES (:key,:config)"),
                         [{"key": "customer_code_settings", "config": json.dumps(settings)},
                          {"key": "role_permissions", "config": json.dumps(roles)}])
        # Duplicate legacy rows stay intact. New allocations start after the global high watermark.
        db.add_all([Customers(**merchant("Old one", customer_code="BE--009")),
                    Customers(**merchant("Old two", customer_code="BE--009")),
                    Customers(**merchant("Old padded", customer_code=" BE--019 "))])
        await db.commit()

    forbidden = await client.post(PREFIX, headers=headers(11), json=merchant("Denied"))
    assert forbidden.status_code == 403
    requests = [
        client.post(PREFIX, headers=headers(employee), json=merchant(f"Operator {employee}", industry="beauty"))
        for employee in (13, 14)
    ]
    requests.append(client.post(PREFIX + "/with-projects", headers=headers(1),
                                json={"customer": merchant("Owner", industry="beauty")}))
    results = await asyncio.gather(*requests)
    assert [r.status_code for r in results] == [201, 201, 201], [r.text for r in results]
    async with sessions() as db:
        customers = (await db.scalars(select(Customers).order_by(Customers.id))).all()
        assert sorted(c.customer_code for c in customers) == [" BE--019 ", "BE--009", "BE--009", "BE--020", "BE--021", "BE--022"]
        assert {c.business_name: c.sales_employee_id for c in customers if c.business_name.startswith("Operator")} == {
            "Operator 13": 13, "Operator 14": 14}
    saved = await client.post(PREFIX, headers=headers(1), json=merchant("Manual", customer_code=" CLIENT-X "))
    assert saved.status_code == 201, saved.text
    assert saved.json()["customer_code"] == "CLIENT-X"
    duplicate = await client.post(PREFIX, headers=headers(14), json=merchant("Hidden conflict", customer_code="CLIENT-X"))
    assert duplicate.status_code == 409 and "Manual" not in duplicate.text
    existing_update = await client.put(PREFIX + "/1", headers=headers(1), json={"customer_code": "BE--009", "city": "Denver"})
    assert existing_update.status_code == 200, existing_update.text
    rename = await client.put(f"{PREFIX}/{saved.json()['id']}", headers=headers(1), json={"customer_code": "BE--009"})
    assert rename.status_code == 409

    handoff = await registered(client)
    async with sessions() as db:
        assert (await db.get(Customers, handoff["customer_id"])).customer_code == "BUS--001"


@pytest.mark.asyncio
async def test_batch_uses_default_format_and_rolls_back_if_manual_code_conflicts(sale_api):
    client, _ = sale_api
    url = PREFIX + "/batch"
    year = datetime.now(ZoneInfo("Asia/Shanghai")).year
    result = await client.post(url, headers=headers(1), json={"items": [merchant("A"), merchant("B")]})
    assert result.status_code == 201, result.text
    assert [c["customer_code"] for c in result.json()] == [f"C{year}0001", f"C{year}0002"]
    failed = await client.post(url, headers=headers(1), json={
        "items": [merchant("Rollback"), merchant("Conflict", customer_code=f"C{year}0001")]})
    assert failed.status_code == 409
    next_row = await client.post(PREFIX, headers=headers(1), json=merchant("After rollback"))
    assert next_row.status_code == 201 and next_row.json()["customer_code"] == f"C{year}0003"


@pytest.mark.asyncio
async def test_owner_first_intake_persists_optional_contact_and_only_explicit_projects(sale_api):
    from models.commissions import CommissionEntry
    from models.management_decisions import BusinessLine, ClassificationReviewDecision, CustomerEngagement
    from models.payments import Payments
    from sqlalchemy import func

    client, sessions = sale_api
    async with sessions() as db:
        db.add(BusinessLine(id=2, code="beauty_os", name="美业 OS", is_recurring=True, is_active=True))
        await db.commit()

    for index, projects in enumerate([[], [{"business_line_code": "beauty_os", "status": "pending_setup"}]]):
        customer = merchant(f"Store {index}", customer_code=None, source=None)
        response = await client.post(PREFIX + "/with-projects", headers=headers(1),
                                     json={"customer": customer, "projects": projects})
        assert response.status_code == 201, response.text
        row = response.json()
        assert row["contact_name"] == "" and row["customer_code"]
        async with sessions() as db:
            stored = await db.get(Customers, row["id"])
            assert stored.contact_name == "" and stored.source is None and stored.customer_code == row["customer_code"]
            assert await db.scalar(select(func.count()).select_from(Customers)) == index + 1
            assert await db.scalar(select(func.count()).select_from(CustomerEngagement)) == index
            assert await db.scalar(select(func.count()).select_from(Payments)) == 0
            assert await db.scalar(select(func.count()).select_from(CommissionEntry)) == 0
            if projects:
                project = await db.scalar(select(CustomerEngagement).where(CustomerEngagement.customer_id == row["id"]))
                assert project.business_line_id == 2 and project.status == "pending_setup" and project.paid_started_at is None
                review = await db.scalar(select(ClassificationReviewDecision).where(ClassificationReviewDecision.customer_id == row["id"]))
                assert review.decision == "confirmed"
        report = await client.get("/api/v1/management-decisions/classification-review", headers=headers(1))
        assert report.status_code == 200 and report.json()["summary"]["project_count"] == index
