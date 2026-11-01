"""Actual owner async onboarding with isolated SQLite and zero provider writes."""
import asyncio
import copy
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4
import pytest
import pytest_asyncio
from sqlalchemy import select,func,text
from models.customers import Customers
from models.employees import Employees
from models.google_business_onboarding import GoogleOnboardingCatalog as Catalog,GoogleOnboardingBatch as Batch,GoogleOnboardingItem as Item,GoogleOnboardingRequest as Request
from services import google_business_onboarding as service
from services import google_business_provider as provider
from test_google_business import gbp_env,OWNER,OPS,SECOND_OWNER,PREFIX

P=PREFIX+"/onboarding"
LOC="accounts/100/locations/3000"
LOC2="accounts/100/locations/4000"


@pytest_asyncio.fixture
async def env(gbp_env,monkeypatch):
    e=gbp_env
    from routers.google_business_onboarding import router
    e.client._transport.app.include_router(router)
    monkeypatch.setenv("T24_GBP_ONBOARDING_WORKER_ENABLED","true")
    e.fake.location_items += [{"location_name":LOC,"title":"Azuma Sushi Bistro","address":"2452 US-9 Unit 109, Malta, NY 12020"},
        {"location_name":LOC2,"title":"Ocean Buffet","address":"123 Test Road, Allentown, PA 18000"}]
    async with e.sessions() as db:
        db.add_all([Customers(id=30,business_name="Azuma Sushi Bistro",contact_name="Private contact",phone="PRIVATEPHONE",email="SECRET@EXAMPLE.TEST",private_notes="SECRET PRIVATE",status="closed",city="Malta",state="NY",country="US",address="2452 US-9 #109, Malta, NY 12020"),
            Customers(id=40,business_name="Ocean Buffet",contact_name="Hidden",phone="SECRET",status="closed",city="Allentown",state="CA",country="US",address="123 Test Rd, Allentown, PA 18000"),
            Customers(id=50,business_name="Stopped Merchant",contact_name="Hidden",phone="SECRET",status="lost")])
        await db.execute(text("CREATE TABLE IF NOT EXISTS private_space_canary(id INTEGER PRIMARY KEY,content TEXT)"));await db.execute(text("INSERT INTO private_space_canary VALUES(1,'PRIVATE_UNCHANGED')"))
        await db.execute(text("CREATE TABLE IF NOT EXISTS monthly_logic_canary(id INTEGER PRIMARY KEY,closing TEXT,commission TEXT)"));await db.execute(text("INSERT INTO monthly_logic_canary VALUES(1,'CLOSED_UNCHANGED','OWNER_UNCHANGED')"));await db.commit()
    return e


async def protected(e):
    async with e.sessions() as db:return {n:[tuple(x) for x in (await db.execute(text('SELECT * FROM "'+n+'" ORDER BY 1'))).all()] for n in ("customers","employees","customer_access_grants","google_business_grants","customer_materials","financial_canary","private_space_canary","monthly_logic_canary")}


async def discover(e,customer_id=None):
    body={"request_id":str(uuid4()),"connection_id":1,**({"customer_id":customer_id} if customer_id else {})}
    r=await e.client.post(P+"/catalogs",json=body);assert r.status_code==202,r.text
    identity=r.json()["catalog"]["id"]
    assert await service.run_tick(sessions=e.sessions)=={"stage":"catalog_ready"}
    r=await e.client.get(P+"/catalogs/"+identity);assert r.status_code==200,r.text
    return r.json(),body


async def preview(e,customer_id=30,location=LOC):
    cat,_=await discover(e)
    body={"request_id":str(uuid4()),"catalog_id":cat["catalog"]["id"],"expected_catalog_revision":cat["catalog"]["revision"],"items":[{"customer_id":customer_id,"location_name":location}]}
    r=await e.client.post(P+"/previews",json=body);assert r.status_code==201,r.text
    return r.json(),body


