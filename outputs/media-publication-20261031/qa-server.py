#!/usr/bin/env python3
"""Loopback-only preview: built CRM UI + real new router + disposable synthetic DB.

No production application lifespan, database, credentials or provider calls.
Existing routes are served by the retained synthetic UI fixture; business writes
outside the new Media Ops namespace are rejected by that fixture.
"""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from urllib.parse import urlsplit
import uuid

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
BACKEND = REPO / 'app/backend'
for key, value in {
    'APP_ENV': 'test', 'ENVIRONMENT': 'test',
    'DATABASE_URL': 'sqlite+aiosqlite:///:memory:',
    'JWT_SECRET_KEY': 'media-ops-local-synthetic-only-key',
    'ENFORCE_EMPLOYEE_STATUS': 'false', 'ENFORCE_EMPLOYEE_SESSIONS': 'false',
}.items():
    os.environ[key] = value
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

spec = importlib.util.spec_from_file_location('media_ui_base', ROOT.parent / 'crm-ui-focus-20261026/qa-fixture-server.py')
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
base.PORT = 8930
base.HOST = '127.0.0.1'
for identity, name in [(11, '合成运营小林'), (12, '合成只读运营'), (13, '合成未授权运营')]:
    employee = {'id': identity, 'name': name, 'role': 'ops', 'status': 'active',
                'department': 'operations', 'position': 'specialist',
                'email': f'ops{identity}@example.test', 'login_username': f'ops{identity}',
                'employee_code': f'QA{identity}', 'created_at': base.STAMP}
    base.EMPLOYEES.append(employee)
base.EMPLOYEES.append({'id':21,'name':'合成其他老板','role':'super_admin','status':'active','department':'management','position':'director','email':'owner2@example.test','login_username':'owner2','employee_code':'QA021','created_at':base.STAMP})
base.ACCOUNTS = {employee['email']: employee for employee in base.EMPLOYEES}
base.ACCOUNTS.update({employee['login_username']: employee for employee in base.EMPLOYEES})
for employee in base.EMPLOYEES:
    base.token_for(employee)

from fastapi import FastAPI, Request, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import text, select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from core.database import Base, get_db
from dependencies.auth import get_current_user
from schemas.auth import UserResponse
from models.customers import Customers
from models.employees import Employees
from models.customer_access_grants import CustomerAccessGrant
from models.service_progresses import Service_progresses
from models.customer_materials import Customer_materials
from models.operation_logs import Operation_logs
from models.media_operations import MediaOperationTask, MediaOperationEvent, MediaOperationPublicationSpec
from routers.media_operations import router
from routers.google_business import router as google_router
from routers import customer_materials as material_router
from models.google_business import *
from services import google_business_ai as google_ai
from types import SimpleNamespace
async def fake_ai_runtime(db):
 return SimpleNamespace(enabled=True,provider="deepseek",model="synthetic-reply-model",base_url="https://ai.synthetic.example/v1",api_key="SYNTHETIC-NOT-REAL-AI-KEY")
async def fake_ai_generate(runtime,messages):
 return json.dumps({"reply":"Thank you for sharing your experience. We are sorry the wait was longer than expected, and appreciate your feedback.","summary":"顾客反馈周末等候时间较长。","issues":["回应等候体验","避免未经核实的整改或补偿承诺"],"risk_flags":[]},ensure_ascii=False)
