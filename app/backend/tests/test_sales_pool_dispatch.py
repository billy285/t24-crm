import asyncio
import json
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.main import app  # Registers the actual router and existing schema.
from core.database import Base
from models.employees import Employees
from models.merchant_pool import MerchantPool
from models.operation_logs import Operation_logs
from models.sales_daily_quotas import SalesDailyQuotas
from models.sales_daily_dial_tasks import SalesDailyDialTasks
from models.sales_leads import SalesLeads
from models.sales_lead_assignment_logs import SalesLeadAssignmentLogs
from routers import merchant_pool
from routers.sales_pool_dispatch import DispatchRequest
from schemas.auth import UserResponse
from services import sales_dossiers  # Registers retained history tables used by ID allocation.
from services.sales_pool_dispatch import build_dispatch_plan, apply_dispatch_plan, real_fields

NOW = datetime(2026,11,10,17,tzinfo=timezone.utc)
TODAY = datetime(2026,11,11).date()


def user(role='admin',id='1',name='Admin'):
    return UserResponse(id=id,role=role,name=name,email='synthetic@dispatch.test')


def merchant(id,**changes):
    data=dict(id=id,business_name=f'Salon {id}',phone=f'+1212555{1000+id:04d}',country='US',state='NY',city='New York',
              address=f'{id} Main Street',pool_status='pending',created_by_id=10,data_source='synthetic')
    data.update(changes);return MerchantPool(**data)


@pytest_asyncio.fixture
async def db(tmp_path):
    engine=create_async_engine('sqlite+aiosqlite:///'+str(tmp_path/'dispatch.sqlite'))
    async with engine.begin() as conn:await conn.run_sync(Base.metadata.create_all)
    sessions=async_sessionmaker(engine,expire_on_commit=False)
    async with sessions() as session:
        session.info['sessions']=sessions
        session.add_all([Employees(id=1,user_id='1',name='Admin',role='admin',status='active'),
            Employees(id=10,user_id='10',name='Manager',role='sales_manager',status='active'),
            Employees(id=21,user_id='21',name='A',role='sales',status='active',supervisor='Manager'),
            Employees(id=22,user_id='22',name='B',role='sales',status='probation',supervisor='Manager'),
            Employees(id=23,user_id='23',name='PRIVATE_OTHER_TEAM',role='sales',status='active',supervisor='Other')])
        await session.commit();yield session
    await engine.dispose()


async def count(db,model):return await db.scalar(select(func.count()).select_from(model))


def quality_hold(id,status='closed'):
    return Operation_logs(user_id='1',action_type=f'prospect_quality:pool:{id}',
        action_detail=json.dumps({'entity_kind':'pool','entity_id':id,'after':{'status':status,'revision':1}}))


@pytest.mark.asyncio
async def test_preview_is_read_only_and_remaining_capacity_reserves_existing_work(db):
    db.add_all([merchant(i) for i in range(1,6)])
    db.add_all([SalesDailyQuotas(sales_employee_id=21,target_date=TODAY,target_count=2),SalesDailyQuotas(sales_employee_id=22,target_date=TODAY,target_count=3)])
    db.add_all([SalesLeads(id=100,business_name='Existing A',phone='+12125559001',assigned_sales_id=21,status='new'),
                SalesLeads(id=101,business_name='Existing B',phone='+12125559002',assigned_sales_id=22,status='new')])
    db.add(SalesDailyDialTasks(sales_employee_id=21,task_date=TODAY,lead_id=100,status='pending'))
    await db.commit()
    plan=await build_dispatch_plan(db,user(),[1,2,3,4,5],[21,22],now=NOW)
    assert plan['assigned_count']==3 and plan['unassigned_count']==2
    by={item['sales_employee_id']:item for item in plan['employees']}
    assert by[21]['assigned_count']==1 and by[21]['today_tasks']==1
    assert by[22]['assigned_count']==2 and by[22]['reserved_existing']==1
    assert await count(db,SalesLeads)==2 and await count(db,SalesDailyDialTasks)==1
    result=await apply_dispatch_plan(db,user(),[1,2,3,4,5],[21,22],plan['plan_sha256'],now=NOW)
    assert result['assigned_count']==3 and await count(db,SalesLeads)==5 and await count(db,SalesDailyDialTasks)==4
    again=await build_dispatch_plan(db,user(),[item['merchant_id'] for item in plan['unassigned']],[21,22],now=NOW)
    assert again['assigned_count']==0


@pytest.mark.asyncio
async def test_current_contact_window_precedes_fuller_but_after_hours_record(db):
    db.add_all([merchant(1,state='CA',city='Los Angeles',website='https://salon.example',contact_name='Owner'),
        merchant(2,business_name='店名待核验｜甲店招聘',address='街道地址待核验（中文招聘来源）')])
    db.add(SalesDailyQuotas(sales_employee_id=21,target_date=TODAY,target_count=1));await db.commit()
    plan=await build_dispatch_plan(db,user(),[1,2],[21],now=NOW)
    assert [row['merchant_id'] for row in plan['assignments']]==[2]
    assert plan['assignments'][0]['quality_status']=='pending'
    assert plan['assignments'][0]['completeness']==1