async def confirmed(e):
    plan,body=await preview(e)
    request={"request_id":str(uuid4()),"expected_revision":plan["batch"]["revision"],"preview_hash":plan["batch"]["preview_hash"],"confirmed_item_ids":[x["id"] for x in plan["items"]],"confirmed":True}
    r=await e.client.post(P+"/batches/"+plan["batch"]["id"]+"/confirm",json=request);assert r.status_code==202,r.text
    return r.json(),request


@pytest.mark.asyncio
async def test_discovery_immediate_durable_owner_scoped_and_identity_suggestions(env):
    before=await protected(env)
    body={"request_id":str(uuid4()),"connection_id":1}
    r=await env.client.post(P+"/catalogs",json=body);assert r.status_code==202 and not env.fake.reads
    again=await env.client.post(P+"/catalogs",json=body);assert again.json()["catalog"]["id"]==r.json()["catalog"]["id"]
    conflict=await env.client.post(P+"/catalogs",json={**body,"customer_id":30});assert conflict.status_code==409
    await service.run_tick(sessions=env.sessions)
    result=(await env.client.get(P+"/requests/"+body["request_id"])).json()
    assert result["catalog"]["catalog"]["status"]=="ready" and result["batch"] is None
    rows={x["customer"]["id"]:x for x in result["catalog"]["comparisons"]}
    assert rows[10]["match_state"]=="already_bound" and rows[30]["match_state"]=="eligible"
    assert rows[40]["match_state"]=="review_needed" and any("州" in x for x in rows[40]["reasons"])
    assert rows[50]["match_state"]=="inactive"
    assert all(x not in str(result) for x in ("SECRET PRIVATE","PRIVATEPHONE","SECRET@EXAMPLE.TEST","token_encrypted","password"))
    env.user=SECOND_OWNER
    assert (await env.client.get(P+"/catalogs/"+r.json()["catalog"]["id"])).status_code==404
    assert (await env.client.get(P+"/requests/"+body["request_id"])).status_code==404
    assert not env.fake.writes and await protected(env)==before


@pytest.mark.asyncio
async def test_employee_denied_before_any_database_access(env):
    from core.database import get_db
    class NoDb:
        def __getattr__(self,name):raise AssertionError("employee must not reach SQL")
    async def db():yield NoDb()
    env.client._transport.app.dependency_overrides[get_db]=db;env.user=OPS
    for method,path,body in [("GET","/context",None),("GET","/catalogs/"+"a"*32,None),("GET","/batches/"+"a"*32,None),("GET","/requests/"+str(uuid4()),None),("POST","/catalogs",{"request_id":str(uuid4()),"connection_id":1})]:
        r=await env.client.request(method,P+path,**({"json":body} if body else {}));assert r.status_code==403


@pytest.mark.asyncio
async def test_frozen_preview_then_confirm_real_worker_atomic_binding_and_no_other_changes(env):
    before=await protected(env);plan,body=await preview(env)
    async with env.sessions() as db:assert await db.scalar(select(func.count()).select_from(env.Binding))==2
    request={"request_id":str(uuid4()),"expected_revision":1,"preview_hash":plan["batch"]["preview_hash"],"confirmed_item_ids":[plan["items"][0]["id"]],"confirmed":True}
    path=P+"/batches/"+plan["batch"]["id"]+"/confirm"
    assert (await env.client.post(path,json=request)).status_code==202
    assert (await env.client.post(path,json=request)).status_code==202
    assert await service.run_tick(sessions=env.sessions)=={"stage":"item_processed"}
    result=(await env.client.get(P+"/batches/"+plan["batch"]["id"])).json()
    assert result["batch"]["status"]=="completed" and result["batch"]["counts"]["bound"]==1
    assert result["items"][0]["google"]["title"]=="Azuma Sushi Bistro"
    assert (await env.client.get(P+"/requests/"+request["request_id"])).json()["batch"]["batch"]["status"]=="completed"
    async with env.sessions() as db:
        b=await db.scalar(select(env.Binding).where(env.Binding.customer_id==30));assert b.location_name==LOC and b.title=="Azuma Sushi Bistro" and b.address=="" and b.primary_operator_id is None
        assert await db.scalar(select(func.count()).select_from(env.Action).where(env.Action.kind=="binding_created"))==1
    ctx=(await env.client.get(P+"/context")).json();evidence=next(x for x in ctx["bindings"] if x["customer_id"]==30)
    assert evidence["google_identity"]["address"]==env.fake.location_items[1]["address"]
    assert await protected(env)==before and not env.fake.writes