google_ai.resolve_ai_runtime_config=fake_ai_runtime
google_ai._generate_text=fake_ai_generate
from services import google_business_provider as google_provider
from cryptography.fernet import Fernet
import copy,time
for k,v in {"ENABLED":"true","API_APPROVED":"true","CLIENT_ID":"synthetic-client.apps.googleusercontent.com","CLIENT_SECRET":"SYNTHETIC-NOT-REAL-CLIENT-SECRET","TOKEN_KEY":Fernet.generate_key().decode(),"PUBLIC_URL":"https://crm.example.com"}.items(): os.environ["T24_GBP_"+k]=v
FAKE_REVIEWS=[{"name":"accounts/100/locations/1000/reviews/review_1","reviewer":{"displayName":"演示顾客 · 陈女士"},"starRating":"FIVE","comment":"环境很好，服务很细心，下次还会再来！","createTime":"2026-10-29T10:00:00Z","updateTime":"2026-10-29T10:00:00Z"},{"name":"accounts/100/locations/1000/reviews/review_2","reviewer":{"displayName":"演示顾客 · 李先生"},"starRating":"TWO","comment":"周末等候时间比较长，希望可以改善。","createTime":"2026-10-29T08:00:00Z","updateTime":"2026-10-29T08:00:00Z"}]
FAKE_POSTS=[]
class FakeGoogle:
 def __init__(self,connection=None): self.connection=connection
 async def locations(self): return {"items":[{"location_name":"accounts/100/locations/1000","title":"演示餐厅 · Harbor Noodles","address":"100 Demo Street, CA"},{"location_name":"accounts/100/locations/1001","title":"演示餐厅 · Garden Kitchen","address":"200 Demo Street, CA"},{"location_name":"accounts/100/locations/1002","title":"演示暂停 · Pine Bistro","address":"300 Demo Street, CA"},{"location_name":"accounts/100/locations/1003","title":"演示归档 · Lake Cafe","address":"400 Demo Street, CA"}],"truncated":False}
 async def reviews(self,location,page_token=None): return {"reviews":[copy.deepcopy(row) for row in FAKE_REVIEWS if row["name"].startswith(location+"/reviews/")]}
 async def review(self,name): return copy.deepcopy(next(x for x in FAKE_REVIEWS if x["name"]==name))
 async def reply(self,name,payload):
  row=next(x for x in FAKE_REVIEWS if x["name"]==name); row["reviewReply"]={"comment":payload["comment"],"updateTime":"2026-10-30T04:00:00Z","reviewReplyState":"APPROVED"}; return copy.deepcopy(row["reviewReply"])
 async def publish(self,location,payload):
  row={**copy.deepcopy(payload),"name":location+"/localPosts/preview_"+str(len(FAKE_POSTS)+1),"state":"LIVE","searchUrl":"https://www.google.com/search?preview=synthetic","createTime":datetime.now(timezone.utc).isoformat()}; FAKE_POSTS.append(row); return copy.deepcopy(row)
 async def posts(self,location): return {"localPosts":copy.deepcopy(FAKE_POSTS)}
 async def post(self,name): return copy.deepcopy(next(x for x in FAKE_POSTS if x["name"]==name))
google_provider.GoogleClient=FakeGoogle
os.environ["T24_GBP_SCHEDULER_ENABLED"]="false"
os.environ.pop("T24_GBP_SCHEDULER_ACTIVATION_FROM",None)
FAKE_REVIEWS.append({"name":"accounts/100/locations/1000/reviews/review_3","reviewer":{"displayName":"演示敏感投诉"},"starRating":"ONE","comment":"I felt sick after dinner and want a refund. Please review this concern.","createTime":"2026-10-30T08:00:00Z","updateTime":"2026-10-30T08:00:00Z"})

TEMP = tempfile.TemporaryDirectory(prefix='t24-media-ops-synthetic-')
engine = create_async_engine('sqlite+aiosqlite:///' + str(Path(TEMP.name) / 'qa.db'))
sessions = async_sessionmaker(engine, expire_on_commit=False)

async def get_synthetic_db():
    async with sessions() as session:
        yield session

async def actor(request: Request):
    identity = request.headers.get('x-synthetic-actor', '')
    employee = next((item for item in base.EMPLOYEES if str(item['id']) == identity), None)
    if not employee:
        raise HTTPException(401, 'Synthetic preview login required')
    return UserResponse(id=str(employee['id']), name=employee['name'], email=employee['email'], role=employee['role'])

