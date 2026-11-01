"""Merchant-first UI and read-only projection. No schema or authority edits.

All 162 populated tables are compared before/after the isolated candidate and
live switch. Recovery uses the unchanged schema and preserves independent rows.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import socket
import stat
import tarfile
import types

HOST='iZj6c4cj7edgnhdimts4l7Z'
SCOPE='media-workspace-scale'
SOURCE_SHA = '7697e1adc61f72cf6b13896a3a41389d8a31b09d'
FRONTEND = '6a8a9ac27c6c'
APPLICATION_FREEZE_SHA = '18a4babc59853930e621b96ec6aa5055ef9b9630b4d1d6e29fd8152923fa17b5'
BASE_SOURCE='8b429dad8a2f144ea27527717d4811fb7ddc9b3c'
BASE_FRONTEND='c814db9f574f'
SCHEMA_REVISION=OLD_REVISION=NEW_REVISION='g32ed456e792'
PREFLIGHT_SHA='18ba4eca4d72fa6ef6caa10d555274545b9a9a1d40c7c66be982bf663e8d1b88'
ACTUAL_PREFLIGHT_SHA = 'f65f71cb6e3e617471dacddaddfd6323357279fc60fc382b5d35a71251356cc1'
BACKEND_FILES=frozenset({'services/media_workspace.py','routers/media_workspace.py'})
# Final immutable application/source hashes are filled only after root QA.
FRONTEND_FILES=frozenset(['app/frontend/src/components/MediaMerchantWorkspace.tsx', 'app/frontend/src/components/MediaPortfolioPanels.tsx', 'app/frontend/src/components/media-merchant-workspace.css', 'app/frontend/src/lib/media-workspace-api.ts', 'app/frontend/src/lib/media-workspace-preferences.ts'])
TEST_FILES=frozenset(['app/backend/tests/test_media_workspace.py', 'app/backend/tests/test_media_workspace_scale.py', 'app/frontend/tests/media-merchant-workflow.test.mjs', 'app/frontend/tests/media-workspace-scale.test.mjs', 'app/frontend/tests/google-onboarding.test.mjs'])
SOURCE_FILES=frozenset('app/backend/'+name for name in BACKEND_FILES)|FRONTEND_FILES|TEST_FILES
ORIGINAL_BACKEND_HASHES={'services/media_workspace.py': '14e031977f8db04f16bc40b7818416279eac52222e6352d39976bee848471bf9', 'routers/media_workspace.py': 'afb4588c6b58787507e8028837a7deeb153364388d270019c0dc1c89b85c4022'}
FINAL_BACKEND_HASHES = {'routers/media_workspace.py': '0748357e1292ad2e320b730aef643aeccc785eee71d461d541dcb3d1291b7b00', 'services/media_workspace.py': '426897bbd41d761b1e0dde9c5dd4df22da938d7a68e7de94e8fbd22a9b49f909'}
BACKEND_BEFORE=ORIGINAL_BACKEND_HASHES
BACKEND_AFTER=FINAL_BACKEND_HASHES
TRUE_FLAGS=('frontend_changed','all162_populated_tables_preserved','existing_full_environment_preserved','existing_ops_credentials_preserved')
FALSE_FLAGS=('database_migration','schema_changed','dependencies_changed','credentials_included','runtime_environment_changed','production_seed_rows','provider_requests','operations_execution_enabled','operations_scheduler_enabled')
H=lambda body:hashlib.sha256(body).hexdigest()


def need(value,code):
    if not value:raise RuntimeError(code)


def encoded(value):return (json.dumps(value,sort_keys=True,indent=2)+'\n').encode()
def digest(value):return H(json.dumps(value,sort_keys=True,separators=(',',':')).encode())


def local_bytes(path,maximum=16*1024**2):
    path=Path(path);before=path.lstat();need(path.resolve()==path.absolute() and stat.S_ISREG(before.st_mode) and before.st_nlink==1,'CANONICAL_REGULAR_LOCAL_FILE_REQUIRED')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as stream:opened=os.fstat(stream.fileno());body=stream.read(maximum+1)
    fields=lambda row:(row.st_dev,row.st_ino,row.st_size,row.st_mtime_ns,row.st_ctime_ns,row.st_mode,row.st_uid,row.st_nlink)
    need(fields(before)==fields(opened)==fields(path.lstat()) and len(body)<=maximum,'BOUNDED_UNCHANGED_LOCAL_FILE_REQUIRED');return body


def protected_read(path,sha):
    path=Path(path)
    for parent in path.parents:
        row=parent.lstat();need(parent.resolve()==parent and stat.S_ISDIR(row.st_mode) and row.st_uid==0 and not row.st_mode&0o022,'PROTECTED_HELPER_PARENT_REQUIRED')
    need(path.lstat().st_uid==0 and stat.S_IMODE(path.lstat().st_mode)==0o600,'ROOT_PRIVATE_HELPER_REQUIRED')
    body=local_bytes(path);need(H(body)==sha,'EXACT_REVIEWED_HELPER_REQUIRED');return body


def pins_ready():
    need(isinstance(ACTUAL_PREFLIGHT_SHA,str) and re.fullmatch('[a-f0-9]{64}',ACTUAL_PREFLIGHT_SHA) and ACTUAL_PREFLIGHT_SHA!='0'*64,'FINAL_CURRENT_READONLY_PREFLIGHT_REQUIRED')
    need(isinstance(SOURCE_SHA,str) and re.fullmatch('[a-f0-9]{40}',SOURCE_SHA) and SOURCE_SHA not in {'0'*40,BASE_SOURCE},'FINAL_IMMUTABLE_APPLICATION_SOURCE_REQUIRED')
    need(isinstance(FRONTEND,str) and re.fullmatch('[a-f0-9]{12}',FRONTEND) and FRONTEND not in {'0'*12,BASE_FRONTEND},'FINAL_REVIEWED_FRONTEND_REQUIRED')
    need(isinstance(APPLICATION_FREEZE_SHA,str) and re.fullmatch('[a-f0-9]{64}',APPLICATION_FREEZE_SHA) and APPLICATION_FREEZE_SHA!='0'*64,'FINAL_APPLICATION_FREEZE_REQUIRED')
    need(bool(FRONTEND_FILES) and isinstance(FINAL_BACKEND_HASHES,dict) and set(FINAL_BACKEND_HASHES)==BACKEND_FILES and all(isinstance(v,str) and re.fullmatch('[a-f0-9]{64}',v) for v in FINAL_BACKEND_HASHES.values()),'FINAL_EXACT_SOURCE_ALLOWLIST_REQUIRED')



def validate_summary(p):
    need(p['stage']=='MEDIA_WORKSPACE_SCALE_PREFLIGHT_CAPTURED' and p['sha256']==ACTUAL_PREFLIGHT_SHA and p['path']=='/opt/t24-crm/releases/media-workspace-scale-preflight-'+ACTUAL_PREFLIGHT_SHA[:12]+'.json' and p['source_sha']==BASE_SOURCE and p['static_source_sha']=='adb948da237f2056bf37e53c9e5ec25c42cb8f78' and p['frontend_version']==BASE_FRONTEND and p['schema_revision']==SCHEMA_REVISION and p['table_count']==162 and p['all162_current_tables_preserved'] is True and p['backend_changed_before']==ORIGINAL_BACKEND_HASHES and p['backend_file_count']==419,'EXACT_CURRENT162_BASELINE_REQUIRED')
    need(p['crm']['id']=='9b247014d54e57e5f671d3f8378c6b387c5301a87471b823e790b0d4965d072b' and p['crm']['image']=='sha256:ed057407d8866958a2966043ddc2457488d77cc00dd7bbabb608bcedc7c0bb09' and p['schema_sha256']=='c111f3fc3154eab704a25536280bf02dfd00d120867da7ed9727ec2c85ac4a7f' and p['content_security_policy_sha256']=='ead64b09efe8c4f35648aa8eafe8855c5268ecf0999e0918b3642dd9dfbfe7a6','EXACT_CURRENT_RUNTIME_SCHEMA_CSP_REQUIRED')
    need(p['environment_sha256']=='3d414fb4b9b5b1ae9bb5ecc1ce503be3c788f8bee27d0806de9d72fd3df0e223' and p['ops_environment_sha256']=='f334ac086b4f8eef3d92cc4b6444558f500590a2bd4020ce07d9d13f1947dfb2','EXACT_CURRENT_FULL_ENVIRONMENT_REQUIRED')
    need(p['google_scheduler_enabled'] is True and p['google_scheduler_activation_from']=='2026-10-30T19:42:04Z' and p['existing_asset_worker_enabled'] is True and p['onboarding_worker_default_enabled'] is True,'EXACT_EXISTING_WORKER_POLICY_REQUIRED')
    need(all(p[key] is False for key in ('ops_execution_enabled','ops_scheduler_enabled','schema_changed','permissions_changed','credential_file_content_read','private_content_read','business_writes','provider_requests','runtime_changed')),'READONLY_PRESERVING_BASELINE_REQUIRED')



def next_nginx(original,old_root,new_root):
    old,new=os.fsencode(str(old_root)),os.fsencode(str(new_root))
    need(original.count(old)==1 and new not in original,'EXACT_SINGLE_STATIC_ROOT_REQUIRED')
    updated=original.replace(old,new,1);need(updated.replace(new,old,1)==original,'ONLY_STATIC_ROOT_CHANGE_ALLOWED');return updated


def extract(release,manifest,core):
    seen=set();total=0
    with tarfile.open(release/'payload.tar.gz','r:gz') as archive:
        for item in archive:
            path=Path(item.name);need(item.isfile() and item.name in manifest['files'] and item.name not in seen and not path.is_absolute() and '..' not in path.parts and str(path)==item.name and 0<item.size<=16*1024**2,'EXACT_REGULAR_PAYLOAD_MEMBER_REQUIRED')
            total+=item.size;need(total<64*1024**2 and len(seen)<10000,'BOUNDED_PAYLOAD_REQUIRED');body=archive.extractfile(item).read(item.size+1)
            need(len(body)==item.size and H(body)==manifest['files'][item.name],'EXACT_PAYLOAD_HASH_REQUIRED')
            parent=release
            for part in path.parts[:-1]:parent/=part;core.mkdir(parent)
            core.write(release/path,body);seen.add(item.name)
    need(seen==set(manifest['files']),'COMPLETE_EXACT_PAYLOAD_REQUIRED')


def _recovery_dependencies(pf):
    """Load immutable parent proofs without executing a stopped container.

    Capture/prepare/activate keep pf.dependencies' live inventory assertion.
    Recovery can begin after the original has stopped: the retained source
    overlay checker validates its pinned image and stopped filesystem instead.
    No process is started and no database/credential content is restored here.
    """
    need(os.geteuid()==0 and socket.gethostname()==pf.HOST,'EXACT_ROOT_SERVER_REQUIRED')
    code=pf.read(pf.OLD/'release.py',pf.HELPER,131072)
    mobile=types.ModuleType('_scale_recovery_mobile_release');mobile.__file__=str(pf.OLD/'release.py');exec(compile(code,mobile.__file__,'exec'),mobile.__dict__)
    need(mobile.SOURCE_SHA==pf.STATIC_SOURCE and mobile.BASE_SOURCE==pf.SOURCE and mobile.FRONTEND==pf.FRONTEND and mobile.HEAD==pf.REVISION,'EXACT_MOBILE_AND_BACKEND_SOURCE_REQUIRED')
    args=types.SimpleNamespace(release=pf.OLD,manifest_sha256=pf.MANIFEST,payload_sha256=pf.PAYLOAD,preflight=pf.ROOT/('google-business-onboarding-mobile-preflight-'+pf.PREFLIGHT[:12]+'.json'),preflight_sha256=pf.PREFLIGHT,review_sha256=pf.PREPARED)
    wrapper=mobile.Release(args);prepared=json.loads(pf.read(pf.OLD/'prepared.json',pf.PREPARED));deployed=json.loads(pf.read(pf.OLD/'deployed.json',pf.DEPLOYED));mobile.validate_prepared(prepared,pf.MANIFEST,pf.PAYLOAD,pf.PREFLIGHT)
    need(deployed['stage']=='GOOGLE_ONBOARDING_MOBILE_STATIC_DEPLOYED' and deployed['source_sha']==pf.STATIC_SOURCE and deployed['backend_source_sha']==pf.SOURCE and deployed['frontend_version']==pf.FRONTEND and deployed['runtime']==pf.RUNTIME and deployed['public_root']==str(pf.PUBLIC) and deployed['prepared_sha256']==pf.PREPARED,'EXACT_COMPLETED_MOBILE_DEPLOYMENT_REQUIRED')
    need(all(deployed[x] is True for x in ('all162_rows_preserved','static_only','content_security_policy_unchanged','old_hashed_assets_preserved')) and all(deployed[x] is False for x in ('database_writes','schema_changes','container_restarts','permissions_changes','environment_changes','provider_or_publication_actions')),'EXACT_PRESERVED_DATA_AND_AUTHORITY_REQUIRED')
    module,flow,inventory=wrapper.pf.dependencies()
    need(len(inventory)==419 and all(inventory.get(name)==sha for name,sha in ORIGINAL_BACKEND_HASHES.items()),'EXACT_CURRENT419_BACKEND_SOURCE_REQUIRED')
    original=flow.m.inspect(pf.RUNTIME['id'])
    need(original['Id']==pf.RUNTIME['id'] and flow.m.runtime(original)==pf.RUNTIME,'EXACT_RECOVERY_ORIGINAL_RUNTIME_REQUIRED')
    flow.source_boundary(original,inventory)
    pf._CACHE=(module,flow,inventory,wrapper,deployed)
    return pf._CACHE[:3]


def _load(args):
    pf=types.ModuleType('_workspace_scale_preflight');pf.__file__=str(args.release/'preflight.py');exec(compile(protected_read(args.release/'preflight.py',PREFLIGHT_SHA),pf.__file__,'exec'),pf.__dict__)
    last,flow,inventory=_recovery_dependencies(pf) if getattr(args,'phase',None)=='recover' else pf.dependencies();retained=flow.retained
    # In-memory parameters only; frozen source helpers remain byte-identical.
    retained.SOURCE_SHA,retained.BASE_SOURCE,retained.FRONTEND=SOURCE_SHA,BASE_SOURCE,FRONTEND
    return pf,flow,inventory,retained



class Methods:
    def __init__(self,args,pf,flow,inventory,retained):
        self.args,self.pf,self.flow,self.retained=args,pf,flow,retained
        self.c,self.ctx,self.m,self.base,self.safe,self.helper,self.pins=flow.c,flow.ctx,flow.m,flow.base,flow.safe,flow.helper,flow.pins
        c=self.c;self.proof=c.strict_json(c.read(args.preflight,sha=args.preflight_sha256));self.manifest=c.strict_json(c.read(args.release/'manifest.json',sha=args.manifest_sha256));c.read(args.release/'payload.tar.gz',maximum=16*1024**2,sha=args.payload_sha256)
        need(self.proof['backend_inventory']==inventory,'EXACT_DEPLOYED_PARENT_INVENTORY_REQUIRED')
        self.source,self.version=SOURCE_SHA,FRONTEND;self.public=Path('/var/www/t24-crm-public/'+SCOPE+'-'+SOURCE_SHA[:12]+'-20261102')
        need(args.release==Path('/opt/t24-crm/releases/'+SCOPE+'-'+SOURCE_SHA[:12]+'-20261102'),'EXACT_RELEASE_NAMESPACE_REQUIRED');self.validate()
        m=self.m;p=self.proof;m.SOURCE,m.SCOPE,m.BACKEND=SOURCE_SHA,SCOPE,set(BACKEND_FILES);m.BASELINE_FRONTEND,m.FRONTEND_VERSION=BASE_FRONTEND,FRONTEND
        m.PUBLIC,m.NGINX_SHA,m.STATIC_SHA=Path(p['public_root']),p['nginx_sha256'],p['public_inventory_sha256'];m.OLD_ID,m.BASE_IMAGE,m.OLD_CONFIG=(p['crm'][key] for key in ('id','image','config'))
        m.public_root=lambda:self.public;m.next_nginx=lambda original:next_nginx(original,p['public_root'],self.public)
        self.old_name='t24-crm-before-'+SCOPE+'-'+SOURCE_SHA[:12];self.candidate_name='t24-crm-candidate-'+SCOPE+'-'+SOURCE_SHA[:12];self.offline_name='t24-'+SCOPE+'-probe-'+SOURCE_SHA[:12]


    def validate(self):
        p,v,a=self.proof,self.manifest,self.args
        need(p['stage']=='MEDIA_WORKSPACE_SCALE_READONLY_PREFLIGHT' and p['source_sha']==BASE_SOURCE and p['frontend_version']==BASE_FRONTEND and p['schema_revision']==SCHEMA_REVISION and len(p['rows'])==162 and p['all162_current_tables_preserved'] is True,'EXACT_CURRENT_POPULATED_ALL162_PROOF_REQUIRED')
        need(v['source_sha']==SOURCE_SHA and v['frontend_version']==FRONTEND and v['baseline_source_sha']==BASE_SOURCE and v['baseline_frontend_version']==BASE_FRONTEND and v['schema_revision']==v['old_schema_revision']==SCHEMA_REVISION and v['additive_tables']==[],'EXACT_SCHEMA_FREE_SOURCE_SCOPE_REQUIRED')
        need(v['application_freeze_sha256']==APPLICATION_FREEZE_SHA and set(v['changed_source_files'])==SOURCE_FILES and len(v['changed_source_files'])==len(SOURCE_FILES) and v['preflight_sha256']==a.preflight_sha256==ACTUAL_PREFLIGHT_SHA and v['payload_sha256']==a.payload_sha256,'EXACT_APPLICATION_FREEZE_AND_PROOF_REQUIRED')
        need(all(v[key] is True for key in TRUE_FLAGS) and all(v[key] is False for key in FALSE_FLAGS),'EXACT_READ_UI_ONLY_FLAGS_REQUIRED')
        need(v['backend_before']==ORIGINAL_BACKEND_HASHES and v['backend_after']==FINAL_BACKEND_HASHES and {name[8:] for name in v['files'] if name.startswith('backend/')}==BACKEND_FILES,'EXACT_TWO_READONLY_MODULES_REQUIRED')
        need(all(v['files']['backend/'+name]==sha for name,sha in FINAL_BACKEND_HASHES.items()) and all(re.fullmatch('[a-f0-9]{64}',sha) for sha in v['files'].values()) and
             {'static/index.html','static/app-version.json'}<=set(v['files']) and all(name in {'backend/'+x for x in BACKEND_FILES} or name.startswith('static/') and self.m.static_path(name[7:]) for name in v['files']),'EXACT_RUNTIME_AND_STATIC_PAYLOAD_REQUIRED')

    def environment(self,info):
        observed=self.flow.environment(info)
        need(observed==(self.proof['environment_sha256'],self.proof['ops_environment_sha256']),'EXACT_CAPTURED_FULL_ENVIRONMENT_REQUIRED')
        return observed


    def nginx(self,updated=False):
        p,m=self.proof,self.m;body=m.NGINX.read_bytes();active=m.run(['nginx','-T'],'ACTIVE_NGINX_REQUIRED');observed=H(active)
        if updated:
            old,new=os.fsencode(p['public_root']),os.fsencode(str(self.public));need(body.count(new)==active.count(new)==1,'EXACT_NEW_STATIC_ROOT_REQUIRED');body=body.replace(new,old,1);active=active.replace(new,old,1)
        need(H(body)==p['nginx_sha256'] and H(active)==p['active_nginx_sha256'],'OTHER_NGINX_BYTES_CHANGED');return observed

    def protections(self,*,updated=False,recovery=False):
        m,p=self.m,self.proof
        need(self.safe.safe_private_boundary(m,self.pins)==p['private_boundary'],'PRIVATE_BOUNDARY_DRIFT')
        credentials={'ops':self.safe.protected_metadata(self.c.ENV_FILE),'google':self.safe.protected_metadata(self.safe.GBP_ENV),
            'meta_read':self.safe.protected_metadata(self.ctx.workflow.core.ENV_FILE),'meta_legacy':self.safe.protected_metadata(self.ctx.workflow.core.LEGACY_ENV_FILE)}
        need(m.credential_boundary()==p['credential_boundary'] and credentials==p['credential_metadata'],'EXISTING_CREDENTIAL_METADATA_DRIFT')
        row=m.BUSINESS.stat();need([row.st_dev,row.st_ino]==p['database_identity'] and m.schema_signature(m.BUSINESS,SCHEMA_REVISION)==p['schema_sha256'],'DATABASE_IDENTITY_OR_SCHEMA_DRIFT')
        (self.retained.sequence_boundary(p['database_metadata'],self.metadata(m.BUSINESS),recovery=True) if recovery else self.retained.live_sequence_boundary(p['database_metadata'],self.metadata(m.BUSINESS)))
        need(digest(m.tree(m.PUBLIC))==p['public_inventory_sha256'],'ORIGINAL_STATIC_CONTENT_DRIFT');self.nginx(updated)


    def current(self):
        self.protections();m,p=self.m,self.proof;old=m.inspect('t24-crm');need(old['State']['Running'] is True and m.runtime(old)==p['crm'],'EXACT_CURRENT_RUNTIME_REQUIRED')
        self.environment(old);self.ctx.workflow.pf.google_environment(old);m.verify_secret_mount(old);m.verify_production_worker_enabled(old);m.retained().require_safe_original_restart(old)
        before=m.inventory(old['Id']);need(before==p['backend_inventory'] and digest(before)==p['backend_inventory_sha256'] and len(before)==p['backend_file_count'] and all(before.get(name)==sha for name,sha in ORIGINAL_BACKEND_HASHES.items()),'CURRENT_BACKEND_SOURCE_DRIFT')
        need(self.retained.evidence(self.rows())==p['rows'],'CURRENT_ALL162_ROWS_DRIFT');m.ready(old['Id']);return old,before


    def image(self):
        m=self.m;need(m.image_id(m.BASE_IMAGE)==m.BASE_IMAGE,'EXACT_EXISTING_IMAGE_REQUIRED');base='t24-crm:'+SCOPE+'-base-'+SOURCE_SHA[:12];prior=m.image_id(base);need(prior is None or prior==m.BASE_IMAGE,'BASE_IMAGE_TAG_DRIFT')
        if prior is None:m.run(['docker','image','tag',m.BASE_IMAGE,base],'BASE_TAG_FAILED')
        docker='FROM '+base+'\n'+''.join('COPY backend/'+name+' /app/backend/'+name+'\n' for name in sorted(BACKEND_FILES))
        m.write(self.args.release/'Dockerfile',docker.encode());m.write(self.args.release/'.dockerignore',b'*\n!Dockerfile\n!backend\n!backend/**\n')
        tag='t24-crm:'+SCOPE+'-'+SOURCE_SHA[:12]
        result=self.pf.dependencies()[0].capture_public_build(['/usr/bin/env','DOCKER_BUILDKIT=0','docker','build','--network=none','--pull=false','-t',tag,str(self.args.release)],self.args.release/'app-build-public.log')
        m.write(self.args.release/'app-build-result.json',encoded(result))
        need(result['exit_code']==0 and result['build_daemon_result_known'],'EXACT_READONLY_PROJECTION_IMAGE_BUILD_FAILED')
        image=m.image_id(tag);need(m.image_id(base)==m.BASE_IMAGE and re.fullmatch('sha256:[a-f0-9]{64}',image or ''),'EXACT_BUILT_CANDIDATE_IMAGE_REQUIRED');return image



    def offline_args(self,data,image):
        command=self.ctx.module.OperationsMethods.offline_args(self,data,image)
        command[-1:-1]=['-e','T24_MEDIA_ASSET_WORKER_ENABLED=false','-e','T24_GBP_ONBOARDING_WORKER_ENABLED=false']
        return command

    def verify_offline_environment(self,info):
        key='T24_GBP_ONBOARDING_WORKER_ENABLED';rows=info['Config']['Env']
        need(isinstance(rows,list) and all(isinstance(row,str) for row in rows) and [row for row in rows if row.split('=',1)[0]==key]==[key+'=false'],'EXACT_ISOLATED_ONBOARDING_WORKER_DISABLED_REQUIRED')
        import copy
        projected=copy.deepcopy(info);projected['Config']['Env']=[row for row in rows if row.split('=',1)[0]!=key]
        self.base.verify_disabled_environment(projected)

    def timestamp_probe(self):
        return "import sys,socket\ndef blocked(*a,**k):raise AssertionError('NO_PROVIDER_NETWORK')\nsocket.socket.connect=blocked\nassert sys.version_info[:2]==(3,10)\nfrom services.meta_operations_provider import _timestamp\nassert _timestamp('2026-11-01T00:00:00+0000')=='2026-11-01T00:00:00+00:00'\nassert _timestamp('2026-11-01T00:00:00-0430')=='2026-11-01T04:30:00+00:00'\nassert _timestamp('2026-11-01T00:00:00Z')=='2026-11-01T00:00:00+00:00'\nassert _timestamp('2026-11-01T00:00:00') is None and _timestamp('2026-11-01T00:00:00+2460') is None\nprint('EXACT_PYTHON310_COMPACT_TIMEZONE_CANARY')\n"

    def projection_probe(self):
        return """import asyncio,socket,sys
