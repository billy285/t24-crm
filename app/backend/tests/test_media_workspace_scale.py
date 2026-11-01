"""Complete local aggregation at >1000 rows/>300 bindings with unchanged ACL.

Only fixture databases and deterministic local provider doubles are used.
This proves completeness/query shape, not a production throughput guarantee.
"""
from datetime import timedelta
from time import perf_counter
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event, select

from models.customers import Customers
from models.employees import Employees
from models.google_business import GoogleBusinessSchedule as Schedule, GoogleBusinessAIDraft as Draft
from models.media_operations import MediaOperationTask as Task
from services import media_workspace as service
from test_media_workspace import projection, seed_task, workspace, PREFIX, PERIOD, INSTANT
from test_google_business import gbp_env, OWNER, OPS, OTHER


async def complete_monthly(*args):
    return [], {}, service._source("monthly", message="Synthetic monthly source not in this scope"), False


@pytest.mark.asyncio
async def test_full_sources_customer_portfolio_and_cursor_beyond_old_caps(projection, monkeypatch):
    env = projection
    monkeypatch.setattr(service, "now", lambda: INSTANT)
    monkeypatch.setattr(service, "_monthly", complete_monthly)
    monkeypatch.setattr(service, "READ_BATCH_SIZE", 73)
    async with env.sessions() as db:
        db.add_all([Customers(id=1000 + n, business_name=f"Scale Merchant {n:04}", contact_name="Synthetic", phone="111", status="closed") for n in range(1005)])
        db.add_all([env.Binding(id=1000 + n, customer_id=1000 + n, customer_name=f"Scale Merchant {n:04}", connection_id=1,
            location_name=f"accounts/100/locations/{10000 + n}", title=f"Scale Merchant {n:04}", address="", active=True,
            revision=1, primary_operator_id=2, created_by_id=1, request_id=str(uuid4())) for n in range(301)])
        tasks = [Task(customer_id=1000 + n % 301, customer_name="Scale Merchant", title=f"Scale task {n}", platform="google_business",
            due_at=INSTANT, timezone="America/Los_Angeles", assignee_id=2, assignee_name=OPS.name, content="Synthetic content",
            status="in_review", revision=1, created_by_id=1, client_request_id=str(uuid4()), creation_fingerprint="f" * 64,
            created_at=INSTANT, updated_at=INSTANT) for n in range(1105)]
        db.add_all(tasks); await db.flush()
        db.add_all([Schedule(binding_id=1000 + n, task_id=tasks[n].id, task_revision=1, payload_fingerprint="f" * 64,
            operator_id=3, owner_id=1, request_id=str(uuid4()), planned_at=INSTANT + timedelta(days=1),
            timezone="America/Los_Angeles", status="scheduled", revision=1, created_by_id=1) for n in range(301)])
        await db.commit()
    statements = []
    def audit(conn, cursor, statement, parameters, context, executemany): statements.append(statement)
    event.listen(env.engine.sync_engine, "before_cursor_execute", audit)
    started = perf_counter()
    try:
        first = await workspace(env, limit=100, view="calendar")
        elapsed = perf_counter() - started
        assert first.status_code == 200, first.text
        value = first.json()
        assert value["summary"]["tasks"] == 1108
        assert value["summary"]["scheduled"] == 301
        assert value["total"] == 1409
        assert value["sources_complete"] is True and value["has_more"] is True
        assert value["portfolio"]["summary"]["merchants"] == 1007
        assert sum(r["total"] for r in value["calendar_days"]) == value["total"]
        assert sum(r["scheduled"] for r in value["calendar_days"]) == 301
        assert sum(r["total"] for r in value["review_groups"]) == 1108
        # Native Google permission checks are bulk-equivalent, not N+1 per binding.
        assert len(statements) < 95, (len(statements), elapsed)
        assert not any(s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP")) for s in statements)
        print(f"complete_fixture: merchants=1007 bindings=302 tasks=1108 schedule=301 sql={len(statements)} elapsed={elapsed:.3f}s")
    finally:
        event.remove(env.engine.sync_engine, "before_cursor_execute", audit)
    # The last 101 bindings beyond the former limit remain reachable and count.
    seen = set(); cursor = None; totals = []
    while True:
        response = await env.projection.get(PREFIX + "/merchants", params={**PERIOD, "q": "Scale", "platform": "google_business", "limit": 47, **({"cursor": cursor} if cursor else {})})
        assert response.status_code == 200, response.text
        page = response.json(); totals.append(page["total"])
        assert not seen.intersection(r["id"] for r in page["items"])
        seen.update(r["id"] for r in page["items"])
        assert all(r["primary_operator_id"] == 2 and r["next_7_days_count"] == 1 for r in page["items"])
        cursor = page["next_cursor"]
        if not cursor: break
    assert seen == set(range(1000, 1301)) and set(totals) == {301}
    assert not env.fake.reads and not env.fake.writes


@pytest.mark.asyncio
async def test_saved_schedule_coverage_and_workload_use_exact_saved_operator(projection, monkeypatch):
    env = projection
    monkeypatch.setattr(service, "now", lambda: INSTANT)
    monkeypatch.setattr(service, "_monthly", complete_monthly)
    async with env.sessions() as db:
        binding = await db.get(env.Binding, 1); binding.primary_operator_id = 2
        db.add(Schedule(binding_id=1, task_id=env.task, task_revision=2, payload_fingerprint="f" * 64,
            operator_id=3, owner_id=1, request_id=str(uuid4()), planned_at=INSTANT + timedelta(days=1),
            timezone="America/Los_Angeles", status="scheduled", revision=1, created_by_id=1))
        db.add(Schedule(binding_id=1, task_id=env.task, task_revision=2, payload_fingerprint="f" * 64,
            operator_id=3, owner_id=1, request_id=str(uuid4()), planned_at=INSTANT + timedelta(days=2),
            timezone="America/Los_Angeles", status="cancelled", revision=1, created_by_id=1))
        await db.commit()
    response = await workspace(env, customer_id=10)
    assert response.status_code == 200, response.text
    people = {r["id"]: r for r in response.json()["portfolio"]["operators"]}
    assert people[2]["merchants"] == 1 and people[2]["scheduled"] == 0
    assert people[3]["merchants"] == 0 and people[3]["scheduled"] == 1
    # Viewing a historical report still shows actual future saved queue coverage.
    rows = await env.projection.get(PREFIX + "/merchants", params={"customer_id": 10, "start": "2026-09-01T00:00:00Z", "end": "2026-10-01T00:00:00Z"})
    assert rows.status_code == 200, rows.text
    merchant = rows.json()["items"][0]
    assert merchant["next_7_days_count"] == 1 and merchant["next_publish_at"] == service.iso(INSTANT + timedelta(days=1))
    assert merchant["scheduled"] == 0  # Selected report period contains no schedules.
    env.user = OPS
    staff = await workspace(env, customer_id=10)
    assert staff.status_code == 200
    assert all(r["id"] == 2 for r in staff.json()["portfolio"]["operators"])
    assert "SECRET-HIDDEN" not in staff.text


@pytest.mark.asyncio
async def test_filters_are_merchant_scope_and_cursor_bound_without_granting_rights(projection, monkeypatch):
    env = projection
    monkeypatch.setattr(service, "_monthly", complete_monthly)
    await seed_task(env, customer_id=20, title="Another hidden task")
    first = await workspace(env, limit=1)
    cursor = first.json()["next_cursor"]
    assert cursor
    assert (await workspace(env, status="review", cursor=cursor)).status_code == 409
    assert (await workspace(env, operator_id=2, cursor=cursor)).status_code == 409
    assert (await workspace(env, status="invalid")).status_code == 422
    assert (await workspace(env, operator_id=-1)).status_code == 422
    assert (await env.projection.get(PREFIX + "/merchants", params={"start": PERIOD["start"]})).status_code == 422
    env.user = OTHER
    denied = await workspace(env, customer_id=20, status="all")
    assert denied.status_code == 404
    response = await workspace(env, status="review")
    assert response.status_code == 200 and "SECRET-HIDDEN" not in response.text
    assert response.json()["portfolio"]["summary"]["merchants"] == 1
    assert next(r["state"] for r in response.json()["sources"] if r["key"] == "meta") == "locked"
    assert not env.fake.reads and not env.fake.writes


@pytest.mark.asyncio
async def test_disabled_connection_owner_fences_google_but_preserves_own_tasks(projection, monkeypatch):
    env = projection
    monkeypatch.setattr(service, "_monthly", complete_monthly)
    env.user = OPS
    async with env.sessions() as db:
        owner = await db.get(Employees, int(OWNER.id)); owner.status = "disabled"; await db.commit()
    response = await workspace(env)
    assert response.status_code == 200, response.text
    rows = response.json()["items"]
    assert len(rows) == 1 and rows[0]["binding_id"] is None
    assert response.json()["portfolio"]["operators"][0]["id"] == int(OPS.id)
    assert not env.fake.reads and not env.fake.writes


@pytest.mark.asyncio
async def test_no_coverage_or_assignment_alarm_for_non_cooperating_or_unconnected(projection, monkeypatch):
    env = projection
    monkeypatch.setattr(service, "_monthly", complete_monthly)
    async with env.sessions() as db:
        customer = await db.get(Customers, 10); customer.status = "paused"
        await db.commit()
    response = await env.projection.get(PREFIX + "/merchants", params=PERIOD)
    assert response.status_code == 200, response.text
    rows = {r["id"]: r for r in response.json()["items"]}
    paused = rows[10]
    assert paused["coverage_state"] == "not_applicable" and paused["assignment_state"] == "not_applicable"
    assert paused["next_7_days_count"] is None
    assert not any(r["code"] in {"no_schedule", "unassigned", "overdue"} for r in paused["issues"])
    # Customer20 has a binding belonging to another owner, which remains hidden.
    assert rows[20]["coverage_state"] == "not_connected" and rows[20]["platforms"] == ["google_business"]
    assert rows[20]["assignment_state"] == "not_applicable"
    assert response.json()["summary"]["unassigned"] == response.json()["summary"]["no_schedule"] == 0
    env.user = OPS
    async with env.sessions() as db:
        from models.customer_access_grants import CustomerAccessGrant
        grant = await db.scalar(select(CustomerAccessGrant).where(CustomerAccessGrant.employee_id == 2, CustomerAccessGrant.customer_id == 10))
        grant.scopes = {"delivery": "read_only", "basic": "none"}; await db.commit()
    own = await env.projection.get(PREFIX + "/merchants", params=PERIOD)
    assert own.status_code == 200 and own.json()["items"][0]["cooperation_status"] is None


@pytest.mark.asyncio
async def test_generated_reply_draft_counts_review_without_claiming_live_inbox(projection, monkeypatch):
    env = projection
    monkeypatch.setattr(service, "now", lambda: INSTANT)
    monkeypatch.setattr(service, "_monthly", complete_monthly)
    async with env.sessions() as db:
        db.add(Draft(id=str(uuid4()), binding_id=1, actor_id=1, request_id=str(uuid4()), review_name="accounts/100/locations/1000/reviews/review",
            review_version="a" * 64, reply_text="Synthetic reply", status="generated", sensitive=True, risk_flags=[], model="synthetic",
            runtime_fingerprint="c" * 64, fingerprint="f" * 64, created_at=INSTANT, expires_at=INSTANT + timedelta(days=3)))
        await db.commit()
    result = await workspace(env, customer_id=10, view="review")
    assert result.status_code == 200, result.text
    value = result.json()
    assert value["summary"]["drafts"] == 1 and value["inbox_complete"] is False
    assert value["portfolio"]["exceptions"][0]["in_review"] == 3  # two tasks + one generated reply
    row = next(r for r in value["items"] if r["kind"] == "google_reply_draft")
    assert row["status"] == "draft" and not row["review_eligible"]
    assert not env.fake.reads and not env.fake.writes


@pytest.mark.asyncio
async def test_monthly_suggested_slots_do_not_change_cross_view_merchant_review_totals(projection, monkeypatch):
    env = projection
    async def monthly(db, ctx, customers, start, end, platform, view):
        if 10 not in customers: return [], {}, service._source("monthly"), False
        customer = customers[10]
        if view == "calendar":
            rows = [service._row("monthly_item", SimpleNamespace(id=n), customer, "google_business", title="Suggested monthly slot",
                status="prepared", at=INSTANT + timedelta(days=n), basis="proposed_publish") for n in (1, 2)]
        else:
            rows = [service._row("monthly_run", SimpleNamespace(id=123), customer, "google_business", title="Monthly batch",
                status="prepared", at=INSTANT, basis="record_created")]
        return rows, {}, service._source("monthly"), False
    monkeypatch.setattr(service, "_monthly", monthly)
    overview = await workspace(env, status="review")
    calendar = await workspace(env, status="review", view="calendar", limit=1)
    assert overview.status_code == calendar.status_code == 200
    assert overview.json()["portfolio"]["summary"] == calendar.json()["portfolio"]["summary"]
    assert calendar.json()["portfolio"]["exceptions"][0]["in_review"] == 3  # two tasks + one batch
    assert sum(r["suggested"] for r in calendar.json()["calendar_days"]) == 2
    assert calendar.json()["total"] == 5  # three tasks + two proposed slots; no batch double count


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["unchanged", "owner_probation", "owner_disabled", "owner_role", "connection_inactive", "binding_inactive", "google_grant_revoked", "customer_invitation_revoked", "other_authorized_owner"])
async def test_bulk_google_visibility_matches_native_read_authority(projection, change):
    """Bulk projection must not become a second, broader Google ACL system."""
    from models.customer_access_grants import CustomerAccessGrant
    from services import google_business as native
    env = projection; env.user = OPS
    async with env.sessions() as db:
        if change.startswith("owner_"):
            owner = await db.get(Employees, 1)
            if change == "owner_probation": owner.status = "probation"
            elif change == "owner_disabled": owner.status = "disabled"
            else: owner.role = "admin"
        elif change == "connection_inactive":
            connection = await db.get(env.Connection, 1); connection.active = False
        elif change == "binding_inactive":
            binding = await db.get(env.Binding, 1); binding.active = False
        elif change == "google_grant_revoked":
            grant = await db.scalar(select(env.Grant).where(env.Grant.binding_id == 1, env.Grant.employee_id == 2))
            grant.can_reply = False; grant.can_publish = False
        elif change == "customer_invitation_revoked":
            grant = await db.scalar(select(CustomerAccessGrant).where(CustomerAccessGrant.customer_id == 10, CustomerAccessGrant.employee_id == 2))
            grant.invitation_status = "revoked"
        elif change == "other_authorized_owner":
            db.add(CustomerAccessGrant(customer_id=20, employee_id=2, access_level="read_only", invitation_source="owner_invitation", invitation_status="active", finance_access="none", scopes={"delivery": "read_only"}))
            db.add(env.Grant(binding_id=2, employee_id=2, can_reply=True, can_publish=False, granted_by_id=9))
        await db.commit()
    async with env.sessions() as db:
        ctx = await service.context(db, env.user)
        customers, _, _ = await service._customers(db, ctx)
        _, bindings, _, _ = await service._google(db, ctx, customers, INSTANT, INSTANT, None, maps_only=True)
        expected = set()
        for identity in (1, 2):
            try:
                row, _, _ = await native._binding(db, ctx, identity)
                expected.add(row.id)
            except HTTPException as exc:
                assert exc.status_code in {403, 404, 409}
        assert set(bindings) == expected
    assert not env.fake.reads and not env.fake.writes
