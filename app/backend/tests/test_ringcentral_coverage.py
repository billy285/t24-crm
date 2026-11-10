"""Window proof, failed pagination and ownership changes must never fake totals."""
from datetime import datetime, timedelta, timezone
import json

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.database import Base
from models.employees import Employees
from models.operation_logs import Operation_logs
from models.ringcentral_call_records import RingCentralCallRecords
from models.ringcentral_connections import RingCentralConnections
from routers import ringcentral as router
from schemas.auth import UserResponse
from services import ringcentral as provider
from services.ringcentral_coverage import binding_key, connection_coverage, record_window, summarize_windows

UTC = timezone.utc


@pytest_asyncio.fixture
async def sync_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=[
            Employees.__table__, Operation_logs.__table__, RingCentralConnections.__table__, RingCentralCallRecords.__table__]))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        db.add_all([Employees(id=11, user_id="11", name="Sales A", role="sales", status="active"),
                    Employees(id=12, user_id="12", name="OTHER_TEAM_PRIVATE", role="sales", status="active")])
        await db.commit()
        yield db
    await engine.dispose()


def connection(employee_id=11, **changes):
    values = dict(employee_id=employee_id, employee_name="Sales A", ringcentral_account_id="account",
                  ringcentral_extension_id=f"extension-{employee_id}", access_token_encrypted="PRIVATE_ACCESS",
                  refresh_token_encrypted="PRIVATE_REFRESH", is_active=True,
                  binding_started_at=datetime.now(UTC) - timedelta(days=4),
                  token_expires_at=datetime.now(UTC) + timedelta(hours=1))
    values.update(changes)
    return RingCentralConnections(**values)


def user(employee_id=11, role="sales"):
    return UserResponse(id=str(employee_id), role=role, name="Sales A", email="synthetic@coverage.test")


@pytest.mark.asyncio
async def test_fixed_window_reads_all_pages_without_using_next_url_or_changing_bounds(monkeypatch):
    calls = []
    start, end = datetime.now(UTC) - timedelta(days=1), datetime.now(UTC)
    async def request(method, path, token, *, params):
        calls.append((path, dict(params)))
        page = params['page']
        return dict(records=[{'id':str(page)}], navigation={'nextPage':{'uri':f'https://untrusted.invalid/wrong-path?page={page+1}'}} if page < 3 else {})
    monkeypatch.setattr(provider, '_authorized_json_request', request)
    result = await provider.fetch_extension_call_log('PRIVATE', date_from=start, date_to=end)
    assert [row['id'] for row in result] == ['1','2','3']
    assert {path for path, _ in calls} == {'/restapi/v1.0/account/~/extension/~/call-log'}
    assert len({params['dateFrom'] for _,params in calls}) == len({params['dateTo'] for _,params in calls}) == 1
    assert result.window == dict(date_from=start,date_to=end,pages=3,fully_paginated=True,scope='extension')


@pytest.mark.asyncio
async def test_first_full_page_without_navigation_is_not_assumed_complete(monkeypatch):
    calls=[]
    async def request(*args, params):
        calls.append(params['page'])
        return {'records':[{'id':str(i)} for i in range(100)] if params['page']==1 else []}
    monkeypatch.setattr(provider,'_authorized_json_request',request)
    result=await provider.fetch_extension_call_log('private',date_from=datetime.now(UTC)-timedelta(days=1))
    assert calls==[1,2] and len(result)==100 and result.window['pages']==2


@pytest.mark.asyncio
async def test_invalid_page_order_and_page_failure_do_not_return_completed_window(monkeypatch):
    async def repeating(*args, **kwargs):
        return {'records':[], 'navigation':{'nextPage':{'uri':'https://provider.invalid/?page=1'}}}
    monkeypatch.setattr(provider,'_authorized_json_request',repeating)
    with pytest.raises(HTTPException,match='502'):
        await provider.fetch_extension_call_log('private',date_from=datetime.now(UTC))
    async def failing(*args, params):
        if params['page']==2:raise HTTPException(502,'provider unavailable')
        return {'records':[{'id':'one'}], 'paging':{'totalPages':2}}
    monkeypatch.setattr(provider,'_authorized_json_request',failing)
    with pytest.raises(HTTPException):
        await provider.fetch_extension_call_log('private',date_from=datetime.now(UTC))


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', [None, {'records':[], 'navigation':{'nextPage':'invalid'}}, {'records':None}, {'records':[], 'paging':{'page':2}}])
async def test_malformed_provider_response_cannot_create_window_proof(monkeypatch,payload):
    async def request(*args,**kwargs):return payload
    monkeypatch.setattr(provider,'_authorized_json_request',request)
    with pytest.raises(HTTPException) as exc:
        await provider.fetch_extension_call_log('private',date_from=datetime.now(UTC))
    assert exc.value.status_code==502


