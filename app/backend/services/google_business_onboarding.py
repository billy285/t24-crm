"""Durable owner onboarding. Google reads only; bindings remain local and atomic.

No customer fields, grants, publication tasks, schedules or private records are
modified. Every binding consumes an explicitly confirmed frozen identity pair.
"""
from __future__ import annotations
import asyncio
import contextlib
from datetime import timedelta
import os
import re
from types import SimpleNamespace
import unicodedata
from uuid import uuid4, uuid5, NAMESPACE_URL

from fastapi import HTTPException
from sqlalchemy import select, or_
from models.customers import Customers
from models.employees import Employees
from models.google_business import GoogleBusinessBinding as Binding, GoogleBusinessConnection as Connection
from models.google_business_onboarding import GoogleOnboardingCatalog as Catalog, GoogleOnboardingBatch as Batch, GoogleOnboardingItem as Item, GoogleOnboardingRequest as Request
from services import google_business as g
from services import google_business_provider as provider
from services.schema_readiness import require_tables, tables_available

TABLES = {Catalog.__tablename__, Batch.__tablename__, Item.__tablename__, Request.__tablename__}
CATALOG_TTL = 600
PREVIEW_TTL = 300
LEASE_SECONDS = 120
_worker = None


def worker_enabled(): return os.getenv("T24_GBP_ONBOARDING_WORKER_ENABLED", "true").strip().lower() == "true"
def marker(connection): return {"id":connection.id, "owner_id":connection.owner_id, "connected_at":g.iso(connection.connected_at)}
def public_customer(row): return {"id":row.id, "name":row.business_name or "", **{x:getattr(row,x) for x in ("status","address","city","state","country")}}
def customer_hash(row): return g.digest({**public_customer(row), "updated_at":g.iso(row.updated_at)})
def require(ok, message, code=409):
    if not ok: raise HTTPException(code, message)


async def context(db, user, *, lock=False):
    # Denied roles must not reach SQL, including schema discovery.
    if g.normalized_role(user) != "super_admin": raise HTTPException(403, "仅老板可以接入 Google 商家")
    ctx = await g.context(db, user, owner=True)
    await require_tables(db, TABLES)
    if lock:
        actor = await db.scalar(select(Employees).where(Employees.id == ctx.identity).with_for_update().execution_options(populate_existing=True))
        require(actor and actor.status in {"active","probation"} and g.normalized_role(SimpleNamespace(role=actor.role)) == "super_admin", "老板身份已失效，请重新登录", 403)
    return ctx


async def customer(db, ctx, customer_id, *, write=False):
    row = await db.scalar(select(Customers).where(Customers.id == customer_id).with_for_update().execution_options(populate_existing=True)) if write else await db.get(Customers,customer_id,populate_existing=True)
    require(row is not None, "客户不存在或不可访问", 404)
    await g.media._customer(db,ctx,customer_id,write=write)
    return row


async def owned(db, model, ctx, identity, *, lock=False):
    query = select(model).where(model.id == identity, model.owner_id == ctx.identity).execution_options(populate_existing=True)
    if lock: query = query.with_for_update()
    row = await db.scalar(query)
    require(row is not None, "接入记录不存在或不属于当前老板", 404)
    return row


async def receipt(db, ctx, request_id, kind=None, payload=None):
    key = g.media._key(request_id)
    row = await db.scalar(select(Request).where(Request.owner_id == ctx.identity,Request.request_id == key))
    if row and kind is not None:
        require(row.kind == kind and row.fingerprint == g.digest(payload), "同一请求编号对应了不同操作或内容")
    if row is None and kind is not None:
        native=await db.scalar(select(Binding.id).where(Binding.request_id==key).limit(1))
        internal=await db.scalar(select(Item.id).where(Item.owner_id==ctx.identity,Item.request_id==key).limit(1))
        require(native is None and internal is None,"该编号已用于门店绑定或内部接入行，请保留原编号查询，不用于其他操作")
    return row


async def legacy_replay_guard(db,ctx,request_id,payload):
    # An old native binding may predate this feature. Keep that replay, while
    # preventing a newer discovery/confirmation UUID from crossing namespaces.
    if not await tables_available(db,TABLES):return
    old=await db.scalar(select(Request).where(Request.owner_id==ctx.identity,Request.request_id==request_id))
    if old:require(old.kind=="legacy_bind" and old.fingerprint==g.digest(payload),"同一请求编号对应了不同操作或内容")
    internal=await db.scalar(select(Item).where(Item.owner_id==ctx.identity,Item.request_id==request_id))
    if internal:
        batch=await db.get(Batch,internal.batch_id)
        require(batch is not None and batch.kind=="legacy","该编号属于批次内部行，请查询原接入批次")


def receipt_data(row):
    return {"request_id":row.request_id,"kind":row.kind,"resource_id":row.resource_id,"created_at":g.iso(row.created_at)}


