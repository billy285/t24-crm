"""Synthetic sales profile workflow: isolation, atomicity, conflicts and audit."""
import importlib.util
import asyncio
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from alembic.migration import MigrationContext
from alembic.operations import Operations
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.main import app
from core.database import Base, get_db
from models.customers import Customers
from models.employees import Employees
from models.management_decisions import BusinessLine, ProductCatalog
from models.merchant_pool import MerchantPool
from models.payments import Payments
from models.sales_call_activities import SalesCallActivities
from models.sales_daily_dial_tasks import SalesDailyDialTasks
from models.sales_leads import SalesLeads
from models.sales_lead_enrichments import SalesLeadEnrichment, SalesLeadEnrichmentAudit, SalesDialAttempt
from services.emp_auth import create_access_token

API='/api/v1/sales-leads'
EDITABLE=('business_name','industry','city','state','country','address','website','store_phone','contacts',
          'preferred_contact_id','interest_product_ids','need_summary','best_contact_time','verification')


def auth(role='sales', employee_id=11, name='Sales A'):
    return {'Authorization':'Bearer '+create_access_token({'emp_id':employee_id,'email':f'{employee_id}@example.test','role':role,'name':name})}


def edit(profile, **changes):
    return {**{key:profile[key] for key in EDITABLE},'expected_revision':profile['revision'],
            'expected_lead_updated_at':profile['lead_updated_at'],'source':'manual',**changes}


@pytest_asyncio.fixture
async def enrichment_api(monkeypatch, tmp_path):
    monkeypatch.setenv('ENFORCE_EMPLOYEE_STATUS','false')
    monkeypatch.setenv('ENFORCE_EMPLOYEE_SESSIONS','false')
    engine=create_async_engine('sqlite+aiosqlite:///'+str(tmp_path/'sales-enrichment.sqlite'))
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions=async_sessionmaker(engine,expire_on_commit=False)
    today=datetime.now(ZoneInfo('Asia/Shanghai')).date()
    async with sessions() as db:
        db.add_all([
            Employees(id=10,user_id='10',name='Manager A',role='sales_manager',status='active'),
            Employees(id=11,user_id='11',name='Sales A',role='sales',supervisor='Manager A',status='active'),
            Employees(id=12,user_id='12',name='Sales B',role='sales',supervisor='Manager B',status='active'),
            SalesLeads(id=1,business_name='Own Store',contact_name='Legacy Owner',phone='+12125550111',country='US',assigned_sales_id=11,merchant_pool_id=77),
            SalesLeads(id=2,business_name='PRIVATE_OTHER_STORE',phone='+12125550222',country='US',assigned_sales_id=12),
            SalesDailyDialTasks(id=101,lead_id=1,sales_employee_id=11,task_date=today,status='pending'),
            SalesDailyDialTasks(id=102,lead_id=2,sales_employee_id=12,task_date=today,status='pending'),
            MerchantPool(id=77,business_name='Original Pool',phone='+12125550111',country='US'),
            Customers(id=80,business_name='PRIVATE_CUSTOMER',contact_name='PRIVATE_OWNER',phone='+12125550333',country='US'),
            Payments(id=90,customer_id=80,amount_due=900,amount_paid=800,net_amount=700,user_id='1',notes='PRIVATE_FINANCE'),
            BusinessLine(id=1,code='enrichment',name='Service',is_active=True),
            ProductCatalog(id=1,business_line_id=1,code='active',name='Active product',billing_kind='recurring',is_active=True),
            ProductCatalog(id=2,business_line_id=1,code='disabled',name='Disabled product',billing_kind='recurring',is_active=False),
            ProductCatalog(id=3,business_line_id=1,code='future',name='Future product',billing_kind='recurring',is_active=True,effective_from=date.today()+timedelta(days=1)),
        ])
        await db.commit()
    async def override_db():
        async with sessions() as db:
            yield db
    app.dependency_overrides[get_db]=override_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
            yield client,sessions
    finally:
        app.dependency_overrides.pop(get_db,None)
        await engine.dispose()


async def get_profile(client, lead_id=1, headers=None):
    response=await client.get(f'{API}/{lead_id}/enrichment',headers=headers or auth())
    assert response.status_code==200,response.text
    return response.json()