@asynccontextmanager
async def lifespan(_app):
    tables = [Customers.__table__, Employees.__table__, CustomerAccessGrant.__table__,
              Service_progresses.__table__, Customer_materials.__table__, Operation_logs.__table__,
              MediaOperationTask.__table__, MediaOperationEvent.__table__, MediaOperationPublicationSpec.__table__, *[table for name,table in Base.metadata.tables.items() if name.startswith("google_business_")]]
    async with engine.begin() as connection:
        await connection.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
        await connection.execute(text('CREATE TABLE app_settings (config_key TEXT PRIMARY KEY, value_json TEXT)'))
    async with sessions() as db:
        for e in base.EMPLOYEES:
            db.add(Employees(id=e['id'], user_id='synthetic', name=e['name'], role=e['role'], status='active'))
        for identity, name, industry in [(101, '演示餐厅 · Garden Kitchen', '餐厅'), (102, '演示美业 · Blossom Studio', '美业'), (103, '演示餐厅 · Harbor Noodles', '餐厅')]:
            db.add(Customers(id=identity, business_name=name, contact_name='合成联系人', phone='+12025550101', industry=industry, status='closed'))
            db.add(Service_progresses(id=identity, customer_id=identity, customer_name=name, user_id='synthetic', service_stage='normal_ops', service_type='media_operation', package_name='合成代运营服务'))
            db.add(Customer_materials(id=identity, customer_id=identity, user_id='synthetic', title='已确认门店图片 · 合成', material_type='image', visibility='team', content_type='image/png', approval_status='approved'))
            for employee_id, access_level in [(11, 'read_write'), (12, 'read_only')]:
                db.add(CustomerAccessGrant(customer_id=identity, employee_id=employee_id,
                    access_level='read_write', scopes={'basic': 'read_only', 'delivery': 'read_write', 'materials': 'read_write' if employee_id == 11 else 'read_only'},
                    finance_access='none', invitation_source='owner_invitation', invitation_status='active'))
        await db.commit()
    yield
    await engine.dispose()

api = FastAPI(lifespan=lifespan)
api.include_router(router)
api.include_router(google_router)
api.include_router(material_router.router)
material_router.MATERIALS_ROOT = Path(TEMP.name) / 'synthetic-materials'
material_router.MATERIALS_ROOT.mkdir(parents=True, exist_ok=True)
api.dependency_overrides[get_db] = get_synthetic_db
api.dependency_overrides[get_current_user] = actor
CLIENT = None
WRITES = []
PREFIX = '/api/v1/media-operations'

def seed():
    owner = {'x-synthetic-actor': '1'}
    now = datetime.now(timezone.utc)
    examples = [
        (101, '周末菜单介绍 · 准备内容', 'instagram', 'draft', now + timedelta(hours=4)),
        (102, '门店环境与护理介绍', 'facebook', 'in_review', now - timedelta(hours=2)),
        (103, '新品展示 · 已审核待发布', 'google_business', 'ready', now + timedelta(hours=1)),
        (101, '周末活动 · 等待客户补图', 'instagram', 'blocked', now - timedelta(days=1)),
        (102, '本周门店介绍 · 已提交凭证', 'instagram', 'completed', now - timedelta(hours=3)),
        (102, '只读验收 · 门店资料介绍', 'instagram', 'draft', now + timedelta(days=1)),
    ]
    for customer, title, platform, status, due in examples:
        response = CLIENT.post(PREFIX, headers=owner, json={
            'client_request_id': str(uuid.uuid4()), 'customer_id': customer,
            'service_progress_id': customer, 'title': title, 'platform': platform,
            'due_at': due.isoformat(), 'timezone': 'America/Los_Angeles', 'assignee_id': 12 if title.startswith('只读验收') else 11,
            'content': '合成文案：分享门店环境与已确认的服务信息。此内容仅用于本地试用，不会发布到任何平台。', 'material_id': customer,
        })
        if response.status_code not in (200, 201):
            raise RuntimeError('Synthetic create failed: ' + response.text)
        row = response.json()
        actions = ['block'] if status == 'blocked' else ['submit', 'approve', 'complete'][:{'draft': 0, 'in_review': 1, 'ready': 2, 'completed': 3}[status]]
        for action in actions:
            response = CLIENT.post(f"{PREFIX}/{row['id']}/transition", headers=owner, json={
                'expected_revision': row['revision'], 'request_id': str(uuid.uuid4()), 'action': action,
                'note': '客户还未补充活动图片，请跟进。' if action == 'block' else '合成验收记录',
                **({'proof_url': 'https://www.instagram.com/p/SYNTHETIC_ONLY/'} if action == 'complete' else {}),
            })
            if response.status_code != 200:
                raise RuntimeError('Synthetic transition failed: ' + response.text)
            row = response.json()