def record(db,ctx,key,kind,payload,resource):
    row=Request(owner_id=ctx.identity,request_id=key,kind=kind,fingerprint=g.digest(payload),resource_id=resource,created_at=g.now());db.add(row);return row


async def own_bindings(db,ctx):
    return list((await db.scalars(select(Binding).join(Connection,Connection.id==Binding.connection_id).where(Connection.owner_id==ctx.identity).order_by(Binding.id))).all())


async def binding_data(db,rows):
    ids=[x.id for x in rows]
    evidence=list((await db.scalars(select(Item).where(Item.binding_id.in_(ids),Item.status=="bound").order_by(Item.updated_at.desc(),Item.id))).all()) if ids else []
    known={}
    for item in evidence:
        if item.binding_id not in known: known[item.binding_id]={**item.snapshot.get("google",{}),"observed_at":g.iso(item.updated_at)}
    return [{"id":x.id,"customer_id":x.customer_id,"location_name":x.location_name,"active":x.active,"title":x.title,"address":x.address,"google_identity":known.get(x.id)} for x in rows]


def catalog_summary(row):
    expired=row.status=="ready" and (row.expires_at is None or g.aware(row.expires_at)<=g.now())
    return {"id":row.id,"connection_id":row.connection_id,"customer_id":row.customer_id,"status":"expired" if expired else row.status,
        "revision":row.revision,"observed_at":g.iso(row.observed_at),"expires_at":g.iso(row.expires_at),"message":"门店目录已过期，请重新发现后核对" if expired else row.message,
        "error_code":row.error_code,"total_locations":len(row.locations),"truncated":row.truncated}


def norm(value): return re.sub(r"[^\w]", "", unicodedata.normalize("NFKC",str(value or "")).casefold(),flags=re.UNICODE).replace("_","")


_STATES=dict(zip(("alabama,alaska,arizona,arkansas,california,colorado,connecticut,delaware,district of columbia,florida,georgia,hawaii,idaho,illinois,indiana,iowa,kansas,kentucky,louisiana,maine,maryland,massachusetts,michigan,minnesota,mississippi,missouri,montana,nebraska,nevada,new hampshire,new jersey,new mexico,new york,north carolina,north dakota,ohio,oklahoma,oregon,pennsylvania,rhode island,south carolina,south dakota,tennessee,texas,utah,vermont,virginia,washington,west virginia,wisconsin,wyoming").split(','),("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY").split()))
_STATE_CODES={**{norm(k):v for k,v in _STATES.items()},**{v.casefold():v for v in _STATES.values()}}


def tokens(value):
    value=unicodedata.normalize("NFKC",str(value or "")).casefold()
    value=re.sub(r"\bu[.]?s[.]?(?=[ -]?\d)","us ",value)
    value=re.sub(r"\b(?:suite|ste|unit)\s*#?\s*(?=\d)","unit ",value).replace("#"," unit ")
    aliases={"street":"st","road":"rd","avenue":"ave","boulevard":"blvd","drive":"dr","lane":"ln","highway":"hwy","suite":"unit","ste":"unit","north":"n","south":"s","east":"e","west":"w"}
    # Preserve token boundaries: 1 23 must never equal 12 3, nor unit 1 04/104.
    return tuple(aliases.get(x,x) for x in re.findall(r"[^\W_]+",value,flags=re.UNICODE))


def address_parts(value):
    """Read only known comma-joined locality/state/ZIP tails, never substrings."""
    parts=[x.strip() for x in str(value or "").split(',') if x.strip()]
    postal=None;state=None
    if parts:
        match=re.fullmatch(r"(?:(.+?)\s+)?(\d{5})(?:-\d{4})?",parts[-1])
        if match:
            postal=match.group(2)
            if match.group(1):parts[-1]=match.group(1)
            else:parts.pop()
    if parts and norm(parts[-1]) in _STATE_CODES:state=_STATE_CODES[norm(parts.pop())]
    city=parts.pop() if state and parts else None
    return {"street":", ".join(parts),"city":city,"state":state,"postal":postal}


def address_norm(value):
    parts=address_parts(value)
    if all(parts.values()):return tokens(parts["street"])+("|city",)+tokens(parts["city"])+("|state",parts["state"],"|zip",parts["postal"])
    return tokens(value)


def identity_warnings(crm,google,*,truncated=False):
    result=[]
    if norm(crm["name"])!=norm(google["title"]):result.append("商家名称存在差异，请老板确认是否为同一家")
    if not crm.get("address") or address_norm(crm["address"])!=address_norm(google["address"]):result.append("完整地址存在差异或缺失，请核对街道、单元及邮编")
    parts=address_parts(google["address"])
    if not all(parts.values()):result.append("Google地址的街道、城市、州或邮编组件不完整，需人工核对")
    if not crm.get("city") or not parts["city"] or tokens(crm["city"])!=tokens(parts["city"]):result.append("CRM单独城市字段与Google城市不一致或缺失，系统不会自动修改")
    if not crm.get("state") or not parts["state"] or _STATE_CODES.get(norm(crm["state"]))!=parts["state"]:result.append("CRM单独州字段与Google州不一致或缺失，系统不会自动修改")
    if truncated:result.append("本次Google目录不完整，未返回的门店不能判断为不存在")
    return result


