"""Owned leads outside the fixed daily quota can be contacted without a prior call."""
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.main import app
from backend.tests.test_sales_lead_isolation import _auth_headers
from core.database import Base, get_db
from models.employees import Employees
from models.merchant_pool import MerchantPool
from models.sales_call_activities import SalesCallActivities
from models.sales_daily_dial_tasks import SalesDailyDialTasks
from models.sales_daily_quotas import SalesDailyQuotas
from models.sales_lead_enrichments import SalesDialAttempt
from models.sales_leads import SalesLeads

SALES = _auth_headers('sales', 11, 'Sales A')
OTHER = _auth_headers('sales', 12, 'Sales B')
MANAGER = _auth_headers('sales_manager', 10, 'Manager')
ADMIN = _auth_headers('admin', 1, 'Admin')
ROOT = '/api/v1/sales-leads'


@pytest_asyncio.fixture
async def manual_contact(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'contacts.db'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    day = datetime.now(ZoneInfo('Asia/Shanghai')).date()
    async with sessions.begin() as db:
        db.add_all([Employees(id=i, user_id=str(i), role=role, name=name, status='active', supervisor='Manager' if i == 11 else None)
                    for i, role, name in [(11, 'sales', 'Sales A'), (12, 'sales', 'Sales B'), (1, 'admin', 'Admin'), (10, 'sales_manager', 'Manager')]])
        db.add(MerchantPool(id=4, business_name='Pool fixture', phone='+12125550104', created_by_id=10))
        db.add_all([SalesLeads(id=i, business_name=f'Example {i}', phone=phone, country='US',
                               assigned_sales_id=11, assigned_sales_name='Sales A') for i, phone in
                    [(1, '+12125550101'), (2, '+12125550102'), (3, 'bad phone')]])
        db.add_all([SalesDailyQuotas(sales_employee_id=11, target_date=day, target_count=1),
                    SalesDailyDialTasks(lead_id=1, sales_employee_id=11, task_date=day, status='pending')])

    async def local_db():
        async with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = local_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            yield client, sessions, day
    finally:
        app.dependency_overrides.pop(get_db)
        await engine.dispose()


@pytest.mark.asyncio
async def test_manual_contact_after_quota_uses_one_task_and_only_explicit_result_counts(manual_contact):
    client, sessions, day = manual_contact
    path = f'{ROOT}/workbench/manual-task/2?target_date={day}'
    queue = f'{ROOT}/workbench/today?target_date={day}'
    before = (await client.get(queue, headers=SALES)).json()
    assert before['quota'] == before['assigned_count'] == 1
    a, b = await asyncio.gather(client.post(path, headers=SALES), client.post(path, headers=SALES))
    assert a.status_code == b.status_code == 200, (a.text, b.text)
    assert a.json() == b.json()
    task_id = a.json()['task_id']
    opened = (await client.get(queue, headers=SALES)).json()
    assert opened['quota'] == 1 and opened['assigned_count'] == 2 and opened['completed_count'] == 0
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(SalesDialAttempt)) == 0
        assert await db.scalar(select(func.count()).select_from(SalesCallActivities)) == 0
    dial = await client.post(f'{ROOT}/workbench/tasks/{task_id}/dial-started', headers=SALES,
                             json={'phone': '+12125550102'})
    assert dial.status_code == 200 and dial.json()['phone'] == '+12125550102'
    assert (await client.get(queue, headers=SALES)).json()['performance']['attempted'] == 0
    record = await client.post(f'{ROOT}/workbench/tasks/{task_id}/result', headers=SALES,
                               json={'outcome': 'no_answer'})
    assert record.status_code == 200, record.text
    assert (await client.post(path, headers=SALES)).json()['task_status'] == 'completed'
    after = (await client.get(queue, headers=SALES)).json()
    assert after['quota'] == 1 and after['completed_count'] == 1
    assert after['performance']['attempted'] == 1 and after['performance']['connected'] == 0


@pytest.mark.asyncio
async def test_manual_contact_preserves_ownership_protection_and_manual_invalid_phone_mark(manual_contact):
    client, sessions, day = manual_contact
    path = f'{ROOT}/workbench/manual-task/3?target_date={day}'
    assert (await client.post(path, headers=OTHER)).status_code == 404
    assert (await client.post(path, headers=ADMIN)).status_code == 403
    assert (await client.post(f'{ROOT}/workbench/manual-task/3?target_date={day - timedelta(days=1)}',
                              headers=SALES)).status_code == 409
    check = '/api/v1/prospect-verification'
    assert (await client.get(f'{check}/lead/3', headers=SALES)).status_code == 200
    assert (await client.get(f'{check}/lead/3', headers=OTHER)).status_code == 404
    assert (await client.get(f'{check}/pool/4', headers=SALES)).status_code == 403
    assert (await client.get(f'{check}/pool/4', headers=MANAGER)).status_code == 200
    assert (await client.get(f'{check}/lead/3', headers=MANAGER)).status_code == 200
    assert (await client.delete(f'{check}/lead/3', headers=SALES)).status_code == 403
    assert (await client.get(f'{check}/lead/3/history', headers=SALES)).status_code == 403
    ok = await client.post(path, headers=SALES)
    assert ok.status_code == 200
    mark = await client.patch('/api/v1/prospect-verification/lead/3', headers=SALES,
                              json={'expected_revision': 0, 'status': 'invalid_phone',
                                    'method': 'source_review', 'notes': '原资料号码不完整'})
    assert mark.status_code == 200, mark.text
    assert (await client.post(path, headers=SALES)).status_code == 409
    async with sessions.begin() as db:
        task = await db.get(SalesDailyDialTasks, ok.json()['task_id'])
        assert task.status == 'cancelled'
        assert await db.scalar(select(func.count()).select_from(SalesCallActivities)) == 0
        lead = await db.get(SalesLeads, 2)
        lead.do_not_contact = True
    assert (await client.post(f'{ROOT}/workbench/manual-task/2?target_date={day}', headers=SALES)).status_code == 409
