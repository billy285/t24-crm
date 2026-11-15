from contextlib import asynccontextmanager
from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from models.commissions import (
    CommissionAgreement, CommissionEntry, CommissionStatement, CommissionStatementCycle,
    CommissionStatementLine, CommissionStatusEvent, SalesPartner,
)
from models.finance_profit_closes import MonthlyProfitClose
from models.finance_refunds import FinanceRefund
from models.customers import Customers
from services.commissions import scan_commissions
from services.commission_statements import (
    assert_entry_outside_statement, get_statement, list_statements, reconcile_statements,
    settle_statement, statement_reminders,
)
from tests.test_commission_service_month_rules import day, fixture, payment


@asynccontextmanager
async def db_with_months(*, guard=0):
    async with fixture() as db:
        conn = await db.connection()
        for t in (CommissionStatement, CommissionStatementLine, CommissionStatementCycle):
            await conn.run_sync(t.__table__.create)
        agreement = await db.get(CommissionAgreement, 1)
        agreement.refund_guard_days = guard
        await db.commit()
        yield db


async def refresh(db, now):
    await scan_commissions(db, commit=False)
    await reconcile_statements(db, now=day(now))
    await db.commit()


async def settle(db, summary, *, now="2026-02-15", reference="bank1"):
    return await settle_statement(db, summary["id"], payout_reference=reference,
        expected_total=summary["total_amount"], expected_entry_count=summary["entry_count"],
        revision=summary["revision"], actor_id="1", actor_name="Finance", now=day(now))


@pytest.mark.asyncio
async def test_issue_schedule_guard_deferral_and_no_double_settlement():
    async with db_with_months(guard=30) as db:
        db.add_all([payment(pid=1, paid="2026-01-10", amount=200),
                    payment(pid=2, paid="2026-01-28", amount=300)])
        await refresh(db, "2026-01-31T12:00:00")
        assert not (await list_statements(db, "2026-01", now=day("2026-01-31T15:59:59")))["items"]
        await refresh(db, "2026-01-31T16:00:00")   # midnight Feb 1 in Beijing
        jan = (await list_statements(db, "2026-01", now=day("2026-02-01")))["items"][0]
        assert (jan["issue_date"], jan["due_date"]) == (date(2026, 2, 1), date(2026, 2, 15))
        assert (jan["status"], jan["entry_count"], jan["deferred_count"], jan["total_amount"],
                jan["deferred_amount"]) == ("scheduled", 1, 1, 100, 150)
        detail = await get_statement(db, jan["id"], now=day("2026-02-01"))
        assert detail["deferred_entries"][0]["due_date"] == date(2026, 3, 15)
        assert not (await list_statements(db,"2026-02",now=day("2026-02-15")))["items"]
        with pytest.raises(HTTPException) as err:
            await settle(db, jan, now="2026-02-14")
        assert err.value.status_code == 409
        jan = (await list_statements(db,"2026-01",now=day("2026-02-15")))["items"][0]
        assert (await statement_reminders(db,now=day("2026-02-15")))["items"] == [
            {"month":"2026-01","ready_count":1,"review_count":0}]
        paid = await settle(db, jan)
        await db.commit()
        assert paid["status"] == "paid" and paid["total_amount"] == 100
        assert (await settle(db, jan)) == paid
        with pytest.raises(HTTPException):
            await settle(db, jan, reference="other")
        assert not (await statement_reminders(db,now=day("2026-02-15")))["items"]
        feb = (await list_statements(db,"2026-02",now=day("2026-03-15")))["items"][0]
        assert feb["total_amount"] == 150 and feb["status"] == "ready"
        assert (await get_statement(db,feb["id"],now=day("2026-03-15")))["entries"][0]["source_month"] == "2026-01"
        assert (await db.scalar(select(func.count(CommissionStatusEvent.id)))) == 3
        with pytest.raises(HTTPException):
            await assert_entry_outside_statement(db, paid["entries"][0]["entry_id"])


