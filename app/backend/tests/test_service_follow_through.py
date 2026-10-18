"""Real isolated API: renewal/operational evidence cannot mutate the ledger."""
import json
import time
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import func, select

from backend.tests.test_sales_catalog_handoffs import PREFIX, grant, headers, registered, sale_api
from backend.tests.test_sales_deal_payments import SECRET, deliver, event, sale_with_link
from core.database import Base
from models.customer_access_grants import CustomerAccessGrant
from models.employees import Employees
from models.sales_deal_handoffs import SalesDealHandoff
from models.sales_deal_payments import SalesPaymentRequest, SalesStripeObservation
from models.service_follow_through import ServiceKickoff, ServiceKickoffAudit, ServiceRenewalEvent, ServiceRenewalSignal
from models.subscriptions import Subscriptions
from services import service_follow_through as service

API = "/api/v1/service-follow-through"
NEW_TABLES = {"service_kickoffs", "service_kickoff_audits", "service_renewal_signals", "service_renewal_events"}


async def old_snapshot(sessions):
    async with sessions() as db:
        # Every existing business row, including all financial/perms/commission
        # tables, must remain exactly equal after the new feature's mutations.
        result = {}
        for table in Base.metadata.sorted_tables:
            if table.name not in NEW_TABLES:
                rows = (await db.execute(select(table))).all()
                result[table.name] = sorted(json.dumps(dict(row._mapping), sort_keys=True, default=str) for row in rows)
        return result


async def linked(client, sessions, monkeypatch):
    monkeypatch.setenv("T24_SALES_STRIPE_WEBHOOK_SECRET", SECRET)
    handoff, request = await sale_with_link(client, sessions)
    assert (await deliver(client, event(request))).status_code == 200
    return handoff, request


def lifecycle(kind="invoice.payment_failed", *, identity="in_renewal001", sub="sub_synthetic001", at=None, event_id=None, **changes):
    at = int(time.time()) if at is None else at
    invoice = kind.startswith("invoice.")
    obj = {"id": identity if invoice else sub, "object": "invoice" if invoice else "subscription", "livemode": True,
        **({"subscription": sub, "amount_due": 21533, "amount_paid": 21533 if kind == "invoice.paid" else 0,
            "paid": kind == "invoice.paid", "status": "paid" if kind == "invoice.paid" else "open", "currency": "usd"} if invoice else
            {"status": "canceled" if kind.endswith("deleted") else "active", "cancel_at_period_end": False, "current_period_end": at + 86400 * 30}),
        "customer_email": "NEVER-PERSIST@example.com", **changes}
    return {"id": event_id or "evt_" + identity + kind.replace(".", ""), "type": kind,
        "livemode": True, "created": at, "data": {"object": obj}}


@pytest.mark.asyncio
async def test_renewal_dedup_terminal_paid_independent_invoices_no_old_business_writes(sale_api, monkeypatch):
    client, sessions = sale_api
    handoff, _ = await linked(client, sessions, monkeypatch)
    before = await old_snapshot(sessions)
    failed = lifecycle()
    assert (await deliver(client, failed)).status_code == 200
    assert (await deliver(client, failed)).status_code == 200
    paid = lifecycle("invoice.paid", at=failed["created"] - 30)
    assert (await deliver(client, paid)).status_code == 200
    assert (await deliver(client, lifecycle(at=failed["created"] + 30, event_id="evt_lateFailed"))).status_code == 200
    # Another invoice remains independently outstanding; the newer paid invoice
    # must not turn the entire customer green.
    assert (await deliver(client, lifecycle(identity="in_separate", event_id="evt_otherFailed"))).status_code == 200
    overview = await client.get(API + "/renewals", headers=headers(1))
    assert overview.status_code == 200, overview.text
    row = overview.json()["items"][0]
    assert row["handoff_id"] == handoff["id"] and row["status"] == "payment_failed"
    assert {item["status"] for item in row["signals"]} == {"payment_observed", "payment_failed"}
    assert overview.json()["counts"]["attention"] == 1
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(ServiceRenewalEvent)) == 4
        assert await db.scalar(select(func.count()).select_from(ServiceRenewalSignal)) == 2
        assert "NEVER-PERSIST" not in str((await db.execute(select(ServiceRenewalSignal))).all())
    assert await old_snapshot(sessions) == before
    altered = json.loads(json.dumps(failed))
    altered["data"]["object"]["amount_due"] = 1
    assert (await deliver(client, altered)).status_code == 409


