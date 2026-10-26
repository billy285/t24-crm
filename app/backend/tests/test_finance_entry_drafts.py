"""Synthetic clerk workflow and atomic owner posting, never production/providers."""
import asyncio
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from alembic.migration import MigrationContext
from alembic.operations import Operations

from core.database import Base, get_db
from dependencies.auth import get_current_user
from models.customers import Customers
from models.employees import Employees
from models.customer_access_grants import CustomerAccessGrant
from models.finance_entry_drafts import FinanceEntryDraft, FinanceEntryDraftAudit
import models.finance_entry_attachments
from models.payments import Payments
from models.expenses import Expenses
from models.company_expenses import Company_expenses
from models.customer_lifecycles import CustomerLifecycleCycle
from models.finance_profit_closes import MonthlyProfitClose
from routers import payments as original_payments
from routers.finance_entry_drafts import router
from schemas.auth import UserResponse
from services import finance_entry_drafts as service


PREFIX = "/api/v1/finance-entry-drafts"
OWNER = UserResponse(id="1", role="super_admin", email="owner@example.test", name="Synthetic Owner")
CLERK = UserResponse(id="2", role="finance", email="clerk@example.test", name="Synthetic Clerk")
OTHER = UserResponse(id="3", role="finance", email="other@example.test", name="Other Clerk")


def receipt(**updates):
    return {"income_type": "management_fee", "product_name": "Synthetic Service", "amount_due": 100, "amount_paid": 100,
            "payment_date": "2026-10-26", "payment_method": "check", "transaction_reference": "CHECK-100",
            "evidence_reference": "Synthetic paper receipt", **updates}


@pytest_asyncio.fixture
async def env(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'synthetic-clerk.db'}", connect_args={"timeout": 5})
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.execute(text("CREATE TABLE IF NOT EXISTS app_settings(config_key TEXT PRIMARY KEY,value_json TEXT)"))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        db.add_all([Employees(id=int(actor.id), user_id="synthetic-" + actor.id, name=actor.name, role=actor.role, status="active") for actor in (OWNER, CLERK, OTHER)])
        db.add_all([Customers(id=10, business_name="Granted Merchant", contact_name="Synthetic", phone="111"), Customers(id=20, business_name="Hidden Merchant", contact_name="Private", phone="222")])
        for identity in (2, 3):
            db.add(CustomerAccessGrant(customer_id=10, employee_id=identity, access_level="read_only", invitation_source="owner_invitation", invitation_status="active", finance_access="receipts", scopes={"basic": "read_only", "materials": "read_only"}))
        await db.commit()
    app = FastAPI()
    app.include_router(router)
    async def database():
        async with sessions() as db:
            yield db
    async def actor():
        return state.user
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = actor
    state = SimpleNamespace(user=CLERK, sessions=sessions, engine=engine)
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://synthetic.test") as client:
        state.client = client
        yield state
    await engine.dispose()


async def create(env, kind="manual_receipt", payload=None, customer_id=10, key=None):
    result = await env.client.post(PREFIX, json={"client_request_id": key or str(uuid4()), "kind": kind, "customer_id": customer_id, "payload": receipt() if payload is None else payload})
    assert result.status_code == 201, result.text
    assert result.headers["cache-control"] == "private, no-store"
    return result.json()


async def action(env, row, operation, *, key=None, reason=None):
    value = {"expected_revision": row["revision"], "request_id": key or str(uuid4())}
    if reason is not None:
        value["reason"] = reason
    return await env.client.post(f"{PREFIX}/{row['id']}/{operation}", json=value)


async def submitted(env, **kwargs):
    row = await create(env, **kwargs)
    response = await action(env, row, "submit")
    assert response.status_code == 200, response.text
    return response.json()


async def counts(env):
    async with env.sessions() as db:
        return {table.__tablename__: await db.scalar(select(func.count()).select_from(table)) for table in (Payments, Expenses, Company_expenses, CustomerLifecycleCycle, FinanceEntryDraftAudit)}


@pytest.mark.asyncio
async def test_options_require_invitation_basic_and_receipts_with_no_sensitive_fields(env):
    response = await env.client.get(PREFIX + "/customer-options")
    assert response.json() == {"items": [{"id": 10, "business_name": "Granted Merchant", "customer_code": None}]}
    async with env.sessions() as db:
        grant = await db.scalar(select(CustomerAccessGrant).where(CustomerAccessGrant.employee_id == 2))
        grant.finance_access = "status"
        await db.commit()
    assert (await env.client.get(PREFIX + "/customer-options")).json() == {"items": []}
    response = await env.client.post(PREFIX, json={"client_request_id": str(uuid4()), "kind": "manual_receipt", "customer_id": 10, "payload": receipt()})
    assert response.status_code == 404
    env.user = UserResponse(id="2", role="ops", email="ops@example.test")
    assert (await env.client.get(PREFIX)).status_code == 403