@pytest.mark.asyncio
@pytest.mark.parametrize("change",["crm","connection","role","duplicate","google","lease"])
async def test_final_live_fence_blocks_changed_identity_revocation_duplicate_and_late_lease(env,change):
    plan,_=await confirmed(env);env.fake.read_started=asyncio.Event();env.fake.release_read=asyncio.Event()
    task=asyncio.create_task(service.run_tick(sessions=env.sessions));await asyncio.wait_for(env.fake.read_started.wait(),2)
    async with env.sessions() as db:
        if change=="crm":(await db.get(Customers,30)).address="DIFFERENT STREET"
        elif change=="connection":(await db.get(env.Connection,1)).active=False
        elif change=="role":(await db.get(Employees,1)).role="admin"
        elif change=="duplicate":db.add(env.Binding(customer_id=40,customer_name="Ocean Buffet",connection_id=1,location_name=LOC,location_id="3000",title="Existing",address="",active=True,revision=1,created_by_id=1,request_id=str(uuid4())))
        elif change=="lease":(await db.get(Item,plan["items"][0]["id"])).lease_at=service.g.now()-timedelta(seconds=121)
        await db.commit()
    if change=="google":env.fake.location_items[1]["address"]="CHANGED GOOGLE ADDRESS"
    env.fake.release_read.set();await task
    async with env.sessions() as db:
        item=await db.get(Item,plan["items"][0]["id"]);assert item.status=="conflict"
        assert await db.scalar(select(env.Binding.id).where(env.Binding.customer_id==30)) is None
    assert not env.fake.writes


@pytest.mark.asyncio
async def test_cancel_between_claim_and_commit_fences_provider_result_and_receipt_is_current(env):
    plan,confirm_request=await confirmed(env);identity=plan["batch"]["id"]
    env.fake.read_started=asyncio.Event();env.fake.release_read=asyncio.Event()
    task=asyncio.create_task(service.run_tick(sessions=env.sessions));await asyncio.wait_for(env.fake.read_started.wait(),2)
    fresh=(await env.client.get(P+"/batches/"+identity)).json()
    body={"request_id":str(uuid4()),"expected_revision":fresh["batch"]["revision"],"reason":"Owner stopped this batch","confirmed":True}
    r=await env.client.post(P+"/batches/"+identity+"/cancel",json=body);assert r.status_code==200
    env.fake.release_read.set();await task
    result=(await env.client.get(P+"/requests/"+confirm_request["request_id"])).json()
    assert result["batch"]["batch"]["status"]=="cancelled" and result["batch"]["items"][0]["status"]=="cancelled"
    async with env.sessions() as db:assert await db.scalar(select(env.Binding.id).where(env.Binding.customer_id==30)) is None
    assert not env.fake.writes


@pytest.mark.asyncio
async def test_stale_catalog_preview_hash_and_customer_rejected_before_queue(env):
    plan,_=await preview(env);identity=plan["batch"]["id"]
    body={"request_id":str(uuid4()),"expected_revision":1,"preview_hash":"a"*64,"confirmed_item_ids":[plan["items"][0]["id"]],"confirmed":True}
    assert (await env.client.post(P+"/batches/"+identity+"/confirm",json=body)).status_code==409
    body.update(request_id=str(uuid4()),preview_hash=plan["batch"]["preview_hash"])
    async with env.sessions() as db:(await db.get(Customers,30)).status="paused";await db.commit()
    assert (await env.client.post(P+"/batches/"+identity+"/confirm",json=body)).status_code==409
    async with env.sessions() as db:assert (await db.get(Item,plan["items"][0]["id"])).status=="preview"
    assert not env.fake.writes


