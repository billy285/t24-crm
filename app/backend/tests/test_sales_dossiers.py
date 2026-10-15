"""Synthetic API and migration proof for the isolated prospect dossier boundary."""
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from alembic.migration import MigrationContext
from alembic.operations import Operations
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.main import app
from core.database import Base, get_db
from models.customers import Customers
from models.employees import Employees
from models.merchant_pool import MerchantPool
from models.payments import Payments
from models.sales_call_activities import SalesCallActivities
from models.sales_daily_dial_tasks import SalesDailyDialTasks
from models.sales_dossiers import (SalesDossierGrant, SalesDossierGrantAudit, SalesDossierHandoff,
                                   SalesDossierSummary, SalesDossierSummaryAudit)
from models.sales_contact_protection import SalesContactProtectionAudit, SalesPhoneSuppression
from models.sales_intelligence import SalesInsightEvents, SalesLeadProfiles
from models.sales_lead_enrichments import SalesLeadEnrichment, SalesLeadEnrichmentAudit
from models.sales_leads import SalesLeads
from services.emp_auth import create_access_token
from services.sales_dossiers import next_sales_lead_id, record_handoff, record_system_handoff

API = "/api/v1/sales-lead-dossiers"
ROLES = {1:("super_admin","Boss"),2:("admin","Admin"),10:("sales_manager","Manager"),
         11:("sales","Sales A"),12:("sales","Sales B"),13:("sales","Sales C"),
         14:("sales","Former Sales"),15:("ops","Operations")}


def auth(eid=11):
    role,name = ROLES[eid]
    return {"Authorization":"Bearer "+create_access_token({"emp_id":eid,"email":f"{eid}@example.test",
                                                            "role":role,"name":name})}


@pytest_asyncio.fixture
async def dossier_api(monkeypatch, tmp_path):
    monkeypatch.setenv("ENFORCE_EMPLOYEE_STATUS", "false")
    monkeypatch.setenv("ENFORCE_EMPLOYEE_SESSIONS", "false")
    engine = create_async_engine("sqlite+aiosqlite:///"+str(tmp_path/"dossiers.sqlite"))
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        db.add_all([Employees(id=eid,user_id=str(eid),name=name,role=role,
            status="inactive" if eid==14 else "active",supervisor="Manager" if eid==11 else "Other Manager")
            for eid,(role,name) in ROLES.items()])
        db.add_all([
            SalesLeads(id=1,business_name="Shared Store",phone="+12125550111",country="US",industry="美业",
                assigned_sales_id=11,assigned_sales_name="Sales A",merchant_pool_id=77),
            SalesLeads(id=2,business_name="Other Store",phone="+12125550222",country="US",assigned_sales_id=12),
            MerchantPool(id=77,business_name="ORIGINAL_STORE",phone="+12125550111",country="US",
                raw_payload='{"secret":"RAW_SECRET"}',existing_customer_id=80,isolation_reason="HIDDEN_CUSTOMER_REASON"),
            Customers(id=80,business_name="PRIVATE_CUSTOMER",contact_name="Private Owner",phone="+12125550888",country="US"),
            Payments(id=90,customer_id=80,amount_due=900,amount_paid=800,net_amount=700,
                     user_id="1",notes="PRIVATE_FINANCE"),
            SalesCallActivities(id=101,lead_id=1,sales_employee_id=11,sales_employee_name="Sales A",
                                outcome="callback",notes="Original call",called_at=datetime.now(timezone.utc)),
            SalesDailyDialTasks(id=201,lead_id=1,sales_employee_id=11,task_date=datetime.now().date(),status="pending"),
            SalesLeadProfiles(lead_id=1,revision=1,payload_json=json.dumps({"need_summary":"Pipeline need",
                "decision_maker":"Owner","next_step":"Current pipeline step","customer_id":80,
                "internal_finance":"HIDDEN_PROFILE_FINANCE"})),
            SalesInsightEvents(lead_id=1,kind="review",actor_id=11,actor_name="Sales A",
                payload_json='{"customer_id":80,"amount_paid":123,"secret":"HIDDEN_EVENT_SECRET"}'),
        ])
        await db.commit()
    async def override_db():
        async with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = override_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app),base_url="http://test") as client:
            yield client,sessions
    finally:
        app.dependency_overrides.pop(get_db,None)
        await engine.dispose()