@pytest.mark.asyncio
async def test_create_save_and_submit_do_not_write_any_ledger_and_are_idempotent(env):
    key = str(uuid4())
    row = await create(env, key=key)
    repeated = await create(env, key=key)
    assert repeated["id"] == row["id"] and repeated["revision"] == 1
    before = await counts(env)
    response = await action(env, row, "submit", key="submit-request-01")
    assert response.status_code == 200
    assert response.json()["status"] == "submitted" and response.json()["revision"] == 2
    repeat = await action(env, row, "submit", key="submit-request-01")
    assert repeat.status_code == 200 and repeat.json()["revision"] == 2
    after = await counts(env)
    assert after["payments"] == after["expenses"] == after["company_expenses"] == after["customer_lifecycle_cycles"] == 0
    assert after["finance_entry_draft_audits"] == before["finance_entry_draft_audits"] + 1
    changed = await env.client.post(PREFIX, json={"client_request_id": key, "kind": "manual_receipt", "customer_id": 10, "payload": receipt(amount_paid=80)})
    assert changed.status_code == 409


@pytest.mark.asyncio
async def test_own_draft_scope_and_revocation_are_rechecked_on_every_read_and_mutation(env):
    row = await create(env)
    env.user = OTHER
    assert (await env.client.get(f"{PREFIX}/{row['id']}")).status_code == 404
    assert (await env.client.get(PREFIX)).json()["total"] == 0
    env.user = CLERK
    async with env.sessions() as db:
        grant = await db.scalar(select(CustomerAccessGrant).where(CustomerAccessGrant.employee_id == 2))
        grant.invitation_status = "revoked"
        await db.commit()
    assert (await env.client.get(f"{PREFIX}/{row['id']}")).status_code == 404
    assert (await env.client.get(PREFIX)).json()["total"] == 0
    assert (await action(env, row, "submit")).status_code == 404
    assert (await env.client.put(f"{PREFIX}/{row['id']}", json={"expected_revision": 1, "payload": receipt()})).status_code == 404
    env.user = OWNER
    assert (await env.client.get(f"{PREFIX}/{row['id']}")).status_code == 200


@pytest.mark.asyncio
async def test_submitted_locked_return_reason_and_revision_cas(env):
    row = await submitted(env)
    assert (await env.client.put(f"{PREFIX}/{row['id']}", json={"expected_revision": row['revision'], "payload": receipt()})).status_code == 409
    assert (await action(env, row, "post")).status_code == 403
    env.user = OWNER
    assert (await action(env, row, "return", reason=" ")).status_code == 422
    response = await action(env, row, "return", reason="请补充付款凭据")
    assert response.status_code == 200
    returned = response.json()
    assert returned["status"] == "returned" and returned["return_reason"] == "请补充付款凭据"
    # An owner may review, but cannot silently edit another person's payload.
    assert (await env.client.put(f"{PREFIX}/{row['id']}", json={"expected_revision": returned["revision"], "payload": receipt()})).status_code == 409
    env.user = CLERK
    assert (await env.client.put(f"{PREFIX}/{row['id']}", json={"expected_revision": 1, "payload": receipt()})).status_code == 409
    edited = await env.client.put(f"{PREFIX}/{row['id']}", json={"expected_revision": returned["revision"], "payload": receipt(notes="补充资料")})
    assert edited.status_code == 200 and edited.json()["revision"] == returned["revision"] + 1


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [{"stripe_fee_amount": 10}, {"net_amount": 99}, {"outstanding_amount": 0}, {"source_deal_id": 5}, {"engagement_id": 2}, {"recorded_by": "Owner"}, {"currency": "CNY"}, {"payment_method": "stripe"}, {"transaction_reference": "in_SYNTHETIC"}, {"amount_paid": -1}, {"amount_paid": "NaN"}, {"amount_paid": "Infinity"}])
async def test_forged_derived_fields_stripe_and_invalid_money_are_rejected(env, bad):
    result = await env.client.post(PREFIX, json={"client_request_id": str(uuid4()), "kind": "manual_receipt", "customer_id": 10, "payload": receipt(**bad)})
    assert result.status_code == 422
    assert (await counts(env))["payments"] == 0