@pytest.mark.asyncio
@pytest.mark.parametrize('actor,ids,sales,code',[(user('sales','21','A'),[1],[21],403),
    (user('sales_manager','10','Manager'),[2],[21],404),(user('sales_manager','10','Manager'),[1],[23],403)])
async def test_scope_and_employee_permissions_are_checked_without_partial_assignment(db,actor,ids,sales,code):
    db.add_all([merchant(1),merchant(2,created_by_id=99)]);await db.commit()
    with pytest.raises(HTTPException) as exc:await build_dispatch_plan(db,actor,ids,sales,now=NOW)
    assert exc.value.status_code==code and await count(db,SalesLeads)==0


@pytest.mark.asyncio
@pytest.mark.parametrize('drift',['merchant','quota','quality','active_sales','task'])
async def test_any_relevant_drift_rejects_entire_confirmation(db,drift):
    db.add_all([merchant(1),merchant(2)]);await db.commit()
    plan=await build_dispatch_plan(db,user(),[1,2],[21],now=NOW)
    if drift=='merchant':(await db.get(MerchantPool,2)).city='Boston'
    elif drift=='quota':db.add(SalesDailyQuotas(sales_employee_id=21,target_date=TODAY,target_count=1))
    elif drift=='quality':db.add(quality_hold(2))
    elif drift=='active_sales':(await db.get(Employees,21)).status='inactive'
    else:db.add(SalesDailyDialTasks(sales_employee_id=21,task_date=TODAY,lead_id=999,status='pending'))
    await db.commit()
    with pytest.raises(HTTPException) as exc:await apply_dispatch_plan(db,user(),[1,2],[21],plan['plan_sha256'],now=NOW)
    assert exc.value.status_code==409 and await count(db,SalesLeads)==0
    assert (await db.get(MerchantPool,1)).pool_status=='pending'


@pytest.mark.asyncio
async def test_failure_after_first_factory_flush_rolls_back_leads_pool_tasks_and_audit(db,monkeypatch):
    db.add_all([merchant(1),merchant(2)]);await db.commit();plan=await build_dispatch_plan(db,user(),[1,2],[21],now=NOW)
    original=merchant_pool._create_sales_lead_from_merchant;calls=[]
    async def fail_second(*args,**kwargs):
        calls.append(True)
        if len(calls)==2:raise HTTPException(500,'synthetic second-row failure')
        return await original(*args,**kwargs)
    monkeypatch.setattr(merchant_pool,'_create_sales_lead_from_merchant',fail_second)
    with pytest.raises(HTTPException):await apply_dispatch_plan(db,user(),[1,2],[21],plan['plan_sha256'],now=NOW)
    assert await count(db,SalesLeads)==await count(db,SalesDailyDialTasks)==await count(db,SalesLeadAssignmentLogs)==0
    assert set((await db.scalars(select(MerchantPool.pool_status))).all())=={'pending'}


@pytest.mark.asyncio
async def test_quality_holds_excluded_and_same_contact_not_assigned_twice(db):
    db.add_all([merchant(1),merchant(2,phone='+1 (212) 555-1001'),merchant(3),quality_hold(3,'invalid_phone')]);await db.commit()
    plan=await build_dispatch_plan(db,user(),[1,2,3],[21],now=NOW)
    assert plan['assigned_count']==1 and plan['unassigned_count']==2
    await apply_dispatch_plan(db,user(),[1,2,3],[21],plan['plan_sha256'],now=NOW)
    assert await count(db,SalesLeads)==1
    with pytest.raises(HTTPException) as exc:await apply_dispatch_plan(db,user(),[1,2,3],[21],plan['plan_sha256'],now=NOW)
    assert exc.value.status_code==409 and await count(db,SalesLeads)==1


@pytest.mark.asyncio
async def test_concurrent_confirmation_cannot_duplicate_pool_assignment(db):
    db.add(merchant(1));await db.commit();plan=await build_dispatch_plan(db,user(),[1],[21],now=NOW);await db.rollback()
    sessions=db.info['sessions']
    async def attempt():
        async with sessions() as session:
            try:return await apply_dispatch_plan(session,user(),[1],[21],plan['plan_sha256'],now=NOW)
            except HTTPException as exc:return exc.status_code
    results=await asyncio.gather(attempt(),attempt())
    assert sum(isinstance(item,dict) for item in results)==1 and 409 in results
    assert await count(db,SalesLeads)==await count(db,SalesDailyDialTasks)==1


def test_request_bounds_and_plan_cannot_accept_client_assignment_override():
    for body in [dict(merchant_ids=list(range(1,202)),sales_ids=[21]),dict(merchant_ids=[1,1],sales_ids=[21]),
                 dict(merchant_ids=[1],sales_ids=[21],assignments=[{'merchant_id':1,'sales_employee_id':23}])]:
        with pytest.raises(ValidationError):DispatchRequest(**body)
    assert real_fields(merchant(1,business_name='店名待核验',address='街道待核验',city='未知',contact_name='待确认',website='unknown'))==0