from types import SimpleNamespace
assert sys.version_info[:2]==(3,10)
def blocked(*a,**k):raise AssertionError('NO_PROVIDER_NETWORK')
socket.socket.connect=blocked
from main import app
import fastapi.routing
prefix='/api/v1/media-workspace'
expected={(prefix+'/merchants','GET'),(prefix+'/workspace','GET')}
schema=app.openapi()
actual={(p,m.upper()) for p,v in schema['paths'].items() if p.startswith(prefix) for m in v if m.lower() in {'get','post','put','patch','delete','head','options','trace'}}
assert actual==expected
contexts=list(fastapi.routing.iter_route_contexts(app.routes)) if hasattr(fastapi.routing,'iter_route_contexts') else app.routes
registered=[(x.path,m,getattr(getattr(x,'endpoint',None),'__module__','')) for x in contexts if getattr(x,'path','').startswith(prefix) for m in (getattr(x,'methods',set()) or set())]
assert len(registered)==2 and {(p,m) for p,m,_ in registered}==expected and all(mod=='routers.media_workspace' for _,_,mod in registered)
import httpx
from fastapi import FastAPI
from routers.media_workspace import router
from dependencies.auth import get_current_user
from core.database import get_db
class NoDb:
 def __getattr__(self,name):raise AssertionError('DENIED_ROLE_MUST_NOT_QUERY_DATABASE')