@pytest.mark.asyncio
async def test_no_new_batch_restore_inactive_or_cross_account_duplicate(env):
    async with env.sessions() as db:(await db.get(env.Binding,1)).active=False;await db.commit()
    cat,_=await discover(env)
    body={"request_id":str(uuid4()),"catalog_id":cat["catalog"]["id"],"expected_catalog_revision":cat["catalog"]["revision"],"items":[{"customer_id":10,"location_name":env.fake.location_items[0]["location_name"]}]}
    assert (await env.client.post(P+"/previews",json=body)).status_code==409
    alias="accounts/300/locations/1000"
    async with env.sessions() as db:
        c=await db.get(Catalog,cat["catalog"]["id"]);c.locations=[*c.locations,{"location_name":alias,"title":"Alias Merchant","address":"1 Test Street, CA 90000","observed_at":service.g.iso(service.g.now())}];await db.commit()
    body.update(request_id=str(uuid4()),items=[{"customer_id":30,"location_name":alias}])
    assert (await env.client.post(P+"/previews",json=body)).status_code==409
    async with env.sessions() as db:assert not (await db.get(env.Binding,1)).active


@pytest.mark.asyncio
async def test_truncated_and_missing_name_never_definitive_missing_or_eligible(env):
    cat,_=await discover(env)
    async with env.sessions() as db:
        row=await db.get(Catalog,cat["catalog"]["id"]);row.truncated=True;row.locations=[];await db.commit()
    result=(await env.client.get(P+"/catalogs/"+cat["catalog"]["id"])).json()
    assert all(x["match_state"]!="unmatched" for x in result["comparisons"])
    assert next(x for x in result["comparisons"] if x["customer"]["id"]==30)["match_state"]=="review_needed"


@pytest.mark.asyncio
async def test_legacy_response_fast_target_only_idempotent_and_recovery_receipt(env):
    before=await protected(env);body={"request_id":str(uuid4()),"customer_id":30,"connection_id":1,"location_name":LOC,"confirmed":True}
    r=await env.client.post(PREFIX+"/bindings",json=body);assert r.status_code==201,r.text
    assert env.fake.reads==[("verify_location",LOC)] and not env.fake.writes
    replay=await env.client.post(PREFIX+"/bindings",json=body);assert replay.status_code==201 and replay.json()==r.json()
    receipt=(await env.client.get(P+"/requests/"+body["request_id"])).json();assert receipt["request_receipt"]["kind"]=="legacy_bind" and receipt["batch"]["items"][0]["status"]=="bound"
    assert await protected(env)==before


@pytest.mark.asyncio
async def test_idle_worker_no_write_and_stale_claim_unknown_not_replayed(env):
    assert await service.run_tick(sessions=env.sessions)=={"stage":"idle"}
    cat,_=await discover(env)
    async with env.sessions() as db:
        row=await db.get(Catalog,cat["catalog"]["id"]);row.status="processing";row.lease_token=uuid4().hex;row.lease_at=service.g.now()-timedelta(seconds=121);await db.commit()
    before=len(env.fake.reads);assert await service.run_tick(sessions=env.sessions)=={"stage":"recovered"}
    result=(await env.client.get(P+"/catalogs/"+cat["catalog"]["id"])).json();assert result["catalog"]["status"]=="unknown" and len(env.fake.reads)==before


