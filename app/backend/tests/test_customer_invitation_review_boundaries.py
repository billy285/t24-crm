"""Review regressions: readonly notes and legacy platform metadata isolation."""
import json

import pytest
from sqlalchemy import func, select, text

from models.customer_access_grants import CustomerAccessGrant
from models.deals import Deals
from models.operation_logs import Operation_logs
from models.subscriptions import Subscriptions
from services.customer_permissions import shared_platform_names
from test_customer_invitation_business_boundaries import auth, invitation_api


@pytest.mark.parametrize('raw,expected', [
    ('google_business,facebook', 'google_business,facebook'),
    ('Google Ads，Facebook', 'Google Ads,Facebook'),
    ('["google_business", "Facebook"]', '["google_business", "Facebook"]'),
    ('Google,PRIVATE_FINANCE_NOTE,Facebook', 'Google,Facebook'),
    ('["Google", "PRIVATE_FINANCE_NOTE", "Instagram"]', '["Google", "Instagram"]'),
    ('{"platforms":["Google"],"price":91234,"notes":"SECRET"}', None),
    ('["Google", {"price":91234}]', None),
    ('"PRIVATE_FINANCE_NOTE"', None),
    ('PRIVATE_FINANCE_NOTE', None),
    ('Google: paid 91234', None),
    ('["Google",12345]', None),
    ('[malformed', None),
])
def test_shared_platform_whitelist_accepts_only_business_labels(raw, expected):
    assert shared_platform_names(raw) == expected


@pytest.mark.asyncio
async def test_default_readonly_cannot_append_customer_note_but_unlinked_note_remains(invitation_api):
    client, db = invitation_api
    payload = {'customer_id':101,'action_type':'user_note','action_detail':'READONLY_WRITE_PROBE'}
    response = await client.post('/api/v1/entities/operation_logs', headers=auth(), json=payload)
    assert response.status_code == 403, response.text
    assert not await db.scalar(select(Operation_logs.id).where(Operation_logs.action_detail=='READONLY_WRITE_PROBE'))
    response = await client.post('/api/v1/entities/operation_logs', headers=auth(), json={**payload,'customer_id':None})
    assert response.status_code == 201, response.text
    assert response.json()['customer_id'] is None
    grant = await db.scalar(select(CustomerAccessGrant).where(CustomerAccessGrant.employee_id==20))
    grant.access_level='read_write'; grant.scopes={'basic':'read_write'}
    await db.commit()
    response = await client.post('/api/v1/entities/operation_logs', headers=auth(), json={**payload,'action_detail':'AUTHORIZED_NOTE'})
    assert response.status_code == 201, response.text


@pytest.mark.asyncio
async def test_customer_note_write_respects_effective_role_limit(invitation_api):
    client, db = invitation_api
    grant = await db.scalar(select(CustomerAccessGrant).where(CustomerAccessGrant.employee_id==20))
    grant.access_level='read_write'; grant.scopes={'basic':'read_write'}
    config=json.loads(await db.scalar(text("SELECT value_json FROM app_settings WHERE config_key='role_permissions'")))
    config['ops']['buttons']=[]
    await db.execute(text("UPDATE app_settings SET value_json=:v WHERE config_key='role_permissions'"), {'v':json.dumps(config)})
    await db.commit()
    response=await client.post('/api/v1/entities/operation_logs',headers=auth(),json={'customer_id':101,'action_type':'user_note','action_detail':'ROLE_LIMIT_WRITE_PROBE'})
    assert response.status_code==403,response.text
    assert not await db.scalar(select(Operation_logs.id).where(Operation_logs.action_detail=='ROLE_LIMIT_WRITE_PROBE'))


@pytest.mark.asyncio
async def test_readonly_admin_batch_note_fails_before_any_insert(invitation_api):
    client, db = invitation_api
    db.add(CustomerAccessGrant(customer_id=101,employee_id=2,access_level='read_only',scopes={'basic':'read_only'},invitation_status='active',invitation_source='owner_invitation'))
    await db.commit()
    before=await db.scalar(select(func.count(Operation_logs.id)))
    response=await client.post('/api/v1/entities/operation_logs/batch',headers=auth('admin',2),json={'items':[
        {'action_type':'user_note','action_detail':'UNLINKED_BATCH_PROBE'},
        {'customer_id':101,'action_type':'user_note','action_detail':'READONLY_BATCH_PROBE'},
    ]})
    assert response.status_code==403,response.text
    assert await db.scalar(select(func.count(Operation_logs.id)))==before


@pytest.mark.asyncio
@pytest.mark.parametrize('entity,model,field,module', [
    ('deals',Deals,'package_platforms','deals'),
    ('subscriptions',Subscriptions,'selected_platforms','renewals'),
    ('subscriptions',Subscriptions,'selected_platforms','delivery'),
])
async def test_shared_platform_metadata_and_query_oracles_are_blocked(invitation_api,entity,model,field,module):
    client,db=invitation_api
    grant=await db.scalar(select(CustomerAccessGrant).where(CustomerAccessGrant.employee_id==20))
    grant.scopes={'basic':'read_only',module:'read_only'}
    row=await db.get(model,101)
    private='{"platforms":["Google"],"price":91234,"notes":"NESTED_FINANCE_PROBE"}'
    setattr(row,field,private)
    await db.commit()
    module_params={'access_module':module} if entity=='subscriptions' else {}
    for suffix in ('','/all','/101'):
        result=await client.get(f'/api/v1/entities/{entity}'+suffix,headers=auth(),params=module_params)
        assert result.status_code==200,result.text
        assert 'NESTED_FINANCE_PROBE' not in result.text and '91234' not in result.text
        item=result.json() if suffix=='/101' else result.json()['items'][0]
        assert field not in item
    for params in ({'query':json.dumps({field:private})},{'sort':field}):
        response=await client.get(f'/api/v1/entities/{entity}',headers=auth(),params={**module_params,**params})
        assert response.status_code==403,response.text
    owner=await client.get(f'/api/v1/entities/{entity}/101',headers=auth('super_admin',1),params=module_params)
    assert owner.status_code==200 and owner.json()[field]==private
    setattr(row,field,'["Google", "PRIVATE_FINANCE_NOTE", "Facebook"]')
    await db.commit()
    safe=await client.get(f'/api/v1/entities/{entity}/101',headers=auth(),params=module_params)
    assert safe.status_code==200 and json.loads(safe.json()[field])==['Google','Facebook']
    assert (await client.get(f'/api/v1/entities/{entity}/102',headers=auth(),params=module_params)).status_code==404
