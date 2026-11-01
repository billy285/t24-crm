"""Private asset studio: preserve all155 current tables and add3 empty tables.

The prepared monthly packet and all existing business/private authority remain.
Rendering uses a separately verified toolchain; recovery is forward-only.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import copy
import selectors
import signal
import sqlite3
import socket
import stat
import subprocess
import tarfile
import time
import types

HOST='iZj6c4cj7edgnhdimts4l7Z'
SCOPE = 'media-asset-studio'
SOURCE_SHA = 'f595f3acfb5bfc4a28dadd3ec181b65f7c540fdd'
FRONTEND = 'c1d87dd771d8'
APPLICATION_FREEZE_SHA = 'cc314579784239cd710c45c39e589ce14a8d05e4d8b28c33f1900510cc0cce00'
BASE_SOURCE = 'd39337fccfd622e506ca3c1a655a126f5218dc42'
BASE_FRONTEND = '8113d14d204f'
OLD_REVISION = 'e10cb234c570'
SCHEMA_REVISION = NEW_REVISION='f21dc345d681'
MIGRATION = 'alembic/versions/f21dc345d681_media_asset_studio.py'
MIGRATIONS=((MIGRATION,NEW_REVISION,OLD_REVISION),)
NEW_TABLES = frozenset(['media_asset_profiles', 'media_asset_jobs', 'media_asset_requests'])
NEW_INDEXES = frozenset(['ix_media_asset_jobs_customer_id'])
NEW_TABLE_SHAPES = {'media_asset_jobs': '47d84f4ce732b9969a5f86187f101b7364b4ca39f8494e023ed0dba90dbc5f90', 'media_asset_profiles': 'b734cecd9babdbe8c9c5c2e44fc8076507d4674e99f07ad6d569b5c6e7a6c403', 'media_asset_requests': 'ad2da4e7814d995e75c0babe1448d3e472f3c43f2580fc56af0d09f16c2c45a5'}
MONTHLY_ROUTES = frozenset([('/api/v1/media-monthly/customers/{customer_id}/workflow-alerts', 'GET'), ('/api/v1/media-monthly/runs/{run_id}/cancel', 'POST'), ('/api/v1/media-monthly/runs/{run_id}/prepare', 'POST'), ('/api/v1/media-monthly/runs/{run_id}/review', 'POST'), ('/api/v1/media-monthly/runs/{run_id}/schedule', 'POST'), ('/api/v1/media-monthly/runs/{run_id}/workflow', 'GET'), ('/api/v1/media-monthly/workflow-requests/{request_id}', 'GET')])
EXISTING_MONTHLY_ROUTES=frozenset([('/api/v1/media-monthly/customers/{customer_id}/profile', 'PUT'), ('/api/v1/media-monthly/customers/{customer_id}/runs', 'GET'), ('/api/v1/media-monthly/customers/{customer_id}/runs', 'POST'), ('/api/v1/media-monthly/customers/{customer_id}/setup', 'GET'), ('/api/v1/media-monthly/requests/{request_id}', 'GET'), ('/api/v1/media-monthly/runs/{run_id}', 'GET'), ('/api/v1/media-monthly/runs/{run_id}/adopt', 'POST'), ('/api/v1/media-monthly/runs/{run_id}/items/{item_id}', 'PATCH')])
PREFLIGHT_SHA = '33e3ced927bc7fd872d5f8b1395ec46f14db48ebb4c8ac4e8199fc067b5b88a9'
ACTUAL_PREFLIGHT_SHA = 'bed4a64393ad4940a3e3c2a583d57a02f7970ce03ba6d96bec1991f7ba3d7bd2'
NEW_BACKEND_FILES = frozenset(['alembic/versions/f21dc345d681_media_asset_studio.py', 'models/media_asset_studio.py', 'routers/media_asset_studio.py', 'schemas/media_asset_studio.py', 'services/media_asset_renderer.py', 'services/media_asset_studio.py'])
EXISTING_BACKEND_HASHES = {'main.py': '12201aedb42b381755022127a28cf701143bba1db2d87ead98dd9b10e55d3892', 'services/media_publication_images.py': '8e2ea1a8ea6a4d55260936c4d7d2095038f6ab4c092c7ed093a27593a6569ce5'}
BACKEND_FILES=NEW_BACKEND_FILES|frozenset(EXISTING_BACKEND_HASHES)
FRONTEND_FILES = frozenset(['app/frontend/src/components/MediaAssetStudio.tsx', 'app/frontend/src/components/MediaMerchantWorkspace.tsx', 'app/frontend/src/components/media-asset-studio.css', 'app/frontend/src/lib/media-asset-studio.ts'])
TEST_FILES = frozenset(['app/backend/tests/test_media_asset_studio.py', 'app/frontend/tests/media-asset-studio.test.mjs', 'app/frontend/tests/media-merchant-workflow.test.mjs'])
SOURCE_FILES=frozenset('app/backend/'+name for name in BACKEND_FILES)|FRONTEND_FILES|TEST_FILES
ORIGINAL_BACKEND_HASHES={name:EXISTING_BACKEND_HASHES.get(name) for name in sorted(BACKEND_FILES)}
FINAL_BACKEND_HASHES = {'alembic/versions/f21dc345d681_media_asset_studio.py': '14739f5170760cac3e396f332698e2030fb3385f57a82146bd30248012dab6d9', 'main.py': 'dfcd63fe31739e280b5093d94f57e000538e27290d0637a0a78634033d70c1b9', 'models/media_asset_studio.py': '4a028424f28b468ed339d171ec0f9656719a9db0837637718875985188d39a49', 'routers/media_asset_studio.py': '78fbecff322aa3baac9627bb16437ae61b64dcb039e66df8f4cf0a8612771039', 'schemas/media_asset_studio.py': '3f6fdd98d001d5ce891ee1d1b3def4f1bb851c63697d941e7701a910f2ed823d', 'services/media_asset_renderer.py': 'a821f9767fec832687a45c7bf30ccfe25625b543893a938295a0df5e10c025bc', 'services/media_asset_studio.py': '3655a9cc05786d879ad7b3afb4fb71c9f7280dcf748d7661bffbc1b89c22f16a', 'services/media_publication_images.py': 'a88ec25f09e91d1b754b5f15f24a17082e820b3af61744f3bec89c31f6ea1834'}
BACKEND_BEFORE=ORIGINAL_BACKEND_HASHES
BACKEND_AFTER=FINAL_BACKEND_HASHES
TRUE_FLAGS = ('frontend_changed', 'all155_original_tables_preserved_except_reviewed_schema_head', 'existing_full_environment_preserved', 'existing_ops_credentials_preserved', 'database_migration', 'schema_changed', 'dependencies_changed', 'only_reviewed_csp_media_src_added')
FALSE_FLAGS = ('credentials_included', 'runtime_environment_changed', 'production_seed_rows', 'provider_requests', 'operations_execution_enabled', 'operations_scheduler_enabled')
CAPTURE_FOCUS_HASHES = {}


TOOLCHAIN_RECEIPT_SHA = '2936b1c77c234e8a8cd027f91c8a028f603424098226349b5834e11c90f6198d'
TOOLCHAIN_IMAGE = 'sha256:e86f40cc1d9cfc531c3aeaec6ce1776adc805c4c9b215669658ee639dfdcc9aa'
TOOLCHAIN_RECEIPT_PATH = Path('/opt/t24-crm/releases/media-asset-studio-toolchain-01d126c4fb9d-20261101/toolchain-prepared.json')
TOOLCHAIN_HELPER_SHA = '01d126c4fb9d7e931e6342db39fb13a8185500952fb3567c58766aeb09cab577'
RENDERER_CANARY_SHA = 'cf8961248786c816055ba62497b76e9baa515f586522903b4cbeb1bce9e04f15'
ASSET_ROUTES=frozenset([('/api/v1/media-asset-studio/customers/{customer_id}/jobs', 'POST'), ('/api/v1/media-asset-studio/customers/{customer_id}/profile', 'PUT'), ('/api/v1/media-asset-studio/customers/{customer_id}/studio', 'GET'), ('/api/v1/media-asset-studio/jobs/{job_id}', 'GET'), ('/api/v1/media-asset-studio/jobs/{job_id}/adopt', 'POST'), ('/api/v1/media-asset-studio/jobs/{job_id}/download', 'GET'), ('/api/v1/media-asset-studio/jobs/{job_id}/preview', 'GET'), ('/api/v1/media-asset-studio/jobs/{job_id}/retry', 'POST'), ('/api/v1/media-asset-studio/requests/{request_id}', 'GET')])
CSP_BEFORE="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self' data:; connect-src 'self' https: wss:; frame-ancestors 'self'; base-uri 'self'; form-action 'self'"
CSP_AFTER="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; media-src 'self' blob:; font-src 'self' data:; connect-src 'self' https: wss:; frame-ancestors 'self'; base-uri 'self'; form-action 'self'"
NGINX_BEFORE_SHA='c06d6788d23ff5a7c8d481c6cb20ad96fef9178d17aa4980193202b762fdccb7'
CSP_AFTER_SHA='ead64b09efe8c4f35648aa8eafe8855c5268ecf0999e0918b3642dd9dfbfe7a6'

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


def capture_public_build(argv,path,timeout=300,maximum=4*1024**2):
    """Capture only the source-only Docker context build, never runtime/env commands."""
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    process=None;selector=selectors.DefaultSelector();count=0;digest_=hashlib.sha256();tail=b'';reason=None;started=time.monotonic()
    try:
        process=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
            env={'PATH':'/usr/local/bin:/usr/bin:/bin','LANG':'C.UTF-8','HOME':'/root','DOCKER_BUILDKIT':'0'},start_new_session=True)
        selector.register(process.stdout,selectors.EVENT_READ)
        with os.fdopen(fd,'wb',closefd=False) as log:
            while True:
                if time.monotonic()-started>=timeout:reason='BUILD_CLIENT_TIMEOUT_RESULT_UNKNOWN';break
                events=selector.select(timeout=min(1,max(.01,timeout)))
                if not events:continue
                chunk=os.read(process.stdout.fileno(),65536)
                if not chunk:
                    if process.poll() is not None:break
                    continue
                if count+len(chunk)>maximum:
                    chunk=chunk[:max(0,maximum-count)];reason='BUILD_PUBLIC_LOG_LIMIT_RESULT_UNKNOWN'
                if chunk:log.write(chunk);count+=len(chunk);digest_.update(chunk);tail=(tail+chunk)[-8192:]
                if reason:break
            log.flush();os.fsync(log.fileno())
        if reason:
            try:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
        code=process.wait(timeout=10)
        safe=re.sub(r'\x1b\[[0-9;]*[A-Za-z]','',tail.decode('utf-8',errors='replace'))
        safe=''.join(c for c in safe if ord(c)>=32 or c in '\n\t')[-8192:]
        return {'exit_code':code,'client_status':reason or 'BUILD_CLIENT_FINISHED','log_sha256':digest_.hexdigest(),
            'log_bytes':count,'public_tail':safe,'elapsed_seconds':round(time.monotonic()-started,3),'build_daemon_result_known':reason is None}
    finally:
        selector.close()
        if process is not None:
            if process.poll() is None:
                try:os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                process.wait(timeout=10)
            if process.stdout is not None:process.stdout.close()
        os.close(fd)
        parent=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:os.fsync(parent)
        finally:os.close(parent)


def pins_ready():
    need(isinstance(SOURCE_SHA,str) and re.fullmatch('[a-f0-9]{40}',SOURCE_SHA) and SOURCE_SHA not in {'0'*40,BASE_SOURCE},'FINAL_IMMUTABLE_APPLICATION_SOURCE_REQUIRED')
    need(isinstance(FRONTEND,str) and re.fullmatch('[a-f0-9]{12}',FRONTEND) and FRONTEND not in {'0'*12,BASE_FRONTEND},'FINAL_REVIEWED_FRONTEND_REQUIRED')
    need(all(isinstance(v,str) and re.fullmatch('[a-f0-9]{64}',v) and v!='0'*64 for v in (APPLICATION_FREEZE_SHA,ACTUAL_PREFLIGHT_SHA)),'FINAL_APPLICATION_AND_BASELINE_FREEZE_REQUIRED')
    need(bool(FRONTEND_FILES) and isinstance(FINAL_BACKEND_HASHES,dict) and set(FINAL_BACKEND_HASHES)==BACKEND_FILES and all(isinstance(v,str) and re.fullmatch('[a-f0-9]{64}',v) for v in FINAL_BACKEND_HASHES.values()),'FINAL_EXACT_SOURCE_ALLOWLIST_REQUIRED')
    need(isinstance(NEW_INDEXES,frozenset) and isinstance(NEW_TABLE_SHAPES,dict) and set(NEW_TABLE_SHAPES)==NEW_TABLES and all(re.fullmatch('[a-f0-9]{64}',v) for v in NEW_TABLE_SHAPES.values()) and isinstance(MONTHLY_ROUTES,frozenset) and bool(MONTHLY_ROUTES),'FINAL_ADDITIVE_SCHEMA_AND_ROUTES_REQUIRED')

    need(isinstance(TOOLCHAIN_RECEIPT_SHA,str) and re.fullmatch('[a-f0-9]{64}',TOOLCHAIN_RECEIPT_SHA) and isinstance(TOOLCHAIN_IMAGE,str) and re.fullmatch('sha256:[a-f0-9]{64}',TOOLCHAIN_IMAGE) and isinstance(TOOLCHAIN_RECEIPT_PATH,Path) and isinstance(TOOLCHAIN_HELPER_SHA,str) and re.fullmatch('[a-f0-9]{64}',TOOLCHAIN_HELPER_SHA) and isinstance(RENDERER_CANARY_SHA,str) and re.fullmatch('[a-f0-9]{64}',RENDERER_CANARY_SHA),'ACTUAL_VERIFIED_TOOLCHAIN_AND_CANARY_REQUIRED')




def validate_summary(p):
    need(p['stage']=='MEDIA_ASSET_STUDIO_PREFLIGHT_CAPTURED' and p['sha256']==ACTUAL_PREFLIGHT_SHA and p['path']=='/opt/t24-crm/releases/media-asset-studio-preflight-'+ACTUAL_PREFLIGHT_SHA[:12]+'.json' and p['source_sha']==BASE_SOURCE and p['frontend_version']==BASE_FRONTEND and p['schema_revision']==OLD_REVISION and p['table_count']==155 and p['backend_file_count']==408 and p['prepared_private_packet_count']==1 and p['all155_current_tables_preserved'] is True and p['prepared_private_packet_preserved'] is True,'EXACT_CURRENT155_BASELINE_REQUIRED')
    need(p['crm']=={'id':'3000cd73a62f0c852874c2124426ec45b47f26d128843fb56f5963ef9ef98058','config':'7224218131950ce106c764ae838f7cb7f4a33ed07530b869346763d226dc56d4','image':'sha256:3e948625074aa6af891ace1e814f98aa9ed8d9bc004d85f6c5cadc6b423c1536','restart':0,'started':'2026-11-01T04:44:42.917603256Z'} and p['environment_sha256']=='3d414fb4b9b5b1ae9bb5ecc1ce503be3c788f8bee27d0806de9d72fd3df0e223' and p['ops_environment_sha256']=='f334ac086b4f8eef3d92cc4b6444558f500590a2bd4020ce07d9d13f1947dfb2','EXACT_RUNTIME_AND_FULL_ENV_REQUIRED')
    need(p['google_scheduler_enabled'] is True and p['google_scheduler_activation_from']=='2026-10-30T19:42:04Z' and p['csp_environment_override_present'] is False,'EXACT_EXISTING_POLICY_REQUIRED')
    need(all(p[k] is False for k in ('ops_execution_enabled','ops_scheduler_enabled','schema_changed','permissions_changed','credential_file_content_read','private_content_read','business_writes','provider_requests','runtime_changed','installation_performed','worker_started')),'READONLY_CURRENT_BASELINE_REQUIRED')


def nginx_policy_count(body,policy):
    values=re.findall(rb'(?im)^[ \t]*add_header[ \t]+Content-Security-Policy[ \t]+"([^"\r\n]*)"[ \t]+always[ \t]*;',body)
    need(1<=len(values)<=12 and all(value==policy for value in values) and len(re.findall(rb'(?i)Content-Security-Policy',body))==len(values),'ONLY_EXACT_EXISTING_STATIC_CSP_DIRECTIVES_ALLOWED')
    return len(values)


def next_nginx(original,old_root,new_root):
    old,new=os.fsencode(str(old_root)),os.fsencode(str(new_root));before,after=CSP_BEFORE.encode(),CSP_AFTER.encode()
    need(H(original)==NGINX_BEFORE_SHA and original.count(old)==1 and new not in original,'EXACT_CAPTURED_SINGLE_STATIC_ROOT_REQUIRED')
    count=nginx_policy_count(original,before)
    need(original.count(before)==count and after not in original and CSP_AFTER==CSP_BEFORE.replace("img-src 'self' data: https:;","img-src 'self' data: https:; media-src 'self' blob:;",1),'ONLY_REVIEWED_MEDIA_SRC_INSERTION_ALLOWED')
    updated=original.replace(old,new,1).replace(before,after)
    need(nginx_policy_count(updated,after)==count and updated.replace(new,old,1).replace(after,before)==original,'ONLY_STATIC_ROOT_AND_EXACT_CSP_BYTES_CHANGE_ALLOWED')
    return updated


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


def _load(args):
    pf=types.ModuleType('_asset_studio_preflight');pf.__file__=str(args.release/'preflight.py');exec(compile(protected_read(args.release/'preflight.py',PREFLIGHT_SHA),pf.__file__,'exec'),pf.__dict__)
    last,flow,inventory=pf.dependencies();retained=flow.retained
    # In-memory parameters only; frozen source helpers remain byte-identical.
    retained.SOURCE_SHA,retained.BASE_SOURCE,retained.FRONTEND=SOURCE_SHA,BASE_SOURCE,FRONTEND
    for name,value in {'OLD_REVISION':OLD_REVISION,'NEW_REVISION':NEW_REVISION,'MIGRATION':MIGRATION,'MIGRATIONS':MIGRATIONS,'NEW_TABLES':NEW_TABLES,'NEW_INDEXES':NEW_INDEXES,'NEW_TABLE_SHAPES':NEW_TABLE_SHAPES}.items():setattr(retained,name,value)
    return pf,flow,inventory,retained



class Methods:
    def __init__(self,args,pf,flow,inventory,retained):
        self.args,self.pf,self.flow,self.retained=args,pf,flow,retained
        self.c,self.ctx,self.m,self.base,self.safe,self.helper,self.pins=flow.c,flow.ctx,flow.m,flow.base,flow.safe,flow.helper,flow.pins
        c=self.c;self.proof=c.strict_json(c.read(args.preflight,sha=args.preflight_sha256));self.manifest=c.strict_json(c.read(args.release/'manifest.json',sha=args.manifest_sha256));c.read(args.release/'payload.tar.gz',maximum=16*1024**2,sha=args.payload_sha256)
        need(self.proof['backend_inventory']==inventory,'EXACT_DEPLOYED_PARENT_INVENTORY_REQUIRED')
        self.source,self.version=SOURCE_SHA,FRONTEND;self.public=Path('/var/www/t24-crm-public/'+SCOPE+'-'+SOURCE_SHA[:12]+'-20261101')
        need(args.release==Path('/opt/t24-crm/releases/'+SCOPE+'-'+SOURCE_SHA[:12]+'-20261101'),'EXACT_RELEASE_NAMESPACE_REQUIRED');self.validate()
        m=self.m;p=self.proof;m.SOURCE,m.SCOPE,m.BACKEND=SOURCE_SHA,SCOPE,set(BACKEND_FILES);m.BASELINE_FRONTEND,m.FRONTEND_VERSION=BASE_FRONTEND,FRONTEND
        m.PUBLIC,m.NGINX_SHA,m.STATIC_SHA=Path(p['public_root']),p['nginx_sha256'],p['public_inventory_sha256'];m.OLD_ID,m.BASE_IMAGE,m.OLD_CONFIG=(p['crm'][key] for key in ('id','image','config'))
        m.public_root=lambda:self.public;m.next_nginx=lambda original:next_nginx(original,p['public_root'],self.public)
        self.base.OLD_REVISION,self.base.NEW_REVISION,self.base.MIGRATION=OLD_REVISION,NEW_REVISION,MIGRATION
        self.base.migration_script=retained.migration_script
        self.pf.google_environment=self.ctx.workflow.pf.google_environment;self.pf.meta_environment=self.environment;self.pf.security_headers=self.ctx.workflow.pf.security_headers;self.pf.ACTIVATION_FROM='2026-10-30T19:42:04Z'
        self.old_name='t24-crm-before-'+SCOPE+'-'+SOURCE_SHA[:12];self.candidate_name='t24-crm-candidate-'+SCOPE+'-'+SOURCE_SHA[:12];self.offline_name='t24-'+SCOPE+'-probe-'+SOURCE_SHA[:12]


    def validate(self):
        p,v,a=self.proof,self.manifest,self.args
        need(p['stage']=='MEDIA_ASSET_STUDIO_READONLY_PREFLIGHT' and p['source_sha']==BASE_SOURCE and p['frontend_version']==BASE_FRONTEND and p['schema_revision']==OLD_REVISION and len(p['rows'])==155 and not NEW_TABLES.intersection(p['rows']) and p['all155_current_tables_preserved'] is True and p['rows']['media_monthly_workflows']['count']==1,'EXACT_CURRENT_POPULATED_ALL155_PROOF_REQUIRED')
        need(v['source_sha']==SOURCE_SHA and v['frontend_version']==FRONTEND and v['baseline_source_sha']==BASE_SOURCE and v['baseline_frontend_version']==BASE_FRONTEND and v['schema_revision']==NEW_REVISION and v['old_schema_revision']==OLD_REVISION and v['additive_tables']==sorted(NEW_TABLES),'EXACT_THREE_TABLE_ADDITIVE_SOURCE_SCOPE_REQUIRED')
        need(v['toolchain_image']==TOOLCHAIN_IMAGE and v['toolchain_helper_sha256']==TOOLCHAIN_HELPER_SHA and v['toolchain_receipt_sha256']==TOOLCHAIN_RECEIPT_SHA and v['renderer_canary_sha256']==RENDERER_CANARY_SHA and v['application_freeze_sha256']==APPLICATION_FREEZE_SHA and set(v['changed_source_files'])==SOURCE_FILES and len(v['changed_source_files'])==len(SOURCE_FILES) and v['preflight_sha256']==a.preflight_sha256==ACTUAL_PREFLIGHT_SHA and v['payload_sha256']==a.payload_sha256,'EXACT_APPLICATION_FREEZE_AND_PROOF_REQUIRED')
        need(all(v[key] is True for key in TRUE_FLAGS) and all(v[key] is False for key in FALSE_FLAGS),'EXACT_DRAFT_ONLY_ADDITIVE_FLAGS_REQUIRED')
        need(v['backend_before']==ORIGINAL_BACKEND_HASHES and v['backend_after']==FINAL_BACKEND_HASHES and {name[8:] for name in v['files'] if name.startswith('backend/')}==BACKEND_FILES,'EXACT_ASSET_RUNTIME_OVERLAY_REQUIRED')
        need(all(v['files']['backend/'+name]==sha for name,sha in FINAL_BACKEND_HASHES.items()) and all(re.fullmatch('[a-f0-9]{64}',sha) for sha in v['files'].values()) and
             {'static/index.html','static/app-version.json'}<=set(v['files']) and all(name in {'backend/'+x for x in BACKEND_FILES} or name.startswith('static/') and self.m.static_path(name[7:]) for name in v['files']),'EXACT_RUNTIME_AND_STATIC_PAYLOAD_REQUIRED')

    def environment(self,info):
        observed=self.flow.environment(info)
        need(observed==(self.proof['environment_sha256'],self.proof['ops_environment_sha256']),'EXACT_CAPTURED_FULL_ENVIRONMENT_REQUIRED')
        env={entry.split('=',1)[0]:entry.split('=',1)[1] for entry in info['Config']['Env'] if '=' in entry}
        need(env.get('T24_MEDIA_ASSET_WORKER_ENABLED','true').lower()=='true' and not any(env.get(k,'').lower() in {'test','testing'} for k in ('APP_ENV','ENVIRONMENT','ENV')),'EXISTING_ENV_MUST_ALLOW_LOCAL_ASSET_WORKER')
        return observed


    def nginx(self,updated=False):
        p,m=self.proof,self.m;body=m.NGINX.read_bytes();active=m.run(['nginx','-T'],'ACTIVE_NGINX_REQUIRED');observed=H(active)
        if updated:
            old,new=os.fsencode(p['public_root']),os.fsencode(str(self.public));before,after=CSP_BEFORE.encode(),CSP_AFTER.encode()
            count=nginx_policy_count(body,after)
            need(body.count(new)==active.count(new)==1 and active.count(after)==count,'EXACT_NEW_STATIC_ROOT_AND_CSP_REQUIRED')
            body=body.replace(new,old,1).replace(after,before);active=active.replace(new,old,1).replace(after,before)
        need(H(body)==p['nginx_sha256'] and H(active)==p['active_nginx_sha256'],'OTHER_NGINX_BYTES_CHANGED');return observed

    def protections(self,*,updated=False,recovery=False,head=OLD_REVISION,schema=None):
        m,p=self.m,self.proof
        need(self.safe.safe_private_boundary(m,self.pins)==p['private_boundary'],'PRIVATE_BOUNDARY_DRIFT')
        credentials={'ops':self.safe.protected_metadata(self.c.ENV_FILE),'google':self.safe.protected_metadata(self.safe.GBP_ENV),
            'meta_read':self.safe.protected_metadata(self.ctx.workflow.core.ENV_FILE),'meta_legacy':self.safe.protected_metadata(self.ctx.workflow.core.LEGACY_ENV_FILE)}
        need(m.credential_boundary()==p['credential_boundary'] and credentials==p['credential_metadata'],'EXISTING_CREDENTIAL_METADATA_DRIFT')
        row=m.BUSINESS.stat();need([row.st_dev,row.st_ino]==p['database_identity'] and m.schema_signature(m.BUSINESS,head)==(p['schema_sha256'] if head==OLD_REVISION else schema),'DATABASE_IDENTITY_OR_SCHEMA_DRIFT')
        (self.retained.sequence_boundary(p['database_metadata'],self.metadata(m.BUSINESS),recovery=True) if recovery else self.retained.live_sequence_boundary(p['database_metadata'],self.metadata(m.BUSINESS)))
        need(digest(m.tree(m.PUBLIC))==p['public_inventory_sha256'],'ORIGINAL_STATIC_CONTENT_DRIFT');self.nginx(updated)


    def current(self):
        self.protections();m,p=self.m,self.proof;old=m.inspect('t24-crm');need(old['State']['Running'] is True and m.runtime(old)==p['crm'],'EXACT_CURRENT_RUNTIME_REQUIRED')
        self.environment(old);self.ctx.workflow.pf.google_environment(old);m.verify_secret_mount(old);m.verify_production_worker_enabled(old);m.retained().require_safe_original_restart(old)
        before=m.inventory(old['Id']);need(before==p['backend_inventory'] and digest(before)==p['backend_inventory_sha256'] and len(before)==p['backend_file_count'] and all(name not in before for name in NEW_BACKEND_FILES) and all(before.get(name)==sha for name,sha in EXISTING_BACKEND_HASHES.items()),'CURRENT_BACKEND_SOURCE_DRIFT')
        need(self.retained.evidence(self.rows())==p['rows'],'CURRENT_ALL155_ROWS_DRIFT');m.ready(old['Id']);return old,before


    def toolchain(self):
        need(TOOLCHAIN_RECEIPT_PATH.parent.parent==Path('/opt/t24-crm/releases') and TOOLCHAIN_RECEIPT_PATH.name=='toolchain-prepared.json','EXACT_TOOLCHAIN_RECEIPT_PATH_REQUIRED')
        receipt=self.c.strict_json(self.c.read(TOOLCHAIN_RECEIPT_PATH,sha=TOOLCHAIN_RECEIPT_SHA))
        need(receipt['stage']=='MEDIA_ASSET_STUDIO_TOOLCHAIN_PREPARED' and receipt['tool_sha256']==TOOLCHAIN_HELPER_SHA and receipt['toolchain_image']==TOOLCHAIN_IMAGE and receipt['base_image']==self.proof['crm']['image'] and receipt['source_sha']==BASE_SOURCE and receipt['frontend_version']==BASE_FRONTEND and receipt['preflight_sha256']==ACTUAL_PREFLIGHT_SHA and receipt['approved_proposal_sha256']=='9c7545b0cb443f56f9b897dfa441cfc3c3ce74dcfe50891725676698f864a1b3' and receipt['added_package_count']==194,'EXACT_VERIFIED_TOOLCHAIN_PROVENANCE_REQUIRED')
        need(all(receipt[key] is True for key in ('all155_current_rows_and_private_packet_preserved','all408_backend_files_unchanged','no_existing_package_upgraded_or_removed','fetch_only_official_signed_debian','install_and_engine_probe_network_none')) and all(receipt[key] is False for key in ('production_or_host_installation','production_container_changed','credentials_or_business_data_mounted','api_or_worker_started','social_ai_or_payment_provider_requests','publications_performed')),'EXACT_ISOLATED_TOOLCHAIN_BOUNDARY_REQUIRED')
        need(self.m.image_id(TOOLCHAIN_IMAGE)==TOOLCHAIN_IMAGE,'EXACT_EXISTING_TOOLCHAIN_IMAGE_REQUIRED')
        return receipt

    def image(self):
        m=self.m;self.toolchain()
        need(m.image_id(m.BASE_IMAGE)==m.BASE_IMAGE,'EXACT_EXISTING_ORIGINAL_IMAGE_REQUIRED')
        docker='FROM '+TOOLCHAIN_IMAGE+'\n'+''.join('COPY backend/'+name+' /app/backend/'+name+'\n' for name in sorted(BACKEND_FILES))
        m.write(self.args.release/'Dockerfile',docker.encode());m.write(self.args.release/'.dockerignore',b'*\n!Dockerfile\n!backend\n!backend/**\n')
        tag='t24-crm:'+SCOPE+'-'+SOURCE_SHA[:12]
        result=capture_public_build(['/usr/bin/env','DOCKER_BUILDKIT=0','docker','build','--network=none','--pull=false','-t',tag,str(self.args.release)],self.args.release/'app-build-public.log')
        m.write(self.args.release/'app-build-result.json',encoded(result))
        need(result['exit_code']==0 and result['build_daemon_result_known'],'EXACT_ASSET_APP_IMAGE_BUILD_FAILED')
        image=m.image_id(tag);need(m.image_id(TOOLCHAIN_IMAGE)==TOOLCHAIN_IMAGE and m.image_id(m.BASE_IMAGE)==m.BASE_IMAGE and re.fullmatch('sha256:[a-f0-9]{64}',image or ''),'EXACT_BUILT_ASSET_CANDIDATE_REQUIRED');return image

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
assert actual==set(expected)
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

    def offline_args(self,data,image):
        command=self.ctx.module.OperationsMethods.offline_args(self,data,image)
        command[-1:-1]=['-e','T24_MEDIA_ASSET_WORKER_ENABLED=false']
        return command

    def monthly_probe(self):
        return """import asyncio,socket,sys