@pytest.mark.asyncio
async def test_provider_selected_account_pages_only_and_bounded_parallel_discovery():
    calls=[]
    class Target(provider.GoogleClient):
        async def request(self,method,api,path,**kw):
            calls.append((method,api,path,kw))
            return {"locations":[{"name":"locations/3000","title":"Target","storefrontAddress":{"addressLines":["1 Test"]}}]} if kw["params"].get("pageToken") else {"locations":[],"nextPageToken":"page2"}
    result=await Target().verify_location(LOC);assert result["location_name"]==LOC
    assert len(calls)==2 and all(x[:3]==("GET","locations","accounts/100/locations") for x in calls)
    active=0;maximum=0
    class Discovery(provider.GoogleClient):
        async def request(self,method,api,path,**kw):
            nonlocal active,maximum
            assert method=="GET"
            if api=="accounts":return {"accounts":[{"name":"accounts/"+str(x)} for x in range(8)]}
            active+=1;maximum=max(maximum,active)
            try:await asyncio.sleep(.01);return {"locations":[{"name":"locations/"+path.split('/')[1],"title":"Synthetic","storefrontAddress":{"addressLines":["1 Test"]}}]}
            finally:active-=1
    result=await Discovery().discover_locations();assert len(result["items"])==8 and 1<maximum<=3 and active==0


@pytest.mark.asyncio
async def test_provider_total_deadline_cancels_child_reads(monkeypatch):
    original=asyncio.wait_for;calls=[];active=0
    async def deadline(coro,timeout):calls.append(timeout);return await original(coro,.02)
    monkeypatch.setattr(provider.asyncio,"wait_for",deadline)
    class Slow(provider.GoogleClient):
        async def request(self,*a,**kw):
            nonlocal active
            active+=1
            try:await asyncio.sleep(10)
            finally:active-=1
    with pytest.raises(provider.ProviderError):await Slow().verify_location(LOC)
    with pytest.raises(provider.ProviderError):await Slow().discover_locations()
    assert calls==[12,90] and active==0


@pytest.mark.asyncio
async def test_two_batches_cannot_claim_same_customer_or_global_location(env):
    plan,_=await preview(env);other,_=await preview(env)
    def body(value):return {"request_id":str(uuid4()),"expected_revision":1,"preview_hash":value["batch"]["preview_hash"],"confirmed_item_ids":[x["id"] for x in value["items"]],"confirmed":True}
    a,b=await asyncio.gather(env.client.post(P+"/batches/"+plan["batch"]["id"]+"/confirm",json=body(plan)),env.client.post(P+"/batches/"+other["batch"]["id"]+"/confirm",json=body(other)))
    assert sorted([a.status_code,b.status_code])==[202,409]
    await service.run_tick(sessions=env.sessions)
    async with env.sessions() as db:assert await db.scalar(select(func.count()).select_from(env.Binding).where(env.Binding.customer_id==30))==1


@pytest.mark.asyncio
async def test_batch_success_and_conflict_independent_receipts_without_rollback_of_completed_row(env):
    cat,_=await discover(env)
    r=await env.client.post(P+"/previews",json={"request_id":str(uuid4()),"catalog_id":cat["catalog"]["id"],"expected_catalog_revision":cat["catalog"]["revision"],"items":[{"customer_id":30,"location_name":LOC},{"customer_id":40,"location_name":LOC2}]})
    assert r.status_code==201;plan=r.json()
    request={"request_id":str(uuid4()),"expected_revision":1,"preview_hash":plan["batch"]["preview_hash"],"confirmed_item_ids":[x["id"] for x in plan["items"]],"confirmed":True}
    assert (await env.client.post(P+"/batches/"+plan["batch"]["id"]+"/confirm",json=request)).status_code==202
    await service.run_tick(sessions=env.sessions)
    async with env.sessions() as db:(await db.get(Customers,40)).status="lost";await db.commit()
    await service.run_tick(sessions=env.sessions)
    result=(await env.client.get(P+"/batches/"+plan["batch"]["id"])).json()
    assert result["batch"]["status"]=="partial" and [x["status"] for x in result["items"]]==["bound","conflict"]
    async with env.sessions() as db:
        assert await db.scalar(select(env.Binding.id).where(env.Binding.customer_id==30)) is not None
        assert await db.scalar(select(env.Binding.id).where(env.Binding.customer_id==40)) is None
    assert not env.fake.writes


