"""Synthetic-only channel scope and login binding regressions (no external services)."""

import json
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.requests import Request

from dependencies.auth import enforce_sales_partner_route
from models.commissions import CommissionAgreement, CommissionEntry, CustomerCommissionAttribution, SalesPartner
from models.customers import Customers
from models.employees import Employees
from models.management_decisions import BusinessLine, CustomerEngagement, ProductCatalog
from models.payments import Payments
from models.subscriptions import Subscriptions
from routers.commissions import (
    AgreementInput, AttributionInput, PartnerInput, PartnerLoginInput,
    bind_partner_login, create_partner, my_partner_dashboard, partner_login_options,
    unbound_partners,
)
from routers.employees import EmployeesData, create_employees
from schemas.auth import UserResponse
from services.partner_portal import build_partner_customer_status_rows


FINANCE = UserResponse(id="99", email="finance@example.test", role="finance", name="Synthetic finance")
PARTNER = UserResponse(id="7", email="partner@example.test", role="sales_partner")


@pytest.mark.parametrize("day,old_current,new_current", [
    (date(2026, 10, 13), True, False),
    (date(2026, 10, 31), True, False),
    (date(2026, 11, 1), False, True),
])
def test_future_handover_preserves_current_scope_until_effective_date(day, old_current, new_current):
    old = SimpleNamespace(id=1, customer_id=1, engagement_id=None, partner_id=1,
        effective_from=date(2026, 1, 1), effective_to=date(2026, 10, 31), is_active=False)
    new = SimpleNamespace(id=2, customer_id=1, engagement_id=None, partner_id=2,
        effective_from=date(2026, 11, 1), effective_to=None, is_active=True)
    project = SimpleNamespace(id=11, customer_id=1, package_name="Current project", status="active_paid", billing_cycle="monthly")
    for attribution, expected in ((old, old_current), (new, new_current)):
        rows = build_partner_customer_status_rows(attributions=[attribution], customer_map={},
            engagements=[project], subscriptions=[], payments=[], scope_attributions=[old, new], as_of=day)
        assert len(rows) == 1
        assert rows[0]["is_active"] is expected
        assert rows[0]["engagement_id"] == (11 if expected else None)
        assert rows[0]["engagement_name"] == ("Current project" if expected else None)
        assert (rows[0]["cooperation_status"] != "historical") is expected
        if expected:
            assert "历史归属" not in rows[0]["commission_impact"]


async def setup_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        for table in (Employees.__table__, Customers.__table__, BusinessLine.__table__, ProductCatalog.__table__,
                      CustomerEngagement.__table__, Subscriptions.__table__, Payments.__table__, SalesPartner.__table__,
                      CommissionAgreement.__table__, CustomerCommissionAttribution.__table__, CommissionEntry.__table__):
            await connection.run_sync(table.create)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def employee(employee_id, *, role="sales_partner", status="active"):
    return Employees(id=employee_id, user_id=f"synthetic-{employee_id}", name=f"Person {employee_id}",
                     email=f"person{employee_id}@example.test", employee_code=f"E{employee_id}", role=role, status=status)