async def get_dossier(client,eid=11,lead=1):
    response = await client.get(f"{API}/{lead}",headers=auth(eid))
    assert response.status_code == 200,response.text
    return response.json()


async def invite(client,eid=12,access="view",revision=0):
    response = await client.post(f"{API}/1/invites",headers=auth(1),
        json={"employee_id":eid,"access":access,"expected_revision":revision})
    assert response.status_code == 200,response.text
    return response.json()


async def protected_snapshot(sessions):
    async with sessions() as db:
        customer = await db.get(Customers,80)
        payment = await db.get(Payments,90)
        original = await db.get(MerchantPool,77)
        call = await db.get(SalesCallActivities,101)
        task = await db.get(SalesDailyDialTasks,201)
        return (customer.business_name,customer.phone,payment.amount_due,payment.amount_paid,payment.net_amount,
                payment.notes,original.business_name,original.raw_payload,call.sales_employee_id,call.notes,task.status)


@pytest.mark.asyncio
async def test_get_has_no_writes_and_projects_safe_original_and_history(dossier_api):
    client,sessions = dossier_api
    before = await protected_snapshot(sessions)
    data = await get_dossier(client)
    assert data["summary"]["revision"] == 0
    assert data["summary"]["need_summary"] == "Pipeline need"
    assert data["original"]["business_name"] == "ORIGINAL_STORE"
    for secret in ("RAW_SECRET","HIDDEN_CUSTOMER_REASON","HIDDEN_PROFILE_FINANCE","HIDDEN_EVENT_SECRET","PRIVATE_FINANCE"):
        assert secret not in json.dumps(data)
    assert "existing_customer_id" not in data["original"]
    assert "customer_id" not in data["insight"]["profile"]
    assert data["insight"]["converted_customer_id"] is None
    assert data["insight"]["timeline"][0].get("details") is None
    async with sessions() as db:
        for model in (SalesDossierSummary,SalesDossierSummaryAudit,SalesDossierGrant,SalesDossierGrantAudit,SalesDossierHandoff):
            assert not (await db.scalars(select(model))).all()
    assert await protected_snapshot(sessions) == before


@pytest.mark.asyncio
async def test_owner_nonprimary_and_cooldown_do_not_offer_suppression_release(dossier_api):
    client,sessions = dossier_api
    data = await get_dossier(client,1)
    assert not data["protection"]["can_contact"]
    assert not data["permissions"]["can_release_protection"]
    assert "主负责人" in data["protection"]["reason"]
    async with sessions() as db:
        lead = await db.get(SalesLeads,1)
        lead.cooldown_until = datetime.now(timezone.utc) + timedelta(days=1)
        await db.commit()
    data = await get_dossier(client,1)
    assert "冷却期" in data["protection"]["reason"]
    assert not data["permissions"]["can_release_protection"]


@pytest.mark.asyncio
async def test_real_dnc_reason_survives_nonprimary_owner_and_invited_actor_without_source_leak(dossier_api):
    from services.sales_contact_protection import PROTECTION_NOTICE
    client,sessions = dossier_api
    await invite(client)
    async with sessions() as db:
        lead = await db.get(SalesLeads,1)
        lead.do_not_contact = True
        lead.do_not_contact_reason = "SECRET_SOURCE_OPERATOR_REASON"
        await db.commit()
    owner = await get_dossier(client,1)
    assert owner["protection"]["reason"] == PROTECTION_NOTICE
    assert owner["permissions"]["can_release_protection"]
    invited = await get_dossier(client,12)
    assert invited["protection"]["reason"] == PROTECTION_NOTICE
    assert not invited["permissions"]["can_release_protection"]
    # The protection object exposes neither an operator nor another record's source.
    assert "SECRET_SOURCE_OPERATOR_REASON" not in json.dumps(invited["protection"])
    assert not {"actor_id","actor_name","source_lead_id","source_reason"} & set(invited["protection"])