@pytest.mark.asyncio
async def test_native_audit_failure_rolls_back_binding_and_explicit_new_plan_can_retry(env,monkeypatch):
    plan,_=await confirmed(env);real=env.service._audit
    async def failure(*args,**kwargs):raise RuntimeError("synthetic after binding flush")
    monkeypatch.setattr(env.service,"_audit",failure);await service.run_tick(sessions=env.sessions)
    async with env.sessions() as db:
        assert await db.scalar(select(env.Binding.id).where(env.Binding.customer_id==30)) is None
        assert (await db.get(Item,plan["items"][0]["id"])).status=="failed"
        assert await db.scalar(select(func.count()).select_from(env.Action).where(env.Action.kind=="binding_created"))==0
    monkeypatch.setattr(env.service,"_audit",real)
    retry,_=await confirmed(env);await service.run_tick(sessions=env.sessions)
    async with env.sessions() as db:assert await db.scalar(select(func.count()).select_from(env.Binding).where(env.Binding.customer_id==30))==1
    assert (await env.client.get(P+"/batches/"+retry["batch"]["id"])).json()["batch"]["status"]=="completed"


@pytest.mark.asyncio
async def test_replay_payload_change_expiry_and_scope_rejected(env):
    cat,_=await discover(env,30)
    base={"request_id":str(uuid4()),"catalog_id":cat["catalog"]["id"],"expected_catalog_revision":cat["catalog"]["revision"],"items":[{"customer_id":40,"location_name":LOC2}]}
    assert (await env.client.post(P+"/previews",json=base)).status_code==422
    base.update(request_id=str(uuid4()),items=[{"customer_id":30,"location_name":LOC}])
    plan=(await env.client.post(P+"/previews",json=base)).json()
    assert (await env.client.post(P+"/previews",json={**base,"items":[{"customer_id":30,"location_name":LOC2}]})).status_code==409
    async with env.sessions() as db:(await db.get(Batch,plan["batch"]["id"])).expires_at=service.g.now()-timedelta(seconds=1);await db.commit()
    body={"request_id":str(uuid4()),"expected_revision":1,"preview_hash":plan["batch"]["preview_hash"],"confirmed_item_ids":[plan["items"][0]["id"]],"confirmed":True}
    assert (await env.client.post(P+"/batches/"+plan["batch"]["id"]+"/confirm",json=body)).status_code==409
    async with env.sessions() as db:(await db.get(Catalog,cat["catalog"]["id"])).expires_at=service.g.now()-timedelta(seconds=1);await db.commit()
    expired=(await env.client.get(P+"/catalogs/"+cat["catalog"]["id"])).json();assert expired["catalog"]["status"]=="expired" and expired["locations"]==[]


@pytest.mark.asyncio
async def test_idle_tick_never_acquires_sqlite_writer_and_flag_off_startup(env,monkeypatch):
    from sqlalchemy import event
    seen=[]
    def observe(conn,cursor,statement,parameters,context,many):seen.append(statement.strip().upper())
    event.listen(env.engine.sync_engine,"before_cursor_execute",observe)
    try:assert await service.run_tick(sessions=env.sessions)=={"stage":"idle"}
    finally:event.remove(env.engine.sync_engine,"before_cursor_execute",observe)
    assert not any(x.startswith(("INSERT","UPDATE","DELETE","BEGIN IMMEDIATE","CREATE","ALTER")) for x in seen)
    monkeypatch.setenv("T24_GBP_ONBOARDING_WORKER_ENABLED","false");assert await service.start_worker() is None
    r=await env.client.post(P+"/catalogs",json={"request_id":str(uuid4()),"connection_id":1});assert r.status_code==503


