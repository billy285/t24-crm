"""Synthetic accounting invariants. No runtime database or external network used."""
import importlib.util
import json
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from models.commissions import CommissionAgreement, CommissionEntry, CustomerCommissionAttribution, SalesPartner
from models.customers import Customers
from models.finance_refunds import FinanceRefund
from models.payments import Payments
from services.commissions import (
    assign_customer_commission_owner, commission_data_quality, preview_customer_commission_owner,
    preview_payment_commission, scan_commissions, sync_refund_commission,
    validate_commission_entry_confirmation, validate_commission_entry_reversal,
)
from tests.test_commission_ledger import _create_tables


def day(value):
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def payment(pid=1, amount=1000, paid="2026-01-15", start=None, end=None, cycle="monthly"):
    return Payments(id=pid, customer_id=1, customer_name="Synthetic", income_type="service_fee",
        amount_due=amount, amount_paid=amount, currency="USD", payment_date=day(paid) if paid else None,
        created_at=day("2026-01-01"), user_id="fixture", billing_cycle=cycle,
        coverage_start=day(start) if start else None, coverage_end=day(end) if end else None)


@asynccontextmanager
async def fixture(mode="first_month_then_renewal", first="2026-01-01", start="2026-01-01"):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    await _create_tables(engine)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        db.add(Customers(id=1, business_name="Synthetic", contact_name="Owner", phone="1"))
        for pid in (1, 2):
            db.add(SalesPartner(id=pid, partner_code=f"S{pid}", name=f"Synthetic {pid}", partner_type="partner",
                status="active", joined_at=date(2026, 1, 1)))
            db.add(CommissionAgreement(id=pid, partner_id=pid, version=1, first_order_rate=.5, renewal_rate=.2,
                calculation_version="service_month_v2", renewal_policy="fixed", activity_decay_json='{"0":1,"1":0.8,"6":0}',
                refund_guard_days=0, effective_from=date(2026, 1, 1), status="active"))
        db.add(CustomerCommissionAttribution(id=1, customer_id=1, partner_id=1, attribution_role="primary",
            effective_from=date(2026, 1, 1), is_active=True, commission_mode=mode,
            first_service_start=date.fromisoformat(first) if first else None,
            commission_start_date=date.fromisoformat(start) if start else None,
            history_basis="First period was settled externally" if mode == "renewal_only" else None))
        await db.commit()
        yield db
    await engine.dispose()


async def entries(db):
    return list((await db.scalars(select(CommissionEntry).order_by(CommissionEntry.id))).all())


@pytest.mark.asyncio
async def test_all_receipts_in_first_service_month_use_first_rate_then_fixed_renewal():
    async with fixture(first="2026-01-15") as db:
        db.add_all([payment(1, paid="2026-01-15"), payment(2, paid="2026-02-14"),
                    payment(3, paid="2026-02-15"), payment(4, paid="2026-09-01")])
        await db.commit()
        await scan_commissions(db)
        rows = await entries(db)
        assert [r.commission_amount for r in rows] == [500, 500, 200, 200]
        assert [r.entry_type for r in rows] == ["first_order", "first_order", "renewal", "renewal"]
        assert all(r.activity_multiplier == 1 for r in rows)


@pytest.mark.asyncio
async def test_yearly_receipt_day_prorates_first_period_and_keeps_cash_month():
    async with fixture() as db:
        db.add(payment(amount=3650, paid="2026-01-20", start="2026-01-01", end="2027-01-01", cycle="yearly"))
        await db.commit()
        await scan_commissions(db)
        assert (await scan_commissions(db))["entries_created"] == 0
        rows = await entries(db)
        assert len(rows) == 2
        assert [r.eligible_service_amount for r in rows] == [310, 3340]
        assert [r.commission_amount for r in rows] == [155, 668]
        assert {r.service_month for r in rows} == {"2026-01"}
        assert json.loads(rows[0].snapshot_json)["service_period_end"] == "2026-02-01"
        assert json.loads(rows[1].snapshot_json)["service_period_end"] == "2027-01-01"
        await validate_commission_entry_confirmation(db, rows[0])
        rows[0].status = "confirmed"
        await db.commit()
        await validate_commission_entry_confirmation(db, rows[1])  # non-overlap is allowed


@pytest.mark.asyncio
async def test_rounding_remainder_and_month_end_anchor_are_exact():
    async with fixture(first="2026-01-31") as db:
        db.add(payment(amount=100.01, paid="2026-01-31", start="2026-01-31", end="2026-03-31", cycle="quarterly"))
        await db.commit()
        await scan_commissions(db)
        rows = await entries(db)
        assert round(sum(r.eligible_service_amount for r in rows), 2) == 100.01
        assert json.loads(rows[0].snapshot_json)["service_period_end"] == "2026-02-28"
        assert rows[0].eligible_service_amount == 47.46
        assert rows[1].eligible_service_amount == 52.55