@pytest.mark.asyncio
async def test_shared_phone_block_offers_only_owner_release_without_other_merchant_details(dossier_api):
    from services.sales_contact_protection import PROTECTION_NOTICE
    client,sessions = dossier_api
    await invite(client)
    async with sessions() as db:
        other = await db.get(SalesLeads,2)
        other.phone = "+12125550111"
        other.business_name = "SECRET_OTHER_PROTECTED_MERCHANT"
        other.do_not_contact = True
        other.do_not_contact_reason = "SECRET_SOURCE_REASON"
        await db.commit()
    owner = await get_dossier(client,1)
    assert owner["protection"]["reason"] == PROTECTION_NOTICE
    assert owner["permissions"]["can_release_protection"]
    invited = await get_dossier(client,12)
    assert not invited["permissions"]["can_release_protection"]
    assert invited["protection"]["reason"] == PROTECTION_NOTICE
    assert "SECRET_OTHER_PROTECTED_MERCHANT" not in json.dumps(invited)
    assert "SECRET_SOURCE_REASON" not in json.dumps(invited)


@pytest.mark.asyncio
@pytest.mark.parametrize("eid",[2,10,11,12])
async def test_only_boss_can_invite_even_when_manager_or_admin_has_read_scope(dossier_api,eid):
    client,_ = dossier_api
    response = await client.post(f"{API}/1/invites",headers=auth(eid),json={"employee_id":13,"access":"view"})
    assert response.status_code in {403,404}


@pytest.mark.asyncio
@pytest.mark.parametrize("eid",[1,2,10,14,15,9999])
async def test_invites_only_active_sales_not_other_roles_or_missing(dossier_api,eid):
    client,_ = dossier_api
    response = await client.post(f"{API}/1/invites",headers=auth(1),json={"employee_id":eid,"access":"view"})
    assert response.status_code == 422,response.text
    data = await get_dossier(client,1)
    assert data["grants"] == []
    assert {row["id"] for row in data["candidates"]} == {12,13}


@pytest.mark.asyncio
async def test_noninvited_is_404_view_is_readonly_and_shared_discovery_is_explicit(dossier_api):
    client,sessions = dossier_api
    assert (await client.get(f"{API}/1",headers=auth(12))).status_code == 404
    assert (await client.get(API,headers=auth(12))).json() == {"items":[],"total":0}
    await invite(client)
    data = await get_dossier(client,12)
    assert not data["permissions"]["can_edit"] and not data["permissions"]["can_edit_profile"]
    assert not data["protection"]["can_contact"] and not data["permissions"]["can_transfer"]
    assert data["candidates"] == []
    listing = (await client.get(API,headers=auth(12))).json()
    assert listing["total"] == 1 and listing["items"][0]["id"] == 1
    assert set(listing["items"][0]) == {"id","business_name","industry","state","owner_name","access","last_contact_at","next_follow_up_at"}
    response = await client.put(f"{API}/1/summary",headers=auth(12),json={"expected_revision":0,"promises":"not allowed"})
    assert response.status_code == 403
    async with sessions() as db:
        assert await db.get(SalesDossierSummary,1) is None