@pytest.mark.asyncio
async def test_cancel_restore_and_deleted_terminal_observation_only(sale_api, monkeypatch):
    client, sessions = sale_api
    await linked(client, sessions, monkeypatch)
    before = await old_snapshot(sessions)
    at = int(time.time())
    for payload in (
        lifecycle("customer.subscription.updated", at=at, event_id="evt_schedule", cancel_at_period_end=True),
        lifecycle("customer.subscription.updated", at=at + 1, event_id="evt_restore", cancel_at_period_end=False),
    ):
        assert (await deliver(client, payload)).status_code == 200
    response = await client.get(API + "/renewals", headers=headers(1))
    assert response.json()["items"][0]["status"] == "watching"
    assert (await deliver(client, lifecycle("customer.subscription.updated", at=at - 10, event_id="evt_oldSchedule", cancel_at_period_end=True))).status_code == 200
    assert (await client.get(API + "/renewals", headers=headers(1))).json()["items"][0]["status"] == "watching"
    assert (await deliver(client, lifecycle("customer.subscription.deleted", at=at + 2, event_id="evt_deleted"))).status_code == 200
    assert (await deliver(client, lifecycle("customer.subscription.updated", at=at + 3, event_id="evt_noResurrect"))).status_code == 200
    assert (await client.get(API + "/renewals", headers=headers(1))).json()["items"][0]["status"] == "cancelled"
    assert await old_snapshot(sessions) == before


@pytest.mark.parametrize("case", ["unknown", "test", "account", "conflicting", "currency", "no_relation", "invalid_type", "invalid_state"])
@pytest.mark.asyncio
async def test_invalid_or_unrelated_lifecycle_ignored_without_storage(sale_api, monkeypatch, case):
    client, sessions = sale_api
    await linked(client, sessions, monkeypatch)
    payload = lifecycle()
    obj = payload["data"]["object"]
    if case == "unknown": obj["subscription"] = "sub_unrelated"
    if case == "test": obj["livemode"] = False
    if case == "account": payload["account"] = "acct_unrelated"
    if case == "conflicting": obj["parent"] = {"subscription_details": {"subscription": "sub_other"}}
    if case == "currency": obj["currency"] = "cny"
    if case == "no_relation": obj.pop("subscription")
    if case == "invalid_type": payload["type"] = "invoice.created"
    if case == "invalid_state": obj.update(paid=True, status="paid")
    assert (await deliver(client, payload)).status_code == 200
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(ServiceRenewalEvent)) == 0
        assert await db.scalar(select(func.count()).select_from(ServiceRenewalSignal)) == 0


@pytest.mark.asyncio
async def test_modern_invoice_parent_link_and_ambiguous_checkout_subscription_fail_closed(sale_api, monkeypatch):
    client, sessions = sale_api
    handoff, _ = await linked(client, sessions, monkeypatch)
    payload = lifecycle("invoice.payment_action_required")
    payload["data"]["object"].pop("subscription")
    payload["data"]["object"]["parent"] = {"type": "subscription_details", "subscription_details": {"subscription": "sub_synthetic001"}}
    assert (await deliver(client, payload)).status_code == 200
    assert (await client.get(API + "/renewals", headers=headers(1))).json()["items"][0]["status"] == "action_required"
    async with sessions() as db:
        row = await db.get(SalesDealHandoff, handoff["id"])
        duplicate = SalesDealHandoff(**{col.name: getattr(row, col.name) for col in SalesDealHandoff.__table__.columns if col.name != "id"})
        duplicate.lead_id, duplicate.deal_id, duplicate.idempotency_key = 999, 999, "synthetic-another-deal"
        db.add(duplicate)
        await db.flush()
        req = SalesPaymentRequest(handoff_id=duplicate.id, reference="t24_" + "a" * 43, link_snapshot={}, created_by_id=1)
        db.add(req)
        await db.flush()
        db.add(SalesStripeObservation(request_id=req.id, session_id="cs_other", subscription_id="sub_synthetic001", status="paid_observed", match_issues=[], latest_event_at=datetime.now(timezone.utc)))
        await db.commit()
    assert (await deliver(client, lifecycle(identity="in_ambiguous"))).status_code == 200
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(ServiceRenewalEvent)) == 1