async def customer_rows(db,ctx,customer_id=None):
    if customer_id is not None:return [await customer(db,ctx,customer_id)]
    rows=list((await db.scalars(select(Customers).order_by(Customers.business_name,Customers.id).limit(201))).all())
    require(len(rows)<=200,"当前客户过多，请先限定一家商家",422)
    return rows


async def catalog_view(db,ctx,row):
    summary=catalog_summary(row);locations=row.locations if summary["status"]=="ready" else []
    bindings=await binding_data(db,await own_bindings(db,ctx));by_customer={x["customer_id"]:x for x in bindings}
    reserved=set((await db.scalars(select(Binding.customer_id))).all())
    comparisons=[]
    for c in await customer_rows(db,ctx,row.customer_id):
        crm=public_customer(c);bound=by_customer.get(c.id);reasons=[];candidates=[]
        if bound or c.id in reserved:
            state="already_bound";reasons=["已有门店绑定；本流程不会覆盖、恢复或更换"]
            if bound and summary["status"]=="ready":
                official=next((x for x in locations if x["location_name"]==bound["location_name"]),None)
                if official:
                    candidates=[official];bound={**bound,"google_identity":official}
                    reasons.append("本次目录已核对原绑定的相同账号与门店路径；仅展示，不重新绑定")
                    reasons.extend(identity_warnings(crm,official,truncated=row.truncated))
                else:reasons.append("本次目录尚未发现原绑定的相同账号门店路径，请补查；原绑定保持不变")
        elif c.status!="closed":state="inactive";reasons=["当前并非合作已成交状态，不接入"]
        elif summary["status"]!="ready":state="review_needed";reasons=["目录尚未完整读取或已过期，暂不能判断匹配"]
        else:
            for x in locations:
                if not x["title"].strip() or not x["address"].strip():continue
                same=norm(crm["name"])==norm(x["title"])
                addr=bool(crm["address"]) and address_norm(crm["address"])==address_norm(x["address"])
                similar=bool(norm(crm["name"])) and min(len(norm(crm["name"])),len(norm(x["title"])))>=5 and (norm(crm["name"]) in norm(x["title"]) or norm(x["title"]) in norm(crm["name"]))
                if same or addr or similar:candidates.append(x)
            candidates=candidates[:10]
            if len(candidates)==1:
                reasons=identity_warnings(crm,candidates[0],truncated=row.truncated)
                state="review_needed" if reasons else "eligible"
            elif candidates:state="review_needed";reasons=["存在多个可能门店，需老板逐项确认"]
            elif row.truncated:state="review_needed";reasons=["目录不完整，当前未匹配不能判断为未找到"]
            else:state="unmatched";reasons=["本次完整目录中未产生名称或完整地址匹配建议，可人工核对后选择"]
            if not crm["name"].strip():state="review_needed";reasons=["CRM商家名称缺失，请先确认资料"]
        comparisons.append({"customer":crm,"match_state":state,"reasons":reasons,"candidates":candidates,"existing_binding":bound})
    return {"is_owner":True,"customer_id":row.customer_id,"catalog":summary,"locations":locations,"comparisons":comparisons}


async def batch_items(db,row):return list((await db.scalars(select(Item).where(Item.batch_id==row.id).order_by(Item.position))).all())


def batch_summary(row,items):
    counts={x:sum(y.status==x for y in items) for x in ("queued","processing","bound","conflict","failed","cancelled","unknown")};counts["total"]=len(items)
    return {"id":row.id,"catalog_id":row.catalog_id,"customer_id":row.customer_id,"status":row.status,"revision":row.revision,"preview_hash":row.preview_hash,
        "expires_at":g.iso(row.expires_at),"created_at":g.iso(row.created_at),"updated_at":g.iso(row.updated_at),"message":row.message,"counts":counts}


async def batch_view(db,ctx,row):
    items=await batch_items(db,row)
    return {"is_owner":True,"customer_id":row.customer_id,"batch":batch_summary(row,items),"items":[{"id":x.id,"position":x.position,"customer":x.snapshot["customer"],"google":x.snapshot["google"],
        "status":x.status,"warnings":x.warnings,"binding_id":x.binding_id,"message":x.message,"error_code":x.error_code,"request_id":x.request_id} for x in items]}


