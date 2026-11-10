"""Real DB/API proof for quality scope, human revisions, and task effects."""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from fastapi import FastAPI, Header, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.database import Base, get_db
from dependencies.auth import get_current_user
from models.employees import Employees
from models.merchant_pool import MerchantPool
from models.operation_logs import Operation_logs
from models.sales_daily_dial_tasks import SalesDailyDialTasks
from models.sales_leads import SalesLeads
from routers.prospect_verification import router
from routers.operation_logs import router as log_router
from schemas.auth import UserResponse
from services.prospect_verification import ensure_quality_history_retained, quality_for_many, quality_status_expression, source_metadata_from_raw

API = '/api/v1/prospect-verification'
ROLES = {1: ('super_admin', 'Boss'), 2: ('admin', 'Admin'), 10: ('sales_manager', 'Manager A'),
         20: ('sales_manager', 'Manager B'), 11: ('sales', 'Sales A'), 12: ('sales', 'Sales B'),
         13: ('ops', 'Operations'), 14: ('sales', 'Inactive')}


def auth(actor=11, **extra):
    return {'x-actor-id': str(actor), **extra}


def body(revision=0, status='valid', **changes):
    return {'expected_revision': revision, 'status': status, 'method': 'call',
            'notes': 'Synthetic first-call observation recorded by the acting employee', **changes}


@pytest_asyncio.fixture
async def verification_api(tmp_path):
    app = FastAPI()
    app.include_router(router)
    app.include_router(log_router)
    engine = create_async_engine('sqlite+aiosqlite:///' + str(tmp_path / 'quality.sqlite'))
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    today = datetime.now(timezone.utc).astimezone(ZoneInfo('Asia/Shanghai')).date()
    async with sessions() as db:
        db.add_all([Employees(id=eid, user_id=str(eid), name=name, role=role,
                             status='inactive' if eid == 14 else 'active',
                             supervisor='Manager A' if eid == 11 else 'Manager B') for eid, (role, name) in ROLES.items()])
        db.add_all([
            MerchantPool(id=101, business_name='店名待核验', phone='+12125550101', country='US',
                         created_by_id=10, address='街道地址待核验（中文招聘来源）；广告日期/刷新日：2026-08-21',
                         data_source='华人招聘待核验|2026-08-21|60594',
                         raw_payload=json.dumps({'prospect_quality': {'status': 'valid', 'revision': 99}, 'secret': 'RAW_PRIVATE'})),
            MerchantPool(id=102, business_name='Other manager pool', phone='+12125550102', created_by_id=20),
            MerchantPool(id=103, business_name='Former pool', phone='+12125550103', created_by_id=10,
                         pool_status='converted', converted_lead_id=202),
            SalesLeads(id=201, business_name='Owned lead', phone='+12125550201', country='US',
                       assigned_sales_id=11, team_manager_id=10, merchant_pool_id=101, status='follow_up'),
            SalesLeads(id=202, business_name='Other lead', phone='+12125550202', assigned_sales_id=12, team_manager_id=20),
            SalesLeads(id=203, business_name='Protected lead', phone='+12125550203', country='US',
                       assigned_sales_id=11, do_not_contact=True, do_not_contact_reason='Original refusal'),
            SalesLeads(id=204, business_name='Customer already', phone='+12125550204', assigned_sales_id=11, converted_customer_id=88),
        ])
        db.add_all([SalesDailyDialTasks(id=tid, lead_id=lead, sales_employee_id=11, task_date=day, status=status)
                    for tid, lead, day, status in [(301, 201, today, 'pending'), (302, 201, today + timedelta(days=1), 'pending'),
                        (303, 201, today - timedelta(days=1), 'pending'), (304, 201, today - timedelta(days=2), 'completed'),
                        (305, 201, today + timedelta(days=2), 'cancelled'), (306, 202, today, 'pending')]])
        await db.commit()
    async def user(x_actor_id: int = Header(11), x_actor_role: str = Header(None)):
        role, name = ROLES[x_actor_id]
        return UserResponse(id=str(x_actor_id), email=f'{x_actor_id}@example.test', name=name, role=x_actor_role or role)
    async def database():
        async with sessions() as db:
            yield db
    app.dependency_overrides[get_current_user] = user
    app.dependency_overrides[get_db] = database
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://quality.test') as client:
        yield client, sessions
    await engine.dispose()


