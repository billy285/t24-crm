import json
from datetime import date, datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from models.commissions import (
    CommissionAgreement,
    CommissionEntry,
    CommissionStatusEvent,
    CustomerCommissionAttribution,
    SalesPartner,
)
from models.customers import Customers
from models.employees import Employees
from models.finance_refunds import FinanceRefund
from models.management_decisions import BusinessLine, CustomerEngagement, ProductCatalog
from models.payments import Payments
from routers.commissions import EntryTransitionInput, transition_entry
from schemas.auth import UserResponse
from services.commissions import scan_commissions


async def _create_tables(engine) -> None:
    tables = [
        Employees.__table__, Customers.__table__, Payments.__table__, FinanceRefund.__table__,
        BusinessLine.__table__, ProductCatalog.__table__, CustomerEngagement.__table__,
        SalesPartner.__table__, CommissionAgreement.__table__, CustomerCommissionAttribution.__table__,
        CommissionEntry.__table__, CommissionStatusEvent.__table__,
    ]
    async with engine.begin() as connection:
        for table in tables:
            await connection.run_sync(table.create)


def _payment(customer_id: int, payment_id: int, when: datetime, amount: float = 1000, *, ads: float = 0, business_line_id: int | None = None) -> Payments:
    return Payments(
        id=payment_id, customer_id=customer_id, customer_name=f"C{customer_id}", income_type="service_fee",
        amount_due=amount, amount_paid=amount, ads_recharge_amount=ads, currency="USD", payment_date=when,
        created_at=when, user_id="finance",
        business_line_id=business_line_id,
    )


@pytest.mark.asyncio
async def test_commission_scan_is_idempotent_excludes_ads_applies_decay_and_refund_reversal():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    await _create_tables(engine)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as db:
        db.add_all([
            Customers(id=1, customer_code="C001", business_name="First", contact_name="Owner", phone="1"),
            Customers(id=2, customer_code="C002", business_name="Second", contact_name="Owner", phone="2"),
            SalesPartner(id=1, partner_code="P001", name="Partner", partner_type="partner", status="active", joined_at=date(2026, 1, 1)),
            CommissionAgreement(
                id=1, partner_id=1, version=1, first_order_rate=.5, renewal_rate=.2,
                activity_decay_json=json.dumps({0: 1, 1: .8, 2: .6, 3: .4, 4: .25, 5: .1, 6: 0}),
                refund_guard_days=30, effective_from=date(2026, 1, 1), status="active",
            ),
            CustomerCommissionAttribution(id=1, customer_id=1, partner_id=1, attribution_role="primary", effective_from=date(2026, 1, 1), is_active=True),
            CustomerCommissionAttribution(id=2, customer_id=2, partner_id=1, attribution_role="primary", effective_from=date(2026, 3, 1), is_active=True),
            _payment(1, 1, datetime(2026, 1, 5, tzinfo=timezone.utc), business_line_id=1),
            _payment(1, 2, datetime(2026, 2, 5, tzinfo=timezone.utc), business_line_id=1),
            _payment(1, 6, datetime(2026, 2, 6, tzinfo=timezone.utc), business_line_id=2),
            _payment(2, 3, datetime(2026, 3, 2, tzinfo=timezone.utc)),
            _payment(1, 4, datetime(2026, 3, 5, tzinfo=timezone.utc)),
            Payments(id=5, customer_id=1, customer_name="First", income_type="ads_fee", amount_due=3000, amount_paid=3000, ads_recharge_amount=3000, currency="USD", payment_date=datetime(2026, 3, 6, tzinfo=timezone.utc), created_at=datetime(2026, 3, 6, tzinfo=timezone.utc), user_id="finance"),
            FinanceRefund(id=1, payment_id=2, customer_id=1, customer_name="First", refund_amount=100, currency="USD", refund_date=datetime(2026, 2, 20, tzinfo=timezone.utc), provider="stripe", stripe_fee_refunded_amount=0, status="completed", created_at=datetime(2026, 2, 20, tzinfo=timezone.utc), user_id="finance"),
        ])
        await db.commit()

        first_scan = await scan_commissions(db)
        second_scan = await scan_commissions(db)
        entries = (await db.scalars(select(CommissionEntry).order_by(CommissionEntry.id))).all()

        assert first_scan["entries_created"] == 6
        assert second_scan["entries_created"] == 0
        assert len(entries) == 6
        assert entries[0].entry_type == "first_order"
        assert entries[0].commission_amount == 500
        assert entries[1].entry_type == "renewal"
        assert entries[1].inactivity_months == 1
        assert entries[1].activity_multiplier == .8
        assert entries[1].commission_amount == 160
        assert next(row for row in entries if row.payment_id == 6).entry_type == "first_order"
        reversal = next(row for row in entries if row.entry_type == "refund_reversal")
        assert reversal.commission_amount == -16
        assert next(row for row in entries if row.payment_id == 3).entry_type == "first_order"
        march_renewal = next(row for row in entries if row.payment_id == 4)
        assert march_renewal.entry_type == "renewal"
        assert march_renewal.activity_multiplier == 1
        assert not any(row.payment_id == 5 for row in entries)

    await engine.dispose()


@pytest.mark.asyncio
async def test_confirmed_snapshot_is_locked_and_partner_stop_blocks_future_receipts():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    await _create_tables(engine)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    finance = UserResponse(id="1", email="finance@example.com", name="Finance", role="finance")

    async with session_factory() as db:
        partner = SalesPartner(id=1, partner_code="P001", name="Partner", partner_type="partner", status="active", joined_at=date(2026, 1, 1))
        db.add_all([
            Customers(id=1, business_name="First", contact_name="Owner", phone="1"), partner,
            CommissionAgreement(id=1, partner_id=1, version=1, first_order_rate=.5, renewal_rate=.2, activity_decay_json=json.dumps({0: 1, 6: 0}), refund_guard_days=30, effective_from=date(2026, 1, 1), status="active"),
            CustomerCommissionAttribution(id=1, customer_id=1, partner_id=1, attribution_role="primary", effective_from=date(2026, 1, 1), is_active=True),
            _payment(1, 1, datetime(2026, 1, 5, tzinfo=timezone.utc)),
        ])
        await db.commit()
        await scan_commissions(db)
        entry = await db.scalar(select(CommissionEntry))
        result = await transition_entry(entry.id, EntryTransitionInput(to_status="confirmed"), finance, db)
        assert result["status"] == "confirmed"

        partner.status = "suspended"
        await db.commit()
        with pytest.raises(HTTPException) as suspended_error:
            await transition_entry(entry.id, EntryTransitionInput(to_status="payable"), finance, db)
        assert suspended_error.value.status_code == 409
        partner.status = "active"

        original_amount = entry.commission_amount
        payment = await db.get(Payments, 1)
        payment.amount_paid = 2000
        partner.status = "terminated"
        partner.stopped_at = date(2026, 2, 1)
        db.add(_payment(1, 2, datetime(2026, 2, 2, tzinfo=timezone.utc)))
        await db.commit()
        await scan_commissions(db)
        entries = (await db.scalars(select(CommissionEntry).order_by(CommissionEntry.id))).all()
        assert len(entries) == 1
        assert entries[0].commission_amount == original_amount

    await engine.dispose()
