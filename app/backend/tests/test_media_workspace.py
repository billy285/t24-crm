"""Local projection security/coverage tests; synthetic data, no external calls."""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from sqlalchemy import event, select, text
from sqlalchemy.exc import OperationalError

from core.database import get_db
from dependencies.auth import get_current_user
from models.customer_access_grants import CustomerAccessGrant
from models.customers import Customers
from models.employees import Employees
from models.media_operations import MediaOperationTask as Task
from models.google_business import GoogleBusinessAction as GoogleAction, GoogleBusinessAIDraft as GoogleDraft, GoogleBusinessSchedule as GoogleSchedule
from models.meta_operations import MetaOperationsTarget as Target, MetaOperationsDraft as MetaDraft, MetaOperationsBinding as OperatingBinding, MetaOperationsCredential as Credential
from routers.media_workspace import router
from services import media_workspace as service
from services import meta_operations as ops, meta_operations_provider as provider
from test_google_business import gbp_env, OWNER, OPS, OTHER, actors
from test_meta_business import meta_env
from test_meta_operations import ops_env

PREFIX = "/api/v1/media-workspace"
INSTANT = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
PERIOD = {"start": "2026-10-01T00:00:00Z", "end": "2026-12-01T00:00:00Z"}


async def client_for(env):
    app = FastAPI(); app.include_router(router)
    async def database():
        async with env.sessions() as db: yield db
    async def actor(): return env.user
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = actor
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://synthetic.test")


async def seed_task(env, **updates):
    values = {"customer_id": 10, "customer_name": "Synthetic Invited Merchant", "title": "Synthetic draft",
        "platform": "google_business", "due_at": INSTANT, "timezone": "America/Los_Angeles",
        "assignee_id": 2, "assignee_name": OPS.name, "content": "Reviewed task content", "status": "in_review",
        "revision": 2, "created_by_id": 1, "client_request_id": str(uuid4()), "creation_fingerprint": "f" * 64,
        "created_at": INSTANT, "updated_at": INSTANT, **updates}
    async with env.sessions() as db:
        row = Task(**values); db.add(row); await db.commit(); return row.id


@pytest_asyncio.fixture
async def projection(gbp_env, monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "synthetic-cursor-signing-key-32-characters")
    env = gbp_env
    env.task = await seed_task(env)
    env.other_task = await seed_task(env, title="OTHER-EMPLOYEE-TASK", assignee_id=3)
    env.hidden_task = await seed_task(env, customer_id=20, customer_name="SECRET-HIDDEN-MERCHANT", title="HIDDEN-OWNER-TASK", assignee_id=1)
    async with await client_for(env) as client:
        env.projection = client; yield env


async def workspace(env, **params):
    return await env.projection.get(PREFIX + "/workspace", params={**PERIOD, **params})


@pytest.mark.asyncio
async def test_owner_review_vs_staff_exact_task_scope_no_finance_private_or_provider(projection):
    env = projection
    statements = []
    def audit(conn, cursor, statement, parameters, context, executemany): statements.append(statement)
    event.listen(env.engine.sync_engine, "before_cursor_execute", audit)
    try:
        owner = await workspace(env, view="review")
        assert owner.status_code == 200, owner.text
        assert owner.json()["summary"]["review_candidates"] == 3
        assert all(r["review_eligible"] for r in owner.json()["items"])
        env.user = OPS
        response = await workspace(env)
        assert response.status_code == 200, response.text
        value = response.json()
        assert [r["source_id"] for r in value["items"] if r["kind"] == "task"] == [env.task]
        assert value["summary"]["review_candidates"] == 0
        assert value["summary"]["tasks"] == 1
        task = value["items"][0]
        assert task["binding_id"] == 1 and task["account_label"] == "Synthetic Invited Merchant"
        assert task["time_basis"] == "task_due"
        assert "SECRET" not in response.text and "financial" not in response.text and "token" not in response.text
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert not env.fake.reads and not env.fake.writes
        assert not any(s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP")) for s in statements)
    finally: event.remove(env.engine.sync_engine, "before_cursor_execute", audit)


@pytest.mark.asyncio
async def test_customer_invitation_does_not_grant_google_account_or_other_tasks(projection):
    env = projection; env.user = OTHER
    response = await workspace(env)
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1
    row = response.json()["items"][0]
    assert row["source_id"] == env.other_task
    assert row["binding_id"] is None and row["account_label"] is None
    denied = await workspace(env, customer_id=20)
    assert denied.status_code == 404
    merchants = await env.projection.get(PREFIX + "/merchants")
    assert [r["id"] for r in merchants.json()["items"]] == [10]
    assert "SECRET" not in merchants.text


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["sales", "finance", "design", "sales_partner"])
async def test_forbidden_roles_fail_before_sql(role):
    class NoDb:
        def __getattr__(self, name): raise AssertionError("unauthorized role touched database")
    with pytest.raises(HTTPException) as error:
        await service.workspace(NoDb(), SimpleNamespace(id="1", role=role), **PERIOD)
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_disabled_or_role_changed_actor_is_denied(projection):
    env = projection; env.user = OPS
    async with env.sessions() as db:
        actor = await db.get(Employees, 2); actor.status = "disabled"; await db.commit()
    assert (await workspace(env)).status_code == 403


