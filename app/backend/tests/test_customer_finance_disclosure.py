"""Attack checks for scoped finance; calculations continue using original inputs."""
from datetime import datetime
import json
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import models.automation
from backend.main import app
from core.database import Base, get_db
from models.customers import Customers
from models.customer_access_grants import CustomerAccessGrant
from models.payments import Payments
from models.expenses import Expenses
from models.finance_refunds import FinanceRefund
from backend.services.emp_auth import create_access_token


def headers(role="ops", employee_id=501):
    return {"Authorization": "Bearer " + create_access_token({"emp_id": employee_id, "role": role, "name": "Viewer", "email": "scope@example.test"})}


@pytest_asyncio.fixture
async def financial_api():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("CREATE TABLE IF NOT EXISTS app_settings (config_key TEXT PRIMARY KEY, value_json TEXT)"))
        await conn.execute(text("CREATE TABLE IF NOT EXISTS monthly_deduction_rates (year_month DATE PRIMARY KEY, rate FLOAT)"))
        await conn.execute(text("CREATE TABLE IF NOT EXISTS monthly_deduction_defaults (id INTEGER PRIMARY KEY, rate FLOAT)"))
        await conn.execute(text("CREATE TABLE IF NOT EXISTS monthly_deduction_audits (id INTEGER PRIMARY KEY)"))
        await conn.execute(text("INSERT INTO monthly_deduction_rates VALUES ('2026-10-01', 0.12)"))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        db.add_all([
            Customers(id=1, business_name="Shared", contact_name="A", phone="111"),
            Customers(id=2, business_name="Other", contact_name="B", phone="222"),
            CustomerAccessGrant(customer_id=1, employee_id=501, access_level="read_only", finance_access="none"),
            Payments(id=11, customer_id=1, amount_due=500, amount_paid=400, outstanding_amount=100,
                currency="USD", management_amount=400, stripe_fee_amount=12, payment_date=datetime(2026,10,1),
                transaction_reference="restricted-reference", notes="financial-note", user_id="owner"),
            Payments(id=22, customer_id=2, amount_due=999, amount_paid=999, currency="USD", user_id="owner"),
            Expenses(id=31, customer_id=1, expense_type="design_fee", amount=25, currency="USD", user_id="owner"),
            Expenses(id=32, customer_id=2, expense_type="design_fee", amount=100, currency="USD", user_id="owner"),
            FinanceRefund(id=41, payment_id=11, customer_id=1, refund_amount=10, currency="USD", refund_date=datetime(2026,10,2),
                status="completed", created_at=datetime(2026,10,2), user_id="owner"),
        ])
        await db.commit()
        async def override():
            yield db
        app.dependency_overrides[get_db] = override
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client, db
        app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_grants_disclose_only_requested_financial_tier(financial_api):
    client, db = financial_api
    path = "/api/v1/entities/customers/1/finance-access-data"
    assert (await client.get(path, headers=headers())).status_code == 403
    assert (await client.get(path.replace('/1/', '/2/'), headers=headers())).status_code == 404
    grant = (await db.execute(select(CustomerAccessGrant))).scalar_one()
    grant.finance_access = "status"
    await db.commit()
    result = await client.get(path, headers=headers())
    assert result.status_code == 200
    assert "no-store" in result.headers["cache-control"]
    data = result.json()
    assert data["status"]["has_outstanding"] is True
    assert data["payments"] == data["expenses"] == data["refunds"] == []
    assert "amount" not in json.dumps(data)
    grant.finance_access = "receipts"
    await db.commit()
    data = (await client.get(path, headers=headers())).json()
    assert [p["id"] for p in data["payments"]] == [11]
    assert data["payments"][0]["amount_paid"] == 400
    assert data["refunds"][0]["refund_amount"] == 10
    assert data["expenses"] == [] and data["deduction_rates"] == {}
    assert not {"stripe_fee_amount", "management_amount", "notes", "transaction_reference"} & data["payments"][0].keys()
    grant.finance_access = "profit"
    await db.commit()
    data = (await client.get(path, headers=headers())).json()
    assert data["payments"][0]["stripe_fee_amount"] == 12
    assert [e["id"] for e in data["expenses"]] == [31]
    assert data["deduction_rates"] == {"2026-10": 0.12}
    assert (await db.execute(text("SELECT COUNT(*) FROM monthly_deduction_rates"))).scalar() == 1
    grant.access_level = "none"
    await db.commit()
    assert (await client.get(path, headers=headers())).status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["admin", "finance", "sales", "ops", "design"])
