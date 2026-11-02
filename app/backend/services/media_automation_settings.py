"""Owner-only versioned defaults for NEW content batches; never publication authority.

Templates/copy carry only generic writing/cadence choices, not accounts, customer
facts, menus, assets, grants, AI consent or already approved/scheduled content.
"""
import copy
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4,uuid5,NAMESPACE_URL
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select,func
from models.customers import Customers
from models.media_monthly import MediaMonthlyProfile as Profile,MediaMonthlyRun as Run
from models.media_monthly_workflow import MediaMonthlyWorkflow as Workflow
from models.media_monthly_automation import MediaMonthlyAutomationPolicy as Policy
from models.media_automation_settings import MediaAutomationSettingVersion as Version,MediaAutomationTemplateVersion as Template,MediaAutomationSettingsPreview as Preview,MediaAutomationSettingsReceipt as Receipt
from schemas.media_automation_settings import Document,PlanRules
from services import media_monthly as monthly,media_operations as media
from services.schema_readiness import require_tables,tables_available

TABLES={Version.__tablename__,Template.__tablename__,Preview.__tablename__,Receipt.__tablename__}
PLATFORMS=("google_business","facebook","instagram")
GROUPS={"cadence":("weekdays","local_time"),"writing":("language","include_prices","forbidden_claims","tone"),"content":("content_mix",)}
TOPICS={"featured":"主推产品／服务","discovery":"菜单／服务推荐","business":"门店介绍"}
BASE={"weekdays":[2,4,6],"local_time":"11:00","language":"en","include_prices":False,"forbidden_claims":[],"content_mix":{"featured":50,"discovery":30,"business":20},"tone":"friendly"}
BUILTINS=(
 {"id":"restaurant","revision":1,"name":"餐厅 · 产品与门店","industry":"restaurant","rules":BASE},
 {"id":"beauty","revision":1,"name":"美业 · 服务与门店","industry":"beauty","rules":{**BASE,"content_mix":{"featured":50,"discovery":20,"business":30},"tone":"professional"}},
 {"id":"general","revision":1,"name":"通用 · 日常经营","industry":"general","rules":{**BASE,"content_mix":{"featured":40,"discovery":20,"business":40}}},
)

def _clean_document(value):
    value=Document.model_validate(value).model_dump(exclude_none=True)
    value["timezone"]=value.get("timezone") or None
    if value["timezone"]:
        try:ZoneInfo(value["timezone"])
        except (ValueError,ZoneInfoNotFoundError):raise HTTPException(422,"请选择有效门店时区") from None
    value["defaults"]=PlanRules.model_validate(value["defaults"]).model_dump()
    value["defaults"]["weekdays"]=sorted(value["defaults"]["weekdays"])
    for platform in PLATFORMS:
        override=value["platform_overrides"].get(platform,{})
        if override:
            checked=PlanRules.model_validate({**value["defaults"],**override}).model_dump()
            override={key:checked[key] for key in override}
            if "weekdays" in override:override["weekdays"]=sorted(override["weekdays"])
            value["platform_overrides"][platform]=override
    for rules in [value["defaults"],*value["platform_overrides"].values()]:
        if "forbidden_claims" in rules:rules["forbidden_claims"]=[monthly._clean(v,100,required=True) for v in rules["forbidden_claims"]]
    return value


def clean_document(value):
    try:return _clean_document(value)
    except ValidationError:raise HTTPException(422,"请核对平台规则、发布日及内容比例，内容比例合计须为100%") from None


def resolved(document,platform):
    monthly.platform_value(platform)
    return copy.deepcopy(PlanRules.model_validate({**document["defaults"],**document.get("platform_overrides",{}).get(platform,{})}).model_dump())


def industry_for(customer):
    name=str(getattr(customer,"industry","") or "").lower()
    if any(w in name for w in ("restaurant","餐","food")):return "restaurant"
    if any(w in name for w in ("beauty","美业","spa","salon")):return "beauty"
    return "general"


async def context(db,user,customer_id=None,*,write=False):
    ctx,customer=await monthly.context(db,user,customer_id,write=write)
    await require_tables(db,TABLES)
    return ctx,customer


async def latest(db,owner,customer,*,month=None):
    query=select(Version).where(Version.owner_id==owner,Version.customer_id==customer)
    if month is not None:query=query.where(Version.effective_from_month<=month)
    return await db.scalar(query.order_by(Version.revision.desc()).limit(1).execution_options(populate_existing=True))


