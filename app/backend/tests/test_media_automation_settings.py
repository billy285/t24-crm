"""Synthetic unified planning defaults: no provider, permission or public writes."""
import asyncio
import copy
import importlib.util
from datetime import datetime,timedelta,timezone
from pathlib import Path
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
import httpx
import pytest
import pytest_asyncio
from sqlalchemy import create_engine,func,inspect,select,text
from core.database import get_db
from dependencies.auth import get_current_user
from models.customers import Customers
from models.employees import Employees
from models.media_monthly import MediaMonthlyRun as Run,MediaMonthlyProfile as Profile
from models.media_monthly_automation import MediaMonthlyAutomationPolicy as Policy
from models.media_monthly_workflow import MediaMonthlyWorkflow as Workflow
from models.media_automation_settings import MediaAutomationSettingVersion as Version,MediaAutomationTemplateVersion as Template,MediaAutomationSettingsPreview as Preview,MediaAutomationSettingsReceipt as Receipt
from routers.media_automation_settings import router
from services import media_automation_settings as service,media_monthly as monthly_service
from test_google_business import gbp_env,OWNER,OPS,SECOND_OWNER,actors
from test_media_monthly import monthly,configured,generated,generate_body
from test_media_monthly_workflow import pipeline,scheduled,reviewed,enable_delivery,view

