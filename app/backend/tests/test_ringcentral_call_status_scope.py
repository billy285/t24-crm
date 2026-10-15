"""Real employee sessions: task history never grants current merchant access."""
from datetime import date, datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.main import app
from core.database import Base, get_db
from models.employees import Employees
from models.ringcentral_call_records import RingCentralCallRecords
from models.sales_daily_dial_tasks import SalesDailyDialTasks
from models.sales_dossiers import SalesDossierGrant
from models.sales_leads import SalesLeads
from services.emp_auth import hash_password


PASSWORD = "Synthetic-status-only-2026!"
PASSWORD_HASH = hash_password(PASSWORD)
API = "/api/ringcentral/calls/recent"


@pytest_asyncio.fixture
async def status_api(tmp_path, monkeypatch):
    monkeypatch.setenv("ENFORCE_EMPLOYEE_STATUS", "true")
    monkeypatch.setenv("ENFORCE_EMPLOYEE_SESSIONS", "true")
    engine = create_async_engine("sqlite+aiosqlite:///" + str(tmp_path / "call-status.sqlite"))
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        db.add_all([
            Employees(id=1,user_id="1",name="Owner",role="super_admin",status="active",email="owner@status.test",password=PASSWORD_HASH),
            Employees(id=10,user_id="10",name="Manager A",role="sales_manager",status="active",email="manager@status.test",password=PASSWORD_HASH),
            Employees(id=11,user_id="11",name="Sales A",role="sales",supervisor="Manager A",status="active",email="sales-a@status.test",password=PASSWORD_HASH),
            Employees(id=12,user_id="12",name="PRIVATE_OTHER_SALES",role="sales",supervisor="Manager B",status="active",email="sales-b@status.test",password=PASSWORD_HASH),
            Employees(id=13,user_id="13",name="Sales C",role="sales",supervisor="Manager A",status="active",email="sales-c@status.test",password=PASSWORD_HASH),
            SalesLeads(id=1,business_name="Own",phone="+12125550111",assigned_sales_id=11,team_manager_id=10),
            SalesLeads(id=2,business_name="PRIVATE_OTHER_MERCHANT",phone="+12125550222",assigned_sales_id=12,team_manager_id=20),
            SalesLeads(id=3,business_name="Team",phone="+12125550333",assigned_sales_id=13,team_manager_id=10),
            SalesLeads(id=4,business_name="PRIVATE_TRANSFERRED_MERCHANT",phone="+12125550444",assigned_sales_id=12,team_manager_id=20),
        ])
        for task_id,lead_id,employee_id,name in [(101,1,11,"Sales A"),(102,2,12,"PRIVATE_OTHER_SALES"),
                (103,3,13,"Sales C"),(104,4,11,"Sales A"),(105,1,12,"PRIVATE_OTHER_SALES")]:
            db.add(SalesDailyDialTasks(id=task_id,lead_id=lead_id,sales_employee_id=employee_id,
                task_date=date.today(),status="completed"))
            db.add(RingCentralCallRecords(provider_key=f"synthetic-{task_id}",lead_id=lead_id,task_id=task_id,
                sales_employee_id=employee_id,sales_employee_name=name,provider_status="Disconnected",
                provider_result="Call connected",connected=True,duration_seconds=60,
                remote_phone="+12125559999",recording_uri="PRIVATE_RECORDING_URI",
                started_at=datetime.now(timezone.utc),sync_status="verified"))
        await db.commit()
    async def override_db():
        async with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = override_db
    headers = {}
    try:
        async with AsyncClient(transport=ASGITransport(app=app),base_url="http://test") as client:
            async def login(email):
                if email not in headers:
                    result = await client.post("/api/v1/emp-auth/login",json={"email":email,"password":PASSWORD})
                    assert result.status_code == 200, result.text
                    headers[email] = {"Authorization":"Bearer "+result.json()["token"]}
                return headers[email]
            yield client,sessions,login
    finally:
        app.dependency_overrides.pop(get_db,None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_current_sales_own_task_and_manager_team_task_keep_minimal_status(status_api):
    client,_,login = status_api
    for email,task_id in [("sales-a@status.test",101),("manager@status.test",103),("owner@status.test",102)]:
        result = await client.get(API,params={"task_id":task_id},headers=await login(email))
        assert result.status_code == 200, result.text
        assert result.json()["available"] and result.json()["connected"]
        assert result.json()["duration_seconds"] == 60
        assert "remote_phone" not in result.json() and "recording_uri" not in result.json()
        assert "PRIVATE_RECORDING_URI" not in result.text


@pytest.mark.asyncio
async def test_manager_cannot_read_another_teams_call_by_task_id(status_api):
    client,_,login = status_api
    result = await client.get(API,params={"task_id":102},headers=await login("manager@status.test"))
    assert result.status_code == 404, result.text
    assert "PRIVATE_OTHER" not in result.text


@pytest.mark.asyncio
async def test_former_task_owner_cannot_read_after_merchant_transferred(status_api):
    client,_,login = status_api
    result = await client.get(API,params={"task_id":104},headers=await login("sales-a@status.test"))
    assert result.status_code == 404, result.text
    assert "PRIVATE_TRANSFERRED" not in result.text


@pytest.mark.asyncio
async def test_missing_and_out_of_scope_tasks_return_same_generic_response(status_api):
    client,_,login = status_api
    headers = await login("sales-a@status.test")
    results = [await client.get(API,params={"task_id":task_id},headers=headers) for task_id in [999,102,104,105]]
    assert all(result.status_code == 404 for result in results), [result.text for result in results]
    assert all(result.json() == results[0].json() for result in results)


@pytest.mark.asyncio
@pytest.mark.parametrize("access",["view","collaborate"])
async def test_dossier_invitation_never_grants_provider_task_status(status_api,access):
    client,sessions,login = status_api
    async with sessions() as db:
        db.add(SalesDossierGrant(lead_id=2,employee_id=11,access=access,status="active",revision=1,
            invited_by_id=1,invited_by_name="Owner"))
        await db.commit()
    result = await client.get(API,params={"task_id":102},headers=await login("sales-a@status.test"))
    assert result.status_code == 404, result.text


@pytest.mark.asyncio
async def test_current_assignment_and_manager_scope_are_checked_again_each_request(status_api):
    client,sessions,login = status_api
    sales = await login("sales-a@status.test")
    manager = await login("manager@status.test")
    assert (await client.get(API,params={"task_id":101},headers=sales)).status_code == 200
    assert (await client.get(API,params={"task_id":101},headers=manager)).status_code == 200
    async with sessions() as db:
        lead = await db.get(SalesLeads,1)
        lead.assigned_sales_id,lead.team_manager_id = 12,20
        await db.commit()
    for headers in [sales,manager]:
        assert (await client.get(API,params={"task_id":101},headers=headers)).status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value",[("lead_id",2),("sales_employee_id",12)])
async def test_inconsistent_provider_record_does_not_leak_through_an_authorized_task(status_api,field,value):
    client,sessions,login = status_api
    async with sessions() as db:
        row = (await db.execute(select(RingCentralCallRecords).where(RingCentralCallRecords.task_id==101))).scalar_one()
        setattr(row,field,value)
        row.sales_employee_name = "PRIVATE_OTHER_SALES"
        await db.commit()
    result = await client.get(API,params={"task_id":101},headers=await login("sales-a@status.test"))
    assert result.status_code == 200, result.text
    assert result.json() == {"available":False,"sync_status":"waiting"}
    assert "PRIVATE_OTHER" not in result.text
