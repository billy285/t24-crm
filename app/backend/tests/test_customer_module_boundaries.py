"""Synthetic HTTP attacks against module sharing; no live customer or file data."""
import json
from types import SimpleNamespace
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from backend.main import app
from core.database import Base, get_db
from models.customer_access_grants import CustomerAccessGrant
from models.customer_ai_copies import Customer_ai_copies
from models.customer_materials import Customer_materials
from models.customer_menu_items import Customer_menu_items
from models.customer_record_audits import CustomerRecordAudit
from models.customer_contacts import Customer_contacts
from models.customers import Customers
from models.employees import Employees
from models.follow_ups import Follow_ups
from models.media_accounts import Media_accounts
from models.service_tasks import Service_tasks
from models.service_progresses import Service_progresses
from services.emp_auth import create_access_token
from routers.customer_ai_copies import _load_operational_context


def headers(role='ops', employee_id=21):
    token=create_access_token({'emp_id':employee_id,'email':f'modules-{employee_id}@example.test','role':role,'name':f'User {employee_id}'})
    return {'Authorization':f'Bearer {token}'}


def q(cid):
    return {'query':json.dumps({'customer_id':cid})}


@pytest_asyncio.fixture
async def module_api(tmp_path, monkeypatch):
    monkeypatch.setenv('ENFORCE_EMPLOYEE_SESSIONS','false')
    engine=create_async_engine('sqlite+aiosqlite:///:memory:',poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions=async_sessionmaker(engine,expire_on_commit=False)
    root=tmp_path/'materials'
    for cid in (101,102):
        (root/str(cid)).mkdir(parents=True)
        (root/str(cid)/'file.txt').write_text(f'synthetic file {cid}')
    from routers import customer_materials as rm
    from backend.routers import customer_materials as bm
    monkeypatch.setattr(rm,'MATERIALS_ROOT',root)
    monkeypatch.setattr(bm,'MATERIALS_ROOT',root)
    async with sessions() as db:
        for eid,role in [(1,'super_admin'),(21,'ops'),(22,'sales_manager'),(23,'admin'),(24,'design'),(25,'finance')]:
            db.add(Employees(id=eid,user_id=str(eid),name=f'User {eid}',role=role,status='active',email=f'modules-{eid}@example.test',department='East'))
        for cid in (101,102,103,104,105):
            db.add_all([
                Customers(id=cid,business_name=f'Customer {cid}',contact_name='Owner',phone='555',sales_employee_id=22 if cid==103 else None),
                Follow_ups(id=cid,customer_id=cid,employee_id=1,content=f'follow {cid}'),
                Customer_contacts(id=cid,customer_id=cid,contact_name=f'contact {cid}'),
                Service_tasks(id=cid,customer_id=cid,task_name=f'task {cid}',task_type='setup_group',status='pending',user_id='1'),
                Service_progresses(id=cid,customer_id=cid,service_stage='deal_handover',user_id='1'),
                Customer_materials(id=cid,customer_id=cid,user_id='1',title=f'material {cid}',material_type='document',visibility='team',file_path=f'{cid}/file.txt'),
                Customer_menu_items(id=cid,customer_id=cid,user_id='1',name=f'item {cid}',item_type='service'),
                Customer_ai_copies(id=cid,customer_id=cid,user_id='1',title=f'copy {cid}',content=f'content {cid}',platform='facebook',content_type='weekly_update'),
                Media_accounts(id=cid,customer_id=cid,user_id='1',platform_name='facebook',account_name='synthetic',login_password='synthetic-secret'),
            ])
        db.add_all([
            CustomerAccessGrant(customer_id=101,employee_id=21,access_level='read_write',scopes={m:'read_write' for m in ('basic','followups','delivery','materials')}),
            CustomerAccessGrant(customer_id=104,employee_id=21,access_level='read_write',scopes={m:'read_only' for m in ('basic','followups','delivery','materials')}),
            CustomerAccessGrant(customer_id=105,employee_id=21,access_level='read_write',scopes={'basic':'read_only','followups':'none','delivery':'none','materials':'read_write'}),
            CustomerAccessGrant(customer_id=103,employee_id=22,access_level='none'),
            CustomerAccessGrant(customer_id=101,employee_id=23,access_level='none'),
            CustomerAccessGrant(customer_id=101,employee_id=24,access_level='read_only',scopes={'basic':'none','followups':'none','delivery':'none','materials':'read_only'}),
            CustomerAccessGrant(customer_id=101,employee_id=25,access_level='read_only',scopes={'materials':'read_only'},finance_access='status'),
            Customer_materials(id=901,customer_id=101,user_id='1',title='owner-only',material_type='document',visibility='owner',file_path='101/file.txt'),
            Customer_materials(id=902,customer_id=101,user_id='1',title='financial receipt',material_type='document',visibility='finance',file_path='101/file.txt'),
            Customer_materials(id=903,customer_id=101,user_id='1',title='forged cross customer path',material_type='document',visibility='team',file_path='102/file.txt'),
        ])
        await db.execute(text('CREATE TABLE IF NOT EXISTS app_settings (config_key TEXT PRIMARY KEY,value_json TEXT NOT NULL,updated_at TIMESTAMP)'))
        buttons=['customer_edit','customer_delete','follow_up_create','follow_up_edit','follow_up_delete','task_create','task_edit','task_delete','media_account_create','media_account_edit','media_account_delete']
        config={role:{'pages':['/customers','/service-board'],'buttons':buttons,'sensitiveFields':{'viewPassword':True}} for role in ('super_admin','ops','sales_manager','admin','finance')}
        config['design']={'pages':['/tasks'],'buttons':[],'sensitiveFields':{'viewPassword':False}}
        await db.execute(text("INSERT INTO app_settings(config_key,value_json) VALUES('role_permissions',:v)"),{'v':json.dumps(config)})
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
@pytest.mark.parametrize('entity',['follow_ups','customer_contacts','service_tasks','service_progresses','media_accounts'])
async def test_module_lists_and_guessed_ids_fail_closed(module_api,entity):
    client,_=module_api
    assert (await client.get(f'/api/v1/entities/{entity}/101',headers=headers())).status_code==200
    assert (await client.get(f'/api/v1/entities/{entity}/102',headers=headers())).status_code==404
    assert (await client.get(f'/api/v1/entities/{entity}/103',headers=headers('sales_manager',22))).status_code in (403,404)
    result=await client.get(f'/api/v1/entities/{entity}',params=q(102),headers=headers())
    assert result.status_code==200 and result.json()['total']==0


@pytest.mark.asyncio
@pytest.mark.parametrize('entity,payload',[
    ('follow_ups',{'content':'mutated'}),('customer_contacts',{'contact_name':'mutated'}),
    ('service_tasks',{'task_name':'mutated'}),('service_progresses',{'notes':'mutated'}),
    ('media_accounts',{'account_name':'mutated'}),('customer_materials',{'title':'mutated'}),
    ('customer_ai_copies',{'title':'mutated'}),('customer_menu_items',{'name':'mutated'}),
])
async def test_read_only_module_cannot_write_or_delete(module_api,entity,payload):
    client,_=module_api
    result=await client.put(f'/api/v1/entities/{entity}/104',json=payload,headers=headers())
    assert result.status_code==403,result.text
    result=await client.delete(f'/api/v1/entities/{entity}/101',headers=headers())
    assert result.status_code==403,result.text


@pytest.mark.asyncio
@pytest.mark.parametrize('entity,field',[('follow_ups','content'),('customer_contacts','contact_name'),('service_tasks','task_name'),('service_progresses','notes'),('media_accounts','account_name')])
async def test_mixed_read_only_batch_does_not_commit_first_write(module_api,entity,field):
    client,_=module_api
    result=await client.put(f'/api/v1/entities/{entity}/batch',json={'items':[{'id':101,'updates':{field:'changed-first'}},{'id':104,'updates':{field:'changed-second'}}]},headers=headers())
    assert result.status_code==403,result.text
    result=await client.get(f'/api/v1/entities/{entity}/101',headers=headers())
    assert result.json().get(field)!='changed-first'


@pytest.mark.asyncio
async def test_material_classification_download_and_path_forgery(module_api):
    client,_=module_api
    result=await client.get('/api/v1/entities/customer_materials',params=q(101),headers=headers())
    assert {row['id'] for row in result.json()['items']}=={101,903}
    for mid in (901,902,903):
        assert (await client.get(f'/api/v1/entities/customer_materials/{mid}/download',headers=headers())).status_code==404
    assert (await client.get('/api/v1/entities/customer_materials/101/download',headers=headers())).status_code==200
    result=await client.post('/api/v1/entities/customer_materials',json={'customer_id':101,'title':'forged','file_path':'102/file.txt'},headers=headers())
    assert result.status_code==400
    assert (await client.put('/api/v1/entities/customer_materials/101',json={'visibility':'owner'},headers=headers())).status_code==403


@pytest.mark.asyncio
async def test_finance_status_does_not_grant_receipt_files(module_api):
    client,db=module_api
    result=await client.get('/api/v1/entities/customer_materials',params=q(101),headers=headers('finance',25))
    assert 902 not in {row['id'] for row in result.json()['items']}
    grant=await db.scalar(select(CustomerAccessGrant).where(CustomerAccessGrant.employee_id==25))
    grant.finance_access='receipts'
    await db.commit()
    result=await client.get('/api/v1/entities/customer_materials',params=q(101),headers=headers('finance',25))
    ids={row['id'] for row in result.json()['items']}
    assert 902 in ids and 901 not in ids


@pytest.mark.asyncio
async def test_design_material_grant_is_readable_but_credentials_are_not_shared(module_api):
    client,_=module_api
    for entity in ('customer_materials','customer_menu_items','customer_ai_copies'):
        result=await client.get(f'/api/v1/entities/{entity}',params=q(101),headers=headers('design',24))
        assert result.status_code==200,result.text
    assert (await client.get('/api/v1/entities/media_accounts/101/password',headers=headers())).status_code==403
    assert (await client.get('/api/v1/entities/media_accounts/all',headers=headers('admin',23))).json()['total']==0


@pytest.mark.asyncio
async def test_ai_and_task_completion_respect_other_modules_and_private_material(module_api):
    client,db=module_api
    user=SimpleNamespace(id='21',role='ops',name='User 21')
    context=await _load_operational_context(db,105,scope_user=user)
    assert context['materials'] and context['service_tasks']==[] and context['service_progresses']==[]
    context=await _load_operational_context(db,101,scope_user=user)
    assert all(row['title'] not in {'owner-only','financial receipt'} for row in context['materials'])
    result=await client.post('/api/v1/entities/service_tasks/101/complete',json={'selected_material_id':901},headers=headers())
    assert result.status_code==400
    assert (await db.get(Service_tasks,101)).status=='pending'


@pytest.mark.asyncio
async def test_business_history_private_and_password_redacted(module_api):
    client,db=module_api
    result=await client.put('/api/v1/entities/follow_ups/101',json={'content':'new by invitee'},headers=headers())
    assert result.status_code==200,result.text
    audit=await db.scalar(select(CustomerRecordAudit).where(CustomerRecordAudit.entity_type=='follow_ups'))
    assert audit.actor_id=='21' and audit.before['content']=='follow 101' and audit.after['content']=='new by invitee'
    result=await client.put('/api/v1/entities/media_accounts/101',json={'login_password':'new-secret'},headers=headers('super_admin',1))
    assert result.status_code==200,result.text
    audit=await db.scalar(select(CustomerRecordAudit).where(CustomerRecordAudit.entity_type=='media_accounts'))
    assert audit.before['login_password']=='[redacted]' and audit.after['login_password']=='[redacted]'
    assert (await client.get('/api/v1/entities/customer_record_audits',headers=headers())).status_code in (403,404)


@pytest.mark.asyncio
async def test_revocation_removes_own_logs_and_admin_cannot_read_company_audit(module_api):
    from models.operation_logs import Operation_logs
    client,db=module_api
    db.add_all([
        Operation_logs(id=710,user_id='21',customer_id=101,action_type='user_note',action_detail='own note'),
        Operation_logs(id=711,user_id='21',customer_id=None,action_type='other',action_detail='company financial secret'),
        Operation_logs(id=712,user_id='21',customer_id=101,action_type='edit_material',action_detail='private attachment original title'),
    ])
    await db.commit()
    listed=await client.get('/api/v1/entities/operation_logs',headers=headers())
    assert {r['id'] for r in listed.json()['items']}=={710,712}
    assert 'private attachment original title' not in listed.text
    assert (await client.get('/api/v1/entities/operation_logs/711',headers=headers())).status_code==404
    assert (await client.get('/api/v1/entities/operation_logs/all',headers=headers('admin',23))).status_code==403
    grant=await db.scalar(select(CustomerAccessGrant).where(CustomerAccessGrant.employee_id==21,CustomerAccessGrant.customer_id==101))
    grant.access_level='none'
    await db.commit()
    assert (await client.get('/api/v1/entities/operation_logs/710',headers=headers())).status_code==404
    assert (await client.get('/api/v1/entities/operation_logs',headers=headers())).json()['total']==0


@pytest.mark.asyncio
async def test_explicit_delete_grant_allows_delete_and_retains_owner_audit(module_api):
    client,db=module_api
    grant=await db.scalar(select(CustomerAccessGrant).where(CustomerAccessGrant.employee_id==21,CustomerAccessGrant.customer_id==101))
    grant.can_delete=True
    await db.commit()
    result=await client.delete('/api/v1/entities/follow_ups/101',headers=headers())
    assert result.status_code==200,result.text
    history=await db.scalar(select(CustomerRecordAudit).where(CustomerRecordAudit.entity_type=='follow_ups'))
    assert history.action=='delete' and history.before['content']=='follow 101' and history.after=={}


@pytest.mark.asyncio
async def test_shared_ai_never_imports_private_materials_or_hidden_customer_notes(module_api):
    from services.customer_ai_context import customer_for_content
    from routers.customer_ai_copies import _build_prompt, CustomerAiGenerateRequest
    client,db=module_api
    owner=SimpleNamespace(id='1',role='super_admin',name='Owner')
    context=await _load_operational_context(db,101,scope_user=owner)
    assert {row['title'] for row in context['materials']}.isdisjoint({'owner-only','financial receipt'})
    customer=await db.get(Customers,101)
    customer.notes='hidden basic module note'
    copy=await db.get(Customer_ai_copies,101)
    copy.prompt='historic broader private source context'
    await db.commit()
    material_user=SimpleNamespace(id='24',role='design',name='User 24')
    safe=await customer_for_content(db,customer,material_user)
    prompt=_build_prompt(safe,CustomerAiGenerateRequest(customer_id=101),context)
    assert 'hidden basic module note' not in prompt
    listed=await client.get('/api/v1/entities/customer_ai_copies',params=q(101),headers=headers('design',24))
    assert listed.status_code==200,listed.text
    assert 'historic broader private source context' not in listed.text
    assert listed.json()['items'][0]['content']=='content 101'
    own=await client.get('/api/v1/entities/customer_ai_copies',params=q(101),headers=headers('super_admin',1))
    assert 'historic broader private source context' in own.text


@pytest.mark.asyncio
async def test_null_material_visibility_cannot_erase_classification(module_api):
    client,db=module_api
    response=await client.put('/api/v1/entities/customer_materials/901',json={'visibility':None,'title':'private renamed'},headers=headers('super_admin',1))
    assert response.status_code==200,response.text
    assert response.json()['visibility']=='owner'
    assert (await client.get('/api/v1/entities/customer_materials/901',headers=headers())).status_code==404


@pytest_asyncio.fixture
async def business_entry_api(module_api):
    from datetime import datetime, timedelta, timezone
    from models.tasks import Tasks
    from models.opportunities import Opportunities
    from models.management_decisions import BusinessLine
    client,db=module_api
    settings=(await db.execute(text("SELECT value_json FROM app_settings WHERE config_key='role_permissions'"))).scalar_one()
    config=json.loads(settings)
    for role in config.values():
        role['pages'].append('/tasks')
    await db.execute(text("UPDATE app_settings SET value_json=:v WHERE config_key='role_permissions'"),{'v':json.dumps(config)})
    db.add(BusinessLine(id=91,code='synthetic',name='Synthetic service',is_active=True))
    for cid in (101,102,104,105):
        db.add(Tasks(id=cid+500,customer_id=cid,title=f'customer task {cid}',assignee_id=21,assignee_name='User 21',status='pending'))
        db.add(Opportunities(id=cid+600,customer_id=cid,customer_name=f'Customer {cid}',business_line_id=91,opportunity_code=f'TEST-{cid}',title=f'opportunity {cid}',estimated_amount=1234.56,probability=50,status='open',stage='initial',owner_employee_id=21,owner_name='User 21',next_follow_up_at=datetime.now(timezone.utc)+timedelta(days=1)))
    db.add(Tasks(id=600,title='personal task',assignee_id=21,assignee_name='User 21',status='pending'))
    db.add(Tasks(id=611,customer_id=101,title='linked opportunity task',opportunity_id=701,assignee_id=21,assignee_name='User 21',status='pending'))
    await db.commit()
    return client,db


@pytest.mark.asyncio
async def test_generic_tasks_intersect_customer_modules_even_if_assigned(business_entry_api):
    client,db=business_entry_api
    for suffix in ('','/all'):
        response=await client.get('/api/v1/entities/tasks'+suffix,headers=headers())
        assert response.status_code==200,response.text
        assert {r['id'] for r in response.json()['items']}=={600,601,604,611}
    assert (await client.get('/api/v1/entities/tasks/602',headers=headers())).status_code==404
    assert (await client.get('/api/v1/entities/tasks/605',headers=headers())).status_code==404
    assert (await client.get('/api/v1/entities/tasks/601',headers=headers('admin',23))).status_code==404
    allowed=await client.put('/api/v1/entities/tasks/600',json={'title':'personal stays editable'},headers=headers())
    assert allowed.status_code==200,allowed.text
    assert (await client.put('/api/v1/entities/tasks/604',json={'title':'readonly attack'},headers=headers())).status_code==403
    assert (await client.put('/api/v1/entities/tasks/601',json={'customer_id':102},headers=headers())).status_code==403
    assert (await client.delete('/api/v1/entities/tasks/601',headers=headers())).status_code==403
    response=await client.put('/api/v1/entities/tasks/batch',json={'items':[{'id':601,'updates':{'title':'must not commit'}},{'id':604,'updates':{'title':'readonly attack'}}]},headers=headers())
    assert response.status_code==403,response.text
    from models.tasks import Tasks
    assert (await db.get(Tasks,601)).title=='customer task 101'


@pytest.mark.asyncio
async def test_task_create_and_linkage_cannot_bypass_customer_boundaries(business_entry_api):
    client,db=business_entry_api
    hidden=await client.post('/api/v1/entities/tasks',json={'title':'guess customer','customer_id':102},headers=headers())
    assert hidden.status_code==404,hidden.text
    forged=await client.post('/api/v1/entities/tasks',json={'title':'forge opportunity','opportunity_id':701},headers=headers())
    assert forged.status_code==403,forged.text
    batch=await client.post('/api/v1/entities/tasks/batch',json={'items':[{'title':'must not commit','customer_id':101},{'title':'readonly attack','customer_id':104}]},headers=headers())
    assert batch.status_code==403,batch.text
    from models.tasks import Tasks
    assert await db.scalar(select(Tasks.id).where(Tasks.title=='must not commit')) is None
    grant=await db.scalar(select(CustomerAccessGrant).where(CustomerAccessGrant.employee_id==21,CustomerAccessGrant.customer_id==101))
    grant.can_delete=True
    await db.commit()
    response=await client.delete('/api/v1/entities/tasks/601',headers=headers())
    assert response.status_code==200,response.text
    history=await db.scalar(select(CustomerRecordAudit).where(CustomerRecordAudit.entity_type=='tasks'))
    assert history.customer_id==101 and history.action=='delete'


@pytest.mark.asyncio
async def test_opportunities_scope_and_financial_mask_do_not_erase_hidden_amount(business_entry_api):
    from models.opportunities import Opportunities
    client,db=business_entry_api
    response=await client.get('/api/v1/opportunities',headers=headers())
    assert response.status_code==200,response.text
    assert {r['id'] for r in response.json()['items']}=={701,704}
    for row in response.json()['items']:
        assert row['estimated_amount'] is None and row['weighted_amount'] is None and row['financial_fields_hidden'] is True
    assert (await client.get('/api/v1/opportunities?customer_id=105',headers=headers())).status_code==403
    assert (await client.put('/api/v1/opportunities/704',json={'title':'readonly attack'},headers=headers())).status_code==403
    assert (await client.put('/api/v1/opportunities/701',json={'estimated_amount':999},headers=headers())).status_code==403
    assert (await client.put('/api/v1/opportunities/701',json={'currency':'CNY'},headers=headers())).status_code==403
    result=await client.put('/api/v1/opportunities/701',json={'title':'valid followup edit','estimated_amount':None,'currency':None},headers=headers())
    assert result.status_code==200,result.text
    assert (await db.get(Opportunities,701)).estimated_amount==1234.56
    grant=await db.scalar(select(CustomerAccessGrant).where(CustomerAccessGrant.employee_id==21,CustomerAccessGrant.customer_id==101))
    grant.finance_access='receipts'
    await db.commit()
    result=await client.get('/api/v1/opportunities?customer_id=101',headers=headers())
    assert result.json()['items'][0]['estimated_amount']==1234.56
    assert result.json()['items'][0]['weighted_amount']==617.28


@pytest.mark.asyncio
async def test_opportunity_nested_followup_and_convert_enforce_real_authority(business_entry_api):
    from datetime import datetime, timedelta, timezone
    client,db=business_entry_api
    body={'content':'should not save','next_follow_up_at':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()}
    for oid in (704,705):
        response=await client.post(f'/api/v1/opportunities/{oid}/follow-ups',json=body,headers=headers())
        assert response.status_code==403,response.text
    assert (await client.post('/api/v1/opportunities/701/convert',headers=headers())).status_code==403
    assert (await client.post('/api/v1/opportunities/701/convert',headers=headers('admin',23))).status_code==403
    created=await client.post('/api/v1/opportunities',json={'customer_id':104,'business_line_id':91,'title':'readonly create','next_follow_up_at':body['next_follow_up_at']},headers=headers())
    assert created.status_code==403,created.text
    assert await db.scalar(select(Follow_ups.id).where(Follow_ups.content=='should not save')) is None


@pytest.mark.asyncio
@pytest.mark.parametrize('role,employee_id',[('ops',21),('admin',23)])
async def test_shared_media_credentials_cannot_be_written_single_or_batch(module_api,role,employee_id):
    client,db=module_api
    if employee_id==23:
        grant=await db.scalar(select(CustomerAccessGrant).where(CustomerAccessGrant.employee_id==23,CustomerAccessGrant.customer_id==101))
        grant.access_level='read_write'
        grant.scopes={'materials':'read_write'}
        await db.commit()
    auth=headers(role,employee_id)
    original=(await db.get(Media_accounts,101)).login_password
    account={'customer_id':101,'platform_name':'Google','account_name':'credential attack','login_password':'must-not-write'}
    results=[
        await client.post('/api/v1/entities/media_accounts',json=account,headers=auth),
        await client.put('/api/v1/entities/media_accounts/101',json={'login_password':'must-not-write'},headers=auth),
        await client.post('/api/v1/entities/media_accounts/batch',json={'items':[{'customer_id':101,'platform_name':'Google','account_name':'must-not-partially-create'},account]},headers=auth),
        await client.put('/api/v1/entities/media_accounts/batch',json={'items':[{'id':101,'updates':{'notes':'must-not-partially-update'}},{'id':101,'updates':{'login_password':'must-not-write'}}]},headers=auth),
    ]
    assert [result.status_code for result in results]==[403,403,403,403]
    assert (await db.get(Media_accounts,101)).login_password==original
    assert (await db.get(Media_accounts,101)).notes!='must-not-partially-update'
    assert await db.scalar(select(Media_accounts.id).where(Media_accounts.account_name.in_(['credential attack','must-not-partially-create']))) is None
    for value in (None,'','   '):
        result=await client.put('/api/v1/entities/media_accounts/101',json={'notes':'metadata still editable','login_password':value},headers=auth)
        assert result.status_code==200,result.text
        result=await client.put('/api/v1/entities/media_accounts/batch',json={'items':[{'id':101,'updates':{'notes':'batch metadata','login_password':value}}]},headers=auth)
        assert result.status_code==200,result.text
        assert (await db.get(Media_accounts,101)).login_password==original
    assert (await client.get('/api/v1/entities/media_accounts/101/password',headers=auth)).status_code==403


@pytest.mark.asyncio
@pytest.mark.parametrize('role,employee_id',[('admin',23),('super_admin',1)])
@pytest.mark.parametrize('suffix',['','/all'])
async def test_media_password_filters_and_sort_never_form_an_oracle(module_api,role,employee_id,suffix):
    client,_=module_api
    auth=headers(role,employee_id)
    for params in ({'query':json.dumps({'login_password':'synthetic-secret'})},
                   {'query':json.dumps({'login_password':'wrong-secret'})},
                   {'query':json.dumps({'login_password':None})},
                   {'sort':'login_password'},{'sort':'-login_password'}):
        result=await client.get('/api/v1/entities/media_accounts'+suffix,params=params,headers=auth)
        assert result.status_code==400,result.text
        assert result.json()=={'detail':'账号密码不支持筛选或排序'}
        assert 'total' not in result.json()


@pytest.mark.asyncio
async def test_owner_can_manage_media_credentials_without_response_or_audit_leak(module_api):
    from core.mask_crypto import key_prefix
    from services.media_accounts import decrypt_media_account_password
    client,db=module_api
    owner=headers('super_admin',1)
    created=await client.post('/api/v1/entities/media_accounts',json={'customer_id':101,'platform_name':'Google','login_password':'owner-only-secret'},headers=owner)
    assert created.status_code==201,created.text
    assert created.json()['login_password'] is None and created.json()['has_password'] is True
    batch=await client.post('/api/v1/entities/media_accounts/batch',json={'items':[{'customer_id':101,'platform_name':'Meta','login_password':'owner-batch-secret'}]},headers=owner)
    assert batch.status_code==201,batch.text
    cid=created.json()['id']
    changed=await client.put('/api/v1/entities/media_accounts/batch',json={'items':[{'id':cid,'updates':{'login_password':'owner-new-secret'}}]},headers=owner)
    assert changed.status_code==200,changed.text
    stored=await db.get(Media_accounts,cid)
    assert stored.login_password.startswith(key_prefix)
    assert decrypt_media_account_password(stored.login_password)=='owner-new-secret'
    audit=await db.scalar(select(CustomerRecordAudit).where(CustomerRecordAudit.entity_type=='media_accounts',CustomerRecordAudit.entity_id==cid))
    assert audit.before['login_password']==audit.after['login_password']=='[redacted]'