@pytest.mark.asyncio
async def test_empty_drafts_evidence_and_mixed_datetime_validation(env):
    row = await create(env, payload={"amount_paid": None, "management_amount": None})
    assert (await action(env, row, "submit")).status_code == 422
    row = await create(env, payload=receipt(evidence_reference=""))
    assert (await action(env, row, "submit")).status_code == 422
    valid = receipt(coverage_start="2026-10-01T00:00:00", coverage_end="2026-11-01T00:00:00Z")
    assert (await create(env, payload=valid))["payload"]["coverage_start"] == valid["coverage_start"]
    invalid = await env.client.post(PREFIX, json={"client_request_id": str(uuid4()), "kind": "manual_receipt", "customer_id": 10, "payload": receipt(coverage_start="2026-10-02T00:00:00Z", coverage_end="2026-10-01T23:00:00")})
    assert invalid.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("split,expected", [({}, (100, 0, "management_fee")), ({"income_type": "ads_fee"}, (0, 100, "ads_fee")), ({"income_type": "management_ads_mixed", "management_amount": 30, "ads_recharge_amount": 70}, (30, 70, "management_ads_mixed"))])
async def test_owner_post_reuses_original_handler_and_manual_amount_rules(env, split, expected):
    row = await submitted(env, payload=receipt(**split))
    env.user = OWNER
    posted = await action(env, row, "post", key="owner-confirm-01")
    assert posted.status_code == 200, posted.text
    data = posted.json()
    assert data["status"] == "posted" and data["posted_entity"] == "payments"
    async with env.sessions() as db:
        payment = await db.get(Payments, data["posted_id"])
        assert (payment.management_amount, payment.ads_recharge_amount, payment.income_type) == expected
        assert payment.amount_paid == payment.net_amount == 100
        assert payment.outstanding_amount == payment.stripe_fee_amount == 0
        assert payment.payment_mode == "manual_collection" and payment.customer_id == 10
        assert payment.recorded_by == CLERK.name and payment.user_id == OWNER.id
    replay = await action(env, row, "post", key="owner-confirm-01")
    assert replay.status_code == 200 and replay.json()["posted_id"] == data["posted_id"]
    assert (await counts(env))["payments"] == 1
    env.user = CLERK
    clerk_data = (await env.client.get(f"{PREFIX}/{row['id']}")).json()
    assert "posted_id" not in clerk_data and "posted_entity" not in clerk_data


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,currency", [(kind, currency) for kind in ("customer_expense", "company_expense") for currency in ("USD", "CNY")])
async def test_expense_handlers_keep_original_currency_amount_and_company_drafts_are_private(env, kind, currency):
    payload = {"amount": 66.75, "currency": currency, "expense_date": "2026-10-26", "expense_month": "2026-10", "evidence_reference": "Synthetic invoice", **({"expense_type": "design_fee"} if kind == "customer_expense" else {"category": "ai_tools"})}
    row = await submitted(env, kind=kind, payload=payload, customer_id=10 if kind == "customer_expense" else None)
    env.user = OTHER
    assert (await env.client.get(f"{PREFIX}/{row['id']}")).status_code == 404
    env.user = OWNER
    result = await action(env, row, "post")
    assert result.status_code == 200, result.text
    model = Expenses if kind == "customer_expense" else Company_expenses
    async with env.sessions() as db:
        entry = await db.get(model, result.json()["posted_id"])
        assert entry.amount == 66.75 and entry.currency == currency


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["manual_receipt", "customer_expense", "company_expense"])
async def test_original_closed_period_guard_blocks_post_without_partial_changes(env, kind):
    payload = receipt() if kind == "manual_receipt" else {"amount": 30, "expense_date": "2026-10-26", "expense_month": "2026-10", "evidence_reference": "Synthetic invoice", **({"expense_type": "design_fee"} if kind == "customer_expense" else {"category": "ai_tools"})}
    row = await submitted(env, kind=kind, payload=payload, customer_id=None if kind == "company_expense" else 10)
    async with env.sessions() as db:
        db.add(MonthlyProfitClose(year_month="2026-10", status="locked", snapshot_json="{}"))
        await db.commit()
    before = await counts(env)
    env.user = OWNER
    result = await action(env, row, "post")
    assert result.status_code == 409, result.text
    assert await counts(env) == before
    current = (await env.client.get(f"{PREFIX}/{row['id']}")).json()
    assert current["status"] == "submitted" and current["revision"] == row["revision"]


@pytest.mark.asyncio
async def test_deleted_customer_cannot_become_an_orphan_payment_and_name_is_canonical(env):
    row = await submitted(env)
    async with env.sessions() as db:
        await db.execute(text("DELETE FROM customers WHERE id=10"))
        await db.commit()
    before = await counts(env)
    env.user = OWNER
    response = await action(env, row, "post")
    assert response.status_code == 404
    assert await counts(env) == before