async def get_context(db,user,customer_id=None):
    ctx=await context(db,user);customers=await customer_rows(db,ctx,customer_id)
    connections=list((await db.scalars(select(Connection).where(Connection.owner_id==ctx.identity).order_by(Connection.id))).all())
    bindings=await binding_data(db,[x for x in await own_bindings(db,ctx) if customer_id is None or x.customer_id==customer_id])
    cq=select(Catalog).where(Catalog.owner_id==ctx.identity);bq=select(Batch).where(Batch.owner_id==ctx.identity)
    if customer_id is not None:cq=cq.where(Catalog.customer_id==customer_id);bq=bq.where(Batch.customer_id==customer_id)
    catalogs=list((await db.scalars(cq.order_by(Catalog.created_at.desc()).limit(20))).all());batches=list((await db.scalars(bq.order_by(Batch.created_at.desc()).limit(20))).all())
    return {"is_owner":True,"customer_id":customer_id,"customers":[public_customer(x) for x in customers],"connections":[{"id":x.id,"label":x.label,"active":x.active,"needs_reconnect":x.needs_reconnect,"connected_at":g.iso(x.connected_at),"last_error":g.MESSAGES.get(x.last_error)} for x in connections],
        "bindings":bindings,"recent_catalogs":[catalog_summary(x) for x in catalogs],"recent_batches":[batch_summary(x,await batch_items(db,x)) for x in batches],"worker_enabled":worker_enabled()}


async def get_catalog(db,user,catalog_id):
    ctx=await context(db,user);return await catalog_view(db,ctx,await owned(db,Catalog,ctx,catalog_id))


async def get_batch(db,user,batch_id):
    ctx=await context(db,user);return await batch_view(db,ctx,await owned(db,Batch,ctx,batch_id))


async def request_result(db,user,request_id):
    ctx=await context(db,user);row=await receipt(db,ctx,request_id);require(row is not None,"尚未查到原请求，请保留编号后稍后再查",404)
    cat=await owned(db,Catalog,ctx,row.resource_id) if row.kind=="discovery" else None
    batch=await owned(db,Batch,ctx,row.resource_id) if cat is None else None
    return {"is_owner":True,"request_receipt":receipt_data(row),"catalog":await catalog_view(db,ctx,cat) if cat else None,"batch":await batch_view(db,ctx,batch) if batch else None}


async def discover(db,user,*,request_id,connection_id,customer_id=None):
    ctx=await context(db,user);key=g.media._key(request_id);payload={"connection_id":connection_id,"customer_id":customer_id}
    async with g.write(db):
        ctx=await context(db,user,lock=True);old=await receipt(db,ctx,key,"discovery",payload)
        if old:row=await owned(db,Catalog,ctx,old.resource_id)
        else:
            require(worker_enabled(),"门店发现队列暂未启用，请稍后重试",503)
            connection=await g._connection(db,ctx,connection_id,lock=True);require(not connection.needs_reconnect,"请先重新授权Google连接")
            if customer_id is not None:await customer(db,ctx,customer_id)
            pending=await db.scalar(select(Catalog.id).where(Catalog.owner_id==ctx.identity,Catalog.status.in_(("queued","processing"))).limit(1))
            require(pending is None,"已有门店发现正在处理，请先恢复查看该请求")
            # Expired discovery catalogs retain only their opaque receipt and
            # status after one day; selected identities live in frozen items.
            expired=list((await db.scalars(select(Catalog).where(Catalog.owner_id==ctx.identity,Catalog.expires_at<g.now()-timedelta(days=1)))).all())
            for old_catalog in expired:old_catalog.locations=[]
            stamp=g.now();row=Catalog(id=uuid4().hex,owner_id=ctx.identity,connection_id=connection_id,customer_id=customer_id,revision=1,status="queued",connection_marker=marker(connection),locations=[],truncated=False,message="门店发现已受理，后台读取中；可离开后恢复查看",created_at=stamp,updated_at=stamp)
            db.add(row);old=record(db,ctx,key,"discovery",payload,row.id)
    return {**await catalog_view(db,ctx,row),"request_receipt":receipt_data(old)}


async def ensure_new_pair(db,ctx,customer_id,location_name,*,ignore_item_id=None):
    # Never disclose a conflicting foreign owner's customer or binding identity.
    existing=await db.scalar(select(Binding.id).where(or_(Binding.customer_id==customer_id,Binding.location_id==location_name.rsplit("/",1)[1])).limit(1))
    require(existing is None,"客户或Google门店已有绑定；请在冲突清单人工核对，本流程不会覆盖或恢复")
    query=select(Item.id).where(Item.status.in_(("queued","processing")),or_(Item.customer_id==customer_id,Item.location_name.like("%/locations/"+location_name.rsplit("/",1)[1])))
    if ignore_item_id is not None:query=query.where(Item.id!=ignore_item_id)
    require(await db.scalar(query.limit(1)) is None,"此客户或Google门店已有接入请求处理中，请先核对原请求")