def partner(partner_id, *, employee_id=None, partner_type="partner"):
    return SalesPartner(id=partner_id, partner_code=f"P{partner_id}", name=f"Partner {partner_id}",
                        partner_type=partner_type, employee_id=employee_id, status="active", joined_at=date(2026, 1, 1))


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/v1/commissions/dashboard"), ("GET", "/api/v1/commissions/options"),
    ("GET", "/api/v1/commissions/partner-login-options"), ("GET", "/api/v1/commissions/payments/1/preview"),
    ("GET", "/api/v1/commissions/unbound-partners"),
    ("POST", "/api/v1/commissions/partners/1/login-account"), ("POST", "/api/v1/commissions/attributions/preview"),
    ("POST", "/api/v1/commissions/scan"), ("POST", "/api/v1/commissions/entries/1/transition"),
    ("GET", "/api/v1/entities/payments"), ("GET", "/api/v1/entities/customers/1"),
])
def test_partner_api_allowlist_stays_closed(method, path):
    with pytest.raises(HTTPException) as error:
        enforce_sales_partner_route(PARTNER, Request({"type": "http", "method": method, "path": path, "headers": []}))
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_portal_hides_internal_notes_and_project_override_and_current_history():
    engine, sessions = await setup_db()
    async with sessions() as db:
        own_partner = partner(1, employee_id=7)
        own_partner.notes = "SECRET_INTERNAL_PARTNER_NOTE"
        agreement = CommissionAgreement(id=1, partner_id=1, version=1, first_order_rate=.4, renewal_rate=.2,
            activity_decay_json=json.dumps({0: 1, 6: 1}), refund_guard_days=0, effective_from=date(2026, 1, 1),
            status="active", notes="SECRET_INTERNAL_AGREEMENT_NOTE")
        db.add_all([
            employee(7), employee(8), own_partner, partner(2, employee_id=8), agreement,
            Customers(id=1, business_name="Owned Customer", contact_name="Owner", phone="1"),
            Customers(id=2, business_name="UNRELATED_CUSTOMER", contact_name="Other", phone="2"),
            Customers(id=3, business_name="Historical Customer", contact_name="Past", phone="3"),
            BusinessLine(id=1, code="LINE", name="Line", is_recurring=True),
            ProductCatalog(id=1, business_line_id=1, code="PRODUCT", name="Product", billing_kind="recurring"),
            CustomerEngagement(id=11, customer_id=1, business_line_id=1, product_id=1, engagement_code="E11", package_name="Visible Project", status="active_paid"),
            CustomerEngagement(id=12, customer_id=1, business_line_id=1, product_id=1, engagement_code="E12", package_name="SECRET_OTHER_PARTNER_PROJECT", status="active_paid"),
            CustomerEngagement(id=31, customer_id=3, business_line_id=1, product_id=1, engagement_code="E31", package_name="SECRET_RENAMED_HISTORY_PROJECT", status="active_paid"),
            CustomerCommissionAttribution(id=1, customer_id=1, partner_id=1, effective_from=date(2026, 1, 1), is_active=True),
            CustomerCommissionAttribution(id=2, customer_id=1, partner_id=2, engagement_id=12, effective_from=date(2026, 1, 1), is_active=True),
            CustomerCommissionAttribution(id=3, customer_id=2, partner_id=2, effective_from=date(2026, 1, 1), is_active=True),
            CustomerCommissionAttribution(id=4, customer_id=3, partner_id=1, engagement_id=31, effective_from=date(2026, 1, 1), effective_to=date(2026, 2, 1), is_active=False),
            CustomerCommissionAttribution(id=5, customer_id=3, partner_id=2, engagement_id=31, effective_from=date(2026, 2, 2), is_active=True),
        ])
        await db.commit()
        result = await my_partner_dashboard(PARTNER, db, None)
        serialized = json.dumps(result, default=str)
        assert "SECRET_" not in serialized
        assert "UNRELATED_CUSTOMER" not in serialized
        assert "notes" not in result["partner"]
        assert "notes" not in result["agreements"][0]
        assert result["available_partners"] == []
        assert [row["engagement_name"] for row in result["customers"] if row["is_active"]] == ["Visible Project"]
        history = next(row for row in result["customers"] if row["customer_id"] == 3)
        assert history["engagement_name"] is None and history["engagement_id"] is None
        assert history["last_receipt_at"] is None and history["next_due_at"] is None
        for requested in (1, 2):
            with pytest.raises(HTTPException) as error:
                await my_partner_dashboard(PARTNER, db, requested)
            assert error.value.status_code == 403
    await engine.dispose()


