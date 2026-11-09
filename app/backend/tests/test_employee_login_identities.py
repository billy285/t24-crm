"""Employee writes must keep username/email logins unambiguous without touching passwords."""
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.main import app
from core.database import Base, get_db
from models.commissions import SalesPartner
from models.employees import Employees
from services.emp_auth import create_access_token

API = '/api/v1/entities/employees'
PASSWORD_FINGERPRINT = 'SYNTHETIC_PASSWORD_FINGERPRINT_ONLY'


@pytest_asyncio.fixture
async def identity_api(tmp_path, monkeypatch):
    monkeypatch.setenv('ENFORCE_EMPLOYEE_STATUS', 'false')
    monkeypatch.setenv('ENFORCE_EMPLOYEE_SESSIONS', 'false')
    engine = create_async_engine('sqlite+aiosqlite:///' + str(tmp_path / 'identity.sqlite'))
    async with engine.begin() as connection:
        await connection.run_sync(lambda connection: Base.metadata.create_all(
            connection, tables=[Employees.__table__, SalesPartner.__table__]))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        db.add_all([
            Employees(id=1, user_id='owner-1', name='Owner', role='super_admin', status='active',
                      email='owner@example.test', login_username='Owner', password=PASSWORD_FINGERPRINT),
            Employees(id=2, user_id='sales-2', name='Sales A', role='sales', status='active',
                      email='sales-a@example.test', login_username='Leo', password=PASSWORD_FINGERPRINT),
            Employees(id=3, user_id='sales-3', name='Sales B', role='sales', status='active',
                      email='sales-b@example.test', login_username='Other', password=PASSWORD_FINGERPRINT),
        ])
        await db.commit()
    async def override_db():
        async with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = override_db
    token = create_access_token({'emp_id':1, 'email':'owner@example.test', 'role':'super_admin', 'name':'Owner'})
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test',
                               headers={'Authorization':'Bearer '+token}) as client:
            yield client, sessions
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('identity', [
    {'login_username':'  lEO  '},
    {'email':' LEO '},
    {'login_username':' SALES-A@EXAMPLE.TEST '},
    {'email':'SALES-A@EXAMPLE.TEST'},
])
async def test_create_rejects_existing_cross_field_identity(identity_api, identity):
    client, sessions = identity_api
    result = await client.post(API, json={'name':'Must Not Be Added', 'role':'sales', **identity})
    assert result.status_code == 409, result.text
    async with sessions() as db:
        assert len((await db.scalars(select(Employees))).all()) == 3
        assert (await db.get(Employees, 2)).password == PASSWORD_FINGERPRINT


@pytest.mark.asyncio
async def test_create_trims_username_and_allows_own_email_as_username(identity_api):
    client, _ = identity_api
    result = await client.post(API, json={'name':'New Sales', 'role':'sales',
        'email':'  NEW@EXAMPLE.TEST ', 'login_username':' New@Example.Test  '})
    assert result.status_code == 201, result.text
    assert result.json()['email'] == 'new@example.test'
    assert result.json()['login_username'] == 'New@Example.Test'
    assert 'password' not in result.json()


@pytest.mark.asyncio
@pytest.mark.parametrize('identities', [
    ({'login_username':'New Name'}, {'login_username':' new NAME '}),
    ({'email':'new@example.test'}, {'login_username':' NEW@EXAMPLE.TEST '}),
    ({'login_username':'new@example.test'}, {'email':' NEW@EXAMPLE.TEST '}),
])
async def test_batch_create_collision_has_no_partial_insert(identity_api, identities):
    client, sessions = identity_api
    result = await client.post(API+'/batch', json={'items':[
        {'name':'First', 'role':'sales', **identities[0]},
        {'name':'Second', 'role':'sales', **identities[1]},
    ]})
    assert result.status_code == 409, result.text
    async with sessions() as db:
        assert len((await db.scalars(select(Employees))).all()) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize('patch', [
    {'login_username':' LEO '},
    {'email':' Leo '},
    {'login_username':' SALES-A@EXAMPLE.TEST '},
])
async def test_update_collision_is_atomic_and_preserves_password(identity_api, patch):
    client, sessions = identity_api
    result = await client.put(API+'/3', json={'department':'Must Not Be Saved', **patch})
    assert result.status_code == 409, result.text
    async with sessions() as db:
        row = await db.get(Employees, 3)
        assert row.email == 'sales-b@example.test' and row.login_username == 'Other'
        assert row.department is None and row.password == PASSWORD_FINGERPRINT


@pytest.mark.asyncio
async def test_batch_update_checks_unchanged_counterpart_in_final_rows(identity_api):
    client, sessions = identity_api
    result = await client.put(API+'/batch', json={'items':[
        {'id':2,'updates':{'login_username':' New Name '}},
        {'id':3,'updates':{'email':' new NAME '}},
    ]})
    assert result.status_code == 409, result.text
    # A requested identity also cannot collide with an unchanged username in a
    # different row that happens to participate in the same batch.
    result = await client.put(API+'/batch', json={'items':[
        {'id':2,'updates':{'department':'Do Not Save'}},
        {'id':3,'updates':{'email':' LEO '}},
    ]})
    assert result.status_code == 409, result.text
    async with sessions() as db:
        assert (await db.get(Employees,2)).department is None
        assert (await db.get(Employees,3)).email == 'sales-b@example.test'


@pytest.mark.asyncio
async def test_update_allows_same_employee_alias_and_keeps_password(identity_api):
    client, sessions = identity_api
    result = await client.put(API+'/2', json={'login_username':' Sales-A@Example.Test '})
    assert result.status_code == 200, result.text
    async with sessions() as db:
        row = await db.get(Employees,2)
        assert row.email == 'sales-a@example.test'
        assert row.login_username == 'Sales-A@Example.Test'
        assert row.password == PASSWORD_FINGERPRINT


@pytest.mark.asyncio
async def test_non_identity_edit_does_not_block_unrelated_legacy_ambiguity(identity_api):
    client, sessions = identity_api
    async with sessions() as db:
        (await db.get(Employees,3)).login_username = 'LEO'
        await db.commit()
    result = await client.put(API+'/2', json={'department':'Updated Team',
        'email':' SALES-A@EXAMPLE.TEST ', 'login_username':' Leo '})
    assert result.status_code == 200, result.text
    async with sessions() as db:
        row = await db.get(Employees,2)
        assert row.department == 'Updated Team' and row.password == PASSWORD_FINGERPRINT