@pytest.mark.asyncio
async def test_collaborator_can_edit_without_widening_any_legacy_or_customer_scope(dossier_api):
    client,sessions = dossier_api
    before = await protected_snapshot(sessions)
    await invite(client,access="collaborate")
    response = await client.put(f"{API}/1/summary",headers=auth(12),
        json={"expected_revision":0,"latest_conclusion":"Needs review","objections":"Time","promises":"Send details"})
    assert response.status_code == 200,response.text
    assert response.json()["summary"]["updated_by_name"] == "Sales B"
    for path,method,body in [("/api/v1/sales-leads/1","GET",None),
        ("/api/v1/sales-leads/1","PUT",{"business_name":"forged"}),
        ("/api/v1/sales-intelligence/leads/1","GET",None),
        ("/api/v1/sales-intelligence/leads/1","PUT",{"revision":1,"pipeline_key":"system","stage_key":"needs","evidence":"forged access"}),
        ("/api/v1/sales-leads/1/enrichment","GET",None),
        ("/api/v1/sales-leads/workbench/tasks/201/dial-started","POST",{"phone":"+12125550111"}),
        ("/api/v1/sales-leads/1/recovery/reassign","POST",{"assigned_sales_id":13,"reason":"forged assignment"}),
        ("/api/v1/customers/80","GET",None),
        ("/api/v1/customers/80/access","GET",None),
        ("/api/v1/payments","GET",None)]:
        denied = await client.request(method,path,headers=auth(12),json=body)
        assert denied.status_code in {403,404},(path,denied.status_code,denied.text)
    # The original sales actor still owns the only queue/task and historical call.
    assert await protected_snapshot(sessions) == before


@pytest.mark.asyncio
async def test_existing_manager_enrichment_rights_and_transfer_roster_stay_scoped(dossier_api):
    client,sessions = dossier_api
    async with sessions() as db:
        employee = await db.get(Employees,13); employee.supervisor = "Manager"; await db.commit()
    data = await get_dossier(client,10)
    assert data["permissions"]["can_edit"] and data["permissions"]["can_transfer"]
    assert not data["permissions"]["can_invite"]
    assert {item["id"] for item in data["candidates"]} == {13}
    updated = await client.put(f"{API}/1/enrichment",headers=auth(10),
        json=enrichment_draft(data["enrichment"],need_summary="Manager verified"))
    assert updated.status_code == 200,updated.text
    assert updated.json()["summary"]["need_summary"] == "Manager verified"
    assert (await client.get(f"{API}/2",headers=auth(10))).status_code == 404


@pytest.mark.asyncio
async def test_failed_enrichment_after_flush_rolls_back_all_dossier_business_and_audit_writes(dossier_api,monkeypatch):
    from fastapi import HTTPException
    import routers.sales_dossiers as router_module
    from services.sales_enrichment import apply_enrichment as real_apply
    client,sessions = dossier_api
    before = await protected_snapshot(sessions)
    data = await get_dossier(client)
    async def failing_apply(db,lead,payload,actor):
        await real_apply(db,lead,payload,actor)
        db.add(SalesDossierSummary(lead_id=lead.id,revision=1,payload={"promises":"partial"},
            updated_by_id=actor.id,updated_by_name=actor.name))
        await db.flush()
        raise HTTPException(409,"Synthetic failure after flush")
    monkeypatch.setattr(router_module,"apply_enrichment",failing_apply)
    failed = await client.put(f"{API}/1/enrichment",headers=auth(),
        json=enrichment_draft(data["enrichment"],business_name="MUST_ROLL_BACK"))
    assert failed.status_code == 409
    assert (await get_dossier(client))["enrichment"]["business_name"] == "Shared Store"
    async with sessions() as db:
        assert await db.get(SalesDossierSummary,1) is None
        assert await db.get(SalesLeadEnrichment,1) is None
        assert not (await db.scalars(select(SalesLeadEnrichmentAudit))).all()
    assert await protected_snapshot(sessions) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("protection",["do_not_contact","converted_customer_id"])