async def writable_ops(client, sessions, handoff):
    await grant(sessions, handoff["customer_id"])
    async with sessions() as db:
        permission = await db.scalar(select(CustomerAccessGrant))
        permission.access_level = "read_write"
        permission.scopes = {**permission.scopes, "delivery": "read_write"}
        await db.commit()
    response = await client.post(f"{PREFIX}/{handoff['id']}/operations-acknowledgment", headers=headers(13), json={"note": "运营本人接收"})
    assert response.status_code == 200, response.text


def item_update(revision=1, **values):
    return {"revision": revision, "status": "completed", "due_date": "2026-10-15", "note": "已核对平台授权", "evidence": "客户群中确认", "completed_on": "2026-10-10", **values}


@pytest.mark.asyncio
async def test_kickoff_get_no_seeds_explicit_initialize_persist_audit_revision_no_old_writes(sale_api):
    client, sessions = sale_api
    handoff = await registered(client)
    await writable_ops(client, sessions, handoff)
    before = await old_snapshot(sessions)
    path = f"{API}/kickoffs/{handoff['id']}"
    for suffix in ("/kickoffs", "/owner-overview", f"/kickoffs/{handoff['id']}"):
        response = await client.get(API + suffix, headers=headers(1))
        assert response.status_code == 200, response.text
        assert "no-store" in response.headers["cache-control"]
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(ServiceKickoff)) == 0
    create = await client.post(path + "/initialize", headers=headers(13), json={"first_delivery_due_date": "2026-10-15"})
    assert create.status_code == 200, create.text
    kickoff = create.json()["kickoff"]
    assert len(kickoff["items"]) == 4 and kickoff["revision"] == 1
    assert "Google Business Profile" in str(kickoff["items"])
    assert kickoff["can_edit"] and "amount" not in kickoff and "payment_status" not in kickoff
    assert (await client.post(path + "/initialize", headers=headers(13), json={"first_delivery_due_date": "2026-10-15"})).json()["kickoff"]["revision"] == 1
    assert (await client.post(path + "/initialize", headers=headers(13), json={"first_delivery_due_date": "2026-10-16"})).status_code == 409
    update = await client.patch(path + "/items/platform_verification", headers=headers(13), json=item_update())
    assert update.status_code == 200, update.text
    assert update.json()["kickoff"]["revision"] == 2
    assert len(update.json()["kickoff"]["audit"]) == 2
    assert (await client.patch(path + "/items/platform_verification", headers=headers(13), json=item_update())).status_code == 409
    assert await old_snapshot(sessions) == before
    persisted = await client.get(path, headers=headers(13))
    assert persisted.json()["kickoff"]["items"][0]["note"] == "已核对平台授权"


