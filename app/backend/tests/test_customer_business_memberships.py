from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from models.customer_access_grants import CustomerAccessGrant
from models.customers import Customers
from models.deals import Deals
from models.subscriptions import Subscriptions
from models.management_decisions import BusinessLine, CustomerEngagement, ProductCatalog
from test_customer_invitation_business_boundaries import auth, invitation_api


@pytest.mark.asyncio
async def test_business_filters_require_visible_evidence_and_deduplicate_before_paging(invitation_api):
    client, db = invitation_api
    path = "/api/v1/entities/customers/business-memberships"
    for ident, code in ((31, "restaurant_os"), (32, "beauty_os")):
        db.add(BusinessLine(id=ident, code=code, name=code))
        db.add(ProductCatalog(id=ident, business_line_id=ident, code=code, name=code, billing_kind="recurring"))
    def project(customer, line, tag, status, **kwargs):
        return CustomerEngagement(customer_id=customer, business_line_id=line, product_id=line,
                                  engagement_code=tag, status=status, **kwargs)
    db.add_all([
        project(101, 31, "setup", "pending_setup"),
        project(101, 31, "trial", "trial"),
        project(101, 32, "never_started", "stopped"),
        project(102, 32, "worked_then_stopped", "stopped", trial_started_at=datetime.now(timezone.utc)),
        Deals(customer_id=102, product_type="ordering_system", deal_amount=0),
        Deals(customer_id=101, product_type="social_media", deal_amount=0),
    ])
    await db.commit()

    async def read(business, headers, **params):
        response = await client.get(path, params={"business": business, **params}, headers=headers)
        assert response.status_code == 200, response.text
        return response.json()

    owner = auth("super_admin", 1)
    first = await read("restaurant_os", owner, limit=1)
    assert first["items"] == [{"customer_id": 101, "business_lines": ["restaurant_os", "managed_service"]}]
    assert first["next_after_id"] == 101
    second = await read("restaurant_os", owner, after_id=first["next_after_id"], limit=1)
    assert second == {"items": [{"customer_id": 102, "business_lines": ["restaurant_os", "beauty_os", "managed_service"]}], "next_after_id": None}
    assert [item["customer_id"] for item in (await read("beauty_os", owner))["items"]] == [102]
    assert len((await read("multiple", owner))["items"]) == 2

    grant = await db.scalar(select(CustomerAccessGrant).where(CustomerAccessGrant.employee_id == 20))
    for modules, restaurant, managed, multi in [
        ({"basic": "read_only"}, [], [], []),
        ({"delivery": "read_only"}, [101], [], []),
        ({"deals": "read_only"}, [], [101], []),
        ({"deals": "read_only", "delivery": "read_only"}, [101], [101], [101]),
    ]:
        grant.scopes = modules
        await db.commit()
        for business, expected in (("restaurant_os", restaurant), ("managed_service", managed), ("multiple", multi)):
            rows = (await read(business, auth()))["items"]
            assert [item["customer_id"] for item in rows] == expected
    grant.invitation_status = "revoked"
    await db.commit()
    assert (await read("multiple", auth()))["items"] == []


@pytest.mark.asyncio
async def test_standalone_subscriptions_require_renewal_scope_and_evidence(invitation_api):
    client, db = invitation_api
    path = "/api/v1/entities/customers/business-memberships"
    for ident, code in ((31, "restaurant_os"), (32, "beauty_os"), (33, "managed_service")):
        db.add(BusinessLine(id=ident, code=code, name=code))
    db.add(Customers(id=103, business_name="Subscription only", contact_name="Contact", phone="555"))
    def subscription(customer, line, status, last_payment=None):
        return Subscriptions(customer_id=customer, business_line_id=line, package_name="Plan",
                             package_price=1, status=status, last_payment_date=last_payment)
    now = datetime.now(timezone.utc)
    db.add_all([
        subscription(103, 32, "active"), subscription(103, 32, "renewed"),
        subscription(103, 31, "stopped", now - timedelta(days=15)),
        subscription(103, 33, "pending"), subscription(103, 33, "stopped", now + timedelta(days=20)),
        subscription(101, 33, "active"),  # Existing deal for this same business.
        subscription(101, 32, "renewal_pending"),
    ])
    await db.commit()

    async def rows(business, headers):
        result = await client.get(path, headers=headers, params={"business": business})
        assert result.status_code == 200, result.text
        return {row["customer_id"]: row["business_lines"] for row in result.json()["items"]}

    owner = auth("super_admin", 1)
    assert (await rows("beauty_os", owner))[103] == ["restaurant_os", "beauty_os"]
    assert 103 in await rows("multiple", owner)
    assert 103 not in await rows("managed_service", owner)
    assert (await rows("multiple", owner))[101] == ["beauty_os", "managed_service"]

    grant = await db.scalar(select(CustomerAccessGrant).where(CustomerAccessGrant.employee_id == 20))
    for module in ("basic", "delivery", "deals"):
        grant.scopes = {module: "read_only"}
        await db.commit()
        assert await rows("beauty_os", auth()) == {}
    grant.scopes = {"renewals": "read_only"}
    await db.commit()
    assert await rows("beauty_os", auth()) == {101: ["beauty_os", "managed_service"]}
    grant.invitation_status = "revoked"
    await db.commit()
    assert await rows("beauty_os", auth()) == {}