async def database():yield NoDb()
actor=SimpleNamespace(id='2147483647',role='sales',email='synthetic-role-probe@invalid.local')
async def user():return actor
isolated=FastAPI();isolated.include_router(router)
isolated.dependency_overrides[get_db]=database;isolated.dependency_overrides[get_current_user]=user
async def check():
 async with httpx.AsyncClient(transport=httpx.ASGITransport(app=isolated),base_url='https://t24-crm.com',follow_redirects=False) as client:
  for role in ('sales','finance'):
   actor.role=role
   for path in ('/merchants','/workspace?start=2026-11-01T00:00:00Z&end=2026-11-02T00:00:00Z'):
    response=await client.get(prefix+path)
    assert response.status_code==403
    assert response.headers.get('cache-control')=='private, no-store'
    assert response.headers.get('referrer-policy')=='no-referrer'
asyncio.run(check())
print('EXACT_PY310_TWO_GET_PROJECTION_ROUTES_ROLE_DENIED')
"""

    def prepare(self):
        self.helper.docker_timestamp_probe();m,a=self.m,self.args;old,before=self.current();need({x.name for x in a.release.iterdir()}=={'release.py','preflight.py','manifest.json','payload.tar.gz'},'FRESH_STAGING_REQUIRED')
        extract(a.release,self.manifest,self.c);expected={**before,**FINAL_BACKEND_HASHES};runtime_sha=self.record('original-runtime.json',m.runtime(old));before_sha=self.record('backend-original-inventory.json',before);after_sha=self.record('backend-candidate-inventory.json',expected)
        image=self.image();data=a.release/'probe-data';data.mkdir(mode=0o700);(a.release/'probe-logs').mkdir(mode=0o700);m.backup(m.BUSINESS,data/'crm_prod.db')
        rows=self.rows(data/'crm_prod.db');metadata=self.metadata(data/'crm_prod.db');need(self.retained.evidence(rows)==self.proof['rows'] and m.schema_signature(data/'crm_prod.db',SCHEMA_REVISION)==self.proof['schema_sha256'],'EXACT_ISOLATED_ALL162_COPY_REQUIRED')
        self.retained.live_sequence_boundary(self.proof['database_metadata'],metadata);need(not m.inspect_optional(self.offline_name),'FRESH_OFFLINE_NAME_REQUIRED')
        command=self.offline_args(data,image);command[2:2]=['--name',self.offline_name,'-d'];m.run(command,'OFFLINE_START_FAILED')
        try:
            m.ready(self.offline_name);self.verify_offline_environment(m.inspect(self.offline_name));need(m.inventory(self.offline_name)==expected,'EXACT_OFFLINE_SOURCE_REQUIRED')
            checks=[(self.projection_probe(),b'EXACT_PY310_TWO_GET_PROJECTION_ROUTES_ROLE_DENIED'),(self.timestamp_probe(),b'EXACT_PYTHON310_COMPACT_TIMEZONE_CANARY'),(self.flow.existing_routes_probe(),b'EXACT_OPERATIONS_AND_EXISTING_ROUTES'),(self.base.gbp_disabled_probe(),b'EXACT_GBP_DISABLED_UNCONFIGURED_NO_NETWORK'),(self.ctx.workflow.meta_disabled_probe(),b'EXACT_META_ABSENT_DISABLED_NO_NETWORK'),(self.ctx.workflow.operations_disabled_probe(),b'EXACT_OPERATIONS_UNCONFIGURED_OFF_NO_NETWORK'),(self.ctx.workflow.owner_denied_probe(),b'EXACT_NONOWNER_ROLE_READ_DENIED_NO_SQL_OR_NETWORK')]
            for code,marker in checks:need(marker in m.run(['docker','exec',self.offline_name,'python','-B','-c',code],'OFFLINE_CANARY_FAILED'),'EXACT_OFFLINE_CANARY_MARKER_REQUIRED')
        finally:m.run(['docker','stop','--time','20',self.offline_name],'OFFLINE_STOP_FAILED',45)
        need(self.rows(data/'crm_prod.db')==rows and self.metadata(data/'crm_prod.db')==metadata and m.schema_signature(data/'crm_prod.db',SCHEMA_REVISION)==self.proof['schema_sha256'],'OFFLINE_ALL162_DATA_SCHEMA_METADATA_CHANGED')
        root,static=m.stage_public(a.release,self.manifest);nginx_sha=H(m.next_nginx(m.NGINX.read_bytes()));self.current()
        result={'stage':'MEDIA_WORKSPACE_SCALE_PREPARED','source_sha':SOURCE_SHA,'frontend_version':FRONTEND,'schema_revision':SCHEMA_REVISION,'old_schema_revision':SCHEMA_REVISION,'table_count':162,
            'old_crm':m.runtime(old),'candidate_image':image,'original_runtime_sha256':runtime_sha,'original_inventory_sha256':before_sha,'candidate_inventory_sha256':after_sha,'public_root':str(root),'public_inventory_sha256':static,'nginx_next_sha256':nginx_sha,
            'preflight_sha256':a.preflight_sha256,'manifest_sha256':a.manifest_sha256,'payload_sha256':a.payload_sha256,
            **{key:True for key in PREPARED_TRUE},**{key:False for key in PREPARED_FALSE}}
        return {**result,'receipt_sha256':self.record('prepared.json',result)}

    def reviewed(self):
        a,m=self.args,self.m;need(re.fullmatch('[a-f0-9]{64}',a.review_sha256 or ''),'CANONICAL_PREPARED_REVIEW_REQUIRED');r=self.c.strict_json(m.read(a.release/'prepared.json',a.review_sha256));validate_prepared(r,a.manifest_sha256,a.payload_sha256,a.preflight_sha256)
        runtime=self.c.strict_json(m.read(a.release/'original-runtime.json',r['original_runtime_sha256']));old=m.inspect(runtime['id']);before=self.c.strict_json(m.read(a.release/'backend-original-inventory.json',r['original_inventory_sha256']));expected=self.c.strict_json(m.read(a.release/'backend-candidate-inventory.json',r['candidate_inventory_sha256']))
        need(runtime==r['old_crm']==self.proof['crm'] and m.runtime(old)==runtime and digest(before)==self.proof['backend_inventory_sha256'] and expected=={**before,**FINAL_BACKEND_HASHES},'EXACT_PREPARED_ORIGINAL_AND_SOURCE_REQUIRED')
        need(m.image_id(r['candidate_image'])==r['candidate_image'] and m.verify_public(self.public,self.manifest)==r['public_inventory_sha256'],'PREPARED_IMAGE_OR_STATIC_DRIFT');return r,old,before,expected

    def fresh(self,r,old,before,expected,state,*,updated=False,live=False,recovery=False):
        self.protections(updated=updated,recovery=recovery)
        need(self.m.verify_public(self.public,self.manifest)==r['public_inventory_sha256'],'STAGED_STATIC_CONTENT_DRIFT')
        original,candidate=self.identities(state,old);self.retained.compare(candidate,old,self.m)
        self.environment(candidate);self.ctx.workflow.pf.google_environment(candidate);self.m.verify_secret_mount(candidate);self.m.verify_production_worker_enabled(candidate)
        need(self.m.runtime(original)['config']==self.m.runtime(old)['config'],'ORIGINAL_RUNTIME_CONFIG_DRIFT')
        if not recovery:need(self.m.runtime(original)==self.m.runtime(old),'ORIGINAL_RUNTIME_PROVENANCE_DRIFT')
        self.source_boundary(original,before);self.source_boundary(candidate,expected)
        need(type(candidate['RestartCount']) is int and candidate['RestartCount']==0,'CANDIDATE_RESTARTED')
        if live:
            need(candidate['State']['Running'] is True and original['State']['Running'] is False and self.m.inspect('t24-crm')['Id']==candidate['Id'],'SINGLE_LIVE_KNOWN_CANDIDATE_REQUIRED');self.helper.validation_window(candidate)
        else:need(candidate['State']['Running'] is False,'PRESTART_CANDIDATE_STOPPED_REQUIRED')
        if not recovery:need(self.retained.evidence(self.rows())==self.proof['rows'],'ALL162_ROWS_CHANGED_DURING_SWITCH')
        return original,candidate

    def public_check(self,identity):
        # The retained exact Ops callback/JPEG sentinels need configured Env
        # validation instead of the older unconfigured-Ops environment guard.
        probe=types.SimpleNamespace(m=self.m,retained=self.retained,proof=self.proof,nginx=self.nginx,pf=types.SimpleNamespace(meta_environment=self.environment,security_headers=self.ctx.workflow.pf.security_headers),rows=self.rows)
        probe.delivery_sentinel=lambda value:self.ctx.module.OperationsMethods.delivery_sentinel(probe,value)
        probe.meta_callback_sentinel=lambda value:self.retained.Release.meta_callback_sentinel(probe,value)
        return self.retained.Release.public_check(probe,identity)

    def activate(self):
        m,a=self.m,self.args;r,old,before,expected=self.reviewed();self.current();need(not(a.release/'activation-started.json').exists() and not m.inspect_optional(self.old_name) and not m.inspect_optional(self.candidate_name),'FRESH_SWITCH_REQUIRED')
        nginx=m.NGINX.read_bytes();need(H(m.next_nginx(nginx))==r['nginx_next_sha256'],'EXACT_REVIEWED_STATIC_ROOT_REQUIRED');self.record('nginx-before.conf',nginx);self.record('activation-started.json',{'source_sha':SOURCE_SHA,'review_sha256':a.review_sha256,'original_id':old['Id'],'candidate_image':r['candidate_image']})
        status,body=m.retained().docker_request('POST','/containers/create?name='+self.candidate_name,m.clone_config(r['candidate_image'],old));need(status==201,'CANDIDATE_CREATE_FAILED');identity=json.loads(body)['Id'];need(re.fullmatch('[a-f0-9]{64}',identity),'EXACT_CREATED_ID_REQUIRED')
        self.record('candidate-created.json',{'source_sha':SOURCE_SHA,'candidate_id':identity,'candidate_image':r['candidate_image'],'original_id':old['Id'],'review_sha256':a.review_sha256});state=self.state(r,old)
        try:
            _,candidate=self.fresh(r,old,before,expected,state);need(candidate['State']['Status']=='created' and candidate['State'].get('StartedAt') in {'','0001-01-01T00:00:00Z','0001-01-01T00:00:00.000000000Z'},'NEVER_STARTED_CANDIDATE_REQUIRED')
            m.run(['docker','stop','--time','30',old['Id']],'ORIGINAL_STOP_FAILED',60);original,_=self.fresh(r,old,before,expected,state);need(original['State']['Running'] is False,'ORIGINAL_STOPPED_REQUIRED')
            m.run(['docker','rename',old['Id'],self.old_name],'ORIGINAL_RENAME_FAILED');m.run(['docker','rename',identity,'t24-crm'],'CANDIDATE_RENAME_FAILED');self.fresh(r,old,before,expected,state)
            m.run(['docker','start',identity],'CANDIDATE_START_FAILED');m.ready(identity);self.fresh(r,old,before,expected,state,live=True)
            m.replace_nginx(nginx,m.next_nginx(nginx));m.retained().reload_nginx();_,candidate=self.fresh(r,old,before,expected,state,updated=True,live=True);privacy=self.public_check(identity);_,candidate=self.fresh(r,old,before,expected,state,updated=True,live=True)
            result={'stage':'MEDIA_WORKSPACE_SCALE_DEPLOYED','source_sha':SOURCE_SHA,'frontend_version':FRONTEND,'schema_revision':SCHEMA_REVISION,'table_count':162,'crm':m.runtime(candidate),'original_id':old['Id'],'preflight_sha256':a.preflight_sha256,'prepared_sha256':a.review_sha256,
                'all162_rows_schema_preserved':True,'existing_full_environment_preserved':True,'existing_ops_credentials_preserved':True,'private_boundary_preserved':True,'old_meta_google_cutoff_preserved':True,'python310_timestamp_canary_verified':True,'exact_getonly_projection_routes_verified':True,
                'operations_execution_enabled':False,'operations_scheduler_enabled':False,'schema_changed':False,'database_restored':False,'provider_requests':False,'credentials_journaled':False,'production_containers_deleted':False,'privacy':privacy}
            return {**result,'receipt_sha256':self.record('deployed.json',result)}
        except BaseException:self.recover_internal(r,old,before,expected);raise

    def recover_internal(self,r,old,before,expected):
        m,a=self.m,self.args;state=self.state(r,old);candidate=m.inspect(state['candidate_id']);need(candidate['Id']==state['candidate_id'] and candidate['Image']==r['candidate_image'],'KNOWN_DURABLE_CANDIDATE_REQUIRED')
        if candidate['State']['Running']:m.run(['docker','stop','--time','30',candidate['Id']],'RECOVERY_CANDIDATE_CONTAINMENT_FAILED',60)
        original,candidate=self.identities(state,old);need(candidate['State']['Running'] is False,'CANDIDATE_CONTAINED_REQUIRED');nginx=m.NGINX.read_bytes();updated=H(nginx)==r['nginx_next_sha256'];self.protections(updated=updated,recovery=True)
        self.retained.compare(candidate,old,m);self.environment(candidate);self.environment(original);self.source_boundary(original,before);self.source_boundary(candidate,expected)
        # No schema change: old image remains compatible; preserve every current
        # independent row and never copy the isolated database back.
        if updated:m.replace_nginx(nginx,m.read(a.release/'nginx-before.conf',self.proof['nginx_sha256']))
        m.retained().reload_nginx()
        if candidate['Name']=='/t24-crm':m.run(['docker','rename',candidate['Id'],self.candidate_name],'RETAIN_CANDIDATE_FAILED')
        if original['Name']!='/t24-crm':m.run(['docker','rename',original['Id'],'t24-crm'],'RESTORE_ORIGINAL_NAME_FAILED')
        if not original['State']['Running']:m.run(['docker','start',original['Id']],'ORIGINAL_RESUME_FAILED')
        m.ready(original['Id']);restored=m.inspect('t24-crm');need(restored['Id']==old['Id'] and restored['State']['Running'] is True and m.runtime(restored)['config']==m.runtime(old)['config'],'EXACT_ORIGINAL_RESTORED_REQUIRED');self.protections(recovery=True);self.environment(restored)
        result={'stage':'MEDIA_WORKSPACE_SCALE_ORIGINAL_RESUMED','source_sha':BASE_SOURCE,'independent_rows_preserved':True,'database_restored':False,'credentials_preserved':True,'operations_execution_enabled':False,'operations_scheduler_enabled':False,'candidate_retained_stopped':True};self.record('recovery.json',result);return result

    def recover(self):
        r,old,before,expected=self.reviewed();need(not(self.args.release/'deployed.json').exists(),'SUCCESSFUL_DEPLOYMENT_REQUIRES_SEPARATE_RECOVERY_REVIEW')
        if not(self.args.release/'candidate-created.json').exists():self.current();return {'stage':'MEDIA_WORKSPACE_SCALE_ORIGINAL_UNCHANGED','manual_orphan_review_required':True,'database_restored':False}
        return self.recover_internal(r,old,before,expected)


PREPARED_TRUE=('all162_rows_unchanged','offline_schema_unchanged','offline_metadata_unchanged','actual_python310_timestamp_canary','exact_getonly_projection_routes','offline_network_none','offline_credentials_absent','offline_workers_off','existing_full_environment_preserved','existing_ops_credentials_preserved','operations_execution_disabled','operations_scheduler_disabled','only_static_root_changes')
PREPARED_FALSE=('provider_requests','production_database_written','credentials_journaled','environment_changed')


def validate_prepared(value,manifest,payload,preflight):
    need(value['stage']=='MEDIA_WORKSPACE_SCALE_PREPARED' and value['source_sha']==SOURCE_SHA and value['frontend_version']==FRONTEND and value['schema_revision']==value['old_schema_revision']==SCHEMA_REVISION and value['table_count']==162 and value['manifest_sha256']==manifest and value['payload_sha256']==payload and value['preflight_sha256']==preflight==ACTUAL_PREFLIGHT_SHA,'EXACT_PREPARED_POLISH_SCOPE_REQUIRED')
    need(all(value[key] is True for key in PREPARED_TRUE) and all(value[key] is False for key in PREPARED_FALSE),'EXACT_ALL162_OFFLINE_ACCEPTANCE_REQUIRED')
    need(all(re.fullmatch('[a-f0-9]{64}',value.get(key,'')) for key in ('original_runtime_sha256','original_inventory_sha256','candidate_inventory_sha256','public_inventory_sha256','nginx_next_sha256')) and re.fullmatch('sha256:[a-f0-9]{64}',value.get('candidate_image','')) and value.get('public_root')=='/var/www/t24-crm-public/'+SCOPE+'-'+SOURCE_SHA[:12]+'-20261102','EXACT_PREPARED_IMAGE_AND_STATIC_PINS_REQUIRED')


def Release(args):
    pins_ready();pf,flow,inventory,retained=_load(args)
    return type('GuardedWorkspaceScaleRelease',(Methods,retained.Release),{})(args,pf,flow,inventory,retained)



def main():
    parser=argparse.ArgumentParser();parser.add_argument('--phase',choices=('prepare','activate','recover'),required=True);parser.add_argument('--release',type=Path,required=True);parser.add_argument('--manifest-sha256',required=True);parser.add_argument('--payload-sha256',required=True);parser.add_argument('--preflight',type=Path,required=True);parser.add_argument('--preflight-sha256',required=True);parser.add_argument('--review-sha256');args=parser.parse_args()
    pins_ready();need(os.geteuid()==0 and socket.gethostname()==HOST,'EXACT_ROOT_SERVER_REQUIRED');resource.setrlimit(resource.RLIMIT_CORE,(0,0));os.umask(0o077)
    need(args.release.resolve()==args.release and args.release.parent==Path('/opt/t24-crm/releases') and args.preflight_sha256==ACTUAL_PREFLIGHT_SHA and args.preflight==Path('/opt/t24-crm/releases/media-workspace-scale-preflight-'+ACTUAL_PREFLIGHT_SHA[:12]+'.json'),'EXACT_PROTECTED_PHASE_PATHS_REQUIRED')
    for parent in (args.release,*args.release.parents):
        row=parent.lstat();need(parent.resolve()==parent and stat.S_ISDIR(row.st_mode) and row.st_uid==0 and not row.st_mode&0o022,'PROTECTED_RELEASE_PARENT_REQUIRED')
    need(stat.S_IMODE(args.release.lstat().st_mode)==0o700 and all(re.fullmatch('[a-f0-9]{64}',value) for value in (args.manifest_sha256,args.payload_sha256,args.preflight_sha256)) and (args.phase!='prepare' or args.review_sha256 is None),'EXACT_PHASE_PINS_REQUIRED')
    fd=os.open('/opt/t24-crm/releases/.media-workspace-scale.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        row=os.fstat(fd);need(stat.S_ISREG(row.st_mode) and row.st_uid==0 and row.st_nlink==1 and stat.S_IMODE(row.st_mode)==0o600,'ROOT_PRIVATE_LOCK_REQUIRED');fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);print(json.dumps(getattr(Release(args),args.phase)(),sort_keys=True))
    finally:os.close(fd)


if __name__=='__main__':
    try:main()
    except BaseException as exc:
        value=str(exc);code=value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',value) else 'MEDIA_WORKSPACE_SCALE_RELEASE_REJECTED';print(json.dumps({'stage':'MEDIA_WORKSPACE_SCALE_RELEASE_REJECTED','code':code,'database_restored':False}));raise SystemExit(1)