@pytest.mark.asyncio
async def test_readonly_collaborators_reassigned_revoked_inactive_and_sales_denied(sale_api):
    client, sessions = sale_api
    handoff = await registered(client)
    path = f"{API}/kickoffs/{handoff['id']}"
    assert (await client.get(path, headers=headers(13))).status_code == 404
    await grant(sessions, handoff["customer_id"])
    readonly = await client.get(path, headers=headers(13))
    assert readonly.status_code == 200 and not readonly.json()["kickoff"]["can_edit"]
    assert (await client.post(path + "/initialize", headers=headers(13), json={"first_delivery_due_date": "2026-10-15"})).status_code == 403
    async with sessions() as db:
        permission = await db.scalar(select(CustomerAccessGrant))
        permission.access_level, permission.scopes = "read_write", {"delivery": "read_write"}
        await db.commit()
    # Editing invitation does not bypass personal acceptance.
    assert (await client.post(path + "/initialize", headers=headers(13), json={"first_delivery_due_date": "2026-10-15"})).status_code == 403
    assert (await client.post(f"{PREFIX}/{handoff['id']}/operations-acknowledgment", headers=headers(13), json={"note": "本人确认接收"})).status_code == 200
    assert (await client.post(path + "/initialize", headers=headers(13), json={"first_delivery_due_date": "2026-10-15"})).status_code == 200
    await grant(sessions, handoff["customer_id"], employee_id=14)
    async with sessions() as db:
        permission = await db.scalar(select(CustomerAccessGrant).where(CustomerAccessGrant.employee_id == 14))
        permission.access_level, permission.scopes = "read_write", {"delivery": "read_write"}
        await db.commit()
    assert (await client.get(path, headers=headers(14))).status_code == 200
    assert (await client.patch(path + "/items/customer_materials", headers=headers(14), json=item_update())).status_code == 403
    async with sessions() as db:
        (await db.get(SalesDealHandoff, handoff["id"])).operations_owner_employee_id = 14
        await db.commit()
    assert (await client.patch(path + "/items/customer_materials", headers=headers(13), json=item_update())).status_code == 403
    async with sessions() as db:
        grant_row = await db.scalar(select(CustomerAccessGrant).where(CustomerAccessGrant.employee_id == 13))
        grant_row.invitation_status = "revoked"
        await db.commit()
    assert (await client.get(path, headers=headers(13))).status_code == 404
    assert not (await client.get(API + "/kickoffs", headers=headers(13))).json()["items"]
    for actor in (11, 12, 15, 16, 17):
        assert (await client.get(path, headers=headers(actor))).status_code in {403, 404}
        for suffix in ("/renewals", "/owner-overview"):
            assert (await client.get(API + suffix, headers=headers(actor))).status_code == 403
    async with sessions() as db:
        (await db.get(Employees, 14)).status = "inactive"
        await db.commit()
    assert (await client.get(path, headers=headers(14))).status_code == 403


@pytest.mark.parametrize("update", [
    {"note": ""}, {"completed_on": None}, {"completed_on": "2099-01-01"}, {"completed_on": "1899-09-30"},
    {"due_date": "2026-09-30"}, {"due_date": "2026-11-01"}, {"status": "pending", "completed_on": "2026-10-10"},
    {"status": "blocked", "note": "", "completed_on": None}, {"note": "含控制\u0000字符"}, {"amount": 198},
])
@pytest.mark.asyncio
async def test_invalid_checklist_dates_notes_status_and_extra_fields_rejected(sale_api, update):
    client, _ = sale_api
    handoff = await registered(client)
    path = f"{API}/kickoffs/{handoff['id']}"
    assert (await client.post(path + "/initialize", headers=headers(1), json={"first_delivery_due_date": "2026-10-15"})).status_code == 200
    response = await client.patch(path + "/items/customer_materials", headers=headers(1), json=item_update(**update))
    assert response.status_code in {400, 422}, response.text
    assert (await client.get(path, headers=headers(1))).json()["kickoff"]["revision"] == 1