@pytest.mark.asyncio
async def test_read_profile_does_not_create_or_modify_any_sales_record(enrichment_api):
    client,sessions=enrichment_api
    data=await get_profile(client)
    assert data['revision']==0 and data['store_phone']=='+12125550111'
    assert data['contacts']==[{'id':'legacy-1','name':'Legacy Owner','role':None,'phone':None,'email':None,'wechat':None,'verification':'pending'}]
    assert data['preferred_contact_id']=='legacy-1' and data['can_edit'] is True
    async with sessions() as db:
        assert (await db.execute(select(SalesLeadEnrichment))).scalars().all()==[]
        assert (await db.get(SalesDailyDialTasks,101)).status=='pending'
    history=await client.get(f'{API}/1/enrichment/history',headers=auth())
    assert history.json()['total']==0


@pytest.mark.asyncio
@pytest.mark.parametrize('role,eid,name,own,other',[('sales',11,'Sales A',200,404),('sales_manager',10,'Manager A',200,404),('admin',1,'Admin',200,200),('ops',13,'Ops',403,403),('sales_partner',14,'Partner',403,403)])
async def test_sales_scope_applies_to_read_write_history_catalog(enrichment_api,role,eid,name,own,other):
    client,_=enrichment_api
    headers=auth(role,eid,name);draft=edit(await get_profile(client))
    for lead_id,expected in [(1,own),(2,other)]:
        assert (await client.get(f'{API}/{lead_id}/enrichment',headers=headers)).status_code==expected
        assert (await client.get(f'{API}/{lead_id}/enrichment/history',headers=headers)).status_code==expected
        if expected!=200:
            assert (await client.put(f'{API}/{lead_id}/enrichment',headers=headers,json=draft)).status_code==expected
    catalog=await client.get(f'{API}/enrichment/catalog',headers=headers)
    assert catalog.status_code==(403 if role in {'ops','sales_partner'} else 200)


@pytest.mark.asyncio
async def test_full_profile_normalizes_numbers_preserves_history_and_other_domains(enrichment_api):
    client,sessions=enrichment_api
    first=await get_profile(client)
    payload=edit(first,business_name='Renamed Store',store_phone='(212) 555-0444',city='NYC',
        contacts=[{'id':'owner-1','name':'Owner','role':'老板','phone':'212-555-0555','email':'owner@example.test','wechat':'wx','verification':'confirmed'}],
        preferred_contact_id='owner-1',interest_product_ids=[1],need_summary='需要广告',best_contact_time='美国东部时间下午',verification='confirmed')
    result=await client.put(f'{API}/1/enrichment',headers=auth(),json=payload)
    assert result.status_code==200,result.text
    saved=result.json();assert saved['revision']==1 and saved['store_phone']=='+12125550444'
    assert saved['contacts'][0]['phone']=='+12125550555' and saved['updated_by_name']=='Sales A'
    assert saved['lead_updated_at']!=first['lead_updated_at']
    history=(await client.get(f'{API}/1/enrichment/history',headers=auth())).json()
    assert history['total']==1 and history['items'][0]['before']['store_phone']=='+12125550111'
    assert history['items'][0]['after']['store_phone']=='+12125550444'
    assert 'contacts' in history['items'][0]['changed_fields']
    async with sessions() as db:
        lead=await db.get(SalesLeads,1);assert lead.phone=='+12125550444' and lead.contact_name=='Owner'
        assert (await db.get(MerchantPool,77)).business_name=='Original Pool'
        assert (await db.get(Customers,80)).business_name=='PRIVATE_CUSTOMER'
        payment=await db.get(Payments,90);assert (payment.amount_due,payment.amount_paid,payment.net_amount,payment.notes)==(900,800,700,'PRIVATE_FINANCE')
        assert (await db.get(SalesDailyDialTasks,101)).status=='pending'
        assert (await db.execute(select(SalesCallActivities))).scalars().all()==[]


@pytest.mark.asyncio
@pytest.mark.parametrize('forged', [{'assigned_sales_id':12},{'customer_id':80},{'converted_customer_id':80},{'actor_id':1},{'commission_partner_id':1},{'amount_paid':0}])
async def test_extra_fields_cannot_change_ownership_customer_or_finance(enrichment_api,forged):
    client,_=enrichment_api
    original=await get_profile(client)
    result=await client.put(f'{API}/1/enrichment',headers=auth(),json={**edit(original),**forged})
    assert result.status_code==422,result.text
    assert (await get_profile(client))['revision']==0