@pytest.mark.asyncio
async def test_cursor_exact_scope_tamper_and_revoked_grant(projection):
    env = projection
    first = await workspace(env, limit=1)
    assert first.status_code == 200, first.text
    cursor = first.json()["next_cursor"]; assert cursor
    second = await workspace(env, limit=1, cursor=cursor)
    assert second.status_code == 200
    assert second.json()["items"][0]["id"] != first.json()["items"][0]["id"]
    assert (await workspace(env, cursor=cursor + "x")).status_code == 409
    assert (await workspace(env, customer_id=10, cursor=cursor)).status_code == 409
    assert (await workspace(env, platform="google_business", cursor=cursor)).status_code == 409
    assert (await workspace(env, view="calendar", cursor=cursor)).status_code == 409
    env.user = OPS
    assert (await workspace(env, cursor=cursor)).status_code == 409
    # A cursor produced for staff becomes invalid after its customer grant is
    # revoked; it must not retain the former row snapshot or target label.
    await seed_task(env, title="Second assigned task")
    own = await workspace(env, limit=1); own_cursor = own.json()["next_cursor"]; assert own_cursor
    async with env.sessions() as db:
        row = await db.scalar(select(CustomerAccessGrant).where(CustomerAccessGrant.employee_id == 2, CustomerAccessGrant.customer_id == 10))
        row.invitation_status = "revoked"; await db.commit()
    result = await workspace(env, cursor=own_cursor)
    assert result.status_code == 409 and "Reviewed task content" not in result.text


@pytest.mark.asyncio
async def test_calendar_real_schedule_and_internal_due_are_separate_and_range_matched(projection):
    env = projection
    async with env.sessions() as db:
        db.add(GoogleSchedule(binding_id=1, task_id=env.task, task_revision=2, payload_fingerprint="f" * 64, operator_id=2,
            owner_id=1, request_id=str(uuid4()), planned_at=INSTANT + timedelta(hours=3), timezone="America/Los_Angeles", status="scheduled", revision=1, created_by_id=1))
        await db.commit()
    response = await workspace(env, customer_id=10, view="calendar")
    assert response.status_code == 200, response.text
    rows = response.json()["items"]
    schedule = next(r for r in rows if r["kind"] == "google_schedule")
    assert schedule["time_basis"] == "scheduled_publish" and schedule["content"] == ""
    assert all(r["time_basis"] == "task_due" for r in rows if r["kind"] == "task")
    assert response.json()["summary"]["scheduled"] == 1
    narrowed = await workspace(env, customer_id=10, end="2026-10-31T00:00:00Z")
    assert narrowed.json()["summary"]["tasks"] == 0 and narrowed.json()["summary"]["scheduled"] == 0


@pytest.mark.asyncio
async def test_google_saved_replies_preserve_actor_visibility_and_honest_missing_reviews(projection):
    env = projection
    async with env.sessions() as db:
        for actor in (1, 2, 3):
            db.add(GoogleDraft(id=str(uuid4()), binding_id=1, actor_id=actor, request_id=str(uuid4()), review_name="accounts/100/locations/1000/reviews/r" + str(actor),
                review_version="a" * 64, reply_text="Saved reply by " + str(actor), status="generated", sensitive=True, risk_flags=[], model="synthetic", runtime_fingerprint="c" * 64,
                fingerprint="f" * 64, created_at=INSTANT, expires_at=service.now() + timedelta(days=1)))
        await db.commit()
    env.user = OPS
    response = await workspace(env, view="inbox")
    assert response.status_code == 200, response.text
    assert [r["content"] for r in response.json()["items"]] == ["Saved reply by 2"]
    assert response.json()["partial"] is True
    assert "尚需在门店同步" in next(s["message"] for s in response.json()["sources"] if s["key"] == "google")
    assert not env.fake.reads