@pytest.mark.asyncio
async def test_pagination_ceiling_rejects_unbounded_provider_history(monkeypatch):
    pages=[]
    async def request(*args,params):
        pages.append(params['page'])
        return {'records':[], 'navigation':{'nextPage':{'uri':f'https://provider.invalid/?page={params["page"]+1}'}}}
    monkeypatch.setattr(provider,'_authorized_json_request',request)
    with pytest.raises(HTTPException) as exc:
        await provider.fetch_extension_call_log('private',date_from=datetime.now(UTC))
    assert exc.value.status_code==502 and len(pages)==100


def test_completed_intervals_merge_but_partial_and_failed_attempts_do_not_fill_gaps():
    start=datetime(2026,1,1,tzinfo=UTC);end=start+timedelta(days=5)
    def window(left,right,status='completed'):
        return dict(requested_from=(start+timedelta(days=left)).isoformat(),requested_to=(start+timedelta(days=right)).isoformat(),status=status,fully_paginated=True,skipped=0)
    summary=summarize_windows([window(0,5,'failed'),window(0,2),window(1,3),window(3,5,'partial')],start,end)
    assert summary['status']=='gaps' and len(summary['fetched_ranges'])==1
    assert summary['unverified_ranges']==[{'start':(start+timedelta(days=3)).isoformat(),'end':end.isoformat()}]
    assert summary['needs_retry'] and summary['data_complete'] is False


@pytest.mark.asyncio
async def test_zero_calls_can_prove_a_fetch_window_without_becoming_call_facts(sync_db):
    conn=connection();sync_db.add(conn);await sync_db.commit()
    end=datetime.now(UTC);start=end-timedelta(days=2)
    record_window(sync_db,conn,binding=binding_key(conn),date_from=start,date_to=end,status='completed',pages=2,fully_paginated=True)
    await sync_db.commit()
    evidence=(await connection_coverage(sync_db,[conn],start=start,end=end))[11]
    assert evidence['status']=='window_fetched' and not evidence['unverified_ranges']
    assert evidence['data_complete'] is False and evidence['last_attempt']['fetched']==0
    assert not (await sync_db.execute(select(RingCentralCallRecords))).scalars().all()


@pytest.mark.asyncio
async def test_old_binding_forged_note_and_other_employee_windows_are_not_coverage(sync_db):
    first,other=connection(),connection(12);sync_db.add_all([first,other]);await sync_db.commit()
    end=datetime.now(UTC);start=end-timedelta(days=1)
    record_window(sync_db,first,binding=binding_key(first),date_from=start,date_to=end,status='completed',fully_paginated=True)
    record_window(sync_db,other,binding=binding_key(other),date_from=start,date_to=end,status='failed',error_code='OTHER_TEAM_PRIVATE')
    await sync_db.commit()
    first.binding_started_at=datetime.now(UTC);await sync_db.commit()
    note=dict(version=1,employee_id=11,binding=binding_key(first),status='completed',fully_paginated=True,skipped=0,requested_from=start.isoformat(),requested_to=end.isoformat())
    sync_db.add(Operation_logs(user_id='11',action_type='user_note',action_detail=json.dumps(note),created_at=datetime.now(UTC)))
    await sync_db.commit()
    result=await connection_coverage(sync_db,[first],start=start,end=end)
    assert set(result)=={11} and result[11]['status']=='unknown' and not result[11]['recent_attempts']
    assert 'OTHER_TEAM_PRIVATE' not in str(result)


async def setup_manual(sync_db,monkeypatch,**changes):
    conn=connection(**changes);sync_db.add(conn);await sync_db.commit()
    async def refresh(employee,current,db):return current
    monkeypatch.setattr(router,'_refresh_connection_if_needed',refresh)
    monkeypatch.setattr(router,'_access_token',lambda _: 'PRIVATE_TOKEN')
    return conn


@pytest.mark.asyncio
async def test_manual_sync_is_own_binding_and_clips_period_before_activation(sync_db,monkeypatch):
    conn=await setup_manual(sync_db,monkeypatch)
    captured=[]
    async def fetch(token,*,date_from,date_to):
        captured.append((date_from,date_to));return provider.CallLogRecords([],date_from=date_from,date_to=date_to,pages=2,scope='extension')
    monkeypatch.setattr(router,'fetch_extension_call_log',fetch)
    result=await router.sync_ringcentral_call_log(days=30,current_user=user(),db=sync_db)
    assert captured[0][0]==conn.binding_started_at.replace(tzinfo=UTC)
    assert result['sync_window']['status']=='completed' and result['sync_window']['pages']==2
    assert result['sync_window']['employee_id']==11
    rows=(await sync_db.execute(select(Operation_logs))).scalars().all()
    assert len(rows)==1 and rows[0].user_id=='11'
    assert 'PRIVATE_TOKEN' not in rows[0].action_detail and 'PRIVATE_ACCESS' not in rows[0].action_detail