from types import SimpleNamespace
assert sys.version_info[:2]==(3,10)
def blocked(*a,**k):raise AssertionError('NO_AI_OR_PUBLIC_PROVIDER_NETWORK')
socket.socket.connect=blocked
from main import app
import fastapi.routing
prefix='/api/v1/media-monthly'
expected="""+repr({**{row:'routers.media_monthly' for row in EXISTING_MONTHLY_ROUTES},**{row:'routers.media_monthly_workflow' for row in MONTHLY_ROUTES}})+"""
schema=app.openapi()
actual={(p,m.upper()) for p,v in schema['paths'].items() if p.startswith(prefix) for m in v if m.lower() in {'get','post','put','patch','delete','head','options','trace'}}
assert actual==set(expected)
contexts=list(fastapi.routing.iter_route_contexts(app.routes)) if hasattr(fastapi.routing,'iter_route_contexts') else app.routes
registered=[(x.path,m,getattr(getattr(x,'endpoint',None),'__module__','')) for x in contexts if getattr(x,'path','').startswith(prefix) for m in (getattr(x,'methods',set()) or set())]
assert len(registered)==len(expected) and {(p,m) for p,m,_ in registered}==set(expected) and all(mod==expected[(p,m)] for p,m,mod in registered)
from services import media_monthly_workflow as monthly
class NoDb:
 def __getattr__(self,name):raise AssertionError('NONOWNER_MONTHLY_MUST_NOT_QUERY_DATABASE')