@pytest.mark.asyncio
async def test_owner_post_uses_current_canonical_customer_name(env):
    row = await submitted(env)
    async with env.sessions() as db:
        await db.execute(text("UPDATE customers SET business_name='Renamed Merchant' WHERE id=10"))
        await db.commit()
    env.user = OWNER
    response = await action(env, row, "post")
    assert response.status_code == 200, response.text
    async with env.sessions() as db:
        payment = await db.get(Payments, response.json()["posted_id"])
        assert payment.customer_name == "Renamed Merchant"


@pytest.mark.asyncio
async def test_different_draft_with_existing_receipt_reference_is_not_double_posted(env):
    first = await submitted(env)
    env.user = OWNER
    assert (await action(env, first, "post")).status_code == 200
    env.user = CLERK
    second = await submitted(env, payload=receipt(transaction_reference=" check-100 "))
    env.user = OWNER
    assert (await action(env, second, "post")).status_code == 409
    assert (await counts(env))["payments"] == 1


@pytest.mark.asyncio
async def test_different_drafts_with_same_reference_cannot_race_to_double_post(env):
    first = await submitted(env)
    second = await submitted(env)
    env.user = OWNER
    responses = await asyncio.gather(action(env, first, "post"), action(env, second, "post"))
    assert sorted(response.status_code for response in responses) == [200, 409]
    assert (await counts(env))["payments"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["after_service_flush", "after_lifecycle_flush", "commission_rollback", "audit_flush", "outer_commit"])
async def test_atomic_failure_never_leaves_half_posted_ledgers_or_audits(env, monkeypatch, fault):
    row = await submitted(env)
    before = await counts(env)
    env.user = OWNER
    if fault == "after_service_flush":
        original = original_payments.PaymentsService.create
        async def fail(self, *args, **kwargs):
            await original(self, *args, **kwargs)
            raise RuntimeError("Synthetic failure after original service commit request")
        monkeypatch.setattr(original_payments.PaymentsService, "create", fail)
    elif fault == "after_lifecycle_flush":
        original = original_payments.sync_lifecycle_from_payments
        async def fail(*args, **kwargs):
            await original(*args, **kwargs)
            raise RuntimeError("Synthetic failure after original lifecycle commit request")
        monkeypatch.setattr(original_payments, "sync_lifecycle_from_payments", fail)
    elif fault == "commission_rollback":
        async def fail(*args, **kwargs):
            raise RuntimeError("Synthetic commission failure")
        monkeypatch.setattr(original_payments, "sync_payment_commission", fail)
    elif fault == "audit_flush":
        original = service.append_audit
        async def fail(*args, **kwargs):
            if args[3] == "post":
                raise RuntimeError("Synthetic audit failure")
            return await original(*args, **kwargs)
        monkeypatch.setattr(service, "append_audit", fail)
    else:
        original = AsyncSession.commit
        async def fail(self):
            if any(isinstance(value, FinanceEntryDraft) and value.status == "posted" for value in self.identity_map.values()):
                raise RuntimeError("Synthetic outer commit failure")
            return await original(self)
        monkeypatch.setattr(AsyncSession, "commit", fail)
    response = await action(env, row, "post")
    assert response.status_code in {409, 500}, response.text
    assert await counts(env) == before
    current = (await env.client.get(f"{PREFIX}/{row['id']}")).json()
    assert current["status"] == "submitted" and current["revision"] == row["revision"]
    assert current["posted_id"] is None


@pytest.mark.asyncio
async def test_one_owner_post_has_only_one_real_commit(env, monkeypatch):
    row = await submitted(env)
    env.user = OWNER
    actual = AsyncSession.commit
    calls = []
    async def track(self):
        calls.append(self)
        return await actual(self)
    monkeypatch.setattr(AsyncSession, "commit", track)
    response = await action(env, row, "post")
    assert response.status_code == 200, response.text
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("same_key", [True, False])
async def test_two_connections_confirm_once_and_lost_response_retry_is_safe(env, same_key):
    row = await submitted(env)
    env.user = OWNER
    first_key = "parallel-confirm-1"
    responses = await asyncio.gather(action(env, row, "post", key=first_key), action(env, row, "post", key=first_key if same_key else "parallel-confirm-2"))
    assert sorted(item.status_code for item in responses) == ([200, 200] if same_key else [200, 409]), [item.text for item in responses]
    assert (await counts(env))["payments"] == 1
    winning_key = first_key if responses[0].status_code == 200 else "parallel-confirm-2"
    replay = await action(env, row, "post", key=winning_key)
    assert replay.status_code == 200
    assert (await counts(env))["payments"] == 1