@pytest.mark.asyncio
async def test_conflicts_protect_revision_and_lead_updates(enrichment_api):
    client,_=enrichment_api
    draft=edit(await get_profile(client),need_summary='old draft')
    first=await client.put(f'{API}/1/enrichment',headers=auth(),json=draft)
    assert first.status_code==200
    assert (await client.put(f'{API}/1/enrichment',headers=auth(),json=draft)).status_code==409
    fresh=edit(first.json())
    update=await client.put(f'{API}/1',headers=auth('admin',1,'Admin'),json={'city':'Changed externally'})
    assert update.status_code==200,update.text
    assert (await client.put(f'{API}/1/enrichment',headers=auth(),json=fresh)).status_code==409
    assert (await get_profile(client))['city']=='Changed externally'


@pytest.mark.asyncio
async def test_assignment_race_uses_current_scope_and_stale_admin_token(enrichment_api):
    client,sessions=enrichment_api
    draft=edit(await get_profile(client))
    async with sessions() as db:
        lead=await db.get(SalesLeads,1);lead.assigned_sales_id=12;await db.commit()
    assert (await client.put(f'{API}/1/enrichment',headers=auth(),json=draft)).status_code==404
    assert (await client.put(f'{API}/1/enrichment',headers=auth('admin',1,'Admin'),json=draft)).status_code==409
    assert (await client.post(f'{API}/workbench/tasks/101/result',headers=auth('admin',1,'Admin'),json={'outcome':'no_answer'})).status_code==409
    async with sessions() as db:
        assert (await db.get(SalesDailyDialTasks,101)).status=='pending'
        assert await db.get(SalesLeadEnrichment,1) is None


@pytest.mark.asyncio
@pytest.mark.parametrize('field,value',[('converted_customer_id',80),('status','converted'),('do_not_contact',True),('is_blacklisted',True)])
async def test_converted_or_blocked_lead_refuses_enrichment_and_dial(enrichment_api,field,value):
    client,sessions=enrichment_api;draft=edit(await get_profile(client))
    async with sessions() as db:
        setattr(await db.get(SalesLeads,1),field,value);await db.commit()
    blocked=await get_profile(client)
    assert blocked['can_edit'] is False and blocked['read_only_reason']
    assert (await client.put(f'{API}/1/enrichment',headers=auth(),json=draft)).status_code==409
    assert (await client.post(f'{API}/workbench/tasks/101/dial-started',headers=auth())).status_code in {400,409}
    assert (await client.post(f'{API}/workbench/tasks/101/result',headers=auth(),json={'outcome':'no_answer','enrichment':draft})).status_code in {400,409}
    async with sessions() as db:
        assert await db.get(SalesLeadEnrichment,1) is None
        assert (await db.get(SalesDailyDialTasks,101)).dial_started_at is None


@pytest.mark.asyncio
async def test_active_products_only_and_unknown_product_rejects_atomically(enrichment_api):
    client,_=enrichment_api
    catalog=await client.get(f'{API}/enrichment/catalog',headers=auth())
    assert catalog.json()=={'items':[{'id':1,'name':'Active product'}]}
    for product_id in (2,3,999):
        response=await client.put(f'{API}/1/enrichment',headers=auth(),json=edit(await get_profile(client),interest_product_ids=[product_id]))
        assert response.status_code==422,response.text
    assert (await get_profile(client))['revision']==0


@pytest.mark.asyncio
async def test_duplicate_phone_only_anonymous_warning_no_identity_or_merge(enrichment_api):
    client,sessions=enrichment_api
    response=await client.put(f'{API}/1/enrichment',headers=auth(),json=edit(await get_profile(client),
        contacts=[{'id':'other','name':'Contact','phone':'+12125550222','verification':'confirmed'}],preferred_contact_id='other',store_phone='+12125550333',verification='confirmed'))
    assert response.status_code==200,response.text
    assert response.json()['verification']=='pending' and response.json()['contacts'][0]['verification']=='pending'
    assert response.json()['warnings'] and all(secret not in response.text for secret in ('PRIVATE_OTHER_STORE','PRIVATE_CUSTOMER','PRIVATE_OWNER','PRIVATE_FINANCE'))
    async with sessions() as db:
        assert (await db.get(SalesLeads,2)).business_name=='PRIVATE_OTHER_STORE'
        assert (await db.get(Customers,80)).phone=='+12125550333'