async def legacy_document(db,ctx,customer):
    industry=industry_for(customer);base=copy.deepcopy(next(t["rules"] for t in BUILTINS if t["id"]==industry))
    profile=await db.scalar(select(Profile).where(Profile.owner_id==ctx.identity,Profile.customer_id==customer.id).execution_options(populate_existing=True))
    overrides={};zones=[]
    for platform in PLATFORMS:
        local=monthly.effective_profile(profile,platform)
        if local:
            overrides[platform]={key:copy.deepcopy(local.rules[key]) for key in ("weekdays","local_time","language","include_prices","forbidden_claims") if key in local.rules}
            zones.append(local.rules["timezone"])
    return clean_document({"industry":industry,"timezone":zones[0] if zones else None,"defaults":base,"platform_overrides":overrides,"template_key":industry,"template_revision":1})


def version_data(row):
    return {"revision":row.revision,"effective_from_month":row.effective_from_month,"document":row.document,"created_at":monthly.iso(row.created_at)} if row else None


async def templates(db,user):
    ctx,_=await context(db,user)
    ids=select(Template.template_id,func.max(Template.revision).label("revision")).where(Template.owner_id==ctx.identity).group_by(Template.template_id).subquery()
    rows=(await db.scalars(select(Template).join(ids,(Template.template_id==ids.c.template_id)&(Template.revision==ids.c.revision)).where(Template.owner_id==ctx.identity).order_by(Template.id.desc()).limit(100))).all()
    builtin=[{"id":t["id"],"revision":t["revision"],"name":t["name"],"builtin":True,"document":{"industry":t["industry"],"timezone":None,"defaults":copy.deepcopy(t["rules"]),"platform_overrides":{},"template_key":t["id"],"template_revision":1}} for t in BUILTINS]
    return {"items":builtin+[{"id":r.template_id,"revision":r.revision,"name":r.name,"builtin":False,"document":r.document} for r in rows],"templates_are_copied_not_live_linked":True}


async def customers(db,user,*,search="",after_id=0):
    ctx,_=await context(db,user)
    if len(search)>100 or after_id<0:raise HTTPException(422,"请核对搜索条件")
    query=select(Customers).where(Customers.status=="closed",Customers.id>after_id)
    if search:query=query.where(Customers.business_name.ilike("%"+search.replace("%","\\%").replace("_","\\_")+"%",escape="\\"))
    rows=list((await db.scalars(query.order_by(Customers.id).limit(51))).all())
    return {"items":[{"id":c.id,"name":c.business_name,"industry":industry_for(c)} for c in rows[:50]],"next_after":rows[49].id if len(rows)>50 else None}


async def get_settings(db,user,customer_id,*,month):
    monthly.valid_month(month);ctx,customer=await context(db,user,customer_id)
    row=await latest(db,ctx.identity,customer.id);active=await latest(db,ctx.identity,customer.id,month=month)
    document=row.document if row else await legacy_document(db,ctx,customer)
    profile=await db.scalar(select(Profile).where(Profile.owner_id==ctx.identity,Profile.customer_id==customer.id))
    sources=[]
    for p in PLATFORMS:
        local=monthly.effective_profile(profile,p)
        sources.append({"platform":p,"profile_ready":bool(local),"menu_count":len(local.menu_item_ids) if local else 0,"image_count":len(local.images) if local else 0,"timezone":local.rules["timezone"] if local else None})
    return {"customer":{"id":customer.id,"name":customer.business_name,"cooperation_active":customer.status=="closed"},"revision":row.revision if row else 0,"version":version_data(row),"effective_version":version_data(active),"document":document,"sources":sources,"month":month,"new_batches_only":True,"publications_changed":False}