# The actual service contract is frozen before this canary is finalized.
assert hasattr(monthly,'context')
async def check():
 for role in ('admin','ops','sales','finance'):
  try:await monthly.context(NoDb(),SimpleNamespace(id='2147483647',role=role))
  except Exception as error:assert getattr(error,'status_code',None)==403
  else:raise AssertionError('NONOWNER_MONTHLY_ACCESS')
asyncio.run(check())
print('EXACT_PY310_MONTHLY_ROUTES_OWNER_ONLY_NO_NETWORK')
"""

    def asset_probe(self):
        return """import asyncio,os,socket,sys
from types import SimpleNamespace
assert sys.version_info[:2]==(3,10)
def blocked(*a,**k):raise AssertionError('NO_PROVIDER_NETWORK')
socket.socket.connect=blocked
assert os.environ.get('T24_MEDIA_ASSET_WORKER_ENABLED')=='false'
from main import app,CONTENT_SECURITY_POLICY
assert CONTENT_SECURITY_POLICY=="""+repr(CSP_AFTER)+"""
import fastapi.routing
prefix='/api/v1/media-asset-studio';expected="""+repr(ASSET_ROUTES)+"""
schema=app.openapi();actual={(p,m.upper()) for p,v in schema['paths'].items() if p.startswith(prefix) for m in v if m.lower() in {'get','post','put','patch','delete','head','options','trace'}}
assert actual==expected
contexts=list(fastapi.routing.iter_route_contexts(app.routes)) if hasattr(fastapi.routing,'iter_route_contexts') else app.routes
registered=[(x.path,m,getattr(getattr(x,'endpoint',None),'__module__','')) for x in contexts if getattr(x,'path','').startswith(prefix) for m in (getattr(x,'methods',set()) or set())]
assert len(registered)==len(expected) and {(p,m) for p,m,_ in registered}==expected and all(mod=='routers.media_asset_studio' for _,_,mod in registered)
from services import media_asset_studio as service
assert service.start_worker() is None
class NoDb:
 def __getattr__(self,name):raise AssertionError('NONOWNER_MUST_NOT_QUERY_SQL')