@pytest.mark.asyncio
async def test_pending_invalid_number_retained_but_not_dialable(enrichment_api):
    client,sessions=enrichment_api
    draft=edit(await get_profile(client),store_phone='12345',verification='pending')
    response=await client.put(f'{API}/1/enrichment',headers=auth(),json=draft)
    assert response.status_code==200 and response.json()['store_phone']=='12345' and response.json()['warnings']
    assert (await client.post(f'{API}/workbench/tasks/101/dial-started',headers=auth())).status_code==422
    response=await client.put(f'{API}/1/enrichment',headers=auth(),json=edit(await get_profile(client),verification='confirmed'))
    assert response.status_code==422
    async with sessions() as db:
        assert (await db.execute(select(SalesDialAttempt))).scalars().all()==[]


@pytest.mark.asyncio
async def test_result_and_enrichment_commit_together_and_use_post_outcome_version(enrichment_api):
    client,sessions=enrichment_api
    draft=edit(await get_profile(client),need_summary='Atomic needs')
    response=await client.post(f'{API}/workbench/tasks/101/result',headers=auth(),json={'outcome':'callback','notes':'约定回访','next_follow_up_at':'2027-01-01T09:00:00Z','enrichment':draft})
    assert response.status_code==200,response.text
    saved=response.json()['enrichment'];assert saved['revision']==1 and saved['need_summary']=='Atomic needs'
    assert saved['lead_updated_at']==response.json()['lead']['updated_at']+'+00:00' or datetime.fromisoformat(saved['lead_updated_at'])==datetime.fromisoformat(response.json()['lead']['updated_at'].replace('Z','+00:00')).replace(tzinfo=timezone.utc)
    assert (await client.put(f'{API}/1/enrichment',headers=auth(),json=edit(saved,best_contact_time='next time'))).status_code==200
    async with sessions() as db:
        assert (await db.get(SalesDailyDialTasks,101)).status=='completed'
        assert len((await db.execute(select(SalesCallActivities))).scalars().all())==1
        rows=(await db.execute(select(SalesLeadEnrichmentAudit).order_by(SalesLeadEnrichmentAudit.revision))).scalars().all()
        assert [row.source for row in rows]==['call','manual']


@pytest.mark.asyncio
async def test_late_call_validation_failure_rolls_back_enrichment_and_audit(enrichment_api):
    client,sessions=enrichment_api
    draft=edit(await get_profile(client),business_name='SHOULD_ROLL_BACK')
    response=await client.post(f'{API}/workbench/tasks/101/result',headers=auth(),json={
        'outcome':'no_answer','enrichment':draft,'contact_details':{'reached_person':'decision_maker'}})
    assert response.status_code==422,response.text
    async with sessions() as db:
        assert (await db.get(SalesLeads,1)).business_name=='Own Store'
        assert (await db.get(SalesDailyDialTasks,101)).status=='pending'
        assert await db.get(SalesLeadEnrichment,1) is None
        assert (await db.execute(select(SalesLeadEnrichmentAudit))).scalars().all()==[]
        assert (await db.execute(select(SalesCallActivities))).scalars().all()==[]


@pytest.mark.asyncio
async def test_dial_attempts_retain_each_saved_number_and_activity_actual_phone(enrichment_api):
    client,sessions=enrichment_api
    await client.put(f'{API}/1/enrichment',headers=auth(),json=edit(await get_profile(client),
        contacts=[{'id':'mobile','name':'Owner','phone':'+12125550444'}],preferred_contact_id='mobile'))
    assert (await client.post(f'{API}/workbench/tasks/101/dial-started',headers=auth(),json={'phone':'+12125559999'})).status_code==409
    first=await client.post(f'{API}/workbench/tasks/101/dial-started',headers=auth())
    second=await client.post(f'{API}/workbench/tasks/101/dial-started',headers=auth(),json={'phone':'212-555-0444'})
    assert first.status_code==second.status_code==200
    assert second.json()['phone']=='+12125550444'
    await client.put(f'{API}/1/enrichment',headers=auth(),json=edit(await get_profile(client),store_phone='+12125550666'))
    result=await client.post(f'{API}/workbench/tasks/101/result',headers=auth(),json={'outcome':'no_answer'})
    assert result.status_code==200,result.text
    history=(await client.get(f'{API}/1/call-history',headers=auth())).json()
    assert history[0]['dial_phone']=='+12125550444'
    async with sessions() as db:
        attempts=(await db.execute(select(SalesDialAttempt).order_by(SalesDialAttempt.id))).scalars().all()
        assert [row.dial_phone for row in attempts]==['+12125550111','+12125550444']
        assert all(row.sales_employee_id==11 and row.lead_id==1 and row.task_id==101 for row in attempts)