async def test_protected_or_converted_dossier_cannot_be_modified_by_invited_collaborator(dossier_api,protection):
    client,sessions = dossier_api
    await invite(client,access="collaborate")
    async with sessions() as db:
        lead = await db.get(SalesLeads,1)
        setattr(lead,protection,True if protection=="do_not_contact" else 80)
        await db.commit()
    data = await get_dossier(client,12)
    assert not data["permissions"]["can_edit"] and not data["protection"]["can_contact"]
    assert (await client.put(f"{API}/1/summary",headers=auth(12),json={"expected_revision":0,"promises":"forged"})).status_code == 403
    assert (await client.put(f"{API}/1/enrichment",headers=auth(12),json=enrichment_draft(data["enrichment"]))).status_code == 403
    assert data["insight"]["converted_customer_id"] is None


@pytest.mark.asyncio
async def test_revocation_deactivation_and_role_change_deny_next_request(dossier_api):
    client,sessions = dossier_api
    await invite(client,access="collaborate")
    assert (await client.put(f"{API}/1/summary",headers=auth(12),json={"expected_revision":0,"promises":"Before revoke"})).status_code == 200
    assert (await client.request("DELETE",f"{API}/1/invites/12",headers=auth(1),json={"expected_revision":1})).status_code == 200
    assert (await client.get(f"{API}/1",headers=auth(12))).status_code == 404
    assert (await client.put(f"{API}/1/summary",headers=auth(12),json={"expected_revision":1,"promises":"stale"})).status_code == 404
    await invite(client,access="view",revision=2)
    async with sessions() as db:
        employee = await db.get(Employees,12); employee.status = "inactive"; await db.commit()
    assert (await client.get(f"{API}/1",headers=auth(12))).status_code == 403
    async with sessions() as db:
        employee = await db.get(Employees,12); employee.status = "active"; employee.role="ops"; await db.commit()
    assert (await client.get(f"{API}/1",headers=auth(12))).status_code == 403
    async with sessions() as db:
        assert (await db.get(SalesDossierSummary,1)).payload["promises"] == "Before revoke"
        assert len((await db.scalars(select(SalesDossierSummaryAudit))).all()) == 1


@pytest.mark.asyncio
async def test_summary_revision_and_derived_fields_prevent_stale_overwrites(dossier_api):
    client,sessions = dossier_api
    draft = {"expected_revision":0,"promises":"first"}
    assert (await client.put(f"{API}/1/summary",headers=auth(),json=draft)).status_code == 200
    assert (await client.put(f"{API}/1/summary",headers=auth(),json=draft)).status_code == 409
    for changed in ({"need_summary":"fork"},{"decision_maker":"fork"},{"next_step":"fork"},{"next_action_at":"2030-01-01T00:00:00Z"}):
        response = await client.put(f"{API}/1/summary",headers=auth(),json={"expected_revision":1,**changed})
        assert response.status_code == 422,response.text
    async with sessions() as db:
        profile = await db.get(SalesLeadProfiles,1)
        profile.payload_json = json.dumps({"need_summary":"New source need","decision_maker":"New Owner","next_step":"New pipeline step"})
        lead = await db.get(SalesLeads,1); lead.next_follow_up_at = datetime(2031,1,1,tzinfo=timezone.utc)
        await db.commit()
    data = await get_dossier(client)
    assert (data["summary"]["need_summary"],data["summary"]["decision_maker"],data["summary"]["next_step"]) == ("New source need","New Owner","New pipeline step")
    assert data["summary"]["next_action_at"].startswith("2031-01-01")
    assert data["summary"]["revision"] == 1
    assert len(data["changes"]) == 1


def enrichment_draft(profile,**changes):
    editable = ("business_name","industry","city","state","country","address","website","store_phone","contacts",
                "preferred_contact_id","interest_product_ids","need_summary","best_contact_time","verification")
    return {**{key:profile[key] for key in editable},"expected_revision":profile["revision"],
            "expected_lead_updated_at":profile["lead_updated_at"],"source":"manual",**changes}