async def _state(db,ctx,customer,*,month):
    row=await latest(db,ctx.identity,customer.id)
    profile=await db.scalar(select(Profile).where(Profile.owner_id==ctx.identity,Profile.customer_id==customer.id).execution_options(populate_existing=True))
    runs=list((await db.scalars(select(Run).where(Run.owner_id==ctx.identity,Run.customer_id==customer.id).order_by(Run.id).limit(2001))).all())
    workflows=list((await db.scalars(select(Workflow).where(Workflow.owner_id==ctx.identity,Workflow.customer_id==customer.id).order_by(Workflow.id).limit(2001))).all())
    if len(runs)>2000 or len(workflows)>2000:raise HTTPException(409,"历史批次较多，请按商家单独处理")
    profiles={p:monthly.profile_data(profile,p) for p in PLATFORMS}
    policies=list((await db.scalars(select(Policy).where(Policy.owner_id==ctx.identity,Policy.customer_id==customer.id,Policy.enabled.is_(True)))).all()) if await tables_available(db,{Policy.__tablename__}) else []
    document=row.document if row else await legacy_document(db,ctx,customer)
    pin=monthly.digest({"customer":customer.id,"customer_name":customer.business_name,"status":customer.status,
        "document":document,"revision":row.revision if row else 0,"profiles":profiles,
        "runs":[[r.id,r.revision,r.status] for r in runs],"workflows":[[w.id,w.revision,w.status] for w in workflows],
        "enabled_policies":sorted([p.id,p.revision] for p in policies)})
    active=await latest(db,ctx.identity,customer.id,month=month)
    before_document=active.document if active else (await legacy_document(db,ctx,customer) if row else document)
    return {"revision":row.revision if row else 0,"document":document,"before_document":before_document,"row":row,"profiles":profiles,"runs":runs,"workflows":workflows,"pin":pin,"enabled_policies":len(policies)}


def _check_month(month,document,state):
    monthly.valid_month(month)
    zone=document.get("timezone") or next((p["rules"]["timezone"] for p in state["profiles"].values() if p),"UTC")
    current=monthly.aware(monthly.now()).astimezone(ZoneInfo(zone)).strftime("%Y-%m")
    if month<current or int(month[:4])*12+int(month[5:])-int(current[:4])*12-int(current[5:])>12:
        raise HTTPException(422,"设置仅用于本月起未来12个月的新内容批次")


def _diff(before,after):
    changes=[]
    for key in ("industry","timezone","template_key","template_revision"):
        if before.get(key)!=after.get(key):changes.append(key)
    for p in PLATFORMS:
        a,b=resolved(before,p),resolved(after,p)
        changes.extend(p+"."+k for k in a if a[k]!=b[k])
    return changes


def _impact(customer,state,document,month):
    platforms=[];before_document=state["before_document"]
    for p in PLATFORMS:
        profile=state["profiles"][p];zone=document.get("timezone") or (profile["rules"]["timezone"] if profile else None)
        oldzone=before_document.get("timezone") or (profile["rules"]["timezone"] if profile else None)
        def count(doc,z):
            rules=resolved(doc,p)
            return len(monthly.slots(month,{**rules,"timezone":z,"posts_per_week":len(rules["weekdays"])})) if z else None
        existing=[r for r in state["runs"] if r.month==month and monthly.run_platform(r)==p and r.status!="archived"]
        platforms.append({"platform":p,"before_count":count(before_document,oldzone),"proposed_count":count(document,zone),"timezone":zone,"existing_batches":len(existing),"source_ready":bool(profile),"content_mix":resolved(document,p)["content_mix"]})
    protected={"batches":len(state["runs"]),"reviewed":sum(w.status=="reviewed" for w in state["workflows"]),"scheduled":sum(w.status=="scheduled" for w in state["workflows"])}
    return {"customer_id":customer.id,"name":customer.business_name,"before_revision":state["revision"],"after_revision":state["revision"]+1,"effective_from_month":month,"document_after":document,"changed_fields":_diff(state["document"],document),"platforms":platforms,"protected":protected,"auto_policies_need_reconfirmation":state["enabled_policies"],"accounts_materials_permissions_copied":False}


async def _build(db,user,body):
    ctx,source=await context(db,user,body["customer_id"],write=True)
    source_state=await _state(db,ctx,source,month=body["month"])
    if source_state["revision"]!=body["expected_revision"]:raise HTTPException(409,"来源设置已有更新，请重新读取后预览")
    pins={str(source.id):source_state["pin"]};targets=[]
    if body["kind"]=="edit":
        if body.get("document") is None or body["target_ids"] or body["platforms"] or body["groups"]:raise HTTPException(422,"请核对单店设置预览")
        proposed=clean_document(body["document"]);_check_month(body["month"],proposed,source_state)
        targets.append(_impact(source,source_state,proposed,body["month"]))
    else:
        ids=body["target_ids"];platforms=body["platforms"];groups=body["groups"]
        if body.get("document") is not None or not ids or len(set(ids))!=len(ids) or source.id in ids or any(type(x)is not int or x<1 for x in ids) or not platforms or len(set(platforms))!=len(platforms) or not groups or len(set(groups))!=len(groups):raise HTTPException(422,"请选择不重复的目标商家、平台及通用规则范围")
        for identity in sorted(ids):
            _,customer=await context(db,user,identity,write=True);state=await _state(db,ctx,customer,month=body["month"])
            document=copy.deepcopy(state["document"])
            for p in platforms:
                rules=resolved(source_state["document"],p);override=document["platform_overrides"].setdefault(p,{})
                for group in groups:
                    for key in GROUPS[group]:override[key]=copy.deepcopy(rules[key])
            document=clean_document(document);_check_month(body["month"],document,state)
            targets.append(_impact(customer,state,document,body["month"]));pins[str(identity)]=state["pin"]
    return ctx,targets,pins