async def readonly_scope():
    async with sessions() as db:
        for grant in (await db.execute(select(CustomerAccessGrant).where(CustomerAccessGrant.employee_id == 12))).scalars():
            grant.access_level = 'read_only'
            grant.scopes = {'basic': 'read_only', 'delivery': 'read_only', 'materials': 'read_only'}
        await db.commit()

async def seed_google():
    async with sessions() as db:
        db.add(GoogleBusinessConnection(id=1,owner_id=1,label="演示 Google 连接（仅本地）",token_encrypted=google_provider.encrypt({"access_token":"SYNTHETIC-ACCESS-TOKEN","refresh_token":"SYNTHETIC-REFRESH-TOKEN","scope":google_provider.SCOPE,"expires_at":time.time()+3600}),active=True,needs_reconnect=False))
        await db.flush()
        db.add(GoogleBusinessBinding(id=1,customer_id=103,customer_name="演示餐厅 · Harbor Noodles",connection_id=1,location_name="accounts/100/locations/1000",title="演示餐厅 · Harbor Noodles",address="100 Demo Street, CA",active=True,revision=1,lifecycle="active",primary_operator_id=11,primary_operator_name="合成运营小林",created_by_id=1,request_id=str(uuid.uuid4())))
        await db.flush()
        db.add(GoogleBusinessBinding(id=2,customer_id=101,customer_name="演示餐厅 · Garden Kitchen",connection_id=1,location_name="accounts/100/locations/1001",title="演示餐厅 · Garden Kitchen",address="",active=True,revision=1,lifecycle="active",created_by_id=1,request_id=str(uuid.uuid4())))
        await db.flush()
        db.add(GoogleBusinessGrant(binding_id=1,employee_id=11,can_reply=True,can_publish=True,granted_by_id=1))
        await db.execute(text("UPDATE media_operation_tasks SET material_id=NULL,material_title=NULL WHERE platform='google_business'"))
        # Regenerate owner approval after removing synthetic private image.
        row=(await db.execute(select(MediaOperationTask).where(MediaOperationTask.platform=='google_business'))).scalar_one()
        event=(await db.execute(select(MediaOperationEvent).where(MediaOperationEvent.task_id==row.id,MediaOperationEvent.action=='approve'))).scalar_one()
        event.snapshot={**event.snapshot,"material_id":None,"material_title":None}
        await db.commit()

async def seed_management():
    async with sessions() as db:
        for identity,name in [(104,"演示暂停 · Pine Bistro"),(105,"演示归档 · Lake Cafe"),(106,"其他老板商家 · 不应可见")]:
            db.add(Customers(id=identity,business_name=name,contact_name="合成联系人",phone="+12025550199",industry="餐厅",state="CA",status="closed"))
        await db.flush()
        for identity,customer,state,active in [(3,104,"paused",True),(4,105,"stopped",False)]:
            db.add(GoogleBusinessBinding(id=identity,customer_id=customer,customer_name="演示暂停 · Pine Bistro" if identity==3 else "演示归档 · Lake Cafe",connection_id=1,location_name="accounts/100/locations/"+str(999+identity),title="合成门店",address="",active=active,revision=1,lifecycle=state,created_by_id=1,request_id=str(uuid.uuid4())))
        db.add(GoogleBusinessConnection(id=2,owner_id=21,label="其他老板连接 · 不应可见",token_encrypted=google_provider.encrypt({"access_token":"SYNTHETIC-ACCESS-TOKEN-FOREIGN","refresh_token":"SYNTHETIC-REFRESH-TOKEN-FOREIGN","scope":google_provider.SCOPE,"expires_at":time.time()+3600}),active=True,needs_reconnect=False))
        await db.flush()
        db.add(GoogleBusinessBinding(id=5,customer_id=106,customer_name="其他老板商家 · 不应可见",connection_id=2,location_name="accounts/200/locations/2000",title="其他老板门店",address="",active=True,revision=1,lifecycle="active",created_by_id=21,request_id=str(uuid.uuid4())))
        db.add(GoogleBusinessAction(binding_id=1,customer_id=103,kind="review_reply",request_id=str(uuid.uuid4()),fingerprint="synthetic",actor_id=11,actor_name="合成运营小林",target_name="accounts/100/locations/1000/reviews/review_1",payload={"reply":"合成已确认回复，仅本地记录。"},status="succeeded",provider_state="APPROVED",message="合成平台确认",created_at=datetime.now(timezone.utc),updated_at=datetime.now(timezone.utc),confirmed_at=datetime.now(timezone.utc)))
        # Synthetic uploads remain private; never invent a public provider-readable image.
        await db.execute(text("UPDATE customer_materials SET file_url=NULL, source_type='upload', copyright_status='unknown' WHERE id=101"))
        await db.commit()
    FAKE_REVIEWS[0]["reviewReply"]={"comment":"Thank you for your kind feedback! This is a synthetic preview reply.","updateTime":"2026-10-30T04:00:00Z","reviewReplyState":"APPROVED"}