async def preview(db,user,*,request_id,catalog_id,expected_catalog_revision,items):
    ctx=await context(db,user);key=g.media._key(request_id);payload={"catalog_id":catalog_id,"expected_catalog_revision":expected_catalog_revision,"items":items}
    async with g.write(db):
        ctx=await context(db,user,lock=True);old=await receipt(db,ctx,key,"preview",payload)
        if old:row=await owned(db,Batch,ctx,old.resource_id)
        else:
            catalog=await owned(db,Catalog,ctx,catalog_id,lock=True)
            require(catalog.status=="ready" and catalog.revision==expected_catalog_revision and catalog.expires_at and g.aware(catalog.expires_at)>g.now(),"目录版本或有效期已变化，请重新发现门店")
            connection=await g._connection(db,ctx,catalog.connection_id,lock=True);require(marker(connection)==catalog.connection_marker and not connection.needs_reconnect,"Google连接已变化，请重新发现")
            require(len({x["customer_id"] for x in items})==len(items) and len({x["location_name"].rsplit("/",1)[1] for x in items})==len(items),"同一客户或Google门店不能在一批中重复选择",422)
            locations={x["location_name"]:x for x in catalog.locations};frozen=[]
            for pair in items:
                require(catalog.customer_id is None or pair["customer_id"]==catalog.customer_id,"所选客户不属于此目录范围",422)
                c=await customer(db,ctx,pair["customer_id"],write=True);require(c.status=="closed" and bool(c.business_name.strip()),"客户未合作或名称缺失，请先人工确认资料")
                loc=locations.get(pair["location_name"]);require(loc is not None and bool(loc["title"].strip()) and bool(loc["address"].strip()),"Google名称或地址缺失，不能进入绑定预检",422)
                await ensure_new_pair(db,ctx,c.id,loc["location_name"])
                frozen.append({"customer":public_customer(c),"google":dict(loc),"customer_hash":customer_hash(c),"connection_marker":marker(connection),"connection_id":connection.id,"warnings":identity_warnings(public_customer(c),loc,truncated=catalog.truncated)})
            stamp=g.now();identity=uuid4().hex;frozen_plan={"owner_id":ctx.identity,"customer_id":catalog.customer_id,"catalog_id":catalog.id,"catalog_revision":catalog.revision,"items":frozen}
            row=Batch(id=identity,owner_id=ctx.identity,catalog_id=catalog.id,customer_id=catalog.customer_id,kind="batch",status="preview",revision=1,preview_hash=g.digest(frozen_plan),snapshot=frozen_plan,expires_at=stamp+timedelta(seconds=PREVIEW_TTL),message="预检未绑定，请逐项核对身份后明确确认",created_at=stamp,updated_at=stamp);db.add(row)
            for index,value in enumerate(frozen):db.add(Item(id=uuid4().hex,batch_id=identity,owner_id=ctx.identity,position=index,customer_id=value["customer"]["id"],location_name=value["google"]["location_name"],request_id=str(uuid5(NAMESPACE_URL,"t24-google-onboarding:"+identity+":"+str(index))),status="preview",snapshot=value,warnings=value["warnings"],message="待老板确认此身份对应关系",created_at=stamp,updated_at=stamp))
            old=record(db,ctx,key,"preview",payload,identity)
    return {**await batch_view(db,ctx,row),"request_receipt":receipt_data(old)}


async def confirm(db,user,batch_id,*,request_id,expected_revision,preview_hash,confirmed_item_ids,confirmed):
    ctx=await context(db,user);key=g.media._key(request_id);payload={"batch_id":batch_id,"expected_revision":expected_revision,"preview_hash":preview_hash,"confirmed_item_ids":confirmed_item_ids,"confirmed":confirmed}
    async with g.write(db):
        ctx=await context(db,user,lock=True);old=await receipt(db,ctx,key,"confirm",payload);row=await owned(db,Batch,ctx,batch_id,lock=True)
        if not old:
            require(confirmed is True and worker_enabled(),"请确认当前身份清单，且接入队列必须启用",422)
            entries=await batch_items(db,row)
            require(row.kind=="batch" and row.status=="preview" and row.revision==expected_revision and row.preview_hash==preview_hash and g.digest(row.snapshot)==preview_hash and g.aware(row.expires_at)>g.now(),"预检版本或有效期已变化，请重新生成预检")
            require(len(confirmed_item_ids)==len(entries) and set(confirmed_item_ids)=={x.id for x in entries},"请确认当前预检的全部选中行",422)
            pending=list((await db.scalars(select(Item.id).where(Item.owner_id==ctx.identity,Item.status.in_(("queued","processing"))).limit(201))).all())
            require(len(pending)+len(entries)<=200,"待处理接入行较多，请先核对已有批次",422)
            for item in entries:
                require(item.snapshot==row.snapshot["items"][item.position],"预检行与冻结清单不一致，请重新预检")
                await fresh_item(db,ctx,item,check_unique=True)
            for item in entries:item.status="queued";item.message="已获老板确认，等待逐行实时核验并绑定";item.updated_at=g.now()
            row.status="queued";row.revision+=1;row.updated_at=g.now();row.message="批次已受理，可离开后恢复；未授权其他操作"
            old=record(db,ctx,key,"confirm",payload,row.id)
    return {**await batch_view(db,ctx,row),"request_receipt":receipt_data(old)}