def test_migration_only_creates_three_empty_domain_tables(tmp_path):
    path = Path(__file__).parents[1] / "alembic/versions/a8d4e2c6f901_finance_entry_drafts.py"
    spec = importlib.util.spec_from_file_location("synthetic_entry_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine(f"sqlite:///{tmp_path / 'synthetic-migration.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE existing_finance_sentinel(id INTEGER PRIMARY KEY, amount INTEGER)"))
        conn.execute(text("INSERT INTO existing_finance_sentinel VALUES(1,12345)"))
        before = conn.execute(text("SELECT sql FROM sqlite_master WHERE name='existing_finance_sentinel'")).scalar()
        module.op = Operations(MigrationContext.configure(conn))
        module.upgrade()
        names = set(conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'" )).scalars())
        assert names == {"existing_finance_sentinel", "finance_entry_drafts", "finance_entry_draft_audits", "finance_entry_attachments"}
        assert conn.execute(text("SELECT sql FROM sqlite_master WHERE name='existing_finance_sentinel'")).scalar() == before
        assert conn.execute(text("SELECT amount FROM existing_finance_sentinel")).scalar() == 12345
        for name in names - {"existing_finance_sentinel"}:
            assert conn.execute(text(f"SELECT COUNT(*) FROM {name}")).scalar() == 0
        with pytest.raises(RuntimeError, match="forward migration"):
            module.downgrade()
        assert conn.execute(text("SELECT amount FROM existing_finance_sentinel")).scalar() == 12345
        assert set(conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).scalars()) == names
    engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["customer_expense", "company_expense"])
async def test_expense_rejects_other_currencies_and_customer_ad_cost(env, kind):
    payload = {"amount": 12, "currency": "EUR", "expense_date": "2026-10-26", "evidence_reference": "Synthetic receipt", **({"expense_type": "design_fee"} if kind == "customer_expense" else {"category": "ai_tools"})}
    response = await env.client.post(PREFIX, json={"client_request_id": str(uuid4()), "kind": kind, "customer_id": 10 if kind == "customer_expense" else None, "payload": payload})
    assert response.status_code == 422
    if kind == "customer_expense":
        payload.update(currency="USD", expense_type="ads_fee")
        response = await env.client.post(PREFIX, json={"client_request_id": str(uuid4()), "kind": kind, "customer_id": 10, "payload": payload})
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_manual_credit_card_uses_original_zero_stripe_fee_rule(env):
    row = await submitted(env, payload=receipt(payment_method="credit_card", amount_paid=80, amount_due=100))
    env.user = OWNER
    response = await action(env, row, "post")
    assert response.status_code == 200, response.text
    async with env.sessions() as db:
        payment = await db.get(Payments, response.json()["posted_id"])
        assert payment.stripe_fee_amount == 0 and payment.net_amount == 80 and payment.outstanding_amount == 20


@pytest.mark.asyncio
async def test_poison_cannot_be_swallowed_by_an_old_handler(env, monkeypatch):
    row = await submitted(env)
    before = await counts(env)
    actual = original_payments.create_payments
    async def swallowed(data, current_user, db):
        ledger = await actual(data, current_user=current_user, db=db)
        try:
            await db.rollback()
        except BaseException:
            pass
        return ledger
    monkeypatch.setattr(original_payments, "create_payments", swallowed)
    env.user = OWNER
    response = await action(env, row, "post")
    assert response.status_code == 409
    assert await counts(env) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [None, SimpleNamespace(id=0), SimpleNamespace(id=True)])
async def test_invalid_old_handler_result_is_not_linked_or_posted(env, monkeypatch, value):
    row = await submitted(env)
    before = await counts(env)
    async def invalid(*args, **kwargs):
        return value
    monkeypatch.setattr(original_payments, "create_payments", invalid)
    env.user = OWNER
    response = await action(env, row, "post")
    assert response.status_code == 409
    assert await counts(env) == before


@pytest.mark.asyncio
async def test_void_is_owner_only_terminal_and_audited_without_ledger_write(env):
    row = await create(env)
    assert (await action(env, row, "void", reason="取消登记事项")).status_code == 403
    env.user = OWNER
    response = await action(env, row, "void", reason="重复登记已作废")
    assert response.status_code == 200 and response.json()["status"] == "voided"
    assert (await action(env, response.json(), "post")).status_code == 409
    assert (await counts(env))["payments"] == 0