@pytest.mark.asyncio
async def test_optional_missing_table_and_local_error_return_partial_not_blank_success(projection, monkeypatch):
    env = projection
    async with env.engine.begin() as conn: await conn.execute(text("DROP TABLE google_business_ai_drafts"))
    first = await workspace(env)
    assert first.status_code == 200 and first.json()["partial"] is True
    assert first.json()["summary"]["tasks"] == 3
    async def failure(*args): raise OperationalError("SELECT synthetic", {}, RuntimeError("SECRET-DB-ERROR"))
    monkeypatch.setattr(service, "_google", failure)
    second = await workspace(env)
    assert second.status_code == 200 and second.json()["summary"]["tasks"] == 3
    assert next(s["state"] for s in second.json()["sources"] if s["key"] == "google") == "error"
    assert "SECRET-DB-ERROR" not in second.text


@pytest.mark.asyncio
async def test_naive_or_unbounded_period_invalid_values_and_only_get_routes(projection):
    env = projection
    assert (await workspace(env, start="2026-10-01T00:00:00")).status_code == 422
    assert (await workspace(env, end="2028-01-01T00:00:00Z")).status_code == 422
    assert (await workspace(env, platform="unknown")).status_code == 422
    assert (await workspace(env, limit=101)).status_code == 422
    response = await env.projection.post(PREFIX + "/workspace", json={"confirmed": True})
    assert response.status_code == 405


@pytest.mark.asyncio
async def test_no_native_meta_disclosure_to_staff_even_with_delivery_invitation(ops_env, monkeypatch):
    env = ops_env; monkeypatch.setenv("JWT_SECRET_KEY", "synthetic-cursor-signing-key-32-characters")
    async with env.sessions() as db:
        db.add(CustomerAccessGrant(customer_id=38, employee_id=2, access_level="read_write", invitation_source="owner_invitation", invitation_status="active", finance_access="none", scopes={"basic": "read_only", "delivery": "read_write"}))
        db.add(MetaDraft(owner_id=1, binding_id=101, kind="post", title="SECRET-OWNER-META-DRAFT", content="SECRET-NATIVE-COPY", revision=1, status="draft", created_at=INSTANT, updated_at=INSTANT))
        await db.commit()
    env.user = OPS
    async with await client_for(env) as client:
        result = await client.get(PREFIX + "/workspace", params=PERIOD)
        assert result.status_code == 200, result.text
        assert "SECRET" not in result.text and "PokeCo" not in result.text
        assert not any(r["kind"].startswith("meta_") for r in result.json()["items"])
        assert next(s["state"] for s in result.json()["sources"] if s["key"] == "meta") == "locked"
    assert not env.ops.reads and not env.ops.writes


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [None, "paused", "expired_grant", "mismatched_grant", "expired_parent", "foreign_parent", "changed_source", "bad_digest", "stale_revision"])
async def test_meta_cache_current_owner_target_parent_and_credential_bound(ops_env, monkeypatch, invalid):
    env = ops_env; monkeypatch.setenv("JWT_SECRET_KEY", "synthetic-cursor-signing-key-32-characters")
    # Exercise real access() parsing without any Meta HTTP.
    grant = {"access_token": "SYNTHETIC-ACCESS-TOKEN", "configuration": "c" * 64,
        "expires_at": service.now().timestamp() + (0 if invalid == "expired_grant" else 86400), "observed_scopes": sorted(provider.SCOPES)}
    parent_id, comment_id = uuid4().hex, uuid4().hex
    parent = {"external_id": "111_900", "content": "Existing synthetic post", "created_at": "2026-11-01T10:00:00+0000"}
    comment = {"external_id": "111_901", "content": "VISIBLE-SYNTHETIC-COMMENT", "created_at": "2026-11-01T11:00:00Z", "author_name": "Visitor", "post_external_id": "111_900", "reply": None}
    async with env.sessions() as db:
        credential = await db.get(Credential, 1); credential.token_encrypted = provider.encrypt(grant)
        credential.granted_scopes = [] if invalid == "mismatched_grant" else sorted(provider.SCOPES)
        b = await db.get(OperatingBinding, 101)
        if invalid == "paused": b.active = False
        if invalid == "changed_source": b.external_id = "999"
        db.add_all([Target(id=parent_id, owner_id=9 if invalid == "foreign_parent" else 1, binding_id=101, binding_revision=1, kind="post", external_id="111_900", snapshot=parent,
            version=ops.digest(parent), expires_at=service.now() + timedelta(days=-1 if invalid == "expired_parent" else 1), created_at=INSTANT),
            Target(id=comment_id, owner_id=1, binding_id=101, binding_revision=2 if invalid == "stale_revision" else 1, kind="comment", external_id="111_901", parent_ref=parent_id, parent_external_id="111_900", snapshot=comment,
            version="0" * 64 if invalid == "bad_digest" else ops.digest(comment), expires_at=service.now() + timedelta(days=1), created_at=INSTANT)])
        await db.commit()
    async with await client_for(env) as client:
        result = await client.get(PREFIX + "/workspace", params={**PERIOD, "view": "inbox", "customer_id": 38})
        assert result.status_code == 200, result.text
        comments = [r for r in result.json()["items"] if r["kind"] == "meta_comment"]
        if invalid is None:
            assert len(comments) == 1 and comments[0]["content"] == "VISIBLE-SYNTHETIC-COMMENT"
            assert comments[0]["navigation"]["post_ref"] == parent_id
            assert comments[0]["version"] == ops.digest(comment)
            assert comments[0]["time_basis"] == "platform_created"
        else: assert comments == [] and "VISIBLE-SYNTHETIC-COMMENT" not in result.text
    assert not env.ops.reads and not env.ops.writes and not env.fake.reads and not env.fake.writes