@pytest.mark.asyncio
async def test_renewal_only_excludes_earlier_service_days_without_inventing_payment():
    async with fixture(mode="renewal_only", start="2026-02-15") as db:
        db.add(payment(amount=590, paid="2026-02-20", start="2026-01-01", end="2026-03-01", cycle="quarterly"))
        await db.commit()
        await scan_commissions(db)
        rows = await entries(db)
        assert len(rows) == 1 and rows[0].entry_type == "renewal"
        assert rows[0].eligible_service_amount == 140 and rows[0].commission_amount == 28
        snap = json.loads(rows[0].snapshot_json)
        assert snap["excluded_service_amount"] == 450
        assert snap["history_basis"] == "First period was settled externally"
        assert rows[0].service_month == "2026-02"


@pytest.mark.parametrize("cycle", ["quarterly", "annual", "yearly", "6 months", "unknown"])
@pytest.mark.asyncio
async def test_ambiguous_long_coverage_fails_closed(cycle):
    async with fixture() as db:
        p = payment(cycle=cycle)
        db.add(p)
        await db.commit()
        assert (await preview_payment_commission(db, p))["issues"]
        await scan_commissions(db)
        assert await entries(db) == []
        assert any(r["type"] == "commission_rule_review" for r in (await commission_data_quality(db))["issues"])


@pytest.mark.asyncio
async def test_missing_payment_date_does_not_invent_commission_date():
    async with fixture() as db:
        db.add_all([payment(1, paid=None), payment(2, paid="2026-02-20")])
        await db.commit()
        await scan_commissions(db)
        rows = await entries(db)
        assert len(rows) == 1 and rows[0].payment_id == 2 and rows[0].entry_type == "renewal"
        assert any("到账日期" in r["description"] for r in (await commission_data_quality(db))["issues"])


@pytest.mark.asyncio
async def test_legacy_configuration_cannot_silently_start_new_calculation():
    async with fixture(mode="legacy", first=None, start=None) as db:
        p = payment()
        db.add(p)
        await db.commit()
        assert "历史归属" in (await preview_payment_commission(db, p))["issues"][0]
        await scan_commissions(db)
        assert not await entries(db)


@pytest.mark.asyncio
async def test_pending_owner_transfer_voids_old_candidate_and_never_duplicates_active():
    async with fixture() as db:
        db.add(payment(paid="2026-01-20"))
        await db.commit()
        await scan_commissions(db)
        await assign_customer_commission_owner(db, customer_id=1, partner_id=2, effective_from=date(2026,1,15),
            commission_mode="first_month_then_renewal", commission_start_date=date(2026,1,15), first_service_start=date(2026,1,1))
        await db.commit()
        await scan_commissions(db)
        rows = await entries(db)
        assert [(r.partner_id, r.status) for r in rows] == [(1, "reversed"), (2, "pending_confirmation")]
        await validate_commission_entry_confirmation(db, rows[1])
        with pytest.raises(ValueError, match="归属已变化"):
            await validate_commission_entry_confirmation(db, rows[0])


@pytest.mark.asyncio
async def test_confirmed_owner_transfer_is_rejected_and_original_snapshot_unchanged():
    async with fixture() as db:
        db.add(payment(paid="2026-01-20"))
        await db.commit()
        await scan_commissions(db)
        row = (await entries(db))[0]
        row.status = "confirmed"
        await db.commit()
        original = (row.commission_amount, row.snapshot_json, row.partner_id, row.agreement_id)
        kwargs = dict(customer_id=1, partner_id=2, effective_from=date(2026,1,15), commission_mode="first_month_then_renewal",
                      commission_start_date=date(2026,1,15), first_service_start=date(2026,1,1))
        assert (await preview_customer_commission_owner(db, **kwargs))["blocked"]
        with pytest.raises(ValueError, match="已确认佣金"):
            await assign_customer_commission_owner(db, **kwargs)
        await scan_commissions(db)
        assert (row.commission_amount, row.snapshot_json, row.partner_id, row.agreement_id) == original