@pytest.mark.asyncio
async def test_login_candidates_bind_and_duplicate_safety():
    engine, sessions = await setup_db()
    async with sessions() as db:
        db.add_all([employee(7), employee(8), employee(9, role="sales"), employee(10, status="inactive"),
                    partner(1), partner(2, employee_id=8), partner(3)])
        await db.commit()
        options = await partner_login_options(FINANCE, db)
        assert [row["id"] for row in options["items"]] == [7]
        for invalid_id in (8, 9, 10):
            with pytest.raises(HTTPException) as error:
                await bind_partner_login(1, PartnerLoginInput(employee_id=invalid_id), FINANCE, db)
            assert error.value.status_code == 409
        bound = await bind_partner_login(1, PartnerLoginInput(employee_id=7), FINANCE, db)
        assert bound["employee_id"] == 7 and bound["login_account"]["id"] == 7
        original_notes = bound["notes"]
        again = await bind_partner_login(1, PartnerLoginInput(employee_id=7), FINANCE, db)
        assert again["notes"] == original_notes
        assert (await partner_login_options(FINANCE, db))["items"] == []
        with pytest.raises(HTTPException) as error:
            await bind_partner_login(3, PartnerLoginInput(employee_id=7), FINANCE, db)
        assert error.value.status_code == 409
        with pytest.raises(HTTPException) as error:
            await create_partner(PartnerInput(partner_code="NEW", name="Duplicate", partner_type="agency",
                                  employee_id=7, joined_at=date(2026, 1, 1)), FINANCE, db)
        assert error.value.status_code == 409
        assert len((await db.scalars(select(SalesPartner))).all()) == 3
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_login_for_explicit_existing_partner_keeps_original_channel():
    engine, sessions = await setup_db()
    admin = UserResponse(id="99", email="admin@example.test", role="super_admin", name="Owner")
    async with sessions() as db:
        original = partner(1)
        original.name = "Existing agency company name"
        original.contact_email = "agency@example.test"
        db.add(original)
        await db.commit()
        assert [row["id"] for row in (await unbound_partners(admin, db))["items"]] == [1]
        account = await create_employees(EmployeesData(name="Individual login name", role="sales_partner",
            email="login@example.test", status="active", existing_partner_id=1), admin, db)
        await db.refresh(original)
        assert original.employee_id == account.id
        assert original.name == "Existing agency company name"
        assert original.contact_email == "agency@example.test"
        assert len((await db.scalars(select(SalesPartner))).all()) == 1
        assert (await unbound_partners(admin, db))["items"] == []
        with pytest.raises(HTTPException) as error:
            await create_employees(EmployeesData(name="Duplicate login", role="sales_partner",
                email="another@example.test", existing_partner_id=1), admin, db)
        assert error.value.status_code == 409
        assert len((await db.scalars(select(Employees))).all()) == 1
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("target,role,expected", [(999, "sales_partner", 404), (1, "sales", 400), (2, "sales_partner", 404), (3, "sales_partner", 409)])
async def test_create_login_rejects_invalid_explicit_target_without_fallback(target, role, expected):
    engine, sessions = await setup_db()
    async with sessions() as db:
        terminated = partner(3)
        terminated.status = "terminated"
        db.add_all([partner(1), partner(2, partner_type="direct"), terminated])
        await db.commit()
        with pytest.raises(HTTPException) as error:
            await create_employees(EmployeesData(name="Uncreated", role=role,
                email="uncreated@example.test", existing_partner_id=target), FINANCE, db)
        assert error.value.status_code == expected
        assert (await db.scalars(select(Employees))).all() == []
        assert len((await db.scalars(select(SalesPartner))).all()) == 3
    await engine.dispose()


def test_new_attribution_requires_explicit_service_period_and_renewal_evidence():
    base = dict(customer_id=1, partner_id=1, effective_from=date(2026, 1, 1), commission_start_date=date(2026, 2, 1))
    with pytest.raises(ValidationError):
        AttributionInput(**base)
    with pytest.raises(ValidationError):
        AttributionInput(**base, commission_mode="renewal_only", first_service_start=date(2025, 12, 1), history_basis="  ")
    configured = AttributionInput(**base, commission_mode="renewal_only", first_service_start=date(2025, 12, 1), history_basis="  历史合同及已付首月凭证  ")
    assert configured.history_basis == "历史合同及已付首月凭证"
    assert AttributionInput(**base, commission_mode="renewal_only", history_basis="历史首月已完成").first_service_start is None
    assert AttributionInput(**base, commission_mode="none").first_service_start is None
    with pytest.raises(ValidationError):
        AttributionInput(**{**base, "commission_start_date": date(2025, 12, 1)}, commission_mode="none")


def test_new_agreements_cannot_silently_enable_decay_or_legacy_calculation():
    base = dict(partner_id=1, first_order_rate=.4, renewal_rate=.2, effective_from=date(2026, 1, 1))
    assert AgreementInput(**base).renewal_policy == "fixed"
    with pytest.raises(ValidationError):
        AgreementInput(**base, activity_decay={0: 1, 6: 0})
    with pytest.raises(ValidationError):
        AgreementInput(**base, renewal_policy="activity_decay")
    with pytest.raises(ValidationError):
        AgreementInput(**base, calculation_version="legacy_v1")