def seed_extra_google_draft():
    owner={"x-synthetic-actor":"1"}
    response=CLIENT.post(PREFIX,headers=owner,json={"client_request_id":str(uuid.uuid4()),"customer_id":101,"title":"合成 Google 草稿 · 尚未审核","platform":"google_business","due_at":(datetime.now(timezone.utc)+timedelta(hours=8)).isoformat(),"timezone":"America/Los_Angeles","assignee_id":11,"content":"合成内容，尚未审核不得发布。","material_id":101})
    if response.status_code not in (200,201): raise RuntimeError("Synthetic extra draft failed")

def seed_publications():
    owner={'x-synthetic-actor':'1'}
    examples=[
      ('合成优惠 · 完整条款与兑换链接', {'topic_type':'OFFER','event':{'title':'周末堂食八折','start_at':'2026-10-31T17:00:00Z','end_at':'2026-11-03T02:00:00Z'},'offer':{'coupon_code':'WEEKEND20','redeem_online_url':'https://example.com/redeem?campaign=weekend&utm_source=google','terms_conditions':'仅限堂食，周六至周一适用；不可与其他优惠同享。真实规则尚须商家确认。'}}),
      ('合成活动 · 完整日期与预约按钮', {'topic_type':'EVENT','event':{'title':'新品试吃交流日','start_at':'2026-11-07T18:00:00Z','end_at':'2026-11-08T01:00:00Z'},'call_to_action':{'action_type':'BOOK','url':'https://example.com/book?event=tasting'}}),
    ]
    for title,publication in examples:
      response=CLIENT.post(PREFIX,headers=owner,json={'client_request_id':str(uuid.uuid4()),'customer_id':103,'title':title,'platform':'google_business','due_at':(datetime.now(timezone.utc)+timedelta(hours=3)).isoformat(),'timezone':'America/Los_Angeles','assignee_id':11,'content':'纯合成验收内容：正文之外，优惠条款、活动起止和行动按钮须完整可见。不会发送至真实平台。','publication':publication})
      if response.status_code not in (200,201):raise RuntimeError('Synthetic publication create failed: '+response.text)
      row=response.json()
      for action in ['submit','approve']:
        response=CLIENT.post(f"{PREFIX}/{row['id']}/transition",headers=owner,json={'expected_revision':row['revision'],'request_id':str(uuid.uuid4()),'action':action,'note':'纯合成结构化内容核对'})
        if response.status_code!=200:raise RuntimeError('Synthetic publication review failed: '+response.text)
        row=response.json()