@pytest.mark.asyncio
async def test_same_partner_new_rule_is_versioned_instead_of_silently_ignored():
    async with fixture() as db:
        db.add(payment(paid="2026-02-20"))
        await db.commit()
        await scan_commissions(db)
        new = await assign_customer_commission_owner(db, customer_id=1, partner_id=1, effective_from=date(2026,2,1),
            commission_mode="none", commission_start_date=date(2026,2,1))
        await db.commit()
        await scan_commissions(db)
        assert new.id != 1 and new.commission_mode == "none"
        assert all(row.status == "reversed" for row in await entries(db))
        assert not (await db.get(CustomerCommissionAttribution, 1)).is_active


def refund(rid=1, amount=1000):
    return FinanceRefund(id=rid, payment_id=1, customer_id=1, customer_name="Synthetic", refund_amount=amount,
        currency="USD", refund_date=day("2026-03-01"), provider="manual", stripe_fee_refunded_amount=0,
        status="completed", created_at=day("2026-03-01"), user_id="fixture")


@pytest.mark.asyncio
async def test_voided_original_never_produces_negative_profit_expense():
    async with fixture() as db:
        db.add(payment())
        await db.commit()
        await scan_commissions(db)
        (await entries(db))[0].status = "reversed"
        db.add(refund())
        await db.commit()
        await scan_commissions(db)
        assert len(await entries(db)) == 1


@pytest.mark.asyncio
async def test_split_refund_is_proportional_idempotent_and_requires_original_confirmation():
    async with fixture() as db:
        db.add(payment(amount=590, start="2026-01-01", end="2026-03-01", cycle="quarterly"))
        await db.commit()
        await scan_commissions(db)
        db.add(refund(amount=295))
        await db.commit()
        await scan_commissions(db)
        assert (await scan_commissions(db))["entries_created"] == 0
        rows = await entries(db)
        originals, reversals = rows[:2], rows[2:]
        assert [r.commission_amount for r in originals] == [155, 56]
        assert [r.commission_amount for r in reversals] == [-77.5, -28]
        with pytest.raises(ValueError, match="原佣金尚未确认"):
            await validate_commission_entry_confirmation(db, reversals[0])
        originals[0].status = "confirmed"
        await db.commit()
        await validate_commission_entry_confirmation(db, reversals[0])
        reversals[0].status = "confirmed"
        await db.commit()
        with pytest.raises(ValueError, match="已有已确认退款"):
            await validate_commission_entry_reversal(db, originals[0])


@pytest.mark.asyncio
async def test_manually_existing_cross_partner_locked_entry_prevents_double_confirmation():
    async with fixture() as db:
        db.add(payment())
        await db.commit()
        await scan_commissions(db)
        row = (await entries(db))[0]
        copy = CommissionEntry(partner_id=2, agreement_id=2, attribution_id=2, customer_id=1, payment_id=1,
            entry_type="first_order", status="confirmed", service_month="2026-01", occurred_at=day("2026-01-15"),
            currency="USD", gross_receipt_amount=1000, eligible_service_amount=1000, contract_rate=.5,
            inactivity_months=0, activity_multiplier=1, commission_amount=500, snapshot_json="{}", idempotency_key="legacy-bad-fixture")
        db.add(copy)
        await db.commit()
        with pytest.raises(ValueError, match="其他渠道"):
            await validate_commission_entry_confirmation(db, row)


@pytest.mark.asyncio
async def test_legacy_locked_snapshot_preserved_byte_for_byte_even_after_new_rule():
    async with fixture() as db:
        db.add(payment())
        legacy = CommissionEntry(partner_id=1, agreement_id=1, attribution_id=1, customer_id=1, payment_id=1,
            entry_type="renewal", status="paid", service_month="2026-01", occurred_at=day("2026-01-15"),
            currency="USD", gross_receipt_amount=1000, eligible_service_amount=1000, contract_rate=.2,
            inactivity_months=2, activity_multiplier=.6, commission_amount=120,
            snapshot_json='{"calculation":"legacy proof", "decay":0.6}', idempotency_key="payment:1:partner:1")
        db.add(legacy)
        await db.commit()
        before = dict((await db.execute(text("SELECT * FROM commission_entries WHERE id=:id"), {"id": legacy.id})).mappings().one())
        await scan_commissions(db)
        after = dict((await db.execute(text("SELECT * FROM commission_entries WHERE id=:id"), {"id": legacy.id})).mappings().one())
        assert before == after