async def test_customer_grant_never_opens_company_ledger_or_financial_write(financial_api, role):
    client, db = financial_api
    grant = (await db.execute(select(CustomerAccessGrant))).scalar_one()
    grant.finance_access = "profit"
    await db.commit()
    for path in ["/api/v1/entities/payments/all", "/api/v1/entities/expenses/all", "/api/v1/entities/company_expenses/all", "/api/v1/deductions-monthly"]:
        assert (await client.get(path, headers=headers(role))).status_code == 403
    result = await client.post("/api/v1/entities/payments", json={"customer_id":1,"amount_due":1,"amount_paid":1}, headers=headers(role))
    assert result.status_code == 403
    assert len((await db.execute(select(Payments))).scalars().all()) == 2


@pytest.mark.asyncio
async def test_owner_retains_original_financial_inputs(financial_api):
    client, _ = financial_api
    response = await client.get("/api/v1/entities/payments/all", headers=headers("super_admin", 1))
    assert response.status_code == 200
    assert {p["id"] for p in response.json()["items"]} == {11,22}


@pytest.mark.asyncio
async def test_ordinary_admin_cannot_create_owner_or_change_role_permissions(financial_api):
    client, _ = financial_api
    response = await client.post("/api/v1/entities/employees", json={"name":"Privilege", "role":"super_admin", "email":"test@example.test"}, headers=headers("admin"))
    assert response.status_code == 403
    response = await client.put("/api/v1/app-config/role_permissions", json={"value":{}}, headers=headers("admin"))
    assert response.status_code == 403

@pytest.mark.asyncio
async def test_delivery_records_hide_finance_and_reject_filter_inference(financial_api):
    from models.deals import Deals
    from models.subscriptions import Subscriptions
    client, db = financial_api
    db.add_all([
        Deals(id=71,customer_id=1,product_type="website",deal_amount=400,notes="private amount",is_paid=True),
        Subscriptions(id=81,customer_id=1,package_name="Website",package_price=400),
    ])
    grant = (await db.execute(select(CustomerAccessGrant))).scalar_one()
    grant.scopes = {"delivery":"read_only"}
    await db.commit()
    for entity, ident, hidden in [('deals',71,'deal_amount'),('subscriptions',81,'package_price')]:
        path='/api/v1/entities/'+entity
        result=await client.get(path+'/'+str(ident),headers=headers())
        assert result.status_code==200
        assert result.json()[hidden] is None
        assert (await client.get(path,params={'query':json.dumps({hidden:400})},headers=headers())).status_code==403
        assert (await client.get(path+'/all',params={'sort':'-'+hidden},headers=headers())).status_code==403
    grant.finance_access='receipts';await db.commit()
    assert (await client.get('/api/v1/entities/deals/71',headers=headers())).json()['deal_amount']==400
    grant.scopes={"delivery":"none"};await db.commit()
    for entity, ident in [('deals',71),('subscriptions',81)]:
        assert (await client.get('/api/v1/entities/'+entity+'/'+str(ident),headers=headers())).status_code==404
        assert (await client.get('/api/v1/entities/'+entity+'/all',headers=headers())).json()['total']==0

@pytest.mark.asyncio
async def test_sales_duplicate_warning_does_not_disclose_hidden_customer(financial_api):
    from models.sales_leads import SalesLeads
    from routers.sales_leads import _find_customer_duplicates
    from types import SimpleNamespace
    _, db=financial_api
    lead=SalesLeads(business_name='Other',phone='222')
    result=await _find_customer_duplicates(db,lead,SimpleNamespace(id=501,role='ops',name='Viewer'))
    assert result and 'customer_id' not in result[0] and 'business_name' not in result[0]
    owner_result=await _find_customer_duplicates(db,lead,SimpleNamespace(id=1,role='super_admin',name='Owner'))
    assert owner_result[0]['customer_id']==2


@pytest.mark.asyncio
async def test_business_record_delete_grant_never_deletes_customer_with_ledger(financial_api):
    client, db=financial_api
    grant=(await db.execute(select(CustomerAccessGrant))).scalar_one()
    grant.access_level="read_write";grant.can_delete=True
    await db.commit()
    assert (await client.delete("/api/v1/entities/customers/1",headers=headers("admin"))).status_code==403
    assert (await client.request("DELETE","/api/v1/entities/customers/batch",json={"ids":[1]},headers=headers("admin"))).status_code==403
    assert await db.get(Customers,1) is not None
    assert (await db.get(Payments,11)).amount_paid==400
