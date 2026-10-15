"""Synthetic attack/regression cases for sales-only contact and transfer guards."""
from datetime import date, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.main import app
from core.database import Base, get_db
from models.employees import Employees
from models.merchant_pool import MerchantPool
from models.sales_call_activities import SalesCallActivities
from models.sales_contact_protection import SalesContactProtectionAudit, SalesPhoneSuppression
from models.sales_daily_dial_tasks import SalesDailyDialTasks
from models.sales_dossiers import SalesDossierHandoff
from models.sales_lead_enrichments import SalesLeadEnrichment, SalesLeadEnrichmentAudit
from models.sales_leads import SalesLeads
from services.emp_auth import create_access_token
from services.sales_lead_cycle import ensure_daily_batch

API = "/api/v1/sales-leads"


def auth(role="sales", employee_id=11, name="Sales A"):
    return {"Authorization": "Bearer " + create_access_token({
        "emp_id": employee_id, "email": f"{employee_id}@example.test", "role": role, "name": name})}


@pytest_asyncio.fixture
async def protection_api(tmp_path):
    engine = create_async_engine("sqlite+aiosqlite:///" + str(tmp_path / "contact.sqlite"))
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(timezone.utc)
    async with sessions() as db:
        db.add_all([
            Employees(id=1, user_id="1", name="Owner", role="super_admin", status="active"),
            Employees(id=10, user_id="10", name="Manager A", role="sales_manager", status="active"),
            Employees(id=11, user_id="11", name="Sales A", role="sales", supervisor="Manager A", status="active"),
            Employees(id=12, user_id="12", name="Sales B", role="sales", supervisor="Manager B", status="active"),
            SalesLeads(id=1, business_name="Own Store", phone="+12125550111", country="US",
                status="contacted", assigned_sales_id=11, assigned_sales_name="Sales A", assigned_at=now),
            SalesLeads(id=2, business_name="PRIVATE_OTHER_STORE", phone="+12125550222", country="US",
                assigned_sales_id=12, assigned_sales_name="Sales B", assigned_at=now),
            SalesDailyDialTasks(id=101, lead_id=1, sales_employee_id=11, task_date=date.today(), status="pending"),
            SalesDailyDialTasks(id=102, lead_id=2, sales_employee_id=12, task_date=date.today(), status="pending"),
            SalesLeadEnrichment(lead_id=1, revision=1, contacts=[{"id":"owner","phone":"+12125550333"}],
                interest_product_ids=[], updated_by_id=11, updated_by_name="Sales A"),
            SalesLeadEnrichmentAudit(lead_id=1, revision=1, source="manual", changed_fields=["store_phone"],
                before={"store_phone":"+12125550444","country":"US"}, after={"store_phone":"+12125550111"},
                actor_id=11, actor_name="Sales A"),
        ])
        await db.commit()
    async def override_db():
        async with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = override_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client, sessions
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


async def block(client):
    response = await client.put(f"{API}/1", headers=auth(), json={
        "do_not_contact": True, "do_not_contact_reason": "商家本人要求不再联系"})
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_dnc_cannot_be_cleared_or_reassigned_through_generic_update(protection_api):
    client, sessions = protection_api
    await block(client)
    for headers in [auth(), auth("sales_manager",10,"Manager A"), auth("admin",1,"Owner"), auth("super_admin",1,"Owner")]:
        for update in [{"do_not_contact":False}, {"status":"new"}, {"do_not_contact":False,"status":"new"}]:
            response = await client.put(f"{API}/1", headers=headers, json=update)
            assert response.status_code == 403, response.text
    assert (await client.put(f"{API}/1", headers=auth("admin",1,"Owner"),
        json={"assigned_sales_id":12})).status_code == 409
    assert (await client.post(f"{API}/workbench/tasks/101/dial-started", headers=auth(),
        json={"phone":"+12125550111"})).status_code == 400  # cancelled by protection
    async with sessions() as db:
        assert (await db.get(SalesLeads,1)).do_not_contact
        assert len((await db.execute(select(SalesPhoneSuppression))).scalars().all()) == 3