@pytest.mark.asyncio
async def test_owner_overview_precise_counts_independent_actions_and_unconnected_legacy_watch(sale_api, monkeypatch):
    client, sessions = sale_api
    handoff = await registered(client)
    monkeypatch.setattr(service, "today", lambda: date(2026, 10, 20))
    async with sessions() as db:
        db.add(Subscriptions(customer_id=999, customer_name="Synthetic Legacy", package_name="Legacy", package_price=12,
            status="active", next_payment_date=datetime(2026, 10, 25)))
        await db.commit()
    overview = await client.get(API + "/owner-overview", headers=headers(1))
    assert overview.status_code == 200, overview.text
    data = overview.json()
    assert data["counts"] == {"pending_receipt": 1, "pending_access": 1, "pending_operations": 1,
        "kickoff_missing": 1, "kickoff_overdue": 0, "kickoff_blocked": 0, "renewal_attention": 0, "renewal_unconnected": 2, "total_actions": 4}
    assert data["coverage"]["linked_subscriptions"] == 0
    watched = await client.get(API + "/renewals?status=unconnected", headers=headers(1))
    assert len(watched.json()["items"]) == 2
    assert all(row["connection_status"] == "unconnected" for row in watched.json()["items"])
    assert any(row["status"] == "upcoming" for row in watched.json()["items"])
    assert (await client.post(f"{API}/kickoffs/{handoff['id']}/initialize", headers=headers(1), json={"first_delivery_due_date": "2026-10-15"})).status_code == 200
    data = (await client.get(API + "/owner-overview", headers=headers(1))).json()
    assert data["counts"]["kickoff_missing"] == 0 and data["counts"]["kickoff_overdue"] == 1
    filtered = (await client.get(API + "/kickoffs?status=overdue", headers=headers(1))).json()
    assert len(filtered["items"]) == 1
    assert (await client.get(API + "/renewals?status=INVALID", headers=headers(1))).status_code == 422

@pytest.mark.asyncio
async def test_lifecycle_signature_limits_and_global_event_id_reuse_protected(sale_api, monkeypatch):
    client, sessions = sale_api
    _, request = await linked(client, sessions, monkeypatch)
    payload = lifecycle()
    assert (await deliver(client, payload, secret="whsec_not_correct_secret")).status_code == 400
    assert (await deliver(client, payload, timestamp=int(time.time()) - 301)).status_code == 400
    conflict = lifecycle(event_id="evt_synthetic001")
    assert (await deliver(client, conflict)).status_code == 409
    assert (await deliver(client, payload)).status_code == 200
    conflict_checkout = event(request, event_id=payload["id"])
    assert (await deliver(client, conflict_checkout)).status_code == 409
    async with sessions() as db:
        rows = (await db.execute(select(ServiceRenewalSignal.__table__))).all()
        events = (await db.execute(select(ServiceRenewalEvent.__table__))).all()
        assert "NEVER-PERSIST@example.com" not in json.dumps([dict(row._mapping) for row in rows + events], default=str)


@pytest.mark.asyncio
async def test_crm_past_due_is_attention_even_with_future_date_and_no_live_link(sale_api):
    client, sessions = sale_api
    async with sessions() as db:
        db.add(Subscriptions(customer_id=999, customer_name="Synthetic Past Due", package_name="Legacy", package_price=12,
            status="past_due", next_payment_date=datetime(2099, 10, 25)))
        await db.commit()
    response = await client.get(API + "/renewals?status=attention", headers=headers(1))
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["status"] == "payment_failed" and item["connection_status"] == "unconnected"
    assert item["href"] == "/customers?detail=999&tab=renewals" and "CRM 登记逾期" in item["status_label"]
    assert response.json()["coverage"]["received_event_count"] == 0