def test_migration_keeps_old_rules_explicitly_legacy_without_touching_entries():
    migration_path = Path(__file__).parents[1] / "alembic/versions/b3e7c1d9a614_commission_service_month_rules.py"
    spec = importlib.util.spec_from_file_location("commission_rules_migration", migration_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE sales_partners (id INTEGER PRIMARY KEY, employee_id INTEGER, partner_type TEXT)"))
        conn.execute(text("CREATE TABLE commission_agreements (id INTEGER PRIMARY KEY, first_order_rate FLOAT)"))
        conn.execute(text("CREATE TABLE customer_commission_attributions (id INTEGER PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE commission_entries (id INTEGER PRIMARY KEY, snapshot_json TEXT)"))
        conn.execute(text("INSERT INTO commission_agreements VALUES (1, 0.5)"))
        conn.execute(text("INSERT INTO customer_commission_attributions VALUES (1)"))
        conn.execute(text("INSERT INTO commission_entries VALUES (1, 'untouched')"))
        with Operations.context(MigrationContext.configure(conn)):
            module.upgrade()
        assert conn.execute(text("SELECT calculation_version,renewal_policy FROM commission_agreements")).one() == ("legacy_v1", "activity_decay")
        assert conn.execute(text("SELECT commission_mode,first_service_start FROM customer_commission_attributions")).one() == ("legacy", None)
        assert conn.execute(text("SELECT snapshot_json FROM commission_entries")).scalar() == "untouched"
    engine.dispose()


@pytest.mark.asyncio
async def test_partial_refund_rounding_sums_to_original_without_extra_cent():
    async with fixture() as db:
        db.add(payment(amount=.1))  # original commission .05
        await db.commit()
        await scan_commissions(db)
        (await entries(db))[0].status = "confirmed"
        db.add_all([refund(1, .05), refund(2, .05)])
        await db.commit()
        await scan_commissions(db)
        rows = await entries(db)
        assert rows[0].commission_amount == .05
        assert round(sum(row.commission_amount for row in rows[1:]), 2) == -.05
        for row in rows[1:]:
            await validate_commission_entry_confirmation(db, row)
            row.status = "confirmed"
            await db.commit()
        assert round(sum(row.commission_amount for row in rows), 2) == 0


@pytest.mark.asyncio
async def test_renewal_only_requires_history_but_does_not_require_unknown_historical_start():
    async with fixture() as db:
        args = dict(customer_id=1, partner_id=1, effective_from=date(2026,2,1), commission_mode="renewal_only",
                    commission_start_date=date(2026,2,1), first_service_start=date(2026,1,1))
        with pytest.raises(ValueError, match="已结清依据"):
            await preview_customer_commission_owner(db, **args)
        result = await preview_customer_commission_owner(db, **{**args, "first_service_start": None, "history_basis": "receipt proof"})
        assert not result["blocked"]


def test_migration_duplicate_binding_fails_before_any_schema_change():
    migration_path = Path(__file__).parents[1] / "alembic/versions/b3e7c1d9a614_commission_service_month_rules.py"
    spec = importlib.util.spec_from_file_location("commission_rules_migration_duplicates", migration_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE sales_partners (id INTEGER PRIMARY KEY, employee_id INTEGER, partner_type TEXT)"))
        conn.execute(text("INSERT INTO sales_partners VALUES (1, 7, 'agency'), (2, 7, 'partner')"))
        with Operations.context(MigrationContext.configure(conn)):
            with pytest.raises(RuntimeError, match="duplicate external channel"):
                module.upgrade()
        assert not conn.execute(text("SELECT name FROM sqlite_master WHERE type='index' AND name='uq_external_partner_employee'")).first()
        assert conn.execute(text("SELECT COUNT(*) FROM sales_partners")).scalar() == 2
    engine.dispose()


@pytest.mark.asyncio
async def test_unknown_first_date_renewal_only_counts_only_explicit_commission_period():
    async with fixture(mode="renewal_only", first=None, start="2026-02-15") as db:
        db.add(payment(amount=590, paid="2026-02-20", start="2026-01-01", end="2026-03-01", cycle="quarterly"))
        await db.commit()
        await scan_commissions(db)
        rows = await entries(db)
        assert len(rows) == 1 and rows[0].entry_type == "renewal" and rows[0].commission_amount == 28
        assert json.loads(rows[0].snapshot_json)["first_service_start"] is None
        await validate_commission_entry_confirmation(db, rows[0])


@pytest.mark.asyncio
async def test_stale_zero_amount_and_legacy_pending_cannot_be_confirmed():
    async with fixture() as db:
        p = payment()
        db.add(p)
        await db.commit()
        await scan_commissions(db)
        row = (await entries(db))[0]
        p.amount_paid = 0
        await db.commit()
        await scan_commissions(db)
        with pytest.raises(ValueError, match="计佣依据已变化"):
            await validate_commission_entry_confirmation(db, row)
        row.snapshot_json = "{}"
        await db.commit()
        with pytest.raises(ValueError, match="历史待确认佣金"):
            await validate_commission_entry_confirmation(db, row)