async def cancel(db,user,batch_id,*,request_id,expected_revision,reason,confirmed):
    ctx=await context(db,user);key=g.media._key(request_id);payload={"batch_id":batch_id,"expected_revision":expected_revision,"reason":reason,"confirmed":confirmed}
    async with g.write(db):
        ctx=await context(db,user,lock=True);old=await receipt(db,ctx,key,"cancel",payload);row=await owned(db,Batch,ctx,batch_id,lock=True)
        if not old:
            require(confirmed is True and reason.strip() and row.revision==expected_revision,"批次版本已变化，请重新查看后取消")
            for item in await batch_items(db,row):
                if item.status in {"preview","queued","processing","unknown"}:item.status="cancelled";item.lease_token=None;item.updated_at=g.now();item.message="老板已取消此未完成行；已绑定行保留"
            row.status="cancelled";row.revision+=1;row.updated_at=g.now();row.message="剩余接入已取消；已经完成的绑定保持不变"
            old=record(db,ctx,key,"cancel",payload,row.id)
    return {**await batch_view(db,ctx,row),"request_receipt":receipt_data(old)}


async def fresh_item(db,ctx,item,*,check_unique=False):
    c=await customer(db,ctx,item.customer_id,write=True);require(c.status=="closed" and customer_hash(c)==item.snapshot["customer_hash"],"客户身份、地址或合作状态已变化，请重新预检")
    connection=await g._connection(db,ctx,item.snapshot["connection_id"],lock=True)
    require(not connection.needs_reconnect and marker(connection)==item.snapshot["connection_marker"],"Google连接已变化，请重新发现并预检")
    if check_unique:await ensure_new_pair(db,ctx,item.customer_id,item.location_name,ignore_item_id=item.id)
    return c,connection


async def finish_batch(db,row):
    if row.status=="cancelled":return
    entries=await batch_items(db,row);states={x.status for x in entries}
    if states&{"queued","processing"}:row.status="processing"
    elif states=={"bound"}:row.status="completed"
    elif "unknown" in states:row.status="unknown"
    elif "bound" in states:row.status="partial"
    else:row.status="failed"
    row.revision+=1;row.updated_at=g.now();row.message="接入结果已逐行保存，请核对冲突和未完成项" if row.status not in {"queued","processing"} else "正在逐行核验；已完成行不会重复绑定"


async def _process_item(db,user,identity,token,*,legacy=False):
    # All network reads happen after releasing SQL transactions. Final CAS and
    # customer/connection/uniqueness checks serialize with the native binding.
    item=await db.get(Item,identity,populate_existing=True)
    try:
        ctx=await context(db,user);require(item is not None and item.owner_id==ctx.identity,"接入行不可访问",404)
        batch=await owned(db,Batch,ctx,item.batch_id)
        if not legacy:require(g.digest(batch.snapshot)==batch.preview_hash and item.snapshot==batch.snapshot["items"][item.position],"冻结身份清单已变化，停止处理")
        await fresh_item(db,ctx,item,check_unique=not legacy);snapshot=dict(item.snapshot)
        await db.rollback()
        target=await g._read_provider(db,user,snapshot["connection_id"],"verify_location",snapshot["google"]["location_name"])
        require(isinstance(target,dict) and target.get("location_name")==snapshot["google"]["location_name"],"此Google门店未在当前授权账号中，请重新读取后选择",422)
        require(all(isinstance(target.get(k),str) for k in ("location_name","title","address")) and bool(target["title"].strip()) and bool(target["address"].strip()) and len(target["title"])<=255 and len(target["address"])<=1000,"Google名称或地址缺失或不完整，不能绑定",422)
        target={k:target[k] for k in ("location_name","title","address")}
        if not legacy:require({k:target[k] for k in ("location_name","title","address")}=={k:snapshot["google"][k] for k in ("location_name","title","address")},"Google门店身份已变化，请重新预检")
        async with g.write(db):
            ctx=await context(db,user,lock=True);item=await owned(db,Item,ctx,identity,lock=True);batch=await owned(db,Batch,ctx,item.batch_id,lock=True)
            require(item.status=="processing" and item.lease_token==token and batch.status!="cancelled","此行已取消或处理权已变化")
            if not legacy:require(g.digest(batch.snapshot)==batch.preview_hash and item.snapshot==batch.snapshot["items"][item.position],"冻结身份清单已变化，停止处理")
            require(item.lease_at is not None and g.aware(item.lease_at)>g.now()-timedelta(seconds=LEASE_SECONDS),"本次处理已过期，请查询原结果")
            await fresh_item(db,ctx,item,check_unique=not legacy)
            result=await g.bind_locked(db,ctx,request_id=item.request_id,customer_id=item.customer_id,connection_id=snapshot["connection_id"],location_name=item.location_name,allow_restore=legacy)
            item.binding_id=result["id"];item.status="bound";item.lease_token=None;item.updated_at=g.now();item.error_code=None;item.message="客户与Google门店已绑定；未分配员工或发布内容"
            if legacy:item.snapshot={**item.snapshot,"google":{**target,"observed_at":g.iso(g.now())}}
            await finish_batch(db,batch)
        return result
    except asyncio.CancelledError:raise
    except Exception as exc:
        await db.rollback()
        async with g.write(db):
            current=await db.get(Item,identity,populate_existing=True)
            if current and current.status=="processing" and current.lease_token==token:
                detail=str(exc.detail) if isinstance(exc,HTTPException) else "Google读取暂未完成，请先查询原接入记录"
                current.status="conflict" if isinstance(exc,HTTPException) and exc.status_code in {403,404,409,422} else "failed"
                current.error_code="IDENTITY_OR_ACCESS_CHANGED" if current.status=="conflict" else "GOOGLE_READ_FAILED"
                current.message=detail[:255];current.lease_token=None;current.updated_at=g.now()
                batch=await db.get(Batch,current.batch_id,populate_existing=True)
                if batch:await finish_batch(db,batch)
        if legacy:raise exc
        return None