@pytest.mark.asyncio
async def test_advance_preparation_current_first_delivery_date_and_blocked_exception(sale_api, monkeypatch):
    client, sessions = sale_api
    handoff = await registered(client)
    monkeypatch.setattr(service, "today", lambda: date(2026, 10, 5))
    path = f"{API}/kickoffs/{handoff['id']}"
    assert (await client.post(path + "/initialize", headers=headers(1), json={"first_delivery_due_date": "2026-10-15"})).status_code == 200
    advanced = await client.patch(path + "/items/customer_materials", headers=headers(1), json=item_update(completed_on="2026-09-25"))
    assert advanced.status_code == 200, advanced.text
    changed = await client.patch(path + "/items/first_delivery_plan", headers=headers(1), json=item_update(revision=2,
        status="blocked", completed_on=None, due_date="2026-10-20", note="客户素材尚未准备完成"))
    assert changed.status_code == 200, changed.text
    assert changed.json()["kickoff"]["first_delivery_due_date"] == "2026-10-20"
    assert changed.json()["kickoff"]["blocked_count"] == 1 and changed.json()["kickoff"]["status"] == "in_progress"
    overview = (await client.get(API + "/owner-overview", headers=headers(1))).json()
    assert overview["counts"]["kickoff_blocked"] == 1 and overview["counts"]["kickoff_overdue"] == 0
    assert any(row["kind"] == "kickoff_blocked" for row in overview["items"])
    monkeypatch.setattr(service, "today", lambda: date(2026, 10, 18))
    # Earliest unfinished task is 10/15, not the new first delivery date 10/20.
    details = (await client.get(path, headers=headers(1))).json()["kickoff"]
    assert details["overdue_days"] == 3 and details["first_delivery_due_date"] == "2026-10-20"


@pytest.mark.parametrize("status,visible", [("expiring_soon", True), ("renewal_pending", True), ("expired", True),
    ("paused", False), ("stopped", False), ("lost", False)])
@pytest.mark.asyncio
async def test_legacy_renewal_dictionary_coverage_without_stopped_services(sale_api, status, visible):
    client, sessions = sale_api
    async with sessions() as db:
        db.add(Subscriptions(customer_id=999, customer_name="Synthetic Watch", package_name="Legacy", package_price=12,
            status=status, next_payment_date=datetime(2026, 10, 18)))
        await db.commit()
    response = await client.get(API + "/renewals", headers=headers(1))
    assert response.status_code == 200
    assert bool(response.json()["items"]) is visible
    if visible:
        row = response.json()["items"][0]
        assert row["connection_status"] == "unconnected" and "CRM 登记" in row["status_label"]
        assert row["due_date"] == "2026-10-18"

@pytest.mark.asyncio
async def test_owner_priority_actual_stripe_failure_before_receipt_and_old_date_watch(sale_api, monkeypatch):
    client, sessions = sale_api
    handoff, _ = await linked(client, sessions, monkeypatch)
    assert (await deliver(client, lifecycle(at=int(time.time()) - 86401))).status_code == 200
    async with sessions() as db:
        db.add(Subscriptions(customer_id=999, customer_name="Old Date", package_name="Legacy", package_price=12,
            status="active", end_date=datetime(2000, 1, 1)))
        await db.commit()
    data = (await client.get(API + "/owner-overview", headers=headers(1))).json()
    assert data["items"][0]["kind"] == "renewal_attention" and data["items"][0]["handoff_id"] == handoff["id"]
    assert data["items"][0]["href"] == f"/sales-leads?view=handoffs&handoff={handoff['id']}"
    assert data["items"][0]["waiting_days"] == 1
    assert data["items"][1]["kind"] == "pending_receipt"
    assert data["items"][-1]["business_name"] == "Old Date"
    assert data["items"][-1]["href"] == "/customers?detail=999&tab=renewals"