@pytest.mark.asyncio
async def test_collaborator_enrichment_uses_existing_validation_revision_and_no_partial_audits(dossier_api):
    client,sessions = dossier_api
    await invite(client,access="collaborate")
    original = (await get_dossier(client,12))["enrichment"]
    bad = await client.put(f"{API}/1/enrichment",headers=auth(12),json=enrichment_draft(original,interest_product_ids=[9999]))
    assert bad.status_code == 422
    async with sessions() as db:
        assert await db.get(SalesLeadEnrichment,1) is None
        assert not (await db.scalars(select(SalesLeadEnrichmentAudit))).all()
    saved = await client.put(f"{API}/1/enrichment",headers=auth(12),json=enrichment_draft(original,need_summary="Current need",business_name="Updated Store",source="call"))
    assert saved.status_code == 200,saved.text
    assert saved.json()["summary"]["need_summary"] == "Current need"
    assert saved.json()["enrichment"]["updated_by_name"] == "Sales B"
    assert (await client.put(f"{API}/1/enrichment",headers=auth(12),json=enrichment_draft(original))).status_code == 409
    async with sessions() as db:
        assert len((await db.scalars(select(SalesLeadEnrichmentAudit))).all()) == 1
        assert (await db.scalars(select(SalesLeadEnrichmentAudit))).one().source == "manual"
        assert (await db.get(MerchantPool,77)).business_name == "ORIGINAL_STORE"


@pytest.mark.asyncio
async def test_invitation_revision_and_strict_fields_cannot_forge_ownership_or_finance(dossier_api):
    client,sessions = dossier_api
    await invite(client)
    stale = await client.post(f"{API}/1/invites",headers=auth(1),json={"employee_id":12,"access":"collaborate","expected_revision":0})
    assert stale.status_code == 409
    for extra in ({"assigned_sales_id":12},{"amount_paid":0},{"customer_id":80},{"actor_id":1}):
        response = await client.put(f"{API}/1/summary",headers=auth(),json={"expected_revision":0,**extra})
        assert response.status_code == 422
    async with sessions() as db:
        assert (await db.get(SalesLeads,1)).assigned_sales_id == 11
        assert not (await db.scalars(select(SalesDossierSummaryAudit))).all()


@pytest.mark.asyncio
async def test_handoff_snapshot_ack_and_repeated_transfer_preserve_original_attribution(dossier_api):
    client,sessions = dossier_api
    before = await protected_snapshot(sessions)
    await client.put(f"{API}/1/summary",headers=auth(),json={"expected_revision":0,"promises":"Historical promise"})
    async with sessions() as db:
        lead = await db.get(SalesLeads,1)
        lead.assigned_sales_id,lead.assigned_sales_name = 12,"Sales B"
        first = await record_handoff(db,lead,type("Actor",(),{"id":"1","name":"Boss","role":"super_admin"})(),
            from_sales_id=11,from_sales_name="Sales A",note="Follow the existing promise")
        first_id = first.id
        await db.commit()
    data = await get_dossier(client,12)
    assert data["permissions"]["can_ack"] is True
    assert data["handoffs"][0]["summary"]["promises"] == "Historical promise"
    # Cross-lead IDs are never accepted, even by the other lead's primary.
    assert (await client.post(f"{API}/2/handoffs/{first_id}/ack",headers=auth(12),json={})).status_code == 404
    assert (await client.post(f"{API}/1/handoffs/{first_id}/ack",headers=auth(1),json={})).status_code == 403
    acknowledged = await client.post(f"{API}/1/handoffs/{first_id}/ack",headers=auth(12),json={"note":"Read and accepted"})
    assert acknowledged.status_code == 200,acknowledged.text
    assert acknowledged.json()["handoffs"][0]["status"] == "acknowledged"
    assert (await client.post(f"{API}/1/handoffs/{first_id}/ack",headers=auth(12),json={})).status_code == 409
    async with sessions() as db:
        lead = await db.get(SalesLeads,1)
        lead.assigned_sales_id,lead.assigned_sales_name = 13,"Sales C"
        second = await record_system_handoff(db,lead,from_sales_id=12,from_sales_name="Sales B",note="Scheduled rotation")
        assert second.id != first_id
        await db.commit()
    assert (await client.get(f"{API}/1",headers=auth(12))).status_code == 404
    third = await get_dossier(client,13)
    assert third["permissions"]["can_ack"]
    assert third["insight"]["contributors"][0]["employee_id"] == 11
    assert await protected_snapshot(sessions) == before