@pytest.mark.asyncio
async def test_dnc_survives_phone_change_delete_reimport_and_alternate_number(protection_api):
    client, sessions = protection_api
    await block(client)
    changed = await client.put(f"{API}/1", headers=auth("admin",1,"Owner"), json={"phone":"+12125550555"})
    assert changed.status_code == 200, changed.text
    assert (await client.delete(f"{API}/1", headers=auth("admin",1,"Owner"))).status_code == 409
    # Simulate a historical pre-guard deletion: suppression still has no lead FK dependency.
    async with sessions() as db:
        await db.delete(await db.get(SalesLeads,1))
        await db.commit()
    for phone in ["+12125550111", "+12125550333", "+12125550444", "+12125550555"]:
        result = await client.post(API, headers=auth("sales_manager",10,"Manager A"),
            json={"business_name":"Reimported", "phone":phone,"assigned_sales_id":11})
        assert result.status_code == 409, result.text
        assert "Own Store" not in result.text and "PRIVATE" not in result.text and "编号" not in result.text
    async with sessions() as db:
        # A separately imported lead can never use an alternate saved number to bypass suppression.
        lead = await db.get(SalesLeads,2)
        db.add(SalesLeadEnrichment(lead_id=2, revision=1, updated_by_id=12,
            contacts=[{"id":"alternate","phone":"+12125550333"}], interest_product_ids=[]))
        db.add(MerchantPool(id=9,business_name="New raw merchant",phone="+12125550444",country="US",pool_status="pending"))
        await db.commit()
    dial = await client.post(f"{API}/workbench/tasks/102/dial-started", headers=auth("sales",12,"Sales B"),
        json={"phone":"+12125550333"})
    assert dial.status_code == 409 and "Own Store" not in dial.text
    converted = await client.post("/api/v1/merchant-pool/9/convert-to-lead",headers=auth("admin",1,"Owner"),
        json={"assigned_sales_id":11})
    assert converted.status_code == 409, converted.text
    async with sessions() as db:
        assert (await db.get(MerchantPool,9)).pool_status == "pending"
        assert (await db.execute(select(SalesCallActivities))).scalars().all() == []


@pytest.mark.asyncio
async def test_owner_release_is_per_number_audited_and_does_not_unblock_other_lead(protection_api):
    client, sessions = protection_api
    await block(client)
    endpoint = f"{API}/1/contact-protection/release"
    body = {"phone":"+12125550111","reason":"已向商家本人核实重新同意联系","resume_lead":True}
    assert (await client.post(endpoint,headers=auth("admin",1,"Owner"),json=body)).status_code == 403
    assert (await client.post(endpoint,headers=auth("super_admin",1,"Owner"),json=body)).status_code == 409
    async with sessions() as db:
        assert (await db.get(SalesPhoneSuppression,"+12125550111")).blocked  # failed resume rolled back
        other = await db.get(SalesLeads,2)
        other.do_not_contact = True
        other.status = "blocked"
        await db.commit()
    for phone, resume in [("+12125550333",False),("+12125550111",True)]:
        response = await client.post(endpoint, headers=auth("super_admin",1,"Owner"),
            json={**body,"phone":phone,"resume_lead":resume})
        assert response.status_code == 200, response.text
    async with sessions() as db:
        assert not (await db.get(SalesLeads,1)).do_not_contact
        assert (await db.get(SalesDailyDialTasks,101)).status == "pending"
        assert (await db.get(SalesLeads,2)).do_not_contact
        assert (await db.get(SalesPhoneSuppression,"+12125550444")).blocked  # historical phone stays protected
        audits = (await db.execute(select(SalesContactProtectionAudit).where(
            SalesContactProtectionAudit.action == "released_and_resumed"))).scalars().all()
        assert len(audits) == 1 and audits[0].actor_id == 1


@pytest.mark.asyncio
async def test_callback_transfer_requires_confirmation_and_handoff_before_contact(protection_api):
    client, sessions = protection_api
    async with sessions() as db:
        lead = await db.get(SalesLeads,1)
        lead.status = "follow_up"
        lead.next_follow_up_at = datetime.now(timezone.utc) + timedelta(days=1)
        await db.commit()
    body = {"assigned_sales_id":12,"reason":"确认原回访约定后转交","handoff_summary":"周三联系老板，先发送案例"}
    admin = auth("super_admin",1,"Owner")
    assert (await client.put(f"{API}/1",headers=admin,json={"status":"new"})).status_code == 409
    assert (await client.post(f"{API}/1/recovery/reassign",headers=admin,json=body)).status_code == 400
    assert (await client.post(f"{API}/1/recovery/reassign",headers=admin,json={**body,
        "expected_owner_id":12,"confirm_protected_transfer":True})).status_code == 409
    assert (await client.post(f"{API}/recovery/batch",headers=admin,json={**body,"lead_ids":[1],"action":"reassign"})).status_code == 400
    transferred = await client.post(f"{API}/1/recovery/reassign",headers=admin,
        json={**body,"expected_owner_id":11,"confirm_protected_transfer":True})
    assert transferred.status_code == 200, transferred.text
    async with sessions() as db:
        handoff = (await db.execute(select(SalesDossierHandoff).where(SalesDossierHandoff.lead_id==1))).scalar_one()
        assert handoff.status == "pending" and handoff.to_sales_id == 12
        task = (await db.execute(select(SalesDailyDialTasks).where(SalesDailyDialTasks.lead_id==1,
            SalesDailyDialTasks.sales_employee_id==12))).scalar_one()
        task_id = task.id
    dial = await client.post(f"{API}/workbench/tasks/{task_id}/dial-started",headers=auth("sales",12,"Sales B"),
        json={"phone":"+12125550111"})
    assert dial.status_code == 409 and "交接" in dial.text
    former = await client.get(f"{API}/1", headers=auth())
    assert former.status_code == 404