@pytest.mark.asyncio
async def test_coverage_counts_distinct_subscriptions_and_excludes_cross_handoff_ambiguity(sale_api, monkeypatch):
    client, sessions = sale_api
    handoff, _ = await linked(client, sessions, monkeypatch)
    async with sessions() as db:
        original_request = await db.scalar(select(SalesPaymentRequest))
        db.add(SalesStripeObservation(request_id=original_request.id, session_id="cs_anotherSameHandoff",
            subscription_id="sub_synthetic002", status="paid_observed", match_issues=[], latest_event_at=datetime.now(timezone.utc)))
        await db.commit()
    initial = (await client.get(API + "/renewals", headers=headers(1))).json()
    assert initial["coverage"]["linked_subscriptions"] == 2 and initial["counts"]["all"] == 1
    assert initial["items"][0]["connection_status"] == "linked"
    async with sessions() as db:
        source = await db.get(SalesDealHandoff, handoff["id"])
        other = SalesDealHandoff(**{column.name: getattr(source, column.name) for column in SalesDealHandoff.__table__.columns if column.name != "id"})
        other.lead_id, other.deal_id, other.idempotency_key = 888, 888, "synthetic-coverage-ambiguity"
        db.add(other)
        await db.flush()
        request = SalesPaymentRequest(handoff_id=other.id, reference="t24_" + "b" * 43, link_snapshot={}, created_by_id=1)
        db.add(request)
        await db.flush()
        db.add(SalesStripeObservation(request_id=request.id, session_id="cs_ambiguousCoverage",
            subscription_id="sub_synthetic001", status="paid_observed", match_issues=[], latest_event_at=datetime.now(timezone.utc)))
        await db.commit()
        ambiguous_handoff_id = other.id
    result = (await client.get(API + "/renewals", headers=headers(1))).json()
    assert result["coverage"]["linked_subscriptions"] == 1
    rows = {row["handoff_id"]: row for row in result["items"]}
    assert rows[handoff["id"]]["connection_status"] == "linked"  # Only synthetic002 remains covered.
    assert rows[ambiguous_handoff_id]["connection_status"] == "unconnected"
    assert result["counts"]["unconnected"] == 1
    assert (await deliver(client, lifecycle())).status_code == 200
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(ServiceRenewalSignal)) == 0

@pytest.mark.asyncio
async def test_legacy_effective_latest_month_suppresses_history_before_status_filter_no_writes(sale_api):
    client, sessions = sale_api
    async with sessions() as db:
        db.add_all([
            Subscriptions(id=101, customer_id=28, customer_name="Effective Merchant", package_name="专业套餐", package_price=329,
                status="active", end_date=datetime(2026, 1, 31), next_payment_date=datetime(2026, 1, 31)),
            Subscriptions(id=102, customer_id=28, customer_name="Effective Merchant", package_name="专业套餐", package_price=329,
                status="expired", end_date=datetime(2026, 3, 2), next_payment_date=datetime(2026, 3, 2)),
            Subscriptions(id=103, customer_id=28, customer_name="Effective Merchant", package_name="专业套餐", package_price=329,
                status="active", end_date=datetime(2026, 6, 2), next_payment_date=datetime(2026, 6, 2)),
        ])
        await db.commit()
    before = await old_snapshot(sessions)
    data = (await client.get(API + "/renewals", headers=headers(1))).json()
    assert [row["id"] for row in data["items"]] == ["crm-103"]
    assert data["items"][0]["due_date"] == "2026-06-02" and data["counts"]["all"] == 1
    assert (await client.get(API + "/owner-overview", headers=headers(1))).json()["counts"]["renewal_attention"] == 1
    assert await old_snapshot(sessions) == before


@pytest.mark.parametrize("latest_status", ["stopped", "lost", "paused", "renewed", "upgraded"])
@pytest.mark.asyncio
async def test_legacy_effective_archived_latest_suppresses_old_active_without_fallback(sale_api, latest_status):
    client, sessions = sale_api
    async with sessions() as db:
        db.add_all([
            Subscriptions(id=101, customer_id=28, package_name="Basic", package_price=198, status="active", end_date=datetime(2026, 1, 31)),
            Subscriptions(id=102, customer_id=28, package_name=" basic ", package_price=198, status=latest_status, end_date=datetime(2026, 6, 2)),
        ])
        await db.commit()
    before = await old_snapshot(sessions)
    data = (await client.get(API + "/renewals", headers=headers(1))).json()
    assert data["items"] == [] and data["counts"]["all"] == 0
    assert (await client.get(API + "/owner-overview", headers=headers(1))).json()["counts"]["renewal_attention"] == 0
    assert await old_snapshot(sessions) == before