PREFIX="/api/v1/media-automation-settings"
AT=datetime(2026,11,1,tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def settings_env(monthly,monkeypatch):
    env=monthly;env.clock=AT
    monkeypatch.setattr(monthly_service,"now",lambda:env.clock)
    await configured(env)
    async with env.sessions() as db:
        db.add_all([Customers(id=30,business_name="Target30",contact_name="Synthetic",phone="30",status="closed",industry="beauty"),Customers(id=40,business_name="Target40",contact_name="Synthetic",phone="40",status="closed")])
        await db.commit()
    env.monthly_client._transport.app.include_router(router)
    yield env


async def get(env,customer=20,month="2026-11"):
    response=await env.monthly_client.get(PREFIX+f"/customers/{customer}",params={"month":month})
    assert response.status_code==200,response.text
    return response.json()


async def body(env,customer=20,**updates):
    value=await get(env,customer)
    document=copy.deepcopy(value["document"])
    document["platform_overrides"]={}
    document["defaults"]["weekdays"]=[1,3]
    return {"request_id":str(uuid4()),"kind":"edit","month":"2026-11","customer_id":customer,"expected_revision":value["revision"],"document":document,"target_ids":[],"platforms":[],"groups":[],**updates}


async def preview(env,value=None):
    value=value or await body(env)
    response=await env.monthly_client.post(PREFIX+"/previews",json=value)
    assert response.status_code==200,response.text
    return response.json(),value


async def apply(env,value,**updates):
    request={"request_id":str(uuid4()),"preview_hash":value["preview_hash"],"confirmed":True,**updates}
    response=await env.monthly_client.post(PREFIX+f"/previews/{value['id']}/apply",json=request)
    return response,request


@pytest.mark.asyncio
async def test_owner_only_all_settings_routes_and_cross_owner_receipts(settings_env):
    env=settings_env;value,request=await preview(env);saved,save_body=await apply(env,value)
    assert saved.status_code==200
    for actor in actors():
        if actor.role=="super_admin":continue
        env.user=actor
        for route in ["/templates","/customers","/customers/20?month=2026-11","/requests/"+save_body["request_id"]]:
            assert (await env.monthly_client.get(PREFIX+route)).status_code==403
        assert (await env.monthly_client.post(PREFIX+"/previews",json=request)).status_code==403
        assert (await env.monthly_client.post(PREFIX+f"/previews/{value['id']}/apply",json=save_body)).status_code==403
        assert (await env.monthly_client.post(PREFIX+"/templates",json={"request_id":str(uuid4()),"name":"Template","document":request["document"]})).status_code==403
    env.user=SECOND_OWNER
    assert (await env.monthly_client.get(PREFIX+"/requests/"+save_body["request_id"])).status_code==404
    assert (await apply(env,value))[0].status_code==404
    assert (await get(env))["revision"]==0
    assert not env.monthly_state.calls and not env.fake.writes and not env.fake.reads


@pytest.mark.asyncio
async def test_templates_are_generic_timezone_free_and_idempotently_copied(settings_env):
    env=settings_env;document=(await body(env))["document"];document["timezone"]="America/Denver"
    payload={"request_id":str(uuid4()),"name":"My generic plan","document":document}
    response=await env.monthly_client.post(PREFIX+"/templates",json=payload)
    assert response.status_code==200,response.text
    value=response.json();assert value["template"]["document"]["timezone"] is None and not value["customers_changed"]
    assert (await env.monthly_client.post(PREFIX+"/templates",json=payload)).json()==value
    assert (await env.monthly_client.post(PREFIX+"/templates",json={**payload,"name":"Changed"})).status_code==409
    listing=(await env.monthly_client.get(PREFIX+"/templates")).json()
    assert len(listing["items"])==4 and listing["templates_are_copied_not_live_linked"]
    env.user=SECOND_OWNER
    assert len((await env.monthly_client.get(PREFIX+"/templates")).json()["items"])==3
    async with env.sessions() as db:
        assert await db.scalar(select(func.count(Version.id)))==0
        assert await db.scalar(select(func.count(Policy.id)))==0


@pytest.mark.parametrize("change",[
    {"timezone":"Not/AZone"}, {"defaults":{"weekdays":[0]}}, {"defaults":{"include_prices":1}},
    {"platform_overrides":{"google_business":{"weekdays":[8]}}},
    {"platform_overrides":{"google_business":{"weekdays":[1,1]}}},
    {"platform_overrides":{"google_business":{"forbidden_claims":[" "]}}},
    {"platform_overrides":{"facebook":{"content_mix":{"featured":50,"discovery":30,"business":10}}}},
    {"defaults":{"assets":[123]}}, {"permissions":{"finance":True}}, {"automatic_publish":True},
])
@pytest.mark.asyncio
async def test_invalid_or_non_whitelist_documents_are_rejected_422(settings_env,change):
    env=settings_env;request=await body(env)
    for key,value in change.items():
        request["document"][key]={**request["document"][key],**value} if key=="defaults" else value
    response=await env.monthly_client.post(PREFIX+"/previews",json=request)
    assert response.status_code==422,response.text
    async with env.sessions() as db:
        assert await db.scalar(select(func.count(Preview.id)))==0


@pytest.mark.asyncio
async def test_preview_exact_impact_cas_and_immutable_post_recovery(settings_env):
    env=settings_env;request=await body(env);request["document"]["timezone"]="America/Denver"
    value,request=await preview(env,request)
    assert value["targets"][0]["platforms"][0]["proposed_count"]==9
    assert all(row["timezone"]=="America/Denver" for row in value["targets"][0]["platforms"])
    assert (await env.monthly_client.post(PREFIX+"/previews",json=request)).json()==value
    assert (await env.monthly_client.post(PREFIX+"/previews",json={**request,"month":"2026-12"})).status_code==409
    assert (await get(env))["revision"]==0
    assert (await apply(env,value,preview_hash="0"*64))[0].status_code==409
    assert (await apply(env,value,confirmed=False))[0].status_code==409
    assert (await apply(env,value,confirmed=1))[0].status_code==422
    saved,save_body=await apply(env,value);assert saved.status_code==200,saved.text
    assert (await env.monthly_client.post(PREFIX+f"/previews/{value['id']}/apply",json=save_body)).json()==saved.json()
    assert (await env.monthly_client.get(PREFIX+"/requests/"+save_body["request_id"])).json()==saved.json()
    assert (await apply(env,value))[0].status_code==409
    assert (await get(env))["revision"]==1
    assert not env.monthly_state.calls and not env.fake.writes


@pytest.mark.parametrize("older_version",[False,True])
@pytest.mark.asyncio
async def test_preview_before_count_uses_selected_month_not_latest_future_version(settings_env,older_version):
    env=settings_env
    if older_version:
        older=await body(env);older["document"]["defaults"]["weekdays"]=[1]
        value,_=await preview(env,older);assert (await apply(env,value))[0].status_code==200
    future=await body(env,month="2026-12");future["document"]["defaults"]["weekdays"]=[1,2,3,4,5,6,7]
    value,_=await preview(env,future);assert (await apply(env,value))[0].status_code==200
    request=await body(env,month="2026-11")
    value,_=await preview(env,request)
    google=next(row for row in value["targets"][0]["platforms"] if row["platform"]=="google_business")
    assert google["before_count"]==(5 if older_version else 12)
    assert google["proposed_count"]==9
    assert "google_business.weekdays" in value["targets"][0]["changed_fields"]
    # Reads still expose the latest draft settings for editing; impact alone
    # compares with the version actually effective in the selected month.
    current=await get(env)
    assert current["document"]["defaults"]["weekdays"]==[1,2,3,4,5,6,7]
    if older_version:assert current["effective_version"]["document"]["defaults"]["weekdays"]==[1]
    else:assert current["effective_version"] is None


@pytest.mark.parametrize("minutes",[15,16])
@pytest.mark.asyncio
async def test_preview_expires_without_any_version_write(settings_env,minutes):
    env=settings_env;value,_=await preview(env);env.clock+=timedelta(minutes=minutes)
    assert (await apply(env,value))[0].status_code==409
    assert (await get(env))["revision"]==0


@pytest.mark.parametrize("mutation",["profile","customer","name","industry","run","policy"])
@pytest.mark.asyncio
async def test_preview_cas_rechecks_relevant_state(settings_env,mutation):
    env=settings_env;value,_=await preview(env)
    async with env.sessions() as db:
        if mutation=="profile":(await db.scalar(select(Profile))).revision+=1
        elif mutation=="customer":(await db.get(Customers,20)).status="paused"
        elif mutation=="name":(await db.get(Customers,20)).business_name="Renamed after preview"
        elif mutation=="industry":(await db.get(Customers,20)).industry="beauty"
        elif mutation=="run":
            profile=await db.scalar(select(Profile));db.add(Run(owner_id=1,customer_id=20,profile_id=profile.id,request_id=str(uuid4()),fingerprint="1"*64,input_hash="2"*64,month="2026-11",snapshot={},runtime={},consent={},status="generated",revision=1,ai_used=False,message="Synthetic",created_at=AT,updated_at=AT))
        else:db.add(Policy(owner_id=1,customer_id=20,platform="google_business",revision=1,enabled=True,lead_days=7,local_time="09:00",timezone="America/Chicago",profile_revision=1,source_signature="1"*64,runtime_fingerprint="2"*64,first_target_month="2026-12",created_at=AT,updated_at=AT))
        await db.commit()
    assert (await apply(env,value))[0].status_code==409
    assert (await get(env))["revision"]==0


@pytest.mark.asyncio
async def test_copy_only_selected_rules_preserves_target_timezone_assets_and_permissions(settings_env):
    env=settings_env;source=await body(env);source["document"]["timezone"]="America/Denver"
    source["document"]["defaults"]["tone"]="professional"
    first,_=await preview(env,source);assert (await apply(env,first))[0].status_code==200
    request={"request_id":str(uuid4()),"kind":"copy","month":"2026-11","customer_id":20,"expected_revision":1,"document":None,"target_ids":[30,40],"platforms":["google_business"],"groups":["writing","cadence"]}
    value,_=await preview(env,request)
    for target in value["targets"]:
        doc=target["document_after"]
        assert doc["timezone"] is None and doc["platform_overrides"]["google_business"]["weekdays"]==[1,3]
        assert "content_mix" not in doc["platform_overrides"]["google_business"]
        assert doc["platform_overrides"]["google_business"]["tone"]=="professional"
        assert "instagram" not in doc["platform_overrides"] and not target["accounts_materials_permissions_copied"]
        assert doc["industry"]==( "beauty" if target["customer_id"]==30 else "general")
    assert (await apply(env,value))[0].status_code==200
    async with env.sessions() as db:
        assert await db.scalar(select(func.count(Profile.id)))==1
        assert await db.scalar(select(func.count(Policy.id)))==0
        assert (await db.execute(text("SELECT * FROM financial_canary"))).one()==(1,"199.00","closed","original-owner")
    assert not env.fake.writes and not env.monthly_state.calls


@pytest.mark.asyncio
async def test_batch_copy_is_atomic_when_last_target_changed(settings_env):
    env=settings_env;request={"request_id":str(uuid4()),"kind":"copy","month":"2026-11","customer_id":20,"expected_revision":0,"document":None,"target_ids":[30,40],"platforms":["google_business"],"groups":["cadence"]}
    value,_=await preview(env,request)
    async with env.sessions() as db:
        (await db.get(Customers,40)).status="paused";await db.commit()
    assert (await apply(env,value))[0].status_code==409
    async with env.sessions() as db:
        assert await db.scalar(select(func.count(Version.id)))==0
        assert await db.scalar(select(func.count(Receipt.id)))==0


@pytest.mark.asyncio
async def test_parallel_apply_different_request_ids_saves_exactly_once(settings_env):
    env=settings_env;value,_=await preview(env)
    results=await asyncio.gather(apply(env,value),apply(env,value))
    assert sorted(response.status_code for response,_ in results)==[200,409]
    async with env.sessions() as db:assert await db.scalar(select(func.count(Version.id)))==1


@pytest.mark.asyncio
async def test_effective_month_and_original_legacy_batch_freeze(settings_env):
    env=settings_env
    async with env.sessions() as db:setup=await monthly_service.setup(db,OWNER,20,month="2026-11")
    original=await env.monthly_client.post("/api/v1/media-monthly/customers/20/runs",json=generate_body(setup))
    assert original.status_code==201,original.text
    value,_=await preview(env,await body(env,month="2026-12"));assert (await apply(env,value))[0].status_code==200
    november=await get(env,month="2026-11");december=await get(env,month="2026-12")
    assert november["effective_version"] is None and december["effective_version"]["revision"]==1
    async with env.sessions() as db:
        current=await monthly_service.setup(db,OWNER,20,month="2026-11")
        future=await monthly_service.setup(db,OWNER,20,month="2026-12")
        assert current["input_hash"]==setup["input_hash"]
        assert current["planning_settings"] is None and future["planning_settings"]["revision"]==1
        assert future["profile"]["rules"]["weekdays"]==[1,3]
    after=(await env.monthly_client.get("/api/v1/media-monthly/runs/"+str(original.json()["id"]))).json()
    assert after=={**original.json(),"source_stale":False}
    assert len(env.monthly_state.calls)==1


@pytest.mark.asyncio
async def test_unknown_preview_result_recovers_read_only_and_uuids_are_unambiguous(settings_env):
    env=settings_env;value,request=await preview(env)
    recovered=await env.monthly_client.get(PREFIX+"/requests/"+request["request_id"])
    assert recovered.status_code==200 and recovered.json()==value
    assert (await apply(env,value,request_id=request["request_id"]))[0].status_code==409
    template={"request_id":request["request_id"],"name":"Conflicting UUID","document":request["document"]}
    assert (await env.monthly_client.post(PREFIX+"/templates",json=template)).status_code==409
    saved,save_body=await apply(env,value);assert saved.status_code==200
    assert (await env.monthly_client.post(PREFIX+"/previews",json={**request,"request_id":save_body["request_id"]})).status_code==409
    assert (await env.monthly_client.get(PREFIX+"/requests/"+request["request_id"])).json()==value
    async with env.sessions() as db:
        assert await db.scalar(select(func.count(Preview.id)))==1
        assert await db.scalar(select(func.count(Version.id)))==1
    assert not env.monthly_state.calls and not env.fake.writes


@pytest.mark.asyncio
async def test_batch_rollback_after_first_version_has_been_added(settings_env,monkeypatch):
    env=settings_env;request={"request_id":str(uuid4()),"kind":"copy","month":"2026-11","customer_id":20,"expected_revision":0,"document":None,"target_ids":[30,40],"platforms":["google_business"],"groups":["cadence"]}
    value,_=await preview(env,request)
    async with env.sessions() as db:
        original=db.add
        def fail_second(row):
            if isinstance(row,Version) and row.customer_id==40:raise RuntimeError("SYNTHETIC_PARTIAL_VERSION_FAILURE")
            return original(row)
        monkeypatch.setattr(db,"add",fail_second)
        with pytest.raises(RuntimeError,match="SYNTHETIC_PARTIAL_VERSION_FAILURE"):
            await service.apply(db,OWNER,value["id"],request_id=str(uuid4()),preview_hash=value["preview_hash"],confirmed=True)
    async with env.sessions() as db:
        assert await db.scalar(select(func.count(Version.id)))==0
        assert await db.scalar(select(func.count(Receipt.id)))==0


@pytest.mark.asyncio
async def test_existing_settings_batch_keeps_own_frozen_revision(settings_env):
    env=settings_env;value,_=await preview(env);assert (await apply(env,value))[0].status_code==200
    async with env.sessions() as db:setup=await monthly_service.setup(db,OWNER,20,month="2026-11")
    original=await env.monthly_client.post("/api/v1/media-monthly/customers/20/runs",json=generate_body(setup))
    assert original.status_code==201,original.text
    request=await body(env);request["document"]["defaults"]["weekdays"]=[2,4,6]
    changed,_=await preview(env,request);assert (await apply(env,changed))[0].status_code==200
    async with env.sessions() as db:
        same=await monthly_service.setup(db,OWNER,20,month="2026-11")
        future=await monthly_service.setup(db,OWNER,20,month="2026-12")
    assert same["input_hash"]==setup["input_hash"] and same["planning_settings"]["revision"]==1
    assert future["planning_settings"]["revision"]==2 and future["profile"]["rules"]["weekdays"]==[2,4,6]
    assert (await env.monthly_client.get("/api/v1/media-monthly/runs/"+str(original.json()["id"]))).json()=={**original.json(),"source_stale":False}


@pytest.mark.parametrize("month",["2026-09","2027-12"])
@pytest.mark.asyncio
async def test_effective_month_rejects_past_or_more_than_twelve_months(settings_env,month):
    env=settings_env;response=await env.monthly_client.post(PREFIX+"/previews",json=await body(env,month=month))
    assert response.status_code==422
    async with env.sessions() as db:assert await db.scalar(select(func.count(Preview.id)))==0


@pytest.mark.asyncio
async def test_settings_changes_preserve_existing_reviewed_and_scheduled_workflow(pipeline):
    env=pipeline;env.monthly_client._transport.app.include_router(router)
    before,_=await scheduled(env)
    from services import media_monthly_workflow as workflow_service
    async with env.sessions() as db:
        rows={name:(await db.execute(text('SELECT * FROM "'+name+'"'))).all() for name in ["media_monthly_profiles","media_monthly_runs","media_monthly_items","media_monthly_workflows","media_operation_tasks","media_operation_events","google_business_schedules"]}
        ctx,customer=await monthly_service.context(db,OWNER,20)
        run=await db.get(Run,env.run["id"]);packet=await db.scalar(select(Workflow).where(Workflow.run_id==run.id))
        native_source=await workflow_service._sources(db,ctx,customer,run,packet.snapshot["choices"])
        source_hash=monthly_service.digest(native_source[0]);assert source_hash==packet.source_hash
    value,_=await preview(env,await body(env));assert (await apply(env,value))[0].status_code==200
    after=await view(env)
    assert after["workflow"]==before["workflow"] and not after["source_stale"]
    async with env.sessions() as db:
        for name,original in rows.items():assert (await db.execute(text('SELECT * FROM "'+name+'"'))).all()==original
        ctx,customer=await monthly_service.context(db,OWNER,20)
        run=await db.get(Run,env.run["id"]);packet=await db.scalar(select(Workflow).where(Workflow.run_id==run.id))
        native_after=await workflow_service._sources(db,ctx,customer,run,packet.snapshot["choices"])
        assert monthly_service.digest(native_after[0])==source_hash==packet.source_hash
    assert not env.fake.writes


@pytest.mark.asyncio
async def test_already_reviewed_packet_can_still_be_scheduled_after_new_settings(pipeline):
    env=pipeline;env.monthly_client._transport.app.include_router(router)
    original,_=await reviewed(env);await enable_delivery(env)
    value,_=await preview(env);assert (await apply(env,value))[0].status_code==200
    state=await view(env)
    assert state["workflow"]==original["workflow"] and not state["source_stale"] and state["capabilities"]["can_schedule"]
    request={"request_id":str(uuid4()),"expected_revision":state["workflow"]["revision"],"preview_hash":state["workflow"]["preview_hash"],"publication_confirmed":True,"confirmation_version":"monthly-publication-v1"}
    response=await env.monthly_client.post(env.url+"/schedule",json=request)
    assert response.status_code==200,response.text
    assert response.json()["workflow"]["status"]=="scheduled" and response.json()["counts"]["scheduled"]==12
    assert not env.fake.writes


@pytest.mark.asyncio
async def test_planning_zone_streams_past_more_than_hundred_future_edits(settings_env):
    env=settings_env;document=(await get(env))["document"]
    at=datetime(2026,11,1,0,30,tzinfo=timezone.utc)
    async with env.sessions() as db:
        for revision in range(1,104):
            doc=copy.deepcopy(document)
            doc["timezone"]="Asia/Tokyo" if revision==1 else "America/Los_Angeles"
            month="2026-12" if revision in {1,103} else "2027-01"
            db.add(Version(owner_id=1,customer_id=20,revision=revision,effective_from_month=month,document=doc,preview_id=str(uuid4()),created_at=AT))
        await db.commit()
        ctx,customer=await monthly_service.context(db,OWNER,20)
        profile=await db.scalar(select(Profile))
        assert await service.planning_zone(db,ctx,customer,profile,"google_business",at)=="Asia/Tokyo"


@pytest.mark.asyncio
async def test_frozen_timezone_cross_month_boundary_blocks_automatic_preparation(settings_env):
    env=settings_env;document=(await get(env))["document"]
    async with env.sessions() as db:
        old=copy.deepcopy(document);old["timezone"]="America/Los_Angeles"
        db.add(Version(owner_id=1,customer_id=20,revision=1,effective_from_month="2026-12",document=old,preview_id=str(uuid4()),created_at=AT))
        await db.commit()
        setup=await monthly_service.setup(db,OWNER,20,month="2026-12")
        original=await monthly_service.generate(db,OWNER,20,**generate_body(setup,month="2026-12"))
        updated=copy.deepcopy(document);updated["timezone"]="Asia/Tokyo"
        db.add(Version(owner_id=1,customer_id=20,revision=2,effective_from_month="2026-12",document=updated,preview_id=str(uuid4()),created_at=AT))
        await db.commit()
    calls=len(env.monthly_state.calls)
    from services import media_monthly_automation as automation
    async with env.sessions() as db:
        ctx,customer=await monthly_service.context(db,OWNER,20)
        result=await automation._source(db,ctx,customer,"google_business",datetime(2026,11,1,0,30,tzinfo=timezone.utc),7)
        assert not result["can_enable"] and result["snapshot"] is None and result["source_signature"] is None
        assert any("跨月" in message for message in result["gaps"])
        assert (await db.get(Run,original["id"])).snapshot["rules"]["timezone"]=="America/Los_Angeles"
    assert len(env.monthly_state.calls)==calls and not env.fake.writes


def test_four_table_empty_migration_preserves_financial_canary():
    path=Path(__file__).parents[1]/"alembic/versions/i54af678a914_media_automation_settings.py"
    spec=importlib.util.spec_from_file_location("settings_migration",path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    engine=create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE financial_canary(id INTEGER PRIMARY KEY,value TEXT)"));connection.execute(text("INSERT INTO financial_canary VALUES(1,'preserved')"))
        with Operations.context(MigrationContext.configure(connection)):module.upgrade()
        assert set(inspect(connection).get_table_names())==service.TABLES|{"financial_canary"}
        for name in service.TABLES:assert connection.execute(text('SELECT COUNT(*) FROM "'+name+'"')).scalar()==0
        with Operations.context(MigrationContext.configure(connection)):module.downgrade()
        assert connection.execute(text("SELECT * FROM financial_canary")).all()==[(1,"preserved")]


@pytest.mark.asyncio
async def test_production_route_discovery_cannot_bypass_versions_through_generic_crud(settings_env):
    env=settings_env
    from main import include_routers_from_package
    app=FastAPI();include_routers_from_package(app)
    paths=app.openapi()["paths"]
    assert PREFIX+"/previews/{preview_id}/apply" in paths and PREFIX+"/requests/{request_id}" in paths
    async def database():
        async with env.sessions() as db:yield db
    async def actor():return env.user
    app.dependency_overrides[get_db]=database;app.dependency_overrides[get_current_user]=actor
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="https://synthetic.test") as client:
        for user in (OWNER,OPS):
            env.user=user
            for table in service.TABLES:
                url="/api/v1/entities/"+table
                assert url not in paths and url+"/{id}" not in paths
                assert (await client.get(url)).status_code==404
                assert (await client.get(url+"/1")).status_code==404
                assert (await client.post(url,json={"revision":9})).status_code==404
                assert (await client.put(url+"/1",json={"revision":9})).status_code==404
                assert (await client.delete(url+"/1")).status_code==404