@pytest.mark.asyncio
async def test_actual_reassign_requires_ack_before_contact_and_supersedes_unread_previous_handoff(dossier_api):
    client,sessions = dossier_api
    payload = {"assigned_sales_id":12,"expected_owner_id":11,"reason":"Change responsible sales",
               "handoff_summary":"Please follow existing record","confirm_protected_transfer":True}
    response = await client.post("/api/v1/sales-leads/1/recovery/reassign",headers=auth(1),json=payload)
    assert response.status_code == 200,response.text
    data = await get_dossier(client,12)
    first_id = data["handoffs"][0]["id"]
    assert data["permissions"]["can_ack"] and not data["protection"]["can_contact"]
    assert data["handoffs"][0]["status"] == "pending"
    owner = await get_dossier(client,1)
    assert not owner["permissions"]["can_release_protection"]
    assert "交接" in owner["protection"]["reason"]
    async with sessions() as db:
        task = (await db.scalars(select(SalesDailyDialTasks).where(SalesDailyDialTasks.sales_employee_id==12,
            SalesDailyDialTasks.lead_id==1,SalesDailyDialTasks.status=="pending"))).first()
        assert task is not None
        task_id = task.id
        assert (await db.get(SalesCallActivities,101)).sales_employee_id == 11
    blocked = await client.post(f"/api/v1/sales-leads/workbench/tasks/{task_id}/dial-started",headers=auth(12),json={"phone":"+12125550111"})
    assert blocked.status_code == 409,blocked.text
    response = await client.post("/api/v1/sales-leads/1/recovery/reassign",headers=auth(1),json={
        **payload,"assigned_sales_id":13,"expected_owner_id":12,"handoff_summary":"New responsible person"})
    assert response.status_code == 200,response.text
    next_data = await get_dossier(client,13)
    assert next_data["handoffs"][0]["status"] == "pending"
    previous = next(item for item in next_data["handoffs"] if item["id"]==first_id)
    assert previous["status"] == "superseded" and previous["note"] == "Please follow existing record"
    assert (await client.post("/api/v1/sales-leads/1/recovery/reassign",headers=auth(1),json=payload)).status_code == 409


@pytest.mark.asyncio
async def test_delete_preserves_revoked_invitation_identity_but_allows_unused_lead(dossier_api):
    client,sessions = dossier_api
    # This lead has no other history/source; even a revoked grant must survive.
    await client.post(f"{API}/2/invites",headers=auth(1),json={"employee_id":13,"access":"view","expected_revision":0})
    assert (await client.delete(f"{API}/2/invites/13?expected_revision=1",headers=auth(1))).status_code == 200
    denied = await client.delete("/api/v1/sales-leads/2",headers=auth(1))
    assert denied.status_code == 409,denied.text
    assert (await client.delete("/api/v1/sales-leads/1",headers=auth(1))).status_code == 409
    async with sessions() as db:
        assert await db.get(SalesLeads,2) is not None
        db.add(SalesLeads(id=100,business_name="Unused",phone="+12125550999",country="US"))
        await db.commit()
    deleted = await client.delete("/api/v1/sales-leads/100",headers=auth(1))
    assert deleted.status_code == 200,deleted.text
    async with sessions() as db:
        assert await db.get(SalesLeads,100) is None
        assert len((await db.scalars(select(SalesDossierGrantAudit).where(SalesDossierGrantAudit.lead_id==2))).all()) == 2