@pytest.mark.asyncio
async def test_pool_manager_scope_and_sales_pool_denial(verification_api):
    client, _ = verification_api
    assert (await client.get(f'{API}/pool/101', headers=auth(10))).status_code == 200
    assert (await client.get(f'{API}/pool/101', headers=auth(20))).status_code == 404
    assert (await client.get(f'{API}/pool/101', headers=auth(11))).status_code == 404
    assert (await client.patch(f'{API}/pool/102', headers=auth(10), json=body())).status_code == 404
    assert (await client.get(f'{API}/pool/102', headers=auth(2))).status_code == 200


@pytest.mark.asyncio
async def test_assigned_lead_and_current_manager_only(verification_api):
    client, _ = verification_api
    for actor in (1, 2, 10, 11):
        assert (await client.get(f'{API}/lead/201', headers=auth(actor))).status_code == 200
    for actor in (12, 20):
        assert (await client.get(f'{API}/lead/201', headers=auth(actor))).status_code == 404
        assert (await client.patch(f'{API}/lead/201', headers=auth(actor), json=body())).status_code == 404
    assert (await client.get(f'{API}/lead/201', headers=auth(13))).status_code == 403
    assert (await client.get(f'{API}/lead/201', headers=auth(14))).status_code == 403
    assert (await client.get(f'{API}/lead/201', headers=auth(11, **{'x-actor-role': 'admin'}))).status_code == 403


@pytest.mark.asyncio
async def test_import_cannot_claim_human_verification_or_invent_source(verification_api):
    client, _ = verification_api
    response = await client.get(f'{API}/pool/101', headers=auth(10))
    data = response.json()
    assert data['prospect_quality']['status'] == 'pending' and data['prospect_quality']['revision'] == 0
    assert data['prospect_source']['source_url'] is None
    assert data['prospect_source']['source_date'] == '2026-08-21'
    assert data['prospect_source']['verification_type'] == 'recruitment_contact'
    assert 'RAW_PRIVATE' not in response.text


@pytest.mark.asyncio
async def test_save_corrects_current_fields_preserves_source_and_server_attribution(verification_api):
    client, sessions = verification_api
    response = await client.patch(f'{API}/pool/101', headers=auth(10), json=body(corrected_fields={
        'business_name': 'Real Store from first call', 'address': '123 Actual Street', 'contact_name': 'Store manager', 'chinese_service': 'yes'}))
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved['prospect_quality']['revision'] == 1 and saved['prospect_quality']['verified_by_id'] == 10
    assert saved['effective_fields']['business_name'] == 'Real Store from first call'
    assert saved['history'][0]['before_fields']['business_name'] == '店名待核验'
    assert saved['history'][0]['actor']['id'] == 10
    async with sessions() as db:
        row = await db.get(MerchantPool, 101)
        assert json.loads(row.raw_payload)['secret'] == 'RAW_PRIVATE'
        assert row.pool_status == 'pending' and row.phone == '+12125550101'
        assert (await quality_for_many(db, 'pool', [101, 102]))[101]['status'] == 'valid'
        assert (await quality_for_many(db, 'pool', [101, 102]))[102]['status'] == 'pending'
    stale = await client.patch(f'{API}/pool/101', headers=auth(10), json=body(status='closed'))
    assert stale.status_code == 409
    assert (await client.get(f'{API}/pool/101', headers=auth(10))).json()['prospect_quality']['status'] == 'valid'


@pytest.mark.asyncio
async def test_parallel_save_has_one_revision_and_loser_preserves_winner(verification_api):
    client, sessions = verification_api
    results = await asyncio.gather(*[client.patch(f'{API}/lead/201', headers=auth(11), json=body(status=status)) for status in ('valid', 'not_target')])
    assert sorted(r.status_code for r in results) == [200, 409]
    async with sessions() as db:
        logs = (await db.scalars(select(Operation_logs).where(Operation_logs.action_type == 'prospect_quality:lead:201'))).all()
        assert len(logs) == 1 and json.loads(logs[0].action_detail)['after']['revision'] == 1


@pytest.mark.asyncio
async def test_contact_protection_and_converted_records_remain_readonly(verification_api):
    client, sessions = verification_api
    for entity in ('lead/203', 'lead/204', 'pool/103'):
        actor = 10 if entity.startswith('pool') else 11
        view = await client.get(f'{API}/{entity}', headers=auth(actor))
        assert view.status_code == 200 and not view.json()['can_edit']
        assert (await client.patch(f'{API}/{entity}', headers=auth(actor), json=body())).status_code == 409
    async with sessions() as db:
        row = await db.get(SalesLeads, 203)
        assert row.do_not_contact and row.do_not_contact_reason == 'Original refusal'