@pytest.mark.asyncio
async def test_skipped_ownership_preserves_last_success_and_records_partial_window(sync_db,monkeypatch):
    old=datetime.now(UTC)-timedelta(days=1);conn=await setup_manual(sync_db,monkeypatch,last_synced_at=old)
    async def fetch(token,*,date_from,date_to):return provider.CallLogRecords([{'id':'skip'}],date_from=date_from,date_to=date_to,pages=1,scope='extension')
    async def skip(*args):return None
    monkeypatch.setattr(router,'fetch_extension_call_log',fetch);monkeypatch.setattr(router,'upsert_call_log_record',skip)
    result=await router.sync_ringcentral_call_log(days=2,current_user=user(),db=sync_db)
    assert result['skipped']==1 and result['sync_window']['status']=='partial'
    assert conn.last_synced_at.replace(tzinfo=UTC)==old


@pytest.mark.asyncio
async def test_provider_failure_is_persisted_safely_and_retry_can_clear_only_sync_error(sync_db,monkeypatch):
    conn=await setup_manual(sync_db,monkeypatch)
    async def fail(*args,**kwargs):raise HTTPException(502,'PRIVATE_PROVIDER_RESPONSE_TOKEN')
    monkeypatch.setattr(router,'fetch_extension_call_log',fail)
    with pytest.raises(HTTPException):await router.sync_ringcentral_call_log(days=2,current_user=user(),db=sync_db)
    row=(await sync_db.execute(select(Operation_logs))).scalar_one()
    assert 'PRIVATE_PROVIDER_RESPONSE_TOKEN' not in row.action_detail and 'PRIVATE_PROVIDER_RESPONSE_TOKEN' not in conn.last_error
    assert json.loads(row.action_detail)['status']=='failed'
    async def succeed(token,*,date_from,date_to):return provider.CallLogRecords([],date_from=date_from,date_to=date_to,pages=1,scope='extension')
    monkeypatch.setattr(router,'fetch_extension_call_log',succeed)
    result=await router.sync_ringcentral_call_log(days=2,current_user=user(),db=sync_db)
    assert result['sync_window']['status']=='completed' and conn.last_error is None


@pytest.mark.asyncio
async def test_rebinding_during_fetch_never_attributes_old_account_calls(sync_db,monkeypatch):
    conn=await setup_manual(sync_db,monkeypatch)
    async def fetch(token,*,date_from,date_to):
        conn.ringcentral_extension_id='replacement';conn.binding_started_at=datetime.now(UTC);await sync_db.commit()
        return provider.CallLogRecords([{'id':'old-owner'}],date_from=date_from,date_to=date_to,pages=1,scope='extension')
    async def forbidden(*args):raise AssertionError('must not attribute old binding data')
    monkeypatch.setattr(router,'fetch_extension_call_log',fetch);monkeypatch.setattr(router,'upsert_call_log_record',forbidden)
    with pytest.raises(HTTPException) as exc:await router.sync_ringcentral_call_log(days=2,current_user=user(),db=sync_db)
    assert exc.value.status_code==409
    assert not (await sync_db.execute(select(RingCentralCallRecords))).scalars().all()


@pytest.mark.asyncio
async def test_conflicting_binding_and_non_sales_roles_do_not_reach_provider(sync_db,monkeypatch):
    await setup_manual(sync_db,monkeypatch)
    await sync_db.execute(text('DROP INDEX uq_ringcentral_connection_provider_identity'))
    sync_db.add(connection(12,ringcentral_extension_id='extension-11'));await sync_db.commit()
    async def forbidden(*args,**kwargs):raise AssertionError('provider must not be called')
    monkeypatch.setattr(router,'fetch_extension_call_log',forbidden)
    for current,code in [(user(),409),(user(role='operations'),403)]:
        with pytest.raises(HTTPException) as exc:await router.sync_ringcentral_call_log(days=2,current_user=current,db=sync_db)
        assert exc.value.status_code==code
        with pytest.raises(HTTPException) as exc:await router.ensure_ringcentral_subscription(current_user=current,db=sync_db)
        assert exc.value.status_code==code
