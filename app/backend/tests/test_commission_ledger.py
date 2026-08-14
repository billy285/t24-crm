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
from models.finance_profit_closes import MonthlyProfitClose
from models.management_decisions import BusinessLine, CustomerEngagement, ProductCatalog
from models.payments import Payments
from models.subscriptions import Subscriptions
from routers.commissions import EntryTransitionInput, my_partner_dashboard, transition_entry
from routers.employees import EmployeesData, create_employees
from schemas.auth import UserResponse
from services.commissions import (
    DIRECT_PARTNER_CODE,
    apply_bulk_customer_attributions,
    auto_assign_new_customer,
    commission_data_quality,
    preview_bulk_customer_attributions,
    scan_commissions,
    transfer_partner_attributions_to_direct,
)


async def _create_tables(engine) -> None:
    tables = [
        Employees.__table__, Customers.__table__, Payments.__table__, FinanceRefund.__table__,
        Subscriptions.__table__,
        BusinessLine.__table__, ProductCatalog.__table__, CustomerEngagement.__table__,
        SalesPartner.__table__, CommissionAgreement.__table__, CustomerCommissionAttribution.__table__,
        CommissionEntry.__table__, CommissionStatusEvent.__table__,
        MonthlyProfitClose.__table__,
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
        db.add(MonthlyProfitClose(
            year_month="2026-01",
            status="locked",
            snapshot_json="{}",
            locked_by="Owner",
            locked_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        ))
        await db.commit()
        payable = await transition_entry(entry.id, EntryTransitionInput(to_status="payable"), finance, db)
        assert payable["status"] == "payable"
        paid = await transition_entry(
            entry.id,
            EntryTransitionInput(to_status="paid", payout_reference="PAY-2026-001"),
            finance,
            db,
        )
        assert paid["status"] == "paid"

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


@pytest.mark.asyncio
async def test_locked_month_blocks_commission_entering_profit_but_allows_non_profit_reversal():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    await _create_tables(engine)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    finance = UserResponse(id="1", email="finance@example.com", name="Finance", role="finance")

    async with session_factory() as db:
        db.add_all([
            Customers(id=1, business_name="First", contact_name="Owner", phone="1"),
            SalesPartner(id=1, partner_code="P001", name="Partner", partner_type="partner", status="active", joined_at=date(2026, 1, 1)),
            CommissionAgreement(id=1, partner_id=1, version=1, first_order_rate=.5, renewal_rate=.2, activity_decay_json=json.dumps({0: 1}), refund_guard_days=0, effective_from=date(2026, 1, 1), status="active"),
            CustomerCommissionAttribution(id=1, customer_id=1, partner_id=1, attribution_role="primary", effective_from=date(2026, 1, 1), is_active=True),
            _payment(1, 1, datetime(2026, 1, 5, tzinfo=timezone.utc)),
            MonthlyProfitClose(
                year_month="2026-01", status="locked", snapshot_json="{}",
                locked_by="Owner", locked_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
            ),
        ])
        await db.commit()
        await scan_commissions(db)
        entry = await db.scalar(select(CommissionEntry))

        with pytest.raises(HTTPException) as closed_month_error:
            await transition_entry(entry.id, EntryTransitionInput(to_status="confirmed"), finance, db)
        assert closed_month_error.value.status_code == 409
        assert "月结" in closed_month_error.value.detail

        reversed_result = await transition_entry(
            entry.id,
            EntryTransitionInput(to_status="reversed", reason="无需结算"),
            finance,
            db,
        )
        assert reversed_result["status"] == "reversed"

    await engine.dispose()


@pytest.mark.asyncio
async def test_new_customer_auto_assignment_and_partner_stop_transfer_to_direct():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    await _create_tables(engine)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as db:
        db.add_all([
            Employees(id=7, user_id="employee-7", role="sales", employee_code="E007", name="Internal Sales", status="active"),
            Customers(id=1, business_name="Employee Customer", contact_name="Owner", phone="1", sales_employee_id=7),
            Customers(id=2, business_name="Direct Customer", contact_name="Owner", phone="2"),
            SalesPartner(id=1, partner_code="EMP-007", name="Internal Sales", partner_type="employee", employee_id=7, status="active", joined_at=date(2026, 1, 1)),
        ])
        await db.commit()

        employee_link = await auto_assign_new_customer(
            db, customer_id=1, sales_employee_id=7, effective_from=date(2026, 4, 1), actor_id="1", actor_name="Admin"
        )
        direct_link = await auto_assign_new_customer(
            db, customer_id=2, sales_employee_id=None, effective_from=date(2026, 4, 1), actor_id="1", actor_name="Admin"
        )
        await db.commit()

        direct_partner = await db.scalar(select(SalesPartner).where(SalesPartner.partner_code == DIRECT_PARTNER_CODE))
        assert employee_link.partner_id == 1
        assert direct_partner is not None
        assert direct_link.partner_id == direct_partner.id

        transferred = await transfer_partner_attributions_to_direct(
            db, partner_id=1, stopped_at=date(2026, 5, 31), actor_id="1", actor_name="Admin"
        )
        await db.commit()
        links = (await db.scalars(select(CustomerCommissionAttribution).where(
            CustomerCommissionAttribution.customer_id == 1
        ).order_by(CustomerCommissionAttribution.id))).all()
        assert transferred == 1
        assert links[0].is_active is False
        assert links[0].effective_to == date(2026, 5, 31)
        assert links[1].partner_id == direct_partner.id
        assert links[1].effective_from == date(2026, 6, 1)
        assert links[1].is_active is True

    await engine.dispose()


@pytest.mark.asyncio
async def test_commission_data_quality_finds_unassigned_receipts_and_missing_agreements():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    await _create_tables(engine)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as db:
        db.add_all([
            Customers(id=1, business_name="No Owner", contact_name="Owner", phone="1"),
            Customers(id=2, business_name="No Agreement", contact_name="Owner", phone="2"),
            SalesPartner(id=1, partner_code="P001", name="Partner", partner_type="partner", status="active", joined_at=date(2026, 1, 1)),
            CustomerCommissionAttribution(id=1, customer_id=2, partner_id=1, attribution_role="primary", effective_from=date(2026, 1, 1), is_active=True),
            _payment(1, 1, datetime(2026, 2, 1, tzinfo=timezone.utc)),
            _payment(2, 2, datetime(2026, 2, 1, tzinfo=timezone.utc)),
        ])
        await db.commit()

        quality = await commission_data_quality(db)
        issue_types = {row["type"] for row in quality["issues"]}
        assert "unattributed_payment" in issue_types
        assert "payment_without_agreement" in issue_types
        assert "partner_without_agreement" in issue_types
        assert quality["coverage_rate"] == 0.0

    await engine.dispose()


@pytest.mark.asyncio
async def test_bulk_attribution_preview_and_apply_are_safe_and_idempotent():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    await _create_tables(engine)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as db:
        db.add_all([
            Employees(id=7, user_id="employee-7", role="sales", employee_code="E007", name="Internal Sales", status="active"),
            Customers(id=1, customer_code="C001", business_name="Employee Customer", contact_name="Owner", phone="1", sales_employee_id=7),
            Customers(id=2, customer_code="C002", business_name="Direct Customer", contact_name="Owner", phone="2"),
            Customers(id=3, customer_code="C003", business_name="Later Owner", contact_name="Owner", phone="3", sales_employee_id=7),
            SalesPartner(id=1, partner_code="EMP-007", name="Internal Sales", partner_type="employee", employee_id=7, status="active", joined_at=date(2026, 1, 1)),
            CustomerCommissionAttribution(id=1, customer_id=3, partner_id=1, attribution_role="primary", effective_from=date(2026, 5, 1), is_active=True),
            _payment(1, 1, datetime(2026, 1, 5, tzinfo=timezone.utc)),
            _payment(2, 2, datetime(2026, 2, 5, tzinfo=timezone.utc)),
            _payment(3, 3, datetime(2026, 3, 5, tzinfo=timezone.utc)),
        ])
        await db.commit()

        preview = await preview_bulk_customer_attributions(db)
        assert preview["source_issue_count"] == 3
        assert preview["target_count"] == 3
        assert preview["ready_count"] == 2
        assert preview["employee_count"] == 1
        assert preview["direct_count"] == 1
        assert preview["manual_review_count"] == 1
        employee_item = next(row for row in preview["items"] if row["customer_id"] == 1)
        direct_item = next(row for row in preview["items"] if row["customer_id"] == 2)
        review_item = next(row for row in preview["items"] if row["customer_id"] == 3)
        assert employee_item["partner_id"] == 1
        assert employee_item["effective_from"] == date(2026, 1, 5)
        assert direct_item["partner_type"] == "direct"
        assert review_item["status"] == "manual_review"

        applied = await apply_bulk_customer_attributions(
            db,
            preview_token=preview["preview_token"],
            actor_id="1",
            actor_name="Admin",
        )
        await db.commit()
        assert applied["assigned_count"] == 2
        assert applied["employee_count"] == 1
        assert applied["direct_count"] == 1

        links = (await db.scalars(select(CustomerCommissionAttribution).order_by(
            CustomerCommissionAttribution.customer_id,
            CustomerCommissionAttribution.id,
        ))).all()
        assert len(links) == 3
        assert next(row for row in links if row.customer_id == 1).partner_id == 1
        direct_partner = await db.scalar(select(SalesPartner).where(SalesPartner.partner_code == DIRECT_PARTNER_CODE))
        assert next(row for row in links if row.customer_id == 2).partner_id == direct_partner.id

        refreshed = await preview_bulk_customer_attributions(db)
        assert refreshed["ready_count"] == 0
        assert refreshed["manual_review_count"] == 1
        with pytest.raises(ValueError, match="重新预览"):
            await apply_bulk_customer_attributions(
                db,
                preview_token=preview["preview_token"],
                actor_id="1",
                actor_name="Admin",
            )

    await engine.dispose()


@pytest.mark.asyncio
async def test_sales_partner_dashboard_is_scoped_to_linked_partner_and_hides_gross_receipts():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    await _create_tables(engine)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    partner_user = UserResponse(id="7", email="partner@example.com", name="Partner Login", role="sales_partner")

    async with session_factory() as db:
        db.add_all([
            Employees(id=7, user_id="partner-7", role="sales_partner", name="Partner Login", status="active"),
            Customers(id=1, customer_code="C001", business_name="Visible Customer", contact_name="Owner", phone="1"),
            Customers(id=2, customer_code="C002", business_name="Hidden Customer", contact_name="Owner", phone="2"),
            SalesPartner(id=1, partner_code="P001", name="Visible Partner", partner_type="partner", employee_id=7, status="active", joined_at=date(2026, 1, 1)),
            SalesPartner(id=2, partner_code="P002", name="Other Partner", partner_type="partner", status="active", joined_at=date(2026, 1, 1)),
            CommissionAgreement(id=1, partner_id=1, version=1, first_order_rate=.5, renewal_rate=.2, activity_decay_json=json.dumps({0: 1, 6: 0}), refund_guard_days=30, effective_from=date(2026, 1, 1), status="active"),
            CommissionAgreement(id=2, partner_id=2, version=1, first_order_rate=.5, renewal_rate=.2, activity_decay_json=json.dumps({0: 1, 6: 0}), refund_guard_days=30, effective_from=date(2026, 1, 1), status="active"),
            CustomerCommissionAttribution(id=1, customer_id=1, partner_id=1, attribution_role="primary", effective_from=date(2026, 1, 1), is_active=True),
            CustomerCommissionAttribution(id=2, customer_id=2, partner_id=2, attribution_role="primary", effective_from=date(2026, 1, 1), is_active=True),
            _payment(1, 1, datetime(2026, 1, 5, tzinfo=timezone.utc)),
            _payment(2, 2, datetime(2026, 1, 5, tzinfo=timezone.utc)),
            CommissionEntry(id=1, partner_id=1, agreement_id=1, attribution_id=1, customer_id=1, payment_id=1, entry_type="first_order", status="paid", service_month="2026-01", occurred_at=datetime(2026, 1, 5, tzinfo=timezone.utc), currency="USD", gross_receipt_amount=3000, eligible_service_amount=1000, contract_rate=.5, inactivity_months=0, activity_multiplier=1, commission_amount=500, snapshot_json="{}", idempotency_key="visible"),
            CommissionEntry(id=2, partner_id=2, agreement_id=2, attribution_id=2, customer_id=2, payment_id=2, entry_type="first_order", status="paid", service_month="2026-01", occurred_at=datetime(2026, 1, 5, tzinfo=timezone.utc), currency="USD", gross_receipt_amount=5000, eligible_service_amount=2000, contract_rate=.5, inactivity_months=0, activity_multiplier=1, commission_amount=1000, snapshot_json="{}", idempotency_key="hidden"),
        ])
        await db.commit()

        payload = await my_partner_dashboard(partner_user, db)
        assert payload["partner"]["id"] == 1
        assert [row["customer_name"] for row in payload["customers"]] == ["Visible Customer"]
        assert [row["customer_name"] for row in payload["entries"]] == ["Visible Customer"]
        assert "gross_receipt_amount" not in payload["entries"][0]
        assert payload["summary"]["currencies"]["USD"]["paid"] == 500

        with pytest.raises(HTTPException) as finance_error:
            await my_partner_dashboard(UserResponse(id="1", email="finance@example.com", role="finance"), db)
        assert finance_error.value.status_code == 403

    await engine.dispose()


@pytest.mark.asyncio
async def test_creating_sales_partner_employee_atomically_links_partner_profile():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    await _create_tables(engine)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    admin = UserResponse(id="1", email="admin@example.com", name="Admin", role="admin")

    async with session_factory() as db:
        employee = await create_employees(
            EmployeesData(
                name="New Partner",
                role="sales_partner",
                email="partner@example.com",
                employee_code="SP-001",
                hire_date="2026-08-08",
            ),
            admin,
            db,
        )
        linked = await db.scalar(select(SalesPartner).where(SalesPartner.employee_id == employee.id))

        assert employee.role == "sales_partner"
        assert linked is not None
        assert linked.partner_code == "SP-001"
        assert linked.partner_type == "partner"
        assert linked.name == "New Partner"
        assert linked.contact_email == "partner@example.com"
        assert linked.joined_at == date(2026, 8, 8)

    await engine.dispose()