@pytest.mark.asyncio
async def test_actual_legacy_interruption_has_unknown_receipt_and_never_auto_replays(env):
    env.fake.read_started=asyncio.Event();env.fake.release_read=asyncio.Event()
    body={"request_id":str(uuid4()),"customer_id":30,"connection_id":1,"location_name":LOC,"confirmed":True}
    task=asyncio.create_task(env.client.post(PREFIX+"/bindings",json=body));await asyncio.wait_for(env.fake.read_started.wait(),2);task.cancel()
    with pytest.raises(asyncio.CancelledError):await task
    result=(await env.client.get(P+"/requests/"+body["request_id"])).json();assert result["batch"]["items"][0]["status"]=="processing"
    async with env.sessions() as db:(await db.get(Item,result["batch"]["items"][0]["id"])).lease_at=service.g.now()-timedelta(seconds=121);await db.commit()
    before=len(env.fake.reads);await service.run_tick(sessions=env.sessions)
    result=(await env.client.get(P+"/requests/"+body["request_id"])).json();assert result["batch"]["items"][0]["status"]=="unknown" and len(env.fake.reads)==before
    assert (await env.client.post(PREFIX+"/bindings",json=body)).status_code==409
    async with env.sessions() as db:assert await db.scalar(select(env.Binding.id).where(env.Binding.customer_id==30)) is None


@pytest.mark.asyncio
async def test_provider_catalog_cap_cancelled_children_and_missing_names_are_preserved():
    class Many(provider.GoogleClient):
        async def request(self,method,api,path,**kw):
            assert method=="GET"
            if api=="accounts":return {"accounts":[{"name":"accounts/"+str(x)} for x in range(8)]}
            account=path.split('/')[1]
            return {"locations":[{"name":"locations/"+account+str(x).zfill(3),"title":"" if x==0 else "Synthetic","storefrontAddress":{"addressLines":["1 Test"]}} for x in range(100)]}
    result=await Many().discover_locations();assert len(result["items"])==500 and result["truncated"] is True
    assert any(x["title"]=="" for x in result["items"])


def test_address_tokens_units_city_state_and_postal_are_not_substring_matches():
    n=service.address_norm
    assert n("1 23 Main Street, Albany, NY 12020")!=n("12 3 Main St, Albany, NY 12020")
    assert n("123 Main St #1 04, Albany, NY 12020")!=n("123 Main St #104, Albany, NY 12020")
    assert n("2452 U.S. 9 #109, Malta, New York, 12020-1954")==n("2452 US-9 Unit 109, Malta, NY 12020")
    crm={"name":"Shop","address":"123 Main Street, Newcastle, NY 12020","city":"Newcastle","state":"CA"}
    google={"title":"Shop","address":"123 Main Street, Newcastle, NY, 12020"}
    warnings=service.identity_warnings(crm,google);assert any("州" in x for x in warnings)
    crm.update(address="123 NY Street, Albany, CA 90000",city="Albany",state="NY")
    warnings=service.identity_warnings(crm,{"title":"Shop","address":"123 NY Street, Albany, CA, 90000"});assert any("州" in x for x in warnings)
    crm.update(address="123 Main St, Malta, NY 12020",city="New York City",state="NY")
    assert any("城市" in x for x in service.identity_warnings(crm,{"title":"Shop","address":crm["address"]}))
    assert any("组件不完整" in x for x in service.identity_warnings({**crm,"city":"Malta"},{"title":"Shop","address":"123 Main St, Malta, NY"}))


@pytest.mark.asyncio
async def test_original_binding_gets_live_comparison_evidence_without_backfill_or_alias_retarget(env):
    async with env.sessions() as db:before=[tuple(x) for x in (await db.execute(text("SELECT * FROM google_business_bindings ORDER BY id"))).all()]
    cat,_=await discover(env);comparison=next(x for x in cat["comparisons"] if x["customer"]["id"]==10)
    assert comparison["match_state"]=="already_bound" and comparison["candidates"][0]["title"]==env.fake.location_items[0]["title"]
    assert any("名称存在差异" in x for x in comparison["reasons"]) and any("组件不完整" in x for x in comparison["reasons"])
    assert comparison["existing_binding"]["google_identity"]["observed_at"]==cat["catalog"]["observed_at"]
    async with env.sessions() as db:
        assert [tuple(x) for x in (await db.execute(text("SELECT * FROM google_business_bindings ORDER BY id"))).all()]==before
        row=await db.get(Catalog,cat["catalog"]["id"]);row.locations=[{**x,"location_name":x["location_name"].replace("accounts/100/","accounts/300/")} for x in row.locations];await db.commit()
    result=(await env.client.get(P+"/catalogs/"+cat["catalog"]["id"])).json();comparison=next(x for x in result["comparisons"] if x["customer"]["id"]==10)
    assert comparison["candidates"]==[] and comparison["existing_binding"]["google_identity"] is None and any("尚未发现" in x for x in comparison["reasons"])