@pytest.mark.asyncio
async def test_summary_is_readonly_batch_and_only_current_scoped_queue(enrichment_api):
    client,sessions=enrichment_api
    saved=await client.put(f'{API}/1/enrichment',headers=auth(),json=edit(await get_profile(client),interest_product_ids=[1],verification='confirmed',contacts=[],preferred_contact_id=None))
    assert saved.status_code==200
    result=await client.get(f'{API}/workbench/today',headers=auth())
    assert result.status_code==200,result.text
    summary=result.json()['items'][0]['lead']['enrichment_summary']
    assert summary=={'has_contact':False,'needs_review':False,'has_interest':True,'interest_product_names':['Active product'],'revision':1}
    async with sessions() as db:
        (await db.get(SalesLeads,1)).assigned_sales_id=12
        (await db.get(SalesDailyDialTasks,101)).status='completed'
        await db.commit()
    result=await client.get(f'{API}/workbench/today',headers=auth())
    assert result.json()['items'] == []  # former task history must not reveal the current dossier


def test_migration_only_adds_sales_tables_and_nullable_dial_columns():
    path=Path(__file__).resolve().parents[1]/'alembic/versions/e6c0b4f8a916_sales_lead_enrichment.py'
    spec=importlib.util.spec_from_file_location('sales_enrichment_migration',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    engine=create_engine('sqlite://')
    with engine.begin() as connection:
        for table in ('sales_daily_dial_tasks','sales_call_activities','customers','payments','merchant_pool'):
            connection.execute(text(f'CREATE TABLE {table} (id INTEGER PRIMARY KEY, value TEXT)'))
            connection.execute(text(f"INSERT INTO {table} (id,value) VALUES (1,'preserve')"))
        module.op=Operations(MigrationContext.configure(connection));module.upgrade()
        tables=set(inspect(connection).get_table_names())
        assert tables=={'sales_daily_dial_tasks','sales_call_activities','customers','payments','merchant_pool','sales_lead_enrichments','sales_lead_enrichment_audits','sales_dial_attempts'}
        for table in ('sales_daily_dial_tasks','sales_call_activities','customers','payments','merchant_pool'):
            assert connection.execute(text(f'SELECT id,value FROM {table}')).all()==[(1,'preserve')]
        for table in ('sales_daily_dial_tasks','sales_call_activities'):
            assert connection.execute(text(f'SELECT dial_phone FROM {table}')).scalar() is None
        with pytest.raises(RuntimeError): module.downgrade()


@pytest.mark.asyncio
async def test_two_tabs_only_one_revision_wins_and_no_lost_update(enrichment_api):
    client,sessions=enrichment_api
    original=await get_profile(client)
    responses=await asyncio.gather(*[
        client.put(f'{API}/1/enrichment',headers=auth(),json=edit(original,need_summary=summary))
        for summary in ('Tab A','Tab B')])
    assert sorted(response.status_code for response in responses)==[200,409]
    saved=await get_profile(client)
    assert saved['revision']==1 and saved['need_summary'] in {'Tab A','Tab B'}
    async with sessions() as db:
        assert len((await db.execute(select(SalesLeadEnrichmentAudit))).scalars().all())==1
        assert (await db.get(SalesDailyDialTasks,101)).status=='pending'


@pytest.mark.asyncio
@pytest.mark.parametrize('matching_mobile_record',[False,True])
async def test_call_result_never_attaches_earlier_store_provider_fact_to_mobile(enrichment_api,matching_mobile_record):
    from models.ringcentral_call_records import RingCentralCallRecords
    client,sessions=enrichment_api
    await client.put(f'{API}/1/enrichment',headers=auth(),json=edit(await get_profile(client),contacts=[{'id':'mobile','name':'Owner','phone':'+12125550444'}],preferred_contact_id='mobile'))
    await client.post(f'{API}/workbench/tasks/101/dial-started',headers=auth())
    await client.post(f'{API}/workbench/tasks/101/dial-started',headers=auth(),json={'phone':'+12125550444'})
    async with sessions() as db:
        db.add(RingCentralCallRecords(provider_key='store-call',sales_employee_id=11,lead_id=1,task_id=101,remote_phone='+12125550111',started_at=datetime.now(timezone.utc),duration_seconds=99,connected=True,sync_status='verified'))
        if matching_mobile_record:
            db.add(RingCentralCallRecords(provider_key='mobile-call',sales_employee_id=11,lead_id=1,task_id=101,remote_phone='+12125550444',started_at=datetime.now(timezone.utc),duration_seconds=41,connected=True,sync_status='verified'))
        await db.commit()
    response=await client.post(f'{API}/workbench/tasks/101/result',headers=auth(),json={'outcome':'no_answer'})
    assert response.status_code==200,response.text
    async with sessions() as db:
        activity=(await db.execute(select(SalesCallActivities))).scalar_one()
        assert activity.dial_phone=='+12125550444'
        assert activity.call_duration_seconds==(41 if matching_mobile_record else None)
        store=(await db.execute(select(RingCentralCallRecords).where(RingCentralCallRecords.provider_key=='store-call'))).scalar_one()
        assert store.activity_id is None


@pytest.mark.asyncio
async def test_product_effective_date_uses_sales_business_day_not_server_utc_day(enrichment_api,monkeypatch):
    import services.sales_enrichment as service
    client,sessions=enrichment_api
    fixed=datetime(2026,10,14,17,0,tzinfo=timezone.utc)  # Shanghai is already Oct 15.
    class BusinessClock(datetime):
        @classmethod
        def now(cls,tz=None):
            return fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None)
    monkeypatch.setattr(service,'datetime',BusinessClock)
    async with sessions() as db:
        await db.execute(text('UPDATE product_catalog SET is_active=0'))
        db.add_all([
            ProductCatalog(id=4,business_line_id=1,code='new-business-day',name='Today product',billing_kind='recurring',is_active=True,effective_from=date(2026,10,15)),
            ProductCatalog(id=5,business_line_id=1,code='old-server-day',name='Expired product',billing_kind='recurring',is_active=True,effective_to=date(2026,10,14)),
        ])
        await db.commit()
    response=await client.get(f'{API}/enrichment/catalog',headers=auth())
    assert response.status_code==200 and response.json()=={'items':[{'id':4,'name':'Today product'}]}