async def preview(db,user,body):
    identity=media._key(body["request_id"]);fingerprint=monthly.digest(body)
    ctx,_=await context(db,user)
    async with media._write(db):
        if await db.scalar(select(Receipt.id).where(Receipt.owner_id==ctx.identity,Receipt.request_id==identity)):
            raise HTTPException(409,"原请求编号已用于设置保存，请查询原结果")
        old=await db.scalar(select(Preview).where(Preview.owner_id==ctx.identity,Preview.request_id==identity))
        if old:
            if old.fingerprint!=fingerprint:raise HTTPException(409,"原预览编号已用于另一组设置")
            return old.result
        ctx,targets,pins=await _build(db,user,body)
        at=monthly.now();uid=str(uuid4());state_hash=monthly.digest({"body":body,"pins":pins})
        result={"id":uid,"request_id":identity,"preview_hash":state_hash,"expires_at":monthly.iso(at+timedelta(minutes=15)),"kind":body["kind"],"month":body["month"],"targets":targets,"new_batches_only":True,"publications_changed":False,"menus_images_accounts_permissions_copied":False}
        db.add(Preview(id=uid,owner_id=ctx.identity,request_id=identity,fingerprint=fingerprint,body=body,state_hash=state_hash,result=result,expires_at=at+timedelta(minutes=15),created_at=at))
    return result


async def apply(db,user,preview_id,*,request_id,preview_hash,confirmed):
    ctx,_=await context(db,user);identity=media._key(request_id)
    fingerprint=monthly.digest({"preview_id":preview_id,"preview_hash":preview_hash,"confirmed":confirmed})
    async with media._write(db):
        if await db.scalar(select(Preview.id).where(Preview.owner_id==ctx.identity,Preview.request_id==identity)):
            raise HTTPException(409,"原请求编号已用于预览，请查询原结果")
        old=await db.scalar(select(Receipt).where(Receipt.owner_id==ctx.identity,Receipt.request_id==identity))
        if old:
            if old.fingerprint!=fingerprint:raise HTTPException(409,"原保存编号已用于其他设置")
            return old.result
        row=await db.get(Preview,preview_id,populate_existing=True)
        if not row or row.owner_id!=ctx.identity:raise HTTPException(404,"未找到本老板账号的设置预览")
        if confirmed is not True or preview_hash!=row.state_hash:raise HTTPException(409,"请确认当前完整影响预览")
        if monthly.aware(row.expires_at)<=monthly.aware(monthly.now()):raise HTTPException(409,"预览已过期，请重新核对影响范围")
        _,targets,pins=await _build(db,user,row.body)
        if monthly.digest({"body":row.body,"pins":pins})!=row.state_hash:raise HTTPException(409,"商家、规则或内容批次已变化，未保存任何设置，请重新预览")
        at=monthly.now();saved=[]
        for target in targets:
            version=Version(owner_id=ctx.identity,customer_id=target["customer_id"],revision=target["after_revision"],effective_from_month=row.body["month"],document=target["document_after"],preview_id=row.id,created_at=at)
            db.add(version);saved.append({"customer_id":version.customer_id,"revision":version.revision,"effective_from_month":version.effective_from_month})
        result={"request_id":identity,"preview_id":row.id,"saved":saved,"new_batches_only":True,"existing_batches_changed":False,"publications_changed":False}
        db.add(Receipt(owner_id=ctx.identity,request_id=identity,fingerprint=fingerprint,result=result,created_at=at));await db.flush()
    return result