async def check():
 for role in ('admin','ops','sales','finance'):
  try:await service.context(NoDb(),SimpleNamespace(id='2147483647',role=role))
  except Exception as error:assert getattr(error,'status_code',None)==403
  else:raise AssertionError('UNAUTHORIZED_ASSET_ACCESS')
asyncio.run(check())
print('EXACT_ASSET_ROUTES_OWNER_ONLY_OFFLINE_WORKER_DISABLED')
"""

    def prepare(self):
        self.helper.docker_timestamp_probe();m,a=self.m,self.args;old,before=self.current();need({x.name for x in a.release.iterdir()}=={'release.py','preflight.py','manifest.json','payload.tar.gz','renderer_canary.py'},'FRESH_STAGING_REQUIRED')
        extract(a.release,self.manifest,self.c);expected={**before,**FINAL_BACKEND_HASHES};runtime_sha=self.record('original-runtime.json',m.runtime(old));before_sha=self.record('backend-original-inventory.json',before);after_sha=self.record('backend-candidate-inventory.json',expected)
        image=self.image();data=a.release/'probe-data';data.mkdir(mode=0o700);(a.release/'probe-logs').mkdir(mode=0o700);m.backup(m.BUSINESS,data/'crm_prod.db')
        rows=self.rows(data/'crm_prod.db');metadata=self.metadata(data/'crm_prod.db');need(self.retained.evidence(rows)==self.proof['rows'] and m.schema_signature(data/'crm_prod.db',OLD_REVISION)==self.proof['schema_sha256'],'EXACT_ISOLATED_ALL155_COPY_REQUIRED')
        self.retained.live_sequence_boundary(self.proof['database_metadata'],metadata);objects=self.retained.objects(data/'crm_prod.db')
        self.run_migration(data,image);schema=self.new_schema(data/'crm_prod.db');migrated=self.rows(data/'crm_prod.db')
        self.retained.additive_objects(objects,self.retained.objects(data/'crm_prod.db'));self.retained.compare_original(rows,migrated);self.retained.sequence_boundary(metadata,self.metadata(data/'crm_prod.db'))
        need(not m.inspect_optional(self.offline_name),'FRESH_OFFLINE_NAME_REQUIRED');command=self.offline_args(data,image);command[2:2]=['--name',self.offline_name,'-d'];m.run(command,'OFFLINE_START_FAILED')
        try:
            m.ready(self.offline_name);self.base.verify_disabled_environment(m.inspect(self.offline_name));need(m.inventory(self.offline_name)==expected,'EXACT_OFFLINE_SOURCE_REQUIRED')
            checks=[(self.asset_probe(),b'EXACT_ASSET_ROUTES_OWNER_ONLY_OFFLINE_WORKER_DISABLED'),(self.monthly_probe(),b'EXACT_PY310_MONTHLY_ROUTES_OWNER_ONLY_NO_NETWORK'),(self.projection_probe(),b'EXACT_PY310_TWO_GET_PROJECTION_ROUTES_ROLE_DENIED'),(self.timestamp_probe(),b'EXACT_PYTHON310_COMPACT_TIMEZONE_CANARY'),(self.ctx.workflow.route_probe(),b'EXACT_OPERATIONS_AND_EXISTING_ROUTES'),(self.base.gbp_disabled_probe(),b'EXACT_GBP_DISABLED_UNCONFIGURED_NO_NETWORK'),(self.ctx.workflow.meta_disabled_probe(),b'EXACT_META_ABSENT_DISABLED_NO_NETWORK'),(self.ctx.workflow.operations_disabled_probe(),b'EXACT_OPERATIONS_UNCONFIGURED_OFF_NO_NETWORK'),(self.ctx.workflow.owner_denied_probe(),b'EXACT_NONOWNER_ROLE_READ_DENIED_NO_SQL_OR_NETWORK')]
            for code,marker in checks:need(marker in m.run(['docker','exec',self.offline_name,'python','-B','-c',code],'OFFLINE_CANARY_FAILED'),'EXACT_OFFLINE_CANARY_MARKER_REQUIRED')
            code=protected_read(a.release/'renderer_canary.py',RENDERER_CANARY_SHA)
            raw=m.run(['docker','exec',self.offline_name,'python','-B','-c',code.decode()],'FINAL_OFFLINE_ASSET_RENDERER_CANARY_FAILED',240)
            need(b'EXACT_FINAL_ASSET_RENDERER_PNG_ALPHA_COLLAGE_H264_RESOURCE_CANARY' in raw,'EXACT_FINAL_RENDERER_CANARY_MARKER_REQUIRED')
            lines=[line for line in raw.splitlines() if line.startswith(b'{')];need(len(lines)==1,'EXACT_COMPACT_RENDERER_RESULT_REQUIRED')
            result=self.c.strict_json(lines[0]);need(result['stage']=='FINAL_ASSET_RENDERER_OFFLINE_VERIFIED' and result['source_sha']==SOURCE_SHA and result['database_calls']==result['provider_calls']==result['business_writes']==0 and result['process_launches']==9 and len(result['cases'])==8 and result['all_private_temporary_trees_removed'] is True and result['one_core_low_priority_minimal_environment'] is True,'EXACT_FINAL_RENDERER_FULL_FLOW_REQUIRED')
            renderer_result_sha=self.record('renderer-canary-result.json',result)
        finally:m.run(['docker','stop','--time','20',self.offline_name],'OFFLINE_STOP_FAILED',45)
        need(self.rows(data/'crm_prod.db')==migrated and self.metadata(data/'crm_prod.db')==metadata and self.new_schema(data/'crm_prod.db')==schema,'OFFLINE_DATA_SCHEMA_METADATA_CHANGED')
        root,static=m.stage_public(a.release,self.manifest);nginx_sha=H(m.next_nginx(m.NGINX.read_bytes()));self.current()
        result={'stage':'MEDIA_ASSET_STUDIO_PREPARED','source_sha':SOURCE_SHA,'frontend_version':FRONTEND,'schema_revision':NEW_REVISION,'old_schema_revision':OLD_REVISION,'original_table_count':155,'new_table_count':158,'additive_tables':sorted(NEW_TABLES),'schema_after_sha256':schema,
            'old_crm':m.runtime(old),'candidate_image':image,'original_runtime_sha256':runtime_sha,'original_inventory_sha256':before_sha,'candidate_inventory_sha256':after_sha,'public_root':str(root),'public_inventory_sha256':static,'nginx_next_sha256':nginx_sha,'nginx_csp_policy_occurrences':nginx_policy_count(m.NGINX.read_bytes(),CSP_BEFORE.encode()),
            'toolchain_receipt_sha256':TOOLCHAIN_RECEIPT_SHA,'toolchain_helper_sha256':TOOLCHAIN_HELPER_SHA,'toolchain_image':TOOLCHAIN_IMAGE,'renderer_canary_sha256':RENDERER_CANARY_SHA,'renderer_canary_result_sha256':renderer_result_sha,'preflight_sha256':a.preflight_sha256,'manifest_sha256':a.manifest_sha256,'payload_sha256':a.payload_sha256,**{key:True for key in PREPARED_TRUE},**{key:False for key in PREPARED_FALSE}}
        return {**result,'receipt_sha256':self.record('prepared.json',result)}


    def reviewed(self):
        a,m=self.args,self.m;need(re.fullmatch('[a-f0-9]{64}',a.review_sha256 or ''),'CANONICAL_PREPARED_REVIEW_REQUIRED');r=self.c.strict_json(m.read(a.release/'prepared.json',a.review_sha256));validate_prepared(r,a.manifest_sha256,a.payload_sha256,a.preflight_sha256)
        runtime=self.c.strict_json(m.read(a.release/'original-runtime.json',r['original_runtime_sha256']));old=m.inspect(runtime['id']);before=self.c.strict_json(m.read(a.release/'backend-original-inventory.json',r['original_inventory_sha256']));expected=self.c.strict_json(m.read(a.release/'backend-candidate-inventory.json',r['candidate_inventory_sha256']))
        need(runtime==r['old_crm']==self.proof['crm'] and m.runtime(old)==runtime and digest(before)==self.proof['backend_inventory_sha256'] and expected=={**before,**FINAL_BACKEND_HASHES},'EXACT_PREPARED_ORIGINAL_AND_SOURCE_REQUIRED')
        need(m.image_id(r['candidate_image'])==r['candidate_image'] and m.verify_public(self.public,self.manifest)==r['public_inventory_sha256'],'PREPARED_IMAGE_OR_STATIC_DRIFT');return r,old,before,expected

    def fresh(self,r,old,before,expected,state,*,migrated=False,updated=False,live=False,baseline=None,recovery=False):
        head=NEW_REVISION if migrated else OLD_REVISION
        self.protections(updated=updated,recovery=recovery,head=head,schema=r['schema_after_sha256'])
        need(self.m.verify_public(self.public,self.manifest)==r['public_inventory_sha256'],'STAGED_STATIC_CONTENT_DRIFT')
        original,candidate=self.identities(state,old);self.retained.compare(candidate,old,self.m)
        self.environment(candidate);self.ctx.workflow.pf.google_environment(candidate);self.m.verify_secret_mount(candidate);self.m.verify_production_worker_enabled(candidate)
        need(self.m.runtime(original)['config']==self.m.runtime(old)['config'],'ORIGINAL_RUNTIME_CONFIG_DRIFT')
        if not recovery:need(self.m.runtime(original)==self.m.runtime(old),'ORIGINAL_RUNTIME_PROVENANCE_DRIFT')
        if migrated:need(original['State']['Running'] is False,'OLD_WORKER_MUST_REMAIN_STOPPED_AFTER_MIGRATION')
        self.source_boundary(original,before);self.source_boundary(candidate,expected)
        need(type(candidate['RestartCount']) is int and candidate['RestartCount']==0,'CANDIDATE_RESTARTED')
        if live:
            need(candidate['State']['Running'] is True and original['State']['Running'] is False and self.m.inspect('t24-crm')['Id']==candidate['Id'],'SINGLE_LIVE_KNOWN_CANDIDATE_REQUIRED');self.helper.validation_window(candidate)
        else:need(candidate['State']['Running'] is False,'PRESTART_CANDIDATE_STOPPED_REQUIRED')
        if migrated:
            need(self.new_schema(self.m.BUSINESS,empty=not recovery)==r['schema_after_sha256'],'EXACT_NEW_THREE_TABLE_SCHEMA_REQUIRED')
            if baseline is not None:self.retained.compare_original(baseline,self.rows(),rows=not recovery,empty=not recovery)
        elif not recovery:need(self.retained.evidence(self.rows())==self.proof['rows'],'ALL155_ROWS_CHANGED_BEFORE_MIGRATION')
        return original,candidate

    def accept(self,r,old,before,expected,state,baseline,*,updated,recovery=False):
        return self.fresh(r,old,before,expected,state,migrated=True,updated=updated,live=True,baseline=baseline,recovery=recovery)[1]


    def public_check(self,identity):
        need(self.pf.public_security_policy(self.m,CSP_AFTER_SHA)==CSP_AFTER,'ONLY_REVIEWED_MEDIA_SRC_CSP_ALLOWED')
        probe=types.SimpleNamespace(m=self.m,retained=self.retained,proof={**self.proof,'content_security_policy_sha256':CSP_AFTER_SHA},nginx=self.nginx,pf=types.SimpleNamespace(meta_environment=self.environment,security_headers=self.ctx.workflow.pf.security_headers),rows=self.rows)
        probe.delivery_sentinel=lambda value:self.ctx.module.OperationsMethods.delivery_sentinel(probe,value)
        probe.meta_callback_sentinel=lambda value:self.retained.Release.meta_callback_sentinel(probe,value)
        result=self.retained.Release.public_check(probe,identity)
        need(result['content_security_policy_sha256']==CSP_AFTER_SHA,'EXACT_EFFECTIVE_PUBLIC_ASSET_CSP_REQUIRED')
        return {**result,'only_reviewed_media_src_self_blob_added':True}

    def activate(self):
        m,a=self.m,self.args;r,old,before,expected=self.reviewed();self.current();need(not(a.release/'activation-started.json').exists() and not m.inspect_optional(self.old_name) and not m.inspect_optional(self.candidate_name),'FRESH_SWITCH_REQUIRED')
        nginx=m.NGINX.read_bytes();need(H(m.next_nginx(nginx))==r['nginx_next_sha256'],'EXACT_REVIEWED_STATIC_ROOT_REQUIRED');self.record('nginx-before.conf',nginx);self.record('activation-started.json',{'source_sha':SOURCE_SHA,'review_sha256':a.review_sha256,'original_id':old['Id'],'candidate_image':r['candidate_image']})
        status,body=m.retained().docker_request('POST','/containers/create?name='+self.candidate_name,m.clone_config(r['candidate_image'],old));need(status==201,'CANDIDATE_CREATE_FAILED');identity=json.loads(body)['Id'];need(re.fullmatch('[a-f0-9]{64}',identity),'EXACT_CREATED_ID_REQUIRED')
        self.record('candidate-created.json',{'source_sha':SOURCE_SHA,'candidate_id':identity,'candidate_image':r['candidate_image'],'original_id':old['Id'],'review_sha256':a.review_sha256});state=self.state(r,old)
        try:
            _,candidate=self.fresh(r,old,before,expected,state);need(candidate['State']['Status']=='created' and candidate['State'].get('StartedAt') in {'','0001-01-01T00:00:00Z','0001-01-01T00:00:00.000000000Z'},'NEVER_STARTED_CANDIDATE_REQUIRED')
            m.run(['docker','stop','--time','30',old['Id']],'ORIGINAL_STOP_FAILED',60);original,_=self.fresh(r,old,before,expected,state);need(original['State']['Running'] is False,'ORIGINAL_STOPPED_REQUIRED')
            baseline=self.rows();need(self.retained.evidence(baseline)==self.proof['rows'],'STOPPED_ORIGINAL_ROWS_DRIFT')
            baseline_sha=self.record('production-before-rows.json',baseline);self.record('production-baseline-identity.json',{'source_sha':SOURCE_SHA,'original_id':old['Id'],'candidate_id':identity,'review_sha256':a.review_sha256,'rows_sha256':baseline_sha})
            self.run_migration(m.BUSINESS.parent,r['candidate_image']);self.retained.compare_original(baseline,self.rows());need(self.new_schema(m.BUSINESS)==r['schema_after_sha256'],'PRODUCTION_ADDITIVE_SCHEMA_DRIFT');self.fresh(r,old,before,expected,state,migrated=True,baseline=baseline)
            m.run(['docker','rename',old['Id'],self.old_name],'ORIGINAL_RENAME_FAILED');m.run(['docker','rename',identity,'t24-crm'],'CANDIDATE_RENAME_FAILED');self.fresh(r,old,before,expected,state,migrated=True,baseline=baseline)
            m.run(['docker','start',identity],'CANDIDATE_START_FAILED');m.ready(identity);self.accept(r,old,before,expected,state,baseline,updated=False)
            m.replace_nginx(nginx,m.next_nginx(nginx));m.retained().reload_nginx();self.accept(r,old,before,expected,state,baseline,updated=True);privacy=self.public_check(identity);candidate=self.accept(r,old,before,expected,state,baseline,updated=True)
            result={'stage':'MEDIA_ASSET_STUDIO_DEPLOYED','source_sha':SOURCE_SHA,'frontend_version':FRONTEND,'schema_revision':NEW_REVISION,'schema_sha256':r['schema_after_sha256'],'original_table_count':155,'table_count':158,'additive_tables':sorted(NEW_TABLES),'crm':m.runtime(candidate),'original_id':old['Id'],'preflight_sha256':a.preflight_sha256,'prepared_sha256':a.review_sha256,
                'all155_original_tables_preserved_except_reviewed_schema_head':True,'three_new_asset_studio_tables_empty':True,'existing_full_environment_preserved':True,'existing_ops_credentials_preserved':True,'private_boundary_preserved':True,'old_meta_google_cutoff_preserved':True,'python310_and_owner_only_canary_verified':True,'toolchain_receipt_sha256':TOOLCHAIN_RECEIPT_SHA,'toolchain_helper_sha256':TOOLCHAIN_HELPER_SHA,'toolchain_image':TOOLCHAIN_IMAGE,'renderer_canary_sha256':RENDERER_CANARY_SHA,'renderer_canary_result_sha256':r['renderer_canary_result_sha256'],'asset_worker_default_enabled_without_env_change':True,'only_reviewed_csp_media_src_added':True,
                'operations_execution_enabled':False,'operations_scheduler_enabled':False,'database_restored':False,'provider_requests':False,'credentials_journaled':False,'production_containers_deleted':False,'publications_or_ai_generation_executed':False,'privacy':privacy}
            return {**result,'receipt_sha256':self.record('deployed.json',result)}
        except BaseException:self.recover_internal(r,old,before,expected);raise


    def recover_internal(self,r,old,before,expected):
        # Retained durable migration settlement and forward-only recovery are
        # parameterized with this exact three-table schema. Never restore DB,
        # drop tables, or restart old code after a committed new schema head.
        result=self.retained.Release.recover_internal(self,r,old,before,expected)
        result={**result,'stage':result['stage'].replace('META_BUSINESS_','MEDIA_ASSET_STUDIO_'),'operations_execution_enabled':False,'operations_scheduler_enabled':False}
        self.record('asset-studio-recovery-result.json',result);return result


    def recover(self):
        r,old,before,expected=self.reviewed();need(not(self.args.release/'deployed.json').exists(),'SUCCESSFUL_DEPLOYMENT_REQUIRES_SEPARATE_RECOVERY_REVIEW')
        if not(self.args.release/'candidate-created.json').exists():self.current();return {'stage':'MEDIA_ASSET_STUDIO_ORIGINAL_UNCHANGED','manual_orphan_review_required':True,'database_restored':False}
        return self.recover_internal(r,old,before,expected)


PREPARED_TRUE=('offline_additive_only','offline_original155_rows_unchanged_except_schema_head','offline_new3_tables_empty','offline_own_metadata_unchanged','actual_python310_verified','exact_monthly_and_existing_routes','offline_owner_only_without_sql_or_network','offline_network_none','offline_credentials_absent','offline_workers_off','existing_full_environment_preserved','existing_ops_credentials_preserved','operations_execution_disabled','operations_scheduler_disabled','only_static_root_and_reviewed_csp_changes','verified_toolchain_used','actual_final_renderer_verified','offline_asset_worker_disabled')
PREPARED_FALSE=('provider_requests','production_database_written','credentials_journaled','environment_changed','publications_or_ai_generation_executed')


def validate_prepared(value,manifest,payload,preflight):
    need(value['stage']=='MEDIA_ASSET_STUDIO_PREPARED' and value['source_sha']==SOURCE_SHA and value['frontend_version']==FRONTEND and value['schema_revision']==NEW_REVISION and value['old_schema_revision']==OLD_REVISION and value['original_table_count']==155 and value['new_table_count']==158 and value['additive_tables']==sorted(NEW_TABLES),'EXACT_PREPARED_ADDITIVE_MONTHLY_SCOPE_REQUIRED')
    need(type(value.get('nginx_csp_policy_occurrences')) is int and 1<=value['nginx_csp_policy_occurrences']<=12,'EXACT_PREPARED_CSP_LOCATION_COUNT_REQUIRED')
    need(value['manifest_sha256']==manifest and value['payload_sha256']==payload and value['preflight_sha256']==preflight==ACTUAL_PREFLIGHT_SHA,'EXACT_PREPARED_FILE_IDENTITIES_REQUIRED')
    need(value['toolchain_receipt_sha256']==TOOLCHAIN_RECEIPT_SHA and value['toolchain_helper_sha256']==TOOLCHAIN_HELPER_SHA and value['toolchain_image']==TOOLCHAIN_IMAGE and value['renderer_canary_sha256']==RENDERER_CANARY_SHA and re.fullmatch('[a-f0-9]{64}',value['renderer_canary_result_sha256']),'EXACT_PREPARED_TOOLCHAIN_AND_REAL_RENDERER_REQUIRED')
    need(all(value[key] is True for key in PREPARED_TRUE) and all(value[key] is False for key in PREPARED_FALSE),'EXACT_OFFLINE_ADDITIVE_DRAFT_ONLY_ACCEPTANCE_REQUIRED')
    need(all(re.fullmatch('[a-f0-9]{64}',value.get(key,'')) for key in ('schema_after_sha256','original_runtime_sha256','original_inventory_sha256','candidate_inventory_sha256','public_inventory_sha256','nginx_next_sha256')) and re.fullmatch('sha256:[a-f0-9]{64}',value.get('candidate_image','')) and value.get('public_root')=='/var/www/t24-crm-public/'+SCOPE+'-'+SOURCE_SHA[:12]+'-20261101','EXACT_PREPARED_IMAGE_STATIC_AND_SCHEMA_PINS_REQUIRED')


def Release(args):
    pins_ready();pf,flow,inventory,retained=_load(args)
    return type('GuardedPrivateAssetStudioRelease',(Methods,retained.Release),{})(args,pf,flow,inventory,retained)



def main():
    parser=argparse.ArgumentParser();parser.add_argument('--phase',choices=('prepare','activate','recover'),required=True);parser.add_argument('--release',type=Path,required=True);parser.add_argument('--manifest-sha256',required=True);parser.add_argument('--payload-sha256',required=True);parser.add_argument('--preflight',type=Path,required=True);parser.add_argument('--preflight-sha256',required=True);parser.add_argument('--review-sha256');args=parser.parse_args()
    pins_ready();need(os.geteuid()==0 and socket.gethostname()==HOST,'EXACT_ROOT_SERVER_REQUIRED');resource.setrlimit(resource.RLIMIT_CORE,(0,0));os.umask(0o077)
    need(args.release.resolve()==args.release and args.release.parent==Path('/opt/t24-crm/releases') and args.preflight_sha256==ACTUAL_PREFLIGHT_SHA and args.preflight==Path('/opt/t24-crm/releases/media-asset-studio-preflight-'+ACTUAL_PREFLIGHT_SHA[:12]+'.json'),'EXACT_PROTECTED_PHASE_PATHS_REQUIRED')
    for parent in (args.release,*args.release.parents):
        row=parent.lstat();need(parent.resolve()==parent and stat.S_ISDIR(row.st_mode) and row.st_uid==0 and not row.st_mode&0o022,'PROTECTED_RELEASE_PARENT_REQUIRED')
    need(stat.S_IMODE(args.release.lstat().st_mode)==0o700 and all(re.fullmatch('[a-f0-9]{64}',value) for value in (args.manifest_sha256,args.payload_sha256,args.preflight_sha256)) and (args.phase!='prepare' or args.review_sha256 is None),'EXACT_PHASE_PINS_REQUIRED')
    fd=os.open('/opt/t24-crm/releases/.media-ops-monthly.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        row=os.fstat(fd);need(stat.S_ISREG(row.st_mode) and row.st_uid==0 and row.st_nlink==1 and stat.S_IMODE(row.st_mode)==0o600,'ROOT_PRIVATE_LOCK_REQUIRED');fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);print(json.dumps(getattr(Release(args),args.phase)(),sort_keys=True))
    finally:os.close(fd)


if __name__=='__main__':
    try:main()
    except BaseException as exc:
        value=str(exc);code=value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',value) else 'MEDIA_ASSET_STUDIO_RELEASE_REJECTED';print(json.dumps({'stage':'MEDIA_ASSET_STUDIO_RELEASE_REJECTED','code':code,'database_restored':False}));raise SystemExit(1)