@pytest.mark.asyncio
async def test_quality_task_closure_and_revalidation_preserve_intent_owner_and_history(verification_api):
    client, sessions = verification_api
    result = await client.patch(f'{API}/lead/201', headers=auth(11), json=body(status='invalid_phone'))
    assert result.status_code == 200, result.text
    async with sessions() as db:
        tasks = {t.id: t.status for t in (await db.scalars(select(SalesDailyDialTasks))).all()}
        assert tasks == {301: 'cancelled', 302: 'cancelled', 303: 'pending', 304: 'completed', 305: 'cancelled', 306: 'pending'}
        lead = await db.get(SalesLeads, 201)
        assert lead.status == 'follow_up' and lead.assigned_sales_id == 11 and not lead.do_not_contact
    result = await client.patch(f'{API}/lead/201', headers=auth(11), json=body(revision=1, status='valid'))
    assert result.status_code == 200, result.text
    async with sessions() as db:
        tasks = {t.id: t.status for t in (await db.scalars(select(SalesDailyDialTasks))).all()}
        assert tasks == {301: 'pending', 302: 'pending', 303: 'pending', 304: 'completed', 305: 'cancelled', 306: 'pending'}
        lead = await db.get(SalesLeads, 201)
        assert lead.status == 'follow_up' and lead.assigned_sales_id == 11 and not lead.do_not_contact


@pytest.mark.asyncio
async def test_client_cannot_forge_actor_or_generic_audit_namespace(verification_api):
    client, _ = verification_api
    bad = await client.patch(f'{API}/lead/201', headers=auth(11), json=body(verified_by_id=1))
    assert bad.status_code == 422
    empty = await client.patch(f'{API}/lead/201', headers=auth(11), json=body(notes='   '))
    assert empty.status_code == 422
    for actor in (1, 11):
        response = await client.post('/api/v1/entities/operation_logs', headers=auth(actor), json={'action_type': 'prospect_quality:lead:201', 'action_detail': '{"after":{"status":"valid"}}'})
        assert response.status_code == 422
    assert (await client.put('/api/v1/entities/operation_logs/1', headers=auth(1), json={})).status_code == 405
    assert (await client.delete('/api/v1/entities/operation_logs/1', headers=auth(1))).status_code == 405


@pytest.mark.asyncio
async def test_quality_filter_plan_scans_ledger_once_and_reads_latest(verification_api):
    client, sessions = verification_api
    for revision, status in [(0, 'invalid_phone'), (1, 'valid')]:
        response = await client.patch(f'{API}/pool/101', headers=auth(10), json=body(revision, status))
        assert response.status_code == 200, response.text
    async with sessions() as db:
        expression = quality_status_expression('pool', MerchantPool.id, 'sqlite')
        query = select(MerchantPool.id, expression.label('quality')).order_by(MerchantPool.id)
        assert dict((await db.execute(query)).all()) == {101: 'valid', 102: 'pending', 103: 'pending'}
        sql = str(query.compile(dialect=db.get_bind().dialect, compile_kwargs={'literal_binds': True}))
        plan = [row[3] for row in (await db.execute(text('EXPLAIN QUERY PLAN ' + sql))).all()]
        assert sum('SCAN operation_logs' in detail for detail in plan) == 1, plan
        assert any('MATERIALIZE' in detail for detail in plan), plan
        print('QUALITY_SQLITE_PLAN', json.dumps(plan))


@pytest.mark.asyncio
async def test_quality_history_blocks_single_and_bulk_id_reuse_without_deleting(verification_api):
    client, sessions = verification_api
    response = await client.patch(f'{API}/pool/101', headers=auth(10), json=body())
    assert response.status_code == 200
    async with sessions() as db:
        await ensure_quality_history_retained(db, 'pool', [102])
        for ids in ([101], [101, 102]):
            with pytest.raises(HTTPException) as rejected:
                await ensure_quality_history_retained(db, 'pool', ids)
            assert rejected.value.status_code == 409 and '归档' in rejected.value.detail
        # Entity namespaces remain independent even when numeric IDs coincide.
        await ensure_quality_history_retained(db, 'lead', [101])
        assert await db.get(MerchantPool, 101) is not None
        assert await db.get(MerchantPool, 102) is not None


def test_explicit_source_date_rejects_invalid_dates_without_guessing_url():
    source = source_metadata_from_raw({'source_date': '2026-13-99'}, {'data_source': '华人招聘待核验|2026-08-21|60594', 'business_name': '店名待核验'})
    assert source['source_url'] is None and source['source_date'] is None
