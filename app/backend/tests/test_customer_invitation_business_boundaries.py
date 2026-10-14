"""Synthetic ASGI tests for independent invitation modules and finance denial."""
import json
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.main import app
from core.database import Base, get_db
from models.customer_access_grants import CustomerAccessGrant
from models.customers import Customers
from models.employees import Employees
from models.customer_contacts import Customer_contacts
from models.follow_ups import Follow_ups
from models.deals import Deals
from models.subscriptions import Subscriptions
from models.service_progresses import Service_progresses
from models.service_tasks import Service_tasks
from models.tasks import Tasks
from models.customer_materials import Customer_materials
from models.customer_menu_items import Customer_menu_items
from models.customer_ai_copies import Customer_ai_copies
from models.media_accounts import Media_accounts
from models.opportunities import Opportunities
from models.management_decisions import BusinessLine
from models.operation_logs import Operation_logs
from services.emp_auth import create_access_token


def auth(role='ops', employee_id=20):
    token=create_access_token({'emp_id':employee_id,'email':f'invite-{employee_id}@example.test','role':role,'name':f'Actor {employee_id}'})
    return {'Authorization':f'Bearer {token}'}


@pytest_asyncio.fixture
async def invitation_api(monkeypatch):
    monkeypatch.setenv('ENFORCE_EMPLOYEE_STATUS','false')
    monkeypatch.setenv('ENFORCE_EMPLOYEE_SESSIONS','false')
    engine=create_async_engine('sqlite+aiosqlite:///:memory:',poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions=async_sessionmaker(engine,expire_on_commit=False)
    async with sessions() as db:
        for eid,role in [(1,'super_admin'),(2,'admin'),(10,'sales'),(11,'sales_manager'),(20,'ops')]:
            db.add(Employees(id=eid,user_id=str(eid),name=f'Actor {eid}',role=role,status='active',email=f'invite-{eid}@example.test',department='Sales',supervisor='Actor 11' if eid==10 else None))
        db.add(BusinessLine(id=1,code='invitation-test',name='Invitation service',is_active=True))
        for cid in (101,102):
            db.add_all([
                Customers(id=cid,business_name=f'Customer {cid}',contact_name='Test contact',phone='555',sales_employee_id=10,sales_person='Actor 10'),
                Customer_contacts(id=cid,customer_id=cid,contact_name='contact-only'),
                Follow_ups(id=cid,customer_id=cid,content='followup-only'),
                Deals(id=cid,customer_id=cid,customer_name=f'Customer {cid}',product_type='managed_service',package_name='Business package',billing_cycle='monthly',sales_name='Actor 10',deal_amount=91234.56,is_paid=True,source_payment_id=9000+cid,notes='PRIVATE_FINANCE_NOTE',is_handed_over=True,needs_group=False,deal_date=datetime(2026,10,1)),
                Subscriptions(id=cid,customer_id=cid,customer_name=f'Customer {cid}',package_name='Subscription package',package_price=4321.99,list_price_snapshot=4432.11,pricing_source='PRIVATE_PRICING',billing_cycle='monthly',status='active',auto_renew=True,renewal_person='RENEWAL_ONLY',last_payment_date=datetime(2026,10,1),next_payment_date=datetime(2026,11,1),renewal_result='PRIVATE_RENEWAL_RESULT',service_scope_json='{"private_finance":"FINANCIAL_JSON"}'),
                Service_progresses(id=cid,customer_id=cid,service_stage='active',user_id='1'),
                Service_tasks(id=cid,customer_id=cid,task_name='Delivery task',status='pending',user_id='1'),
                Tasks(id=cid,customer_id=cid,title='Assigned delivery task',assignee_id=20,assignee_name='Actor 20',status='pending'),
                Customer_materials(id=cid,customer_id=cid,user_id='1',title='Team material',material_type='document',visibility='team'),
                Customer_menu_items(id=cid,customer_id=cid,user_id='1',name='Menu item',item_type='service'),
                Customer_ai_copies(id=cid,customer_id=cid,user_id='1',title='Copy',content='content',platform='facebook',content_type='weekly_update'),
                Media_accounts(id=cid,customer_id=cid,user_id='1',platform_name='Google',account_name='Media',login_password='PRIVATE_PASSWORD'),
                Opportunities(id=cid,customer_id=cid,customer_name=f'Customer {cid}',business_line_id=1,opportunity_code=f'INV-{cid}',title='Opportunity',stage='initial',status='open',estimated_amount=1234.56,next_follow_up_at=datetime.now(timezone.utc)+timedelta(days=1)),
            ])
        db.add(CustomerAccessGrant(customer_id=101,employee_id=20,access_level='read_only',scopes={'basic':'read_only','deals':'read_only'},invitation_status='active',invitation_source='owner_invitation',granted_by_id='1',finance_access='none'))
        # An old automatic grant is not a reviewed invitation.
        db.add(CustomerAccessGrant(customer_id=101,employee_id=10,access_level='read_write',scopes={m:'read_write' for m in ('basic','contacts','followups','opportunities','delivery','renewals','deals','materials')},invitation_status='pending_review',invitation_source='legacy'))
        await db.execute(text('CREATE TABLE IF NOT EXISTS app_settings (config_key TEXT PRIMARY KEY,value_json TEXT NOT NULL,updated_at TIMESTAMP)'))
        buttons=['customer_edit','customer_delete','follow_up_create','follow_up_edit','task_create','task_edit','task_delete','media_account_create','media_account_edit']
        config={r:{'pages':['/customers','/service-board','/tasks'],'buttons':buttons,'dataScope':'all'} for r in ('ops','admin','sales','sales_manager','super_admin')}
        await db.execute(text("INSERT INTO app_settings(config_key,value_json) VALUES('role_permissions',:value)"),{'value':json.dumps(config)})
        await db.commit()
        async def override_db():
            yield db
        app.dependency_overrides[get_db]=override_db
        try:
            async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
                yield client,db
        finally:
            app.dependency_overrides.pop(get_db,None)
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('role,employee_id',[('sales',10),('sales_manager',11),('admin',2)])
async def test_owner_department_and_legacy_grants_do_not_replace_invitation(invitation_api,role,employee_id):
    client,_=invitation_api
    for entity in ('deals','customer_contacts','follow_ups','service_progresses','subscriptions','media_accounts','tasks'):
        response=await client.get(f'/api/v1/entities/{entity}',headers=auth(role,employee_id))
        if entity in {'media_accounts','tasks'} and role in {'sales','sales_manager'}:
            assert response.status_code==403
            assert (await client.get(f'/api/v1/entities/{entity}/101',headers=auth(role,employee_id))).status_code==403
            continue
        assert response.status_code==200,(entity,response.text)
        assert response.json()['total']==0,(entity,response.text)
        direct=await client.get(f'/api/v1/entities/{entity}/101',headers=auth(role,employee_id))
        assert direct.status_code==404,(entity,direct.text)
    opportunities=await client.get('/api/v1/opportunities',headers=auth(role,employee_id))
    if role in {'sales','sales_manager'}:
        assert opportunities.status_code==403
    else:
        assert opportunities.status_code==200 and opportunities.json()['total']==0


@pytest.mark.asyncio
async def test_default_basic_deals_invite_is_business_read_only_and_does_not_unlock_other_modules(invitation_api):
    client,_=invitation_api
    for suffix in ('','/all','/101'):
        response=await client.get('/api/v1/entities/deals'+suffix,headers=auth())
        assert response.status_code==200,response.text
        row=response.json() if suffix=='/101' else response.json()['items'][0]
        assert row['id']==101 and row['package_name']=='Business package' and row['is_handed_over'] is True
        assert set(row).isdisjoint({'deal_amount','is_paid','source_payment_id','notes','opportunity_id'})
        assert '91234.56' not in response.text and 'PRIVATE_FINANCE_NOTE' not in response.text
    for suffix in ('','/all'):
        for params in ({'query':json.dumps({'is_paid':True})},{'query':json.dumps({'source_payment_id':9101})},{'sort':'deal_amount'},{'sort':'-notes'}):
            assert (await client.get('/api/v1/entities/deals'+suffix,params=params,headers=auth())).status_code==403
    for entity in ('customer_contacts','follow_ups','service_progresses','service_tasks','subscriptions','media_accounts','tasks'):
        listing=await client.get(f'/api/v1/entities/{entity}',headers=auth())
        assert listing.status_code==200 and listing.json()['total']==0,(entity,listing.text)
        assert (await client.get(f'/api/v1/entities/{entity}/101',headers=auth())).status_code==404
    for entity in ('customer_materials','customer_menu_items','customer_ai_copies'):
        response=await client.get(f'/api/v1/entities/{entity}',params={'query':json.dumps({'customer_id':101})},headers=auth())
        assert response.status_code==403,response.text
    for path in ('/api/v1/opportunities?customer_id=101','/api/v1/entities/customers/101/finance-access-data','/api/v1/entities/operation_logs/all','/api/v1/customer-lifecycle/customers/101','/api/v1/management-decisions/engagements?customer_id=101'):
        assert (await client.get(path,headers=auth())).status_code==403,path
    for method,path,payload in [('PUT','/api/v1/entities/deals/101',{'deal_amount':1}),('PATCH','/api/v1/entities/deals/101/handoff',{'is_handed_over':False}),('POST','/api/v1/entities/deals/101/finalize',{})]:
        assert (await client.request(method,path,json=payload,headers=auth())).status_code==403,path


@pytest.mark.asyncio
@pytest.mark.parametrize('module,entity',[('contacts','customer_contacts'),('followups','follow_ups'),('opportunities','opportunities'),('delivery','service_progresses'),('renewals','subscriptions'),('materials','media_accounts')])
async def test_each_invitation_module_is_independent(invitation_api,module,entity):
    client,db=invitation_api
    grant=await db.scalar(select(CustomerAccessGrant).where(CustomerAccessGrant.employee_id==20))
    grant.scopes={module:'read_only'}
    await db.commit()
    path='/api/v1/opportunities' if entity=='opportunities' else f'/api/v1/entities/{entity}'
    response=await client.get(path,headers=auth())
    assert response.status_code==200,response.text
    assert response.json()['total']==1,response.text
    assert response.json()['items'][0]['id']==101
    assert (await client.get('/api/v1/entities/deals/101',headers=auth())).status_code==404
    if module not in {'delivery','renewals'}:
        assert (await client.get('/api/v1/entities/subscriptions',params={'access_module':'delivery'},headers=auth())).json()['total']==0
        assert (await client.get('/api/v1/entities/subscriptions',headers=auth())).json()['total']==0


@pytest.mark.asyncio
async def test_delivery_and_renewals_share_no_implicit_permission_or_financial_fields(invitation_api):
    client,db=invitation_api
    grant=await db.scalar(select(CustomerAccessGrant).where(CustomerAccessGrant.employee_id==20))
    grant.scopes={'delivery':'read_only'}
    await db.commit()
    delivery=await client.get('/api/v1/entities/subscriptions/101?access_module=delivery',headers=auth())
    assert delivery.status_code==200,delivery.text
    assert delivery.json()['package_name']=='Subscription package'
    assert set(delivery.json()).isdisjoint({'package_price','list_price_snapshot','pricing_source','last_payment_date','next_payment_date','renewal_person','renewal_result','auto_renew','service_scope_json'})
    assert (await client.get('/api/v1/entities/subscriptions/101',headers=auth())).status_code==404
    for field in ('renewal_person','next_payment_date','package_price','service_scope_json'):
        result=await client.get('/api/v1/entities/subscriptions',params={'access_module':'delivery','query':json.dumps({field:'probe'})},headers=auth())
        assert result.status_code==403,result.text
    grant.scopes={'renewals':'read_only'}
    await db.commit()
    renewal=await client.get('/api/v1/entities/subscriptions/101',headers=auth())
    assert renewal.status_code==200,renewal.text
    assert renewal.json()['renewal_person']=='RENEWAL_ONLY'
    assert set(renewal.json()).isdisjoint({'package_price','last_payment_date','renewal_result','service_scope_json'})
    assert (await client.get('/api/v1/entities/subscriptions/101?access_module=delivery',headers=auth())).status_code==404
    assert (await client.get('/api/v1/entities/service_progresses/101',headers=auth())).status_code==404


@pytest.mark.asyncio
async def test_revocation_and_cross_module_nested_writes_fail_closed(invitation_api):
    client,db=invitation_api
    grant=await db.scalar(select(CustomerAccessGrant).where(CustomerAccessGrant.employee_id==20))
    grant.access_level='read_write'
    grant.scopes={'opportunities':'read_write'}
    await db.commit()
    response=await client.post('/api/v1/opportunities/101/follow-ups',json={'content':'cross module should fail','next_follow_up_at':datetime.now(timezone.utc).isoformat()},headers=auth())
    assert response.status_code==403,response.text
    assert await db.scalar(select(Follow_ups.id).where(Follow_ups.content=='cross module should fail')) is None
    grant.invitation_status='revoked'
    await db.commit()
    assert (await client.get('/api/v1/opportunities',headers=auth())).json()['total']==0
    assert (await client.get('/api/v1/entities/deals/101',headers=auth())).status_code==404


@pytest.mark.asyncio
async def test_owner_financial_read_is_unchanged_and_business_invite_does_not_leak_old_audit(invitation_api):
    client,db=invitation_api
    owner=auth('super_admin',1)
    response=await client.get('/api/v1/entities/deals/101',headers=owner)
    assert response.status_code==200 and response.json()['deal_amount']==91234.56
    assert response.json()['is_paid'] is True and response.json()['source_payment_id']==9101
    response=await client.get('/api/v1/entities/subscriptions/101',headers=owner)
    assert response.status_code==200 and response.json()['package_price']==4321.99
    db.add_all([
        Operation_logs(user_id='20',customer_id=101,action_type='edit_payment',action_detail='PRIVATE_FINANCE_NOTE'),
        Operation_logs(user_id='20',customer_id=101,action_type='user_note',action_detail='ordinary note'),
    ])
    await db.commit()
    history=await client.get('/api/v1/entities/operation_logs',headers=auth())
    assert history.status_code==200 and history.json()['total']==1
    assert 'PRIVATE_FINANCE_NOTE' not in history.text
    assert history.json()['items'][0]['action_type']=='user_note'


@pytest.mark.asyncio
async def test_delivery_does_not_disclose_material_reference_titles_or_filter_them(invitation_api):
    client,db=invitation_api
    grant=await db.scalar(select(CustomerAccessGrant).where(CustomerAccessGrant.employee_id==20))
    grant.scopes={'delivery':'read_only'}
    task=await db.get(Service_tasks,101)
    task.selected_material_id=101;task.selected_material_title='PRIVATE_LINKED_MATERIAL_TITLE'
    task.selected_copy_id=101;task.selected_copy_title='PRIVATE_LINKED_COPY_TITLE'
    await db.commit()
    for suffix in ('','/all','/101'):
        result=await client.get('/api/v1/entities/service_tasks'+suffix,headers=auth())
        assert result.status_code==200,result.text
        assert 'PRIVATE_LINKED_' not in result.text
        row=result.json() if suffix=='/101' else result.json()['items'][0]
        assert row['selected_material_id'] is None and row['selected_copy_id'] is None
    for params in ({'query':json.dumps({'selected_material_title':'PRIVATE_LINKED_MATERIAL_TITLE'})},{'sort':'-selected_copy_id'}):
        assert (await client.get('/api/v1/entities/service_tasks',params=params,headers=auth())).status_code==403
    grant.scopes={'delivery':'read_only','materials':'read_only'}
    material=await db.get(Customer_materials,101);material.visibility='owner'
    await db.commit()
    row=(await client.get('/api/v1/entities/service_tasks/101',headers=auth())).json()
    assert row['selected_material_id'] is None and row['selected_material_title'] is None
    assert row['selected_copy_id']==101
    owner=(await client.get('/api/v1/entities/service_tasks/101',headers=auth('super_admin',1))).json()
    assert owner['selected_material_title']=='PRIVATE_LINKED_MATERIAL_TITLE'


@pytest.mark.asyncio
async def test_automatic_tasks_follow_source_module_and_never_disclose_finance_through_delivery(invitation_api):
    from models.automation import DataQualityIssue
    client,db=invitation_api
    grant=await db.scalar(select(CustomerAccessGrant).where(CustomerAccessGrant.employee_id==20))
    grant.scopes={'delivery':'read_only'}
    for ident,code in ((301,'finance_receivable_open'),(302,'customer_follow_up_overdue'),(303,'delivery_task_overdue'),(304,'new_unknown_code'),(306,'subscription_missing_next_payment')):
        db.add(DataQualityIssue(id=ident,issue_key=f'invitation-{ident}',code=code,customer_id=101,customer_name='Customer',message='Sensitive source'))
        db.add(Tasks(id=ident,title=code,customer_id=101,source_type='system',automation_issue_id=ident,assignee_id=20,notes='PRIVATE_AMOUNT_99999' if ident==301 else 'Reminder'))
    db.add(Tasks(id=305,title='Personal task',customer_id=None,assignee_id=20,notes='Personal'))
    await db.commit()
    for suffix in ('','/all'):
        response=await client.get('/api/v1/entities/tasks'+suffix,headers=auth())
        assert response.status_code==200,response.text
        assert {r['id'] for r in response.json()['items']}=={101,303,305}
        assert 'PRIVATE_AMOUNT' not in response.text
    assert (await client.get('/api/v1/entities/tasks/301',headers=auth())).status_code==404
    grant.scopes={'followups':'read_only'};await db.commit()
    assert {r['id'] for r in (await client.get('/api/v1/entities/tasks',headers=auth())).json()['items']}=={302,305}
    assert (await client.get('/api/v1/entities/tasks/301',headers=auth('super_admin',1))).json()['notes']=='PRIVATE_AMOUNT_99999'
    grant.access_level='read_write';grant.scopes={'renewals':'read_write'};await db.commit()
    assert {r['id'] for r in (await client.get('/api/v1/entities/tasks',headers=auth())).json()['items']}=={305,306}
    assert (await client.put('/api/v1/entities/tasks/306',json={'notes':'cannot change renewal'},headers=auth())).status_code==403
    assert (await db.get(Tasks,306)).notes=='Reminder'


@pytest.mark.asyncio
async def test_followup_link_cannot_write_an_uninvited_opportunity_or_other_customer(invitation_api):
    client,db=invitation_api
    grant=await db.scalar(select(CustomerAccessGrant).where(CustomerAccessGrant.employee_id==20))
    grant.access_level='read_write';grant.scopes={'followups':'read_write'}
    await db.commit()
    payload={'customer_id':101,'opportunity_id':101,'content':'linked followup'}
    assert (await client.post('/api/v1/entities/follow_ups',json=payload,headers=auth())).status_code==403
    assert (await client.post('/api/v1/entities/follow_ups/batch',json={'items':[payload]},headers=auth())).status_code==403
    grant.scopes={'followups':'read_write','opportunities':'read_write'};await db.commit()
    response=await client.post('/api/v1/entities/follow_ups',json={**payload,'opportunity_id':102},headers=auth())
    assert response.status_code==404,response.text
    response=await client.post('/api/v1/entities/follow_ups',json=payload,headers=auth())
    assert response.status_code==201,response.text
    assert response.json()['opportunity_id']==101
    update=await client.put('/api/v1/entities/follow_ups/101',json={'opportunity_id':102},headers=auth())
    assert update.status_code==404,update.text
    assert (await db.get(Follow_ups,101)).opportunity_id is None