@pytest.mark.asyncio
async def test_cooling_and_cross_scope_paths_cannot_bypass_contact_protection(protection_api):
    client, sessions = protection_api
    async with sessions() as db:
        lead = await db.get(SalesLeads,1)
        lead.cooldown_until = datetime.now(timezone.utc) + timedelta(days=60)
        lead.automation_state = "cooling"
        await db.commit()
    for path, body in [("dial-started",{"phone":"+12125550111"}), ("result",{"outcome":"no_answer","notes":"本次未接通"})]:
        response = await client.post(f"{API}/workbench/tasks/101/{path}",headers=auth(),json=body)
        assert response.status_code == 409 and "冷却" in response.text
    for path, method, body in [("2","put",{"do_not_contact":True}),
        ("2/follow-up","post",{"outcome":"no_answer"})]:
        response = await getattr(client,method)(f"{API}/{path}",headers=auth(),json=body)
        assert response.status_code == 404 and "PRIVATE_OTHER_STORE" not in response.text


@pytest.mark.asyncio
async def test_shared_protected_phone_excluded_from_generated_queue_without_merging(protection_api):
    client, sessions = protection_api
    await block(client)
    async with sessions() as db:
        db.add(SalesLeads(id=3,business_name="Independent Shared Switchboard",phone="+12125550333",country="US"))
        await db.commit()
        await ensure_daily_batch(db,12,date.today(),100)
    async with sessions() as db:
        assert await db.get(SalesLeads,3) is not None
        assert (await db.execute(select(SalesDailyDialTasks).where(SalesDailyDialTasks.lead_id==3))).scalars().all() == []


@pytest.mark.asyncio
async def test_actual_dnc_result_persists_all_known_numbers_and_completed_call(protection_api):
    client, sessions = protection_api
    response = await client.post(f"{API}/workbench/tasks/101/result", headers=auth(),
        json={"outcome":"do_not_contact","notes":"对方明确要求停止联系"})
    assert response.status_code == 200, response.text
    async with sessions() as db:
        task = await db.get(SalesDailyDialTasks,101)
        assert task.status == "completed" and task.completed_activity_id
        assert (await db.get(SalesLeads,1)).do_not_contact
        assert len((await db.execute(select(SalesPhoneSuppression))).scalars().all()) == 3
        assert len((await db.execute(select(SalesCallActivities))).scalars().all()) == 1


@pytest.mark.asyncio
async def test_automatic_rotation_creates_acknowledgement_only_for_prior_relationship(protection_api):
    client, sessions = protection_api
    then = datetime.now(timezone.utc) - timedelta(days=91)
    async with sessions() as db:
        db.add(SalesLeads(id=3,business_name="Rotated",phone="+12125550777",country="US",status="contacted",
            last_assigned_sales_id=11, rotation_count=1, last_contact_at=then,
            cooldown_until=then+timedelta(days=90), next_follow_up_at=then+timedelta(days=90)))
        db.add(SalesCallActivities(lead_id=3,sales_employee_id=11,sales_employee_name="Sales A",
            outcome="existing_provider",notes="原服务商合作到期后再谈",called_at=then))
        await db.commit()
        await ensure_daily_batch(db,12,date.today(),100)
    async with sessions() as db:
        handoff = (await db.execute(select(SalesDossierHandoff).where(SalesDossierHandoff.lead_id==3))).scalar_one()
        assert handoff.from_sales_id == 11 and handoff.to_sales_id == 12 and handoff.status == "pending"
        assert handoff.created_by_name == "系统轮转"
        assert (await db.execute(select(SalesDossierHandoff).where(SalesDossierHandoff.lead_id==2))).scalars().all() == []