@pytest.mark.asyncio
async def test_completed_task_can_dial_and_append_result_without_reopening_or_overwriting(enrichment_api):
    client,sessions=enrichment_api
    await client.post(f'{API}/workbench/tasks/101/dial-started',headers=auth())
    first=await client.post(f'{API}/workbench/tasks/101/result',headers=auth(),json={'outcome':'callback','notes':'First call','next_follow_up_at':'2027-01-01T09:00:00Z'})
    assert first.status_code==200
    async with sessions() as db:
        task=await db.get(SalesDailyDialTasks,101)
        original_id,completed_at=task.completed_activity_id,task.completed_at
        original=await db.get(SalesCallActivities,original_id)
        original_values=(original.outcome,original.notes,original.dial_phone,original.dial_attempt_id)
    dial=await client.post(f'{API}/workbench/tasks/101/dial-started',headers=auth())
    assert dial.status_code==200,dial.text
    aid=dial.json()['dial_attempt_id']
    result=await client.post(f'{API}/1/follow-up',headers=auth(),json={'outcome':'callback','notes':'Second call','next_follow_up_at':'2027-01-02T09:00:00Z','dial_attempt_id':aid})
    assert result.status_code==200,result.text
    async with sessions() as db:
        task=await db.get(SalesDailyDialTasks,101)
        assert task.status=='completed' and task.completed_activity_id==original_id and task.completed_at==completed_at
        original=await db.get(SalesCallActivities,original_id)
        assert (original.outcome,original.notes,original.dial_phone,original.dial_attempt_id)==original_values
        activities=(await db.execute(select(SalesCallActivities).order_by(SalesCallActivities.id))).scalars().all()
        assert len(activities)==2 and activities[1].dial_attempt_id==aid and activities[1].dial_phone=='+12125550111'
    replay=await client.post(f'{API}/1/follow-up',headers=auth(),json={'outcome':'no_answer','dial_attempt_id':aid})
    assert replay.status_code==409,replay.text


