"""Sales acceptance with real password logins and enforced persistent sessions.

All databases/accounts are synthetic and isolated. No authentication dependency
or route handler is mocked. The private service uses a separate, read-only CRM
identity connection just as the deployed service does.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import secrets
import time
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.main import app
from core.database import Base, db_manager, get_db
from models.customers import Customers
from models.employee_auth_sessions import EmployeeAuthSession
from models.employees import Employees
from models.merchant_pool import MerchantPool
from models.payments import Payments
from models.private_workspace import PrivateItem, PrivateWorkspaceBase
from models.ringcentral_call_records import RingCentralCallRecords
from models.sales_call_activities import SalesCallActivities
from models.sales_daily_dial_tasks import SalesDailyDialTasks
from models.sales_dossiers import SalesDossierGrant
from models.sales_deal_controls import SalesHandoffChecklists, SalesQuoteRequests
from models.sales_leads import SalesLeads
from services.emp_auth import hash_password
from services.private_workspace import get_private_db
from services.private_workspace_app import create_private_workspace_app

DOSSIERS = "/api/v1/sales-lead-dossiers"
LEADS = "/api/v1/sales-leads"
CUSTOMERS = "/api/v1/entities/customers"
ALWAYS_PRIVATE = ("CUSTOMER_PRIVATE_SENTINEL", "PAYMENT_PRIVATE_SENTINEL", "OWNER_PRIVATE_SENTINEL")
MERCHANT_SENTINELS = {
    101: ("MERCHANT_A_ONLY", "+12125550111", "ACTIVITY_A_ONLY"),
    202: ("MERCHANT_B_ONLY", "+12125550222", "ACTIVITY_B_ONLY"),
    303: ("HIDDEN_EXTERNAL_MERCHANT", "+12125550333", "HIDDEN_EXTERNAL_ACTIVITY"),
}


@pytest.fixture(scope="module")
def acceptance_credential():
    password = secrets.token_urlsafe(24)
    return password, hash_password(password)


@dataclass
class SalesAcceptance:
    client: AsyncClient = field(repr=False)
    private_client: AsyncClient = field(repr=False)
    sessions: object = field(repr=False)
    private_sessions: object = field(repr=False)
    headers: dict = field(default_factory=dict, repr=False)
    evidence: list = field(default_factory=list, repr=False)
    private_reads: list = field(default_factory=list, repr=False)

    async def request(self, method, path, *, actor=12, expected=200, allowed=(202,), private=False, json_body=None):
        client = self.private_client if private else self.client
        response = await client.request(method, path, headers=self.headers[actor], json=json_body)
        self.evidence.append({"surface":"private" if private else "crm", "method":method,
                              "path":path, "status":response.status_code, "body":response.json()})
        expected_codes = expected if isinstance(expected,tuple) else (expected,)
        assert response.status_code in expected_codes, (method, path, response.status_code)
        # Check the complete body, including nested metadata, facets and history.
        for sentinel in ALWAYS_PRIVATE:
            assert sentinel not in response.text, (method, path, "private data leaked")
        for lead_id, sentinels in MERCHANT_SENTINELS.items():
            if lead_id not in allowed:
                for sentinel in sentinels:
                    assert sentinel not in response.text, (method, path, "unrelated merchant leaked")
        return response

    async def invite(self, access="view", revision=0):
        return await self.request("POST", f"{DOSSIERS}/101/invites", actor=1, allowed=(101,),
            json_body={"employee_id":12,"access":access,"expected_revision":revision})

    async def protected_snapshot(self):
        # All non-sales business rows are included, so customer permissions,
        # financial records and original pool evidence cannot silently change.
        payload = {}
        async with self.sessions() as db:
            for name, table in sorted(Base.metadata.tables.items()):
                if name == "employees" or name.startswith(("sales_", "employee_")):
                    continue
                rows = [dict(row) for row in (await db.execute(select(table))).mappings()]
                payload[name] = sorted((json.dumps(row,sort_keys=True,default=str) for row in rows))
        async with self.private_sessions() as db:
            for name, table in sorted(PrivateWorkspaceBase.metadata.tables.items()):
                rows = [dict(row) for row in (await db.execute(select(table))).mappings()]
                payload["private:"+name] = sorted(json.dumps(row,sort_keys=True,default=str) for row in rows)
        return hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()


@pytest_asyncio.fixture
async def strict_sales_accounts(monkeypatch, tmp_path, acceptance_credential):
    monkeypatch.setenv("ENFORCE_EMPLOYEE_STATUS", "true")
    monkeypatch.setenv("ENFORCE_EMPLOYEE_SESSIONS", "true")
    monkeypatch.setenv("PRIVATE_WORKSPACE_OWNER_IDS", "1")
    business_path = tmp_path/"business.sqlite"
    engine = create_async_engine("sqlite+aiosqlite:///"+str(business_path))
    private_engine = create_async_engine("sqlite+aiosqlite:///"+str(tmp_path/"private.sqlite"))
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with private_engine.begin() as connection:
        await connection.run_sync(PrivateWorkspaceBase.metadata.create_all)
    sessions = async_sessionmaker(engine,expire_on_commit=False)
    private_sessions = async_sessionmaker(private_engine,expire_on_commit=False)
    password, password_hash = acceptance_credential
    now = datetime.now(timezone.utc)
    today = now.astimezone(ZoneInfo("Asia/Shanghai")).date()
    async with sessions() as db:
        db.add_all([Employees(id=eid,user_id=f"acceptance-{eid}",name=name,role=role,status=status,
                             email=f"acceptance-{eid}@example.test",password=password_hash)
            for eid,name,role,status in [(1,"Synthetic Owner","super_admin","active"),
                (11,"Synthetic Sales A","sales","active"),(12,"Synthetic Sales B","sales","probation"),
                (13,"Unrelated Sales","sales","active")]])
        for lead_id,eid,pool_id in [(101,11,501),(202,12,502),(303,13,503)]:
            name,phone,note = MERCHANT_SENTINELS[lead_id]
            db.add(MerchantPool(id=pool_id,business_name=name,phone=phone,country="US",pool_status="converted",
                converted_lead_id=lead_id,raw_payload='{"private":"CUSTOMER_PRIVATE_SENTINEL"}'))
            db.add(SalesLeads(id=lead_id,business_name=name,phone=phone,country="US",state="NY",industry="美业",
                assigned_sales_id=eid,assigned_sales_name=f"Synthetic Sales {eid}",merchant_pool_id=pool_id,
                status="contacted",last_contact_at=now))
            db.add(SalesDailyDialTasks(id=lead_id*10+1,lead_id=lead_id,sales_employee_id=eid,task_date=today,status="pending"))
            db.add(SalesCallActivities(id=lead_id*10+2,lead_id=lead_id,sales_employee_id=eid,
                sales_employee_name=f"Synthetic Sales {eid}",outcome="callback",notes=note,called_at=now))
        # Even the recorded salesperson is not an owner invitation to this customer.
        db.add(Customers(id=880,business_name="CUSTOMER_PRIVATE_SENTINEL",contact_name="Private contact",
                         phone="+12125550880",sales_employee_id=12,private_notes="CUSTOMER_PRIVATE_SENTINEL"))
        db.add(Payments(id=990,customer_id=880,amount_due=5000,amount_paid=4000,net_amount=3990,
                        user_id="1",notes="PAYMENT_PRIVATE_SENTINEL"))
        await db.commit()
    async with private_sessions() as db:
        db.add(PrivateItem(id="private-acceptance-item",owner_id="1",source_id="gmail",external_id="test-item",
            kind="mail",title="OWNER_PRIVATE_SENTINEL",summary="OWNER_PRIVATE_SENTINEL",status="connected"))
        await db.commit()

    async def business_db():
        async with sessions() as db:
            yield db
    private_reads = []
    async def isolated_private_db():
        private_reads.append("opened")
        async with private_sessions() as db:
            yield db

    # The independent private app has no CRM route-allowlist middleware. Its own
    # live role/session/owner checks must deny these same employee tokens.
    private_app = create_private_workspace_app()
    reader_engine = create_async_engine(f"sqlite+aiosqlite:///file:{business_path}?mode=ro&uri=true")
    private_app.state.private_business_sessions = async_sessionmaker(reader_engine,expire_on_commit=False)
    private_app.dependency_overrides[get_private_db] = isolated_private_db
    app.dependency_overrides[get_db] = business_db
    app.dependency_overrides[get_private_db] = isolated_private_db
    monkeypatch.setattr(db_manager,"async_session_maker",sessions)
    try:
        async with AsyncClient(transport=ASGITransport(app=app),base_url="http://test") as client, \
                   AsyncClient(transport=ASGITransport(app=private_app),base_url="http://private.test") as private_client:
            acceptance = SalesAcceptance(client,private_client,sessions,private_sessions,private_reads=private_reads)
            # Password verification and session creation are the actual login route.
            for eid in (1,11,12):
                response = await client.post("/api/v1/emp-auth/login",
                    json={"email":f"acceptance-{eid}@example.test","password":password})
                assert response.status_code == 200
                result = response.json()
                assert result["employee"]["id"] == eid
                acceptance.headers[eid] = {"Authorization":"Bearer "+result["token"]}
            async with sessions() as db:
                assert len((await db.scalars(select(EmployeeAuthSession))).all()) == 3
            yield acceptance
            # Full non-login responses are available to inspect in the isolated
            # pytest temp directory; authentication credentials are never recorded.
            (tmp_path/"response-evidence.json").write_text(json.dumps(acceptance.evidence,ensure_ascii=False,indent=2))
    finally:
        app.dependency_overrides.pop(get_db,None)
        app.dependency_overrides.pop(get_private_db,None)
        await reader_engine.dispose()
        await private_engine.dispose()
        await engine.dispose()


async def profile_draft(data, **changes):
    profile = data["enrichment"]
    fields = ("business_name","industry","city","state","country","address","website","store_phone","contacts",
              "preferred_contact_id","interest_product_ids","need_summary","best_contact_time","verification")
    return {**{key:profile[key] for key in fields},"expected_revision":profile["revision"],
            "expected_lead_updated_at":profile["lead_updated_at"],"source":"manual",**changes}


@pytest.mark.asyncio
async def test_password_sessions_limit_lists_search_stats_and_idor_to_current_owner(strict_sales_accounts):
    a = strict_sales_accounts
    before = await a.protected_snapshot()
    me = await a.request("GET","/api/v1/emp-auth/me")
    assert me.json()["id"] == 12 and me.json()["status"] == "probation"
    listing = await a.request("GET",LEADS)
    assert [item["id"] for item in listing.json()["items"]] == [202]
    stats = await a.request("GET",LEADS+"/stats")
    assert stats.json()["total"] == 1
    insight = await a.request("GET","/api/v1/sales-intelligence/leads")
    assert [item["id"] for item in insight.json()["items"]] == [202]
    for search in ("MERCHANT_A_ONLY","HIDDEN_EXTERNAL_MERCHANT","+1 (212) 555-0333"):
        result = await a.request("GET",LEADS+"?search="+search)
        assert result.json()["total"] == 0
    filtered = await a.request("GET","/api/v1/sales-intelligence/leads?lead_ids=101&lead_ids=303&owner=11")
    assert filtered.json()["items"] == []
    for lead_id in (101,303,999999):
        for suffix in ("","/call-history","/enrichment","/enrichment/history"):
            await a.request("GET",f"{LEADS}/{lead_id}{suffix}",expected=404)
        await a.request("GET",f"{DOSSIERS}/{lead_id}",expected=404)
    await a.request("GET",f"{LEADS}/202")
    await a.request("GET",f"{DOSSIERS}/202")
    assert await a.protected_snapshot() == before


@pytest.mark.asyncio
async def test_view_invitation_is_discoverable_readonly_and_never_enters_dial_queue(strict_sales_accounts):
    a = strict_sales_accounts
    before = await a.protected_snapshot()
    await a.invite("view")
    data = (await a.request("GET",f"{DOSSIERS}/101",allowed=(101,202))).json()
    assert not data["permissions"]["can_edit"] and not data["protection"]["can_contact"]
    shared = await a.request("GET",DOSSIERS+"?shared_only=true",allowed=(101,202))
    assert [(row["id"],row["access"]) for row in shared.json()["items"]] == [(101,"view")]
    # Invitations are a separate discovery surface, never global legacy scope.
    listing = await a.request("GET",LEADS)
    assert [row["id"] for row in listing.json()["items"]] == [202]
    workbench = await a.request("GET",LEADS+"/workbench/today")
    assert [row["lead"]["id"] for row in workbench.json()["items"]] == [202]
    await a.request("GET",LEADS+"/workbench/today?sales_employee_id=11",expected=403)
    await a.request("PUT",f"{DOSSIERS}/101/summary",expected=403,
                    json_body={"expected_revision":0,"promises":"Denied write"})
    await a.request("PUT",f"{DOSSIERS}/101/enrichment",expected=403,json_body=await profile_draft(data))
    await a.request("POST",f"{DOSSIERS}/101/invites",expected=403,
                    json_body={"employee_id":11,"access":"collaborate"})
    assert await a.protected_snapshot() == before


@pytest.mark.asyncio
async def test_collaborator_edits_only_dossier_not_legacy_dial_reassign_or_financial_fields(strict_sales_accounts):
    a = strict_sales_accounts
    before = await a.protected_snapshot()
    await a.invite("collaborate")
    data = (await a.request("GET",f"{DOSSIERS}/101",allowed=(101,202))).json()
    assert data["permissions"]["can_edit"]
    for key in ("can_invite","can_transfer","can_edit_profile","can_review","can_release_protection"):
        assert not data["permissions"][key]
    await a.request("PUT",f"{DOSSIERS}/101/summary",allowed=(101,202),
        json_body={"expected_revision":0,"latest_conclusion":"Synthetic collaboration","promises":"Send business details"})
    await a.request("PUT",f"{DOSSIERS}/101/enrichment",allowed=(101,202),
        json_body=await profile_draft(data,need_summary="Synthetic merchant need"))
    updated = (await a.request("GET",f"{DOSSIERS}/101",allowed=(101,202))).json()
    assert updated["summary"]["need_summary"] == "Synthetic merchant need"
    assert updated["enrichment"]["updated_by_name"] == "Synthetic Sales B"
    assert {item["kind"] for item in updated["changes"]} == {"summary","enrichment"}
    for method,path,body,code in [
        ("GET",f"{LEADS}/101",None,404),
        ("GET",f"{LEADS}/101/enrichment/history",None,404),
        ("PUT",f"{LEADS}/101",{"business_name":"Denied name"},404),
        ("PUT","/api/v1/sales-intelligence/leads/101",{"revision":0,"pipeline_key":"system","stage_key":"needs","evidence":"Denied update"},404),
        ("POST",f"{LEADS}/workbench/tasks/1011/dial-started",{"phone":"+12125550111"},403),
        ("POST",f"{LEADS}/workbench/tasks/1011/result",{"outcome":"no_answer"},403),
        ("POST",f"{LEADS}/101/follow-up",{"outcome":"no_answer"},404),
        ("POST",f"{LEADS}/101/recovery/reassign",{"assigned_sales_id":12,"reason":"Denied transfer"},403),
        ("POST",f"{LEADS}/101/convert-to-customer",{"confirmation_notes":"Denied conversion"},403),
    ]:
        await a.request(method,path,expected=code,json_body=body)
    for forged in ({"assigned_sales_id":12},{"customer_id":880},{"amount_paid":0},{"commission_partner_id":1}):
        await a.request("PUT",f"{DOSSIERS}/101/summary",expected=422,
                        json_body={"expected_revision":1,**forged})
    workbench = await a.request("GET",LEADS+"/workbench/today")
    assert [row["lead"]["id"] for row in workbench.json()["items"]] == [202]
    async with a.sessions() as db:
        assert (await db.get(SalesLeads,101)).assigned_sales_id == 11
        assert (await db.get(SalesCallActivities,1012)).sales_employee_id == 11
        assert (await db.get(SalesDailyDialTasks,1011)).sales_employee_id == 11
    assert await a.protected_snapshot() == before


@pytest.mark.asyncio
async def test_revoking_invitation_removes_access_next_request_without_logout(strict_sales_accounts):
    a = strict_sales_accounts
    await a.invite("collaborate")
    old_draft = (await a.request("GET",f"{DOSSIERS}/101",allowed=(101,202))).json()
    await a.request("DELETE",f"{DOSSIERS}/101/invites/12?expected_revision=1",actor=1,allowed=(101,))
    await a.request("GET",f"{DOSSIERS}/101",expected=404)
    await a.request("PUT",f"{DOSSIERS}/101/summary",expected=404,
                    json_body={"expected_revision":0,"promises":"Stale browser write"})
    await a.request("PUT",f"{DOSSIERS}/101/enrichment",expected=404,json_body=await profile_draft(old_draft))
    shared = await a.request("GET",DOSSIERS)
    assert shared.json() == {"items":[],"total":0}
    await a.request("GET",f"{DOSSIERS}/202")
    await a.request("GET","/api/v1/emp-auth/me")


@pytest.mark.asyncio
async def test_global_entities_customer_finance_and_original_pool_do_not_follow_dossier_invite(strict_sales_accounts):
    a = strict_sales_accounts
    before = await a.protected_snapshot()
    await a.invite("collaborate")
    for path in ["/api/v1/entities/employees/directory","/api/v1/entities/operation_logs",
                 "/api/v1/entities/payments","/api/v1/entities/payments/990",
                 "/api/v1/entities/expenses","/api/v1/entities/company_expenses",
                 "/api/v1/commissions","/api/v1/finance-adjustments/refunds",
                 "/api/v1/merchant-pool","/api/v1/merchant-pool/stats",
                 "/api/v1/sales-intelligence/pool/503"]:
        await a.request("GET",path,expected=403)
    customers = await a.request("GET",CUSTOMERS)
    assert customers.json()["items"] == []
    for suffix in ("","/finance-access-data","/access","/private-note","/record-audits"):
        await a.request("GET",f"{CUSTOMERS}/880{suffix}",expected=404 if suffix in {"","/finance-access-data"} else 403)
    await a.request("PUT",f"{CUSTOMERS}/880/access",expected=403,json_body={"grants":[]})
    assert await a.protected_snapshot() == before


@pytest.mark.asyncio
async def test_crm_and_standalone_private_service_reject_real_sales_session_without_opening_private_db(strict_sales_accounts):
    a = strict_sales_accounts
    before = await a.protected_snapshot()
    await a.invite("collaborate")
    for path in ("/api/v1/private-workspace","/api/v1/private-workspace/items",
                 "/api/v1/private-workspace/preferences","/api/v1/private-workspace/personal-finance/state"):
        await a.request("GET",path,expected=403)
        await a.request("GET",path,expected=403,private=True)
    access = await a.request("GET","/api/v1/private-workspace/access",private=True)
    assert access.json() == {"allowed":False}
    assert a.private_reads == []
    assert await a.protected_snapshot() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("change",["deactivated","session_revoked","password_changed","expired_session"])
async def test_status_and_session_changes_invalidate_existing_password_login_on_next_request(strict_sales_accounts,change):
    a = strict_sales_accounts
    await a.invite("collaborate")
    await a.request("GET",f"{DOSSIERS}/101",allowed=(101,202))
    async with a.sessions() as db:
        if change == "deactivated":
            employee = await db.get(Employees,12); employee.status = "inactive"
        elif change == "password_changed":
            employee = await db.get(Employees,12); employee.password = hash_password(secrets.token_urlsafe(24))
        else:
            row = (await db.scalars(select(EmployeeAuthSession).where(EmployeeAuthSession.employee_id==12))).one()
            if change == "session_revoked":
                row.revoked_at = int(time.time())
            else:
                row.expires_at = int(time.time())-1
        await db.commit()
    for path in ("/api/v1/emp-auth/me",LEADS,f"{DOSSIERS}/101","/api/v1/entities/payments"):
        await a.request("GET",path,expected=401)
    await a.request("GET","/api/v1/private-workspace/items",expected=401,private=True)


@pytest.mark.asyncio
async def test_live_role_change_does_not_trust_old_owner_claim_or_keep_invitation_for_nonsales(strict_sales_accounts):
    a = strict_sales_accounts
    await a.invite("collaborate")
    async with a.sessions() as db:
        employee = await db.get(Employees,1); employee.role = "sales"
        invitee = await db.get(Employees,12); invitee.role = "ops"
        await db.commit()
    # Both tokens were issued by real password login before this role change.
    await a.request("GET","/api/v1/entities/payments",actor=1,expected=403)
    await a.request("POST",f"{DOSSIERS}/101/invites",actor=1,expected=404,
                    json_body={"employee_id":13,"access":"view"})
    await a.request("GET",f"{DOSSIERS}/101",expected=403)
    await a.request("GET","/api/v1/private-workspace",actor=1,expected=403,private=True)


@pytest.mark.asyncio
async def test_handoff_employee_options_expose_only_minimal_selector_fields(strict_sales_accounts):
    a = strict_sales_accounts
    response = await a.request("GET","/api/v1/sales-deal-controls/options")
    # This existing selector intentionally lists active handoff staff. It is
    # not a general directory or an invitation to their merchant/customer data.
    assert response.json()["employees"]
    for row in response.json()["employees"]:
        assert set(row) == {"id","name","role","department","position"}
    for field_name in ("password","email","phone","salary","bank_account","credential_fingerprint"):
        assert field_name not in response.text


@pytest.mark.asyncio
async def test_former_owner_cannot_read_ringcentral_task_status_after_real_reassignment(strict_sales_accounts):
    a = strict_sales_accounts
    async with a.sessions() as db:
        db.add(RingCentralCallRecords(id=994,provider_key="acceptance-call",sales_employee_id=12,
            sales_employee_name="Synthetic Sales B",lead_id=202,task_id=2021,
            provider_status="CallConnected",provider_result="MERCHANT_B_ONLY",connected=True,
            duration_seconds=73,started_at=datetime.now(timezone.utc),sync_status="verified"))
        await db.commit()
    before = await a.protected_snapshot()
    await a.request("GET","/api/ringcentral/calls/recent?task_id=2021")
    await a.request("POST",f"{LEADS}/202/recovery/reassign",actor=1,allowed=(202,),json_body={
        "assigned_sales_id":11,"expected_owner_id":12,"confirm_protected_transfer":True,
        "reason":"Synthetic reassignment","handoff_summary":"Read the existing history"})
    await a.request("GET",f"{LEADS}/202",expected=404,allowed=())
    await a.request("GET",f"{DOSSIERS}/202",expected=404,allowed=())
    await a.request("GET","/api/ringcentral/calls/recent?task_id=2021",expected=(403,404),allowed=())
    assert await a.protected_snapshot() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("converted",[False,True])
@pytest.mark.parametrize(("current_quote","quote_id"),[(700,701),(700,None),(None,701)])
async def test_ordinary_sales_cannot_reset_confirmed_payment_by_changing_handoff_quote(strict_sales_accounts,converted,current_quote,quote_id):
    a = strict_sales_accounts
    async with a.sessions() as db:
        for quote_id in (700,701):
            db.add(SalesQuoteRequests(id=quote_id,lead_id=202,package_name="Synthetic quote",status="approved",
                final_amount=500,list_amount=500,submitted_by_id=12,reviewed_by_id=1))
        db.add(SalesHandoffChecklists(id=800,lead_id=202,quote_id=current_quote,
            customer_goal="Original goal",finance_payment_confirmed=True,payment_status="paid",amount_received=500,
            payment_reference="Synthetic confirmed payment",payment_confirmed_by_id=1,
            payment_confirmed_by_name="Synthetic Owner",payment_confirmed_at=datetime.now(timezone.utc)))
        if converted:
            lead = await db.get(SalesLeads,202)
            lead.converted_customer_id = 880
            lead.converted_at = datetime.now(timezone.utc)
            lead.status = "won"
        await db.commit()
    async def payment_state():
        async with a.sessions() as db:
            row = await db.get(SalesHandoffChecklists,800)
            return (row.quote_id,row.finance_payment_confirmed,row.payment_status,row.amount_received,
                    row.payment_reference,row.payment_confirmed_by_id,row.customer_goal)
    before = await payment_state()
    response = await a.client.put("/api/v1/sales-deal-controls/202/handoff",headers=a.headers[12],
        json={"quote_id":quote_id,"customer_goal":"Ordinary sales attempted reset"})
    a.evidence.append({"surface":"crm","method":"PUT","path":"/api/v1/sales-deal-controls/202/handoff",
                       "status":response.status_code,"body":response.json()})
    after = await payment_state()
    assert response.status_code == 409 and after == before, (response.status_code,before,after)


@pytest.mark.asyncio
async def test_ordinary_sales_can_update_same_quote_delivery_brief_without_changing_payment_evidence(strict_sales_accounts):
    a = strict_sales_accounts
    async with a.sessions() as db:
        db.add(SalesQuoteRequests(id=700,lead_id=202,package_name="Synthetic quote",status="approved",
            final_amount=500,list_amount=500,submitted_by_id=12,reviewed_by_id=1))
        db.add(SalesHandoffChecklists(id=800,lead_id=202,quote_id=700,
            customer_goal="Original goal",finance_payment_confirmed=True,payment_status="paid",amount_received=500,
            payment_reference="Synthetic confirmed payment",payment_date="2026-10-16",payment_confirmed_by_id=1,
            payment_confirmed_by_name="Synthetic Owner",payment_confirmed_at=datetime.now(timezone.utc)))
        await db.commit()
    async def evidence():
        async with a.sessions() as db:
            row = await db.get(SalesHandoffChecklists,800)
            return (row.quote_id,row.finance_payment_confirmed,row.payment_status,row.amount_received,
                row.payment_reference,row.payment_date,row.payment_confirmed_by_id,row.payment_confirmed_by_name,row.payment_confirmed_at)
    before, protected = await evidence(), await a.protected_snapshot()
    await a.request("PUT","/api/v1/sales-deal-controls/202/handoff",
                    json_body={"quote_id":700,"customer_goal":"Updated delivery brief"})
    assert await evidence() == before
    async with a.sessions() as db:
        assert (await db.get(SalesHandoffChecklists,800)).customer_goal == "Updated delivery brief"
    assert await a.protected_snapshot() == protected


@pytest.mark.asyncio
async def test_ordinary_sales_can_change_unconfirmed_preconversion_quote_preserving_existing_workflow(strict_sales_accounts):
    a = strict_sales_accounts
    async with a.sessions() as db:
        for quote_id in (700,701):
            db.add(SalesQuoteRequests(id=quote_id,lead_id=202,package_name="Synthetic quote",status="approved",
                final_amount=500,list_amount=500,submitted_by_id=12,reviewed_by_id=1))
        db.add(SalesHandoffChecklists(id=800,lead_id=202,quote_id=700,customer_goal="Original goal",
            finance_payment_confirmed=False,payment_status="pending",amount_received=0))
        await db.commit()
    before = await a.protected_snapshot()
    saved = await a.request("PUT","/api/v1/sales-deal-controls/202/handoff",
        json_body={"quote_id":701,"customer_goal":"Updated proposal"})
    assert saved.json()["quote_id"] == 701
    assert saved.json()["payment_status"] == "pending" and saved.json()["amount_received"] == 0
    async with a.sessions() as db:
        assert not (await db.get(SalesHandoffChecklists,800)).finance_payment_confirmed
        assert (await db.get(SalesLeads,202)).converted_customer_id is None
    assert await a.protected_snapshot() == before