async def legacy_bind(db,user,*,request_id,customer_id,connection_id,location_name):
    """Old tabs keep their synchronous response; uncertain work has a receipt."""
    ctx=await context(db,user);key=g.media._key(request_id);payload={"customer_id":customer_id,"connection_id":connection_id,"location_name":location_name}
    async with g.write(db):
        ctx=await context(db,user,lock=True);old=await receipt(db,ctx,key,"legacy_bind",payload)
        if old:
            batch=await owned(db,Batch,ctx,old.resource_id);item=(await batch_items(db,batch))[0]
            if item.status=="bound":
                bound,_,permissions=await g._binding(db,ctx,item.binding_id);return g.binding_data(bound,permissions)
            raise HTTPException(409,"原绑定请求已有持久结果，请先查询原编号；不会自动重发")
        c=await customer(db,ctx,customer_id,write=True);require(c.status=="closed","请先确认该客户仍处于合作已成交状态")
        connection=await g._connection(db,ctx,connection_id,lock=True);require(not connection.needs_reconnect,"Google连接需重新授权")
        stamp=g.now();identity=uuid4().hex;token=uuid4().hex
        snapshot={"customer":public_customer(c),"customer_hash":customer_hash(c),"google":{"location_name":location_name,"title":"","address":"","observed_at":g.iso(stamp)},"connection_id":connection.id,"connection_marker":marker(connection)}
        batch=Batch(id=identity,owner_id=ctx.identity,catalog_id=None,customer_id=customer_id,kind="legacy",status="processing",revision=1,preview_hash=g.digest(payload),snapshot=payload,expires_at=stamp+timedelta(seconds=PREVIEW_TTL),message="旧版绑定已受理，可按原编号查询",created_at=stamp,updated_at=stamp);db.add(batch)
        item=Item(id=uuid4().hex,batch_id=identity,owner_id=ctx.identity,position=0,customer_id=customer_id,location_name=location_name,request_id=key,status="processing",snapshot=snapshot,warnings=[],lease_token=token,lease_at=stamp,message="正在实时核验选中Google门店",created_at=stamp,updated_at=stamp);db.add(item);record(db,ctx,key,"legacy_bind",payload,identity)
    return await _process_item(db,user,item.id,token,legacy=True)


def sessions_factory():
    from core.database import db_manager
    return db_manager.async_session_maker


async def _actor(db,owner_id):
    row=await db.get(Employees,owner_id,populate_existing=True)
    require(row is not None,"老板账号不存在",403)
    return SimpleNamespace(id=str(row.id),role=row.role,name=row.name)