@pytest.mark.asyncio
async def test_source_cap_is_explicit_partial_and_counts_never_claim_full_portfolio(projection, monkeypatch):
    env = projection; monkeypatch.setattr(service, "SOURCE_CAP", 1)
    result = await workspace(env)
    assert result.status_code == 200, result.text
    assert result.json()["partial"] is True
    assert result.json()["summary"]["tasks"] == 1
    assert len(result.json()["items"]) == 1


@pytest.mark.asyncio
async def test_merchant_metadata_reuses_basic_scope_and_current_google_assignment(projection):
    env = projection; env.user = OPS
    async with env.sessions() as db:
        customer = await db.get(Customers, 10)
        customer.city = "Synthetic City"; customer.state = "CA"; customer.industry = "餐厅"
        binding = await db.get(env.Binding, 1); binding.primary_operator_id = 2; binding.primary_operator_name = "Old display name"
        await db.commit()
    first = await env.projection.get(PREFIX + "/merchants")
    assert first.status_code == 200, first.text
    merchant = first.json()["items"][0]
    assert merchant["region"] == "Synthetic City, CA" and merchant["industry"] == "餐厅"
    assert merchant["timezone"] == "America/Los_Angeles"
    assert merchant["primary_operator_name"] == OPS.name
    async with env.sessions() as db:
        grant = await db.scalar(select(CustomerAccessGrant).where(CustomerAccessGrant.employee_id == 2, CustomerAccessGrant.customer_id == 10))
        grant.access_level = "read_only"; grant.scopes = {"basic": "none", "delivery": "read_only"}; await db.commit()
    second = await env.projection.get(PREFIX + "/merchants")
    assert second.status_code == 200, second.text
    merchant = second.json()["items"][0]
    assert merchant["region"] is None and merchant["industry"] is None
    assert merchant["can_edit"] is False and merchant["can_create"] is False
    assert "Synthetic City" not in second.text


@pytest.mark.asyncio
async def test_independent_meta_cache_survives_only_legacy_read_expiry(ops_env, monkeypatch):
    from models.meta_business import MetaBusinessConnection, MetaBusinessBinding
    env = ops_env; monkeypatch.setenv("JWT_SECRET_KEY", "synthetic-cursor-signing-key-32-characters")
    grant = {"access_token": "SYNTHETIC-ACCESS-TOKEN", "configuration": "c" * 64,
        "expires_at": service.now().timestamp() + 86400, "observed_scopes": sorted(provider.SCOPES)}
    snapshot = {"external_id": "111_900", "content": "INDEPENDENT-PUBLISHER-SNAPSHOT", "created_at": "2026-11-01T10:00:00Z"}
    async with env.sessions() as db:
        old = await db.get(MetaBusinessConnection, 1); old.active = False; old.needs_reconnect = True; old.revision += 1
        source = await db.get(MetaBusinessBinding, 101); source.active = False
        credential = await db.get(Credential, 1); credential.token_encrypted = provider.encrypt(grant); credential.granted_scopes = sorted(provider.SCOPES)
        db.add(Target(id=uuid4().hex, owner_id=1, binding_id=101, binding_revision=1, kind="post", external_id="111_900", snapshot=snapshot,
            version=ops.digest(snapshot), expires_at=service.now() + timedelta(days=1), created_at=INSTANT))
        await db.commit()
    async with await client_for(env) as client:
        value = await client.get(PREFIX + "/workspace", params={**PERIOD, "customer_id": 38, "view": "calendar"})
        assert value.status_code == 200, value.text
        assert "INDEPENDENT-PUBLISHER-SNAPSHOT" in value.text
        assert not env.ops.reads and not env.ops.writes