class PreviewHandler(base.FixtureHandler):
    def forward_media(self):
        employee = self.employee()
        if not employee:
            return self.json_response({'detail': '请使用本地合成账号登录'}, 401)
        length = int(self.headers.get('Content-Length') or 0)
        if length > 5*1024*1024:
            return self.json_response({'detail': 'preview request too large'}, 413)
        body = self.rfile.read(length) if length else None
        response = CLIENT.request(self.command, self.path, headers={
            'x-synthetic-actor': str(employee['id']), 'content-type': self.headers.get('Content-Type','application/json'),
        }, content=body)
        if self.command != 'GET':
            WRITES.append({'method': self.command, 'path': self.path, 'status': response.status_code, 'role': employee['role']})
        if response.headers.get('content-type','').startswith(('image/','video/','application/pdf','application/octet-stream')):
            self.send_response(response.status_code);self.common_headers(response.headers.get('content-type','application/octet-stream'));self.send_header('Content-Length',str(len(response.content)))
            if response.headers.get('content-disposition'):self.send_header('Content-Disposition',response.headers['content-disposition'])
            self.end_headers();self.wfile.write(response.content);return
        return self.json_response(response.json(), response.status_code, category='synthetic_media_router')

    def do_GET(self):
        path = urlsplit(self.path).path
        if not path.startswith(('/api/','/assets/','/__')) and not Path(path).suffix:
            body=(base.DIST/'index.html').read_text().replace('<title>', '<title>合成预览 · ',1).encode()
            self.send_response(200)
            self.common_headers('text/html; charset=utf-8')
            self.send_header('Content-Length',str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == '/__media__/mobile':
            from urllib.parse import parse_qs
            width=parse_qs(urlsplit(self.path).query).get('width',['390'])[0]
            if width not in ['320','390','430']:width='390'
            body=f'<html><meta name="viewport" content="width=device-width,initial-scale=1"><title>合成移动验收</title><body style="margin:0;background:#edf2f8"><iframe title="实际窄屏CRM" src="/media-ops" style="border:0;width:{width}px;height:844px;background:white"></iframe></body></html>'.encode()
            self.send_response(200);self.common_headers('text/html; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body);return
        if path == '/api/v1/entities/customers':
            from urllib.parse import parse_qs
            actor=self.employee()
            if not actor:return self.json_response({'detail':'合成账号尚未登录'},401)
            query=json.loads(parse_qs(urlsplit(self.path).query).get('query',['{}'])[0]);identity=int(query.get('id') or 0)
            can_read=actor['role']=='super_admin' or actor['id'] in (11,12) and identity in (101,102,103)
            can_write=actor['role']=='super_admin' or actor['id']==11 and can_read
            permissions={'access_level':'read_write' if can_write else 'read_only' if can_read else 'none','invitation_status':'active' if can_read else 'none','invitation_source':'owner_invitation' if can_read else None,'can_manage_access':actor['role']=='super_admin','modules':{key:{'read':can_read,'write':can_write} for key in ['basic','delivery','materials']},'finance_access':'none'}
            return self.json_response({'items':[{'id':identity,'business_name':'合成客户资料','effective_permissions':permissions}] if identity else [],'total':1 if identity else 0})
        if path.startswith((PREFIX,"/api/v1/google-business","/api/v1/entities/customer_materials")):

            return self.forward_media()
        if path == '/__media__/status':
            return self.json_response({'synthetic_only': True, 'real_backend_router': True,
                'production_access': False, 'provider_calls': False, 'synthetic_writes': WRITES,
                'blocked_other_writes': base.BLOCKED_WRITES})
        return super().do_GET()

    def do_POST(self):
        path=urlsplit(self.path).path
        if path.startswith('/api/v1/google-business/oauth') or path.startswith('/api/v1/google-business/connections'):
            return self.json_response({'detail':'本地合成验收不发起真实账号授权或连接'},409)
        if path.startswith((PREFIX,"/api/v1/google-business","/api/v1/entities/customer_materials")):
            return self.forward_media()
        return super().do_POST()

    do_PUT = do_POST
    do_PATCH = do_POST
    do_DELETE = do_POST

if __name__ == '__main__':
    with TestClient(api) as CLIENT:
        seed()
        CLIENT.portal.call(readonly_scope)
        CLIENT.portal.call(seed_google)
        CLIENT.portal.call(seed_management)
        seed_extra_google_draft()
        seed_publications()
        print(json.dumps({'preview': 'http://127.0.0.1:8930/media-ops?google=preview', 'synthetic_only': True, 'accounts': ['owner', 'ops11', 'ops12', 'ops13', 'owner2', 'sales'], 'password': base.PASSWORD}), flush=True)
        server = base.ThreadingHTTPServer((base.HOST, base.PORT), PreviewHandler)
        try:
            server.serve_forever()
        finally:
            server.server_close()
    TEMP.cleanup()