async def run_tick(*,sessions=None):
    sessions=sessions or sessions_factory()
    if sessions is None:return {"stage":"database_unavailable"}
    async with sessions() as db:
        if not await tables_available(db,TABLES):return {"stage":"schema_not_ready"}
        cat=await db.scalar(select(Catalog.id).where(Catalog.status.in_(("queued","processing"))).limit(1));item=await db.scalar(select(Item.id).where(Item.status.in_(("queued","processing"))).limit(1))
        if cat is None and item is None:return {"stage":"idle"}
        cutoff=g.now()-timedelta(seconds=LEASE_SECONDS)
        for model in (Catalog,Item):
            if await db.scalar(select(model.id).where(model.status=="processing",model.lease_at>cutoff).limit(1)) is not None:return {"stage":"busy"}
        await db.rollback();claimed=None
        async with g.write(db):
            stamp=g.now()
            for model in (Catalog,Item):
                processing=list((await db.scalars(select(model).where(model.status=="processing").with_for_update())).all())
                for row in processing:
                    if row.lease_at is not None and g.aware(row.lease_at)>stamp-timedelta(seconds=LEASE_SECONDS):return {"stage":"busy"}
                    row.status="unknown";row.lease_token=None;row.updated_at=stamp;row.message="上次处理已中断；请核对原请求，不自动重发";row.error_code="INTERRUPTED"
                    if model is Catalog:row.revision+=1
                    else:
                        batch=await db.get(Batch,row.batch_id,populate_existing=True)
                        if batch:await finish_batch(db,batch)
            row=await db.scalar(select(Catalog).where(Catalog.status=="queued").order_by(Catalog.created_at,Catalog.id).limit(1).with_for_update());kind="catalog"
            if row is None:row=await db.scalar(select(Item).where(Item.status=="queued").order_by(Item.created_at,Item.batch_id,Item.position,Item.id).limit(1).with_for_update());kind="item"
            if row is not None:
                token=uuid4().hex;row.status="processing";row.lease_token=token;row.lease_at=stamp;row.updated_at=stamp
                if kind=="catalog":row.revision+=1
                else:
                    batch=await db.get(Batch,row.batch_id,populate_existing=True)
                    if not batch or batch.kind!="batch" or batch.status not in {"queued","processing"}:
                        row.status="cancelled";row.lease_token=None;row.message="批次当前不可执行，已停止此行";row.updated_at=stamp
                        row=None
                    else:batch.status="processing";batch.revision+=1;batch.updated_at=stamp
                if row is not None:claimed=(kind,row.id,row.owner_id,token)
        if claimed is None:return {"stage":"recovered"}
        kind,identity,owner_id,token=claimed
        try:
            user=await _actor(db,owner_id)
            if kind=="item":await _process_item(db,user,identity,token);return {"stage":"item_processed"}
            row=await db.get(Catalog,identity,populate_existing=True);ctx=await context(db,user)
            connection=await g._connection(db,ctx,row.connection_id);require(marker(connection)==row.connection_marker and not connection.needs_reconnect,"Google连接已变化，请重新发现")
            saved_marker=dict(row.connection_marker);connection_id=row.connection_id;await db.rollback()
            result=await g._read_provider(db,user,connection_id,"discover_locations")
            require(isinstance(result,dict) and type(result.get("truncated")) is bool and isinstance(result.get("items"),list) and len(result["items"])<=500,"Google目录返回不完整",422)
            sanitized=[];stamp=g.now()
            for x in result["items"]:
                require(isinstance(x,dict) and isinstance(x.get("location_name"),str) and len(x["location_name"])<=200 and provider.LOCATION.fullmatch(x["location_name"]) and isinstance(x.get("title"),str) and len(x["title"])<=255 and isinstance(x.get("address"),str) and len(x["address"])<=1000,"Google目录返回不完整",422)
                sanitized.append({"location_name":x["location_name"],"title":x["title"],"address":x["address"],"observed_at":g.iso(stamp)})
            require(len({x["location_name"] for x in sanitized})==len(sanitized),"Google目录返回重复门店，请重新发现",422)
            async with g.write(db):
                ctx=await context(db,user,lock=True);row=await owned(db,Catalog,ctx,identity,lock=True);connection=await g._connection(db,ctx,connection_id,lock=True)
                require(row.status=="processing" and row.lease_token==token and marker(connection)==saved_marker and not connection.needs_reconnect,"目录处理权或连接已变化")
                require(row.lease_at is not None and g.aware(row.lease_at)>g.now()-timedelta(seconds=LEASE_SECONDS),"目录处理租约已过期，请重新发现")
                row.status="ready";row.revision+=1;row.lease_token=None;row.locations=sanitized;row.truncated=result["truncated"];row.observed_at=stamp;row.expires_at=stamp+timedelta(seconds=CATALOG_TTL);row.updated_at=stamp;row.message="门店目录已读取，请逐家核对；尚未绑定或授权员工";row.error_code=None
            return {"stage":"catalog_ready"}
        except asyncio.CancelledError:raise
        except Exception:
            await db.rollback()
            async with g.write(db):
                row=await db.get(Catalog,identity,populate_existing=True) if kind=="catalog" else await db.get(Item,identity,populate_existing=True)
                if row and row.status=="processing" and row.lease_token==token:
                    row.status="failed";row.lease_token=None;row.updated_at=g.now();row.error_code="ACCESS_OR_GOOGLE_READ_FAILED";row.message="未完成读取；请核对老板身份、Google连接后重新发起"
                    if kind=="catalog":row.revision+=1
                    else:
                        batch=await db.get(Batch,row.batch_id,populate_existing=True)
                        if batch:await finish_batch(db,batch)
            return {"stage":"failed"}


async def _loop():
    while True:
        try:await run_tick()
        except asyncio.CancelledError:raise
        except Exception:pass  # No identities, credentials, provider bodies or private data in logs.
        await asyncio.sleep(2)


async def start_worker():
    global _worker
    if not worker_enabled() or any(os.getenv(x,"").lower() in {"test","testing"} for x in ("APP_ENV","ENVIRONMENT","ENV")):return None
    if _worker is None or _worker.done():_worker=asyncio.create_task(_loop())
    return _worker


async def stop_worker(task):
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):await task