@pytest.mark.asyncio
async def test_legacy_effective_package_normalization_customer_isolation_and_pending_separation(sale_api):
    client, sessions = sale_api
    async with sessions() as db:
        db.add_all([
            Subscriptions(id=101, customer_id=28, package_name="Google、 Meta", package_price=198, status="active", end_date=datetime(2026, 1, 31)),
            Subscriptions(id=102, customer_id=28, package_name=" META,google ", package_price=198, status="active", end_date=datetime(2026, 6, 2)),
            Subscriptions(id=103, customer_id=28, package_name="google，meta", package_price=198, status="pending", end_date=datetime(2099, 1, 1)),
            Subscriptions(id=104, customer_id=28, package_name="Website", package_price=99, status="active", end_date=datetime(2026, 2, 1)),
            Subscriptions(id=105, customer_id=29, package_name="google，meta", package_price=198, status="active", end_date=datetime(2026, 3, 1)),
        ])
        await db.commit()
    before = await old_snapshot(sessions)
    data = (await client.get(API + "/renewals", headers=headers(1))).json()
    assert {row["id"] for row in data["items"]} == {"crm-102", "crm-104", "crm-105"}
    assert await old_snapshot(sessions) == before


@pytest.mark.asyncio
async def test_pending_known_handoff_retained_without_replacing_existing_effective_legacy(sale_api, monkeypatch):
    client, sessions = sale_api
    handoff, _ = await linked(client, sessions, monkeypatch)
    async with sessions() as db:
        pending = await db.get(Subscriptions, handoff["subscription_id"])
        assert pending.status == "pending"
        db.add_all([
            Subscriptions(id=101, customer_id=handoff["customer_id"], package_name=pending.package_name, package_price=198,
                status="active", end_date=datetime(2026, 1, 31)),
            Subscriptions(id=102, customer_id=handoff["customer_id"], package_name=pending.package_name, package_price=198,
                status="active", end_date=datetime(2026, 6, 2)),
        ])
        await db.commit()
    before = await old_snapshot(sessions)
    data = (await client.get(API + "/renewals", headers=headers(1))).json()
    assert {row["id"] for row in data["items"]} == {f"handoff-{handoff['id']}", "crm-102"}
    assert next(row for row in data["items"] if row["handoff_id"])["connection_status"] == "linked"
    assert await old_snapshot(sessions) == before


@pytest.mark.parametrize("field", ["end_date", "next_payment_date", "updated_at", "created_at", "id"])
def test_effective_legacy_uses_existing_frontend_priority_field_order(field):
    from types import SimpleNamespace
    common = {"customer_id": 28, "package_name": "Base", "status": "active", "end_date": None,
        "next_payment_date": None, "updated_at": None, "created_at": None}
    first = SimpleNamespace(id=101, **common)
    second = SimpleNamespace(id=102, **common)
    if field == "id":
        expected = second
    else:
        setattr(first, field, datetime(2026, 6, 2))
        setattr(second, field, datetime(2026, 1, 31))
        fields = ("end_date", "next_payment_date", "updated_at", "created_at")
        for later in fields[fields.index(field) + 1:]:
            setattr(second, later, datetime(2099, 1, 1))
        expected = first  # Earlier comparator field beats later fields and id.
    assert service._effective_legacy_subscriptions([second, first]) == [expected]

@pytest.mark.asyncio
async def test_mapped_effective_nonpending_handoff_does_not_resurrect_older_legacy(sale_api, monkeypatch):
    client, sessions = sale_api
    handoff, _ = await linked(client, sessions, monkeypatch)
    async with sessions() as db:
        mapped = await db.get(Subscriptions, handoff["subscription_id"])
        mapped.status = "active"
        db.add(Subscriptions(id=101, customer_id=handoff["customer_id"], package_name=mapped.package_name,
            package_price=198, status="active", end_date=datetime(2026, 1, 31)))
        await db.commit()
    before = await old_snapshot(sessions)
    data = (await client.get(API + "/renewals", headers=headers(1))).json()
    assert [row["id"] for row in data["items"]] == [f"handoff-{handoff['id']}"]
    assert data["items"][0]["connection_status"] == "linked"
    assert await old_snapshot(sessions) == before