@pytest.mark.asyncio
async def test_request_uuid_cannot_cross_binding_discovery_or_internal_item_namespaces(env):
    body={"request_id":str(uuid4()),"customer_id":30,"connection_id":1,"location_name":LOC,"confirmed":True}
    r=await env.client.post(PREFIX+"/bindings",json=body);assert r.status_code==201
    assert (await env.client.post(P+"/catalogs",json={"request_id":body["request_id"],"connection_id":1})).status_code==409
    async with env.sessions() as db:
        rec=await db.scalar(select(Request).where(Request.request_id==body["request_id"]));rec.kind="discovery";await db.commit()
    assert (await env.client.post(PREFIX+"/bindings",json=body)).status_code==409


@pytest.mark.asyncio
async def test_confirm_detects_mutated_frozen_item_even_if_customer_is_current(env):
    plan,_=await preview(env)
    async with env.sessions() as db:
        item=await db.get(Item,plan["items"][0]["id"]);item.snapshot={**item.snapshot,"google":{**item.snapshot["google"],"title":"ALTERED"}};await db.commit()
    body={"request_id":str(uuid4()),"expected_revision":1,"preview_hash":plan["batch"]["preview_hash"],"confirmed_item_ids":[plan["items"][0]["id"]],"confirmed":True}
    assert (await env.client.post(P+"/batches/"+plan["batch"]["id"]+"/confirm",json=body)).status_code==409


@pytest.mark.asyncio
async def test_missing_google_identity_and_nonboolean_confirmation_never_queue(env):
    plan,_=await preview(env)
    body={"request_id":str(uuid4()),"expected_revision":1,"preview_hash":plan["batch"]["preview_hash"],"confirmed_item_ids":[plan["items"][0]["id"]],"confirmed":1}
    assert (await env.client.post(P+"/batches/"+plan["batch"]["id"]+"/confirm",json=body)).status_code==422
    cat,_=await discover(env)
    async with env.sessions() as db:
        row=await db.get(Catalog,cat["catalog"]["id"]);row.locations=[{**x,"title":""} for x in row.locations];await db.commit()
    request={"request_id":str(uuid4()),"catalog_id":cat["catalog"]["id"],"expected_catalog_revision":cat["catalog"]["revision"],"items":[{"customer_id":30,"location_name":LOC}]}
    assert (await env.client.post(P+"/previews",json=request)).status_code==422


@pytest.mark.parametrize("row",[{"name":"bad-resource","title":"Shop"},{"name":"locations/1","title":"X"*256},{"name":"locations/1","title":"Shop","storefrontAddress":{"addressLines":[{"not":"text"}]}}])
def test_malformed_google_location_never_becomes_a_complete_empty_inventory(row):
    with pytest.raises(provider.ProviderError):provider.GoogleClient._location_rows("accounts/100",{"locations":[row]})


@pytest.mark.asyncio
async def test_only_minimal_google_identity_is_persisted_even_if_provider_double_has_extra_fields(env):
    env.fake.location_items[1]={**env.fake.location_items[1],"UNEXPECTED_TOKEN":"MUST_NOT_PERSIST"}
    body={"request_id":str(uuid4()),"customer_id":30,"connection_id":1,"location_name":LOC,"confirmed":True}
    assert (await env.client.post(PREFIX+"/bindings",json=body)).status_code==201
    async with env.sessions() as db:
        item=await db.scalar(select(Item).where(Item.request_id==body["request_id"]))
        assert set(item.snapshot["google"])=={"location_name","title","address","observed_at"} and "MUST_NOT_PERSIST" not in str(item.snapshot)