@pytest.mark.asyncio
async def test_completed_task_dial_rejects_reassignment_and_old_sales(enrichment_api):
    client,sessions=enrichment_api
    result=await client.post(f'{API}/workbench/tasks/101/result',headers=auth(),json={'outcome':'no_answer'})
    assert result.status_code==200
    async with sessions() as db:
        lead=await db.get(SalesLeads,1);lead.assigned_sales_id=12;await db.commit()
    assert (await client.post(f'{API}/workbench/tasks/101/dial-started',headers=auth())).status_code==404
    assert (await client.post(f'{API}/workbench/tasks/101/dial-started',headers=auth('admin',1,'Admin'))).status_code==409
    async with sessions() as db:
        assert (await db.execute(select(SalesDialAttempt))).scalars().all()==[]
        assert (await db.get(SalesDailyDialTasks,101)).status=='completed'


@pytest.mark.asyncio
async def test_supplemental_no_attempt_does_not_guess_actual_phone(enrichment_api):
    client,sessions=enrichment_api
    await client.post(f'{API}/workbench/tasks/101/result',headers=auth(),json={'outcome':'no_answer'})
    response=await client.post(f'{API}/1/follow-up',headers=auth(),json={'outcome':'callback','notes':'Legacy supplemental','next_follow_up_at':'2027-01-01T09:00:00Z'})
    assert response.status_code==200,response.text
    async with sessions() as db:
        row=(await db.execute(select(SalesCallActivities).order_by(SalesCallActivities.id.desc()))).scalars().first()
        assert row.dial_phone is None and row.dial_attempt_id is None


@pytest.mark.asyncio
async def test_supplemental_cannot_consume_another_lead_or_employee_dial(enrichment_api):
    client,sessions=enrichment_api
    await client.post(f'{API}/workbench/tasks/101/result',headers=auth(),json={'outcome':'no_answer'})
    other=await client.post(f'{API}/workbench/tasks/102/dial-started',headers=auth('sales',12,'Sales B'))
    assert other.status_code==200
    response=await client.post(f'{API}/1/follow-up',headers=auth(),json={'outcome':'no_answer','dial_attempt_id':other.json()['dial_attempt_id']})
    assert response.status_code==409,response.text
    async with sessions() as db:
        assert len((await db.execute(select(SalesCallActivities))).scalars().all())==1


@pytest.mark.asyncio
async def test_supplemental_does_not_take_ambiguous_old_same_number_provider_call(enrichment_api):
    from models.ringcentral_call_records import RingCentralCallRecords
    client,sessions=enrichment_api
    await client.post(f'{API}/workbench/tasks/101/dial-started',headers=auth())
    await client.post(f'{API}/workbench/tasks/101/result',headers=auth(),json={'outcome':'no_answer'})
    async with sessions() as db:
        original=(await db.execute(select(SalesCallActivities))).scalar_one()
        original_id=original.id
        db.add(RingCentralCallRecords(provider_key='old-same-phone',sales_employee_id=11,lead_id=1,task_id=101,remote_phone='+12125550111',started_at=datetime.now(timezone.utc),duration_seconds=99,connected=True,sync_status='verified'))
        await db.commit()
    newdial=await client.post(f'{API}/workbench/tasks/101/dial-started',headers=auth())
    response=await client.post(f'{API}/1/follow-up',headers=auth(),json={'outcome':'callback','notes':'New result','next_follow_up_at':'2027-01-01T09:00:00Z','dial_attempt_id':newdial.json()['dial_attempt_id']})
    assert response.status_code==200,response.text
    async with sessions() as db:
        activities=(await db.execute(select(SalesCallActivities).order_by(SalesCallActivities.id))).scalars().all()
        assert len(activities)==2 and all(row.call_duration_seconds is None for row in activities)
        assert (await db.get(SalesDailyDialTasks,101)).completed_activity_id==original_id
        record=(await db.execute(select(RingCentralCallRecords))).scalar_one()
        assert record.activity_id is None