async def request_result(db,user,request_id):
    ctx,_=await context(db,user);key=media._key(request_id)
    row=await db.scalar(select(Receipt).where(Receipt.owner_id==ctx.identity,Receipt.request_id==key))
    if row is None:
        original=await db.scalar(select(Preview).where(Preview.owner_id==ctx.identity,Preview.request_id==key))
        if original is None:raise HTTPException(404,"原设置请求结果尚未找到，请保留请求编号")
        await monthly.context(db,user,original.body["customer_id"])
        for target in original.result.get("targets",[]):await monthly.context(db,user,target["customer_id"])
        return original.result
    for target in row.result.get("saved",[]):await monthly.context(db,user,target["customer_id"])
    return row.result


async def save_template(db,user,*,request_id,name,document):
    ctx,_=await context(db,user);key=media._key(request_id);document=clean_document(document);document["timezone"]=None
    uid=str(uuid5(NAMESPACE_URL,f"t24-automation-template:{ctx.identity}:{key}"));document["template_key"]=uid;document["template_revision"]=1
    name=monthly._clean(name,80,required=True);fingerprint=monthly.digest({"kind":"template","name":name,"document":document})
    async with media._write(db):
        if await db.scalar(select(Preview.id).where(Preview.owner_id==ctx.identity,Preview.request_id==key)):
            raise HTTPException(409,"原请求编号已用于预览，请查询原结果")
        old=await db.scalar(select(Receipt).where(Receipt.owner_id==ctx.identity,Receipt.request_id==key))
        if old:
            if old.fingerprint!=fingerprint:raise HTTPException(409,"原模板请求已用于其他内容")
            return old.result
        row=Template(owner_id=ctx.identity,template_id=uid,revision=1,name=name,document=document,created_at=monthly.now());db.add(row)
        result={"request_id":key,"template":{"id":uid,"revision":1,"name":name,"document":document,"builtin":False},"customers_changed":False}
        db.add(Receipt(owner_id=ctx.identity,request_id=key,fingerprint=fingerprint,result=result,created_at=monthly.now()))
    return result


async def plan_for_month(db,ctx,customer,profile,month,platform):
    """Resolve a frozen batch first. Settings edits cannot stale an existing run."""
    if profile is None or not await tables_available(db,TABLES):return profile,None
    existing=await db.scalar(select(Run).where(Run.owner_id==ctx.identity,Run.customer_id==customer.id,Run.month==month,monthly.platform_clause(platform),Run.status!="archived").order_by(Run.id.desc()).limit(1))
    if existing:
        plan=(existing.snapshot or {}).get("automation_settings")
        if not plan:return profile,None
    else:
        version=await latest(db,ctx.identity,customer.id,month=month)
        if not version:return profile,None
        document=version.document
        plan={"revision":version.revision,"effective_from_month":version.effective_from_month,"industry":document["industry"],"template_key":document.get("template_key"),"template_revision":document.get("template_revision"),"rules":resolved(document,platform),"timezone":document.get("timezone")}
    rules=plan["rules"];base={**profile.rules,**{k:copy.deepcopy(rules[k]) for k in ("weekdays","local_time","language","include_prices","forbidden_claims")},"timezone":plan.get("timezone") or profile.rules["timezone"],"posts_per_week":len(rules["weekdays"]),"_automation_plan":{"content_mix":rules["content_mix"],"tone":rules["tone"]}}
    virtual=SimpleNamespace(**{k:v for k,v in vars(profile).items() if k!="rules"},rules=base)
    return virtual,copy.deepcopy(plan)


async def planning_zone(db,ctx,customer,profile,platform,at):
    zone=profile.rules["timezone"]
    if not await tables_available(db,TABLES):return zone
    # All supported IANA local dates are within one day of UTC. Exclude
    # impossible future effective months in SQL, then stream newest-first so
    # many future edits cannot hide the still-effective original timezone.
    latest_local=monthly.aware(at)+timedelta(days=1)
    upper=f"{latest_local.year+1}-01" if latest_local.month==12 else f"{latest_local.year:04d}-{latest_local.month+1:02d}"
    versions=await db.stream_scalars(select(Version).where(Version.owner_id==ctx.identity,
        Version.customer_id==customer.id,Version.effective_from_month<=upper).order_by(Version.revision.desc()))
    try:
        async for row in versions:
            candidate=row.document.get("timezone") or zone
            local=monthly.aware(at).astimezone(ZoneInfo(candidate))
            month=f"{local.year+1}-01" if local.month==12 else f"{local.year:04d}-{local.month+1:02d}"
            if row.effective_from_month<=month:return candidate
    finally:await versions.close()
    return zone