@pytest.mark.asyncio
async def test_new_lead_id_skips_all_preexisting_orphans_without_reusing_invites_or_history(dossier_api):
    client,sessions = dossier_api
    async with sessions() as db:
        db.add(SalesDossierGrant(lead_id=40100,employee_id=13,access="view",status="revoked",revision=1,
            invited_by_id=1,invited_by_name="Boss"))
        await db.flush()
        assert await next_sales_lead_id(db) == 40101
        db.add(SalesCallActivities(lead_id=40200,sales_employee_id=11,sales_employee_name="Sales A",
            outcome="callback",notes="Orphaned historical contact",called_at=datetime.now(timezone.utc)))
        await db.flush()
        assert await next_sales_lead_id(db) == 40201
        customer = await db.get(Customers,80); customer.sales_lead_id = 40300
        await db.flush()
        assert await next_sales_lead_id(db) == 40301
        merchant = await db.get(MerchantPool,77); merchant.converted_lead_id = 40400
        await db.flush()
        assert await next_sales_lead_id(db) == 40401
        db.add(SalesPhoneSuppression(phone_key="+12125550444",blocked=True,reason="Historical suppression",source_lead_id=40500))
        await db.flush()
        assert await next_sales_lead_id(db) == 40501
        db.add(SalesContactProtectionAudit(phone_key="+12125550444",lead_id=40600,action="blocked",reason="Historical audit"))
        await db.commit()
    created = await client.post("/api/v1/sales-leads",headers=auth(1),json={
        "business_name":"Fresh merchant","phone":"+12125550777","country":"US"})
    assert created.status_code == 201,created.text
    new_id = created.json()["id"]
    assert new_id == 40601
    assert (await client.get(f"{API}/{new_id}",headers=auth(13))).status_code == 404
    data = await get_dossier(client,1,new_id)
    assert data["grants"] == [] and data["handoffs"] == [] and data["insight"]["timeline"] == []


@pytest.mark.asyncio
async def test_retained_sqlite_id_limit_fails_before_any_new_lead_write(dossier_api):
    client,sessions = dossier_api
    async with sessions() as db:
        db.add(SalesDossierGrant(lead_id=2**63-1,employee_id=13,access="view",status="revoked",revision=1,
            invited_by_id=1,invited_by_name="Boss"))
        await db.commit()
    failed = await client.post("/api/v1/sales-leads",headers=auth(1),json={
        "business_name":"MUST_NOT_CREATE","phone":"+12125550777","country":"US"})
    assert failed.status_code == 409,failed.text
    async with sessions() as db:
        assert (await db.scalars(select(SalesLeads.id).where(SalesLeads.business_name=="MUST_NOT_CREATE"))).first() is None


def test_additive_migration_only_adds_seven_sales_tables_and_keeps_existing_data():
    path = Path(__file__).parents[1]/"alembic"/"versions"/"f7d1c5a9b027_sales_unified_dossiers.py"
    spec = importlib.util.spec_from_file_location("dossier_migration",path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    assert module.down_revision == "e6c0b4f8a916"
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE finance_guard(id INTEGER PRIMARY KEY, amount NUMERIC, note TEXT)"))
        connection.execute(text("INSERT INTO finance_guard VALUES(1,12.34,'unchanged')"))
        connection.execute(text("CREATE TABLE sales_leads(id INTEGER PRIMARY KEY, name TEXT)"))
        connection.execute(text("INSERT INTO sales_leads VALUES(7,'unchanged lead')"))
        before = {name:[dict(row._mapping) for row in connection.execute(text("SELECT * FROM "+name))]
                  for name in ("finance_guard","sales_leads")}
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
        added = set(inspect(connection).get_table_names()) - set(before)
        assert added == {"sales_dossier_summaries","sales_dossier_summary_audits","sales_dossier_grants",
            "sales_dossier_grant_audits","sales_dossier_handoffs","sales_phone_suppressions","sales_contact_protection_audits"}
        for name,rows in before.items():
            assert [dict(row._mapping) for row in connection.execute(text("SELECT * FROM "+name))] == rows
        for name in added:
            assert not inspect(connection).get_foreign_keys(name)
        with pytest.raises(RuntimeError,match="Preserve"):
            module.downgrade()