@pytest.mark.asyncio
async def test_original_refund_atomicity_revisions_and_late_revenue():
    async with db_with_months() as db:
        db.add(payment(pid=1, amount=1000))
        await refresh(db,"2026-02-15")
        jan = (await list_statements(db,"2026-01",now=day("2026-02-15")))["items"][0]
        db.add(FinanceRefund(customer_id=1,payment_id=1,currency="USD",refund_amount=200,
                             status="completed", refund_date=day("2026-01-22"), reason="refund", created_at=day("2026-01-22"), user_id="finance"))
        await refresh(db,"2026-02-15")
        with pytest.raises(HTTPException) as err:
            await settle(db, jan)
        assert "已变化" in str(err.value.detail)
        jan = await get_statement(db, jan["id"], now=day("2026-02-15"))
        assert jan["total_amount"] == 400
        paid = await settle(db, jan)
        await db.commit()
        assert set(x["entry_type"] for x in paid["entries"]) == {"first_order","refund_reversal"}
        assert len((await db.scalars(select(CommissionEntry).where(CommissionEntry.status=="paid"))).all()) == 2
        db.add(payment(pid=2,amount=100,paid="2026-01-20"))
        await refresh(db,"2026-03-15")
        assert await get_statement(db,jan["id"],now=day("2026-03-15")) == paid
        other = (await list_statements(db,"2026-02",now=day("2026-03-15")))["items"][0]
        assert other["total_amount"] == 50
        with pytest.raises(HTTPException) as err:
            await settle(db,other,now="2026-03-15")
        assert "已登记" in str(err.value.detail)
        assert (await settle(db,other,now="2026-03-15",reference="bank2"))["status"] == "paid"


@pytest.mark.asyncio
async def test_separate_currencies_and_protection_issues():
    async with db_with_months() as db:
        rmb = payment(pid=2, amount=600)
        rmb.currency = "CNY"
        db.add_all([payment(pid=1,amount=198),rmb])
        await refresh(db,"2026-02-15")
        statements = (await list_statements(db,"2026-01",now=day("2026-02-15")))["items"]
        assert [(r["currency"],r["total_amount"]) for r in statements] == [("CNY",300),("USD",99)]
        db.add(MonthlyProfitClose(year_month="2026-01",status="locked",snapshot_json="{}",locked_by="finance"))
        await db.commit()
        closed = await get_statement(db,statements[1]["id"],now=day("2026-02-15"))
        assert closed["status"] == "needs_review" and "已关账" in str(closed["issues"])
        with pytest.raises(HTTPException):
            await settle(db,statements[1])
        assert (await db.scalar(select(func.count(CommissionStatusEvent.id)))) == 0
        await db.delete(await db.scalar(select(MonthlyProfitClose)))
        (await db.get(SalesPartner,1)).status = "suspended"
        await db.commit()
        assert (await get_statement(db,statements[0]["id"],now=day("2026-02-15")))["status"] == "needs_review"


@pytest.mark.asyncio
async def test_unknown_owner_and_historical_agreement_have_no_fabricated_totals():
    async with db_with_months() as db:
        (await db.get(CommissionAgreement,1)).calculation_version = "legacy_v1"
        db.add(Customers(id=10,business_name="No owner",phone="20",contact_name="Test"))
        no_owner = payment(pid=2)
        no_owner.customer_id = 10
        db.add_all([payment(pid=1),no_owner])
        await refresh(db,"2026-02-15")
        result = await list_statements(db,"2026-01",now=day("2026-02-15"))
        assert result["items"][0]["status"] == "needs_review"
        assert result["items"][0]["total_amount"] == 0
        assert "历史规则" in str(result["items"][0]["issues"])
        assert [i["payment_id"] for i in result["issues"]] == [2]
        assert (await list_statements(db,"2026-01",partner_id=2,now=day("2026-02-15"))) == {
            "month":"2026-01","items":[],"issues":[]}


@pytest.mark.asyncio
async def test_transactions_rollback_all_previous_lines_when_a_later_candidate_fails():
    async with db_with_months() as db:
        db.add_all([payment(pid=1,amount=400),payment(pid=2,amount=200)])
        await refresh(db,"2026-02-15")
        jan = (await list_statements(db,"2026-01",now=day("2026-02-15")))["items"][0]
        # A newer receipt edits the second candidate after the finance user previews it.
        from models.payments import Payments
        (await db.get(Payments,2)).amount_paid = 2
        await db.commit()
        with pytest.raises(HTTPException) as err:
            await settle(db,jan)
        assert err.value.status_code == 409
        await db.commit()  # Even a caller catching the failure cannot commit a partial payout.
        assert list((await db.scalars(select(CommissionEntry.status))).all()) == ["pending_confirmation"] * 2
        assert (await db.scalar(select(func.count(CommissionStatusEvent.id)))) == 0
        assert (await db.get(CommissionStatement,jan["id"])).paid_at is None


@pytest.mark.asyncio
async def test_concurrent_settlement_of_same_statement_keeps_one_receipt(tmp_path):
    import asyncio
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

    path = tmp_path / "parallel.db"
    async with db_with_months() as db:
        db.add(payment(pid=1,amount=198))
        await refresh(db,"2026-02-15")
        jan = (await list_statements(db,"2026-01",now=day("2026-02-15")))["items"][0]
        await db.commit()
        await db.execute(text("VACUUM INTO :target"), {"target": str(path)})

    engine = create_async_engine("sqlite+aiosqlite:///" + str(path))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async def pay(reference):
        async with sessions() as session:
            try:
                result = await settle(session,jan,reference=reference)
                await session.commit()
                return result["payout_reference"]
            except HTTPException as exc:
                await session.rollback()
                return exc.status_code
    assert sorted(await asyncio.gather(pay("same"),pay("same"))) == ["same","same"]
    assert await pay("another") == 409
    async with sessions() as session:
        assert await session.scalar(select(func.count(CommissionStatusEvent.id))) == 3
        assert await session.scalar(select(func.count(CommissionStatementLine.id))) == 1
    await engine.dispose()


def test_migration_adds_only_statement_tables_and_reverses_cleanly():
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect, text

    script = Path(__file__).parents[1] / "alembic/versions/k76cd890c136_monthly_commission_statements.py"
    spec = importlib.util.spec_from_file_location("synthetic_statement_migration", script)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE sales_partners (id INTEGER PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE commission_entries (id INTEGER PRIMARY KEY)"))
        conn.execute(text("INSERT INTO commission_entries VALUES (1)"))
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
            assert set(inspect(conn).get_table_names()) == {"commission_statement_cycles",
                "commission_statements", "commission_statement_lines","sales_partners","commission_entries"}
            assert {c["name"] for c in inspect(conn).get_unique_constraints("commission_statements")} == {
                "uq_commission_statement_payout","uq_commission_statement_period"}
            migration.downgrade()
            assert set(inspect(conn).get_table_names()) == {"sales_partners","commission_entries"}
            assert conn.scalar(text("SELECT COUNT(*) FROM commission_entries")) == 1
    engine.dispose()


@pytest.mark.asyncio
async def test_previously_confirmed_legacy_snapshot_can_settle_unchanged_or_be_paid_separately():
    async with db_with_months() as db:
        cny = payment(pid=2,amount=100)
        cny.currency = "CNY"
        db.add_all([payment(pid=1,amount=100),cny])
        await scan_commissions(db)
        rows = list((await db.scalars(select(CommissionEntry).order_by(CommissionEntry.id))).all())
        # Old, recognized rates/snapshots do not need a new agreement or recomputation.
        for row in rows:
            row.snapshot_json = '{"calculation_version":"legacy_v1","activity_multiplier":0.6}'
            row.commission_amount = 30
            row.status = "confirmed"
        await db.commit()
        await reconcile_statements(db,now=day("2026-02-15"))
        statements = (await list_statements(db,"2026-01",now=day("2026-02-15")))["items"]
        cny_statement, usd_statement = statements
        await assert_entry_outside_statement(db,rows[0].id,transition="payable")
        rows[0].status = "payable"
        await db.flush()
        await assert_entry_outside_statement(db,rows[0].id,transition="paid")
        rows[0].status, rows[0].payout_reference = "paid", "legacy-payment"
        await db.commit()
        assert [(s["currency"],s["total_amount"]) for s in
                (await list_statements(db,"2026-01",now=day("2026-02-15")))["items"]] == [("CNY",30)]
        with pytest.raises(HTTPException) as removed:
            await get_statement(db,usd_statement["id"],now=day("2026-02-15"))
        assert removed.value.status_code == 410
        paid = await settle(db,cny_statement)
        await db.commit()
        assert paid["total_amount"] == 30
        assert rows[0].payout_reference == "legacy-payment"
        assert not (await statement_reminders(db,now=day("2026-02-15")))["items"]
