"""Exact backend-only diagnostic patch; no static, Nginx, schema or env changes."""
import argparse
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import socket
import stat
import sys
import time
import types

H=lambda body:hashlib.sha256(body).hexdigest()
HOST='iZj6c4cj7edgnhdimts4l7Z'
SOURCE_SHA='a03766539ef3430f350f467652511a43ee3c4abf'
APPLICATION_FREEZE_SHA='0963aadc922ba34873e89105d13373ef2a41dbaca1b4640228c4afcfcd4a9695'
FRONTEND='58d2c585210f'
BASE_SOURCE='6cf69fbe4cbe8f13eb359df0fbae7f4fb7180729'
REVISION='bde8da01f247'
SCOPE='meta-oauth-diagnostics'
ACTUAL_PREFLIGHT_SHA='3ae9447b3242ff8173d9dd6be75966a12d571652779bbe89124e58930135d05a'
PREFLIGHT_SHA='f842386c5a9f4b9979324d81d5ef11d81a88e0518dee3dd0eeaa937c1b07b559'
BACKEND_FILES=frozenset({'services/meta_business_provider.py','routers/meta_business.py'})
TEST_FILES=frozenset({'app/backend/tests/test_meta_business_callback_diagnostics.py'})
SOURCE_FILES=frozenset('app/backend/'+name for name in BACKEND_FILES)|TEST_FILES


def need(ok,code):
    if not ok:raise RuntimeError(code)


def digest(value):return H(json.dumps(value,sort_keys=True,separators=(',',':')).encode())
def encoded(value):return (json.dumps(value,sort_keys=True,indent=2)+'\n').encode()


def pins_ready():
    need(isinstance(SOURCE_SHA,str) and re.fullmatch('[a-f0-9]{40}',SOURCE_SHA) and SOURCE_SHA!='0'*40 and isinstance(APPLICATION_FREEZE_SHA,str) and re.fullmatch('[a-f0-9]{64}',APPLICATION_FREEZE_SHA) and APPLICATION_FREEZE_SHA!='0'*64 and isinstance(TEST_FILES,frozenset) and bool(TEST_FILES) and SOURCE_FILES==frozenset('app/backend/'+name for name in BACKEND_FILES)|TEST_FILES,'ACTUAL_DIAGNOSTIC_SOURCE_AND_FREEZE_REQUIRED')


def local_bytes(path,maximum=1048576):
    path=Path(path);row=path.lstat();need(path.resolve()==path.absolute() and stat.S_ISREG(row.st_mode) and row.st_nlink==1,'CANONICAL_REGULAR_LOCAL_SOURCE_REQUIRED')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as stream:opened=os.fstat(stream.fileno());body=stream.read(maximum+1)
    after=path.lstat();fields=lambda v:(v.st_dev,v.st_ino,v.st_size,v.st_mtime_ns,v.st_ctime_ns,v.st_nlink)
    need(fields(row)==fields(opened)==fields(after) and len(body)<=maximum,'LOCAL_SOURCE_READ_DRIFT');return body


def validate_summary(value):
    need(value['stage']=='META_OAUTH_DIAGNOSTICS_PREFLIGHT_CAPTURED' and value['source_sha']==BASE_SOURCE and value['frontend_version']==FRONTEND and value['schema_revision']==REVISION and value['table_count']==141,'EXACT_CURRENT_META_BASELINE_REQUIRED')
    need(all(value[k] is True for k in ('meta_enabled_configured','exact_nine_meta_environment_keys_preserved','meta_existing_rows_preserved','google_scheduler_enabled')) and all(value[k] is False for k in ('credential_file_content_read','private_content_read','business_writes','provider_requests','runtime_changed')),'READONLY_CONFIGURED_META_BASELINE_REQUIRED')
    need(value['sha256']==ACTUAL_PREFLIGHT_SHA and value['path']=='/opt/t24-crm/releases/meta-oauth-diagnostics-preflight-'+value['sha256'][:12]+'.json','EXACT_DIAGNOSTIC_PROOF_PATH_REQUIRED')


def compare(candidate,original,image,m):
    need(candidate['Image']==image and candidate['Config']['Env']==original['Config']['Env'] and candidate['Config'].get('Labels')==original['Config'].get('Labels'),'EXACT_PATCH_IMAGE_ENV_AND_LABELS_REQUIRED')
    for info in (candidate,original):
        need(info['HostConfig'].get('AutoRemove') is False,'PRODUCTION_AUTOREMOVE_FORBIDDEN')
        oom=info['HostConfig'].get('OomKillDisable','missing');need(oom is None or oom is False,'EXACT_OOM_DEFAULT_REQUIRED')
        for item in info.get('NetworkSettings',{}).get('Networks',{}).values():need(item.get('IPAMConfig') is None or item.get('IPAMConfig')=={},'EXPLICIT_IPAM_UNSUPPORTED')
    left,right=original['HostConfig']['OomKillDisable'],candidate['HostConfig']['OomKillDisable'];need(left is right or left is None and right is False,'UNPROVEN_OOM_DEFAULT_DIRECTION')
    normalized=copy.deepcopy(candidate)
    for key in ('Image','Hostname'):normalized['Config'][key]=copy.deepcopy(original['Config'].get(key))
    normalized['HostConfig']['OomKillDisable']=left
    need(m.runtime(normalized)['config']==m.runtime(original)['config'],'NON_IMAGE_RUNTIME_CONFIGURATION_CHANGED')


class Release:
    def __init__(self,args):
        pins_ready();self.args=args;path=args.release/'preflight.py'
        row=path.lstat();need(row.st_uid==0 and stat.S_IMODE(row.st_mode)==0o600,'PROTECTED_PREFLIGHT_REQUIRED')
        body=local_bytes(path);need(H(body)==PREFLIGHT_SHA,'EXACT_REVIEWED_PREFLIGHT_REQUIRED')
        self.pf=types.ModuleType('_diagnostic_preflight');self.pf.__file__=str(path);exec(compile(body,str(path),'exec'),self.pf.__dict__)
        self.core,self.baseline,self.activation,self.ctx=self.pf.dependencies();self.m=self.ctx.m;self.w=self.ctx.release;self.base=self.ctx.base;self.helper=self.ctx.helper
        self.proof=json.loads(self.pf.read(args.preflight,args.preflight_sha256));self.manifest=json.loads(self.m.read(args.release/'manifest.json',args.manifest_sha256));self.m.read(args.release/'payload.tar.gz',args.payload_sha256);self.validate()
        need(args.release==Path('/opt/t24-crm/releases/'+SCOPE+'-'+SOURCE_SHA[:12]+'-20261101'),'EXACT_DIAGNOSTIC_RELEASE_PATH_REQUIRED')
        self.source=SOURCE_SHA;self.version=FRONTEND
        self.m.SOURCE,self.m.SCOPE,self.m.BACKEND=SOURCE_SHA,SCOPE,set(BACKEND_FILES);self.m.BASE_IMAGE=self.proof['crm']['image']
        self.old_name='t24-crm-before-'+SCOPE+'-'+SOURCE_SHA[:12];self.candidate_name='t24-crm-candidate-'+SCOPE+'-'+SOURCE_SHA[:12];self.offline_name='t24-'+SCOPE+'-offline-'+SOURCE_SHA[:12]

    def validate(self):
        p,v,a=self.proof,self.manifest,self.args
        need(a.preflight_sha256==ACTUAL_PREFLIGHT_SHA and p['stage']=='META_OAUTH_DIAGNOSTICS_READONLY_PREFLIGHT' and p['host']==HOST and p['source_sha']==BASE_SOURCE and p['frontend_version']==FRONTEND and p['schema_revision']==REVISION and len(p['rows'])==141,'EXACT_ACTUAL_CONFIGURED_META_PROOF_REQUIRED')
        need(p['crm']['id']==self.pf.ORIGINAL_ID and p['crm']['image']==self.pf.IMAGE and p['activated_receipt_sha256']==self.pf.ACTIVATED_SHA and all(p[k] is True for k in ('meta_enabled_configured','exact_nine_meta_environment_keys_preserved','meta_existing_rows_preserved','google_scheduler_enabled')),'EXACT_ACTIVE_RUNTIME_REQUIRED')
        need(v['source_sha']==SOURCE_SHA and v['application_freeze_sha256']==APPLICATION_FREEZE_SHA and v['baseline_source_sha']==BASE_SOURCE and v['frontend_version']==FRONTEND and v['schema_revision']==REVISION,'EXACT_DIAGNOSTIC_SOURCE_SCOPE_REQUIRED')
        need(all(v[k] is False for k in ('database_migration','production_seed_rows','credentials_included','frontend_changed','nginx_changed','runtime_environment_changed')) and v['existing_meta_and_google_data_preserved'] is True,'BACKEND_ONLY_NO_BUSINESS_CONFIGURATION_CHANGE_REQUIRED')
        need(set(v['changed_source_files'])==SOURCE_FILES and len(v['changed_source_files'])==len(SOURCE_FILES),'EXACT_DIAGNOSTIC_APPLICATION_DELTA_REQUIRED')
        need(v['preflight_sha256']==a.preflight_sha256 and v['payload_sha256']==a.payload_sha256 and set(v['backend_before'])==set(v['backend_after'])==BACKEND_FILES and v['backend_before']==p['backend_changed_before'],'EXACT_BACKEND_PROOF_AND_PACKAGE_REQUIRED')
        need(set(v['files'])=={'backend/'+name for name in BACKEND_FILES} and all(v['files']['backend/'+name]==v['backend_after'][name] and v['backend_before'][name]!=v['backend_after'][name] for name in BACKEND_FILES),'EXACT_TWO_RUNTIME_ONLY_PAYLOAD_REQUIRED')
        need(all(isinstance(value,str) and re.fullmatch('[a-f0-9]{64}',value) for value in [*v['files'].values(),*v['backend_before'].values(),*v['backend_after'].values()]),'EXACT_RUNTIME_MEMBER_HASHES_REQUIRED')

    def record(self,name,value):
        sha=self.m.write(self.args.release/name,value);fd=os.open(self.args.release,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:os.fsync(fd)
        finally:os.close(fd)
        return sha

    def rows(self,path=None):return self.w.snapshot(self.m,path or self.m.BUSINESS)
    def metadata(self,path):return self.helper.db_metadata(path)
    def source_boundary(self,info,expected):return self.base.Release.source_overlay_boundary(self,info,expected)

    def boundaries(self,*,recovery=False):
        current=self.baseline.protected_sample(self.ctx);p=self.proof
        self.w.sequence_boundary(p['database_metadata'],current['database_metadata'],recovery=True) if recovery else self.w.live_sequence_boundary(p['database_metadata'],current['database_metadata'])
        for key,value in current.items():
            if key=='database_metadata' or recovery and key=='rows':continue
            need(value==p[key],'CURRENT_DATA_SCHEMA_STATIC_NGINX_OR_PRIVATE_DRIFT')
        need(self.ctx.safe.protected_metadata(self.core.ENV_FILE)==p['meta_credential_metadata'],'EXISTING_META_KEY_FILE_METADATA_CHANGED')
        need(H(self.pf.read(self.pf.ACTIVATION_ROOT/'credential-receipt.json',self.pf.CREDENTIAL_RECEIPT_SHA))==p['meta_credential_receipt_sha256'],'EXISTING_META_CREDENTIAL_RECEIPT_CHANGED')
        self.core.directory(self.core.ENV_FILE.parent)

    def nginx(self,updated=False):
        self.boundaries();return self.proof['active_nginx_sha256']

    def environment(self,info):
        self.ctx.pf.google_environment(info);need(self.pf.meta_environment(self.core,info)==self.proof['meta_environment_sha256'] and digest(info['Config']['Env'])==self.proof['environment_sha256'],'EXACT_EXISTING_META_AND_GOOGLE_ENV_REQUIRED')
        self.m.verify_secret_mount(info);self.m.verify_production_worker_enabled(info)

    def current(self):
        self.boundaries();old=self.m.inspect('t24-crm');need(old['State']['Running'] is True and self.m.runtime(old)==self.proof['crm'],'EXACT_ORIGINAL_RUNTIME_REQUIRED');self.environment(old)
        inventory=self.m.inventory(old['Id']);need(digest(inventory)==self.proof['backend_inventory_sha256'] and len(inventory)==self.proof['backend_file_count'],'CURRENT_BACKEND_INVENTORY_DRIFT');self.m.ready(old['Id']);return old,inventory

    def image(self):
        m=self.m;need(m.image_id(m.BASE_IMAGE)==m.BASE_IMAGE,'EXACT_LOCAL_BASE_IMAGE_REQUIRED');base='t24-crm:'+SCOPE+'-base-'+SOURCE_SHA[:12];found=m.image_id(base);need(found is None or found==m.BASE_IMAGE,'BASE_TAG_DRIFT')
        if found is None:m.run(['docker','image','tag',m.BASE_IMAGE,base],'BASE_TAG_FAILED')
        m.write(self.args.release/'Dockerfile',('FROM '+base+'\n'+''.join('COPY backend/'+name+' /app/backend/'+name+'\n' for name in sorted(BACKEND_FILES))).encode());m.write(self.args.release/'.dockerignore',m.dockerignore());tag='t24-crm:'+SCOPE+'-'+SOURCE_SHA[:12]
        m.run(['docker','build','--network=none','--pull=false','-t',tag,str(self.args.release)],'PATCH_IMAGE_BUILD_FAILED',300);image=m.image_id(tag);need(image!=m.BASE_IMAGE and re.fullmatch('sha256:[a-f0-9]{64}',image or ''),'EXACT_DIAGNOSTIC_IMAGE_REQUIRED');return image

    def offline_args(self,data,image):return self.w.Release.offline_args(self,data,image)
    def route_probe(self):return self.w.Release.route_probe(self)

    def prepare(self):
        self.helper.docker_timestamp_probe();m,a=self.m,self.args;old,before=self.current();need({path.name for path in a.release.iterdir()}=={'release.py','preflight.py','manifest.json','payload.tar.gz'},'FRESH_DIAGNOSTIC_STAGING_REQUIRED')
        m.extract(a.release,self.manifest);expected={**before,**self.manifest['backend_after']};before_sha=self.record('backend-before.json',before);after_sha=self.record('backend-after.json',expected)
        image=self.image();data=a.release/'probe-data';data.mkdir(mode=0o700);(a.release/'probe-logs').mkdir(mode=0o700);m.backup(m.BUSINESS,data/'crm_prod.db')
        rows=self.rows(data/'crm_prod.db');metadata=self.metadata(data/'crm_prod.db');objects=self.w.objects(data/'crm_prod.db');need(self.w.evidence(rows)==self.proof['rows'] and m.schema_signature(data/'crm_prod.db',REVISION)==self.proof['schema_sha256'],'ISOLATED_COPY_DRIFT');self.w.live_sequence_boundary(self.proof['database_metadata'],metadata)
        need(not m.inspect_optional(self.offline_name),'FRESH_OFFLINE_CANDIDATE_REQUIRED');argv=self.offline_args(data,image);argv[2:2]=['--name',self.offline_name,'-d'];m.run(argv,'OFFLINE_START_FAILED')
        try:
            m.ready(self.offline_name);info=m.inspect(self.offline_name);self.base.verify_disabled_environment(info);self.ctx.pf.meta_environment(info);need(m.inventory(self.offline_name)==expected,'OFFLINE_PATCH_SOURCE_DRIFT')
            checks=[("import sys;assert sys.version_info[:2]==(3,10);print('EXACT_PYTHON310')",b'EXACT_PYTHON310'),(self.route_probe(),b'EXACT_META_AND_EXISTING_MEDIA_GOOGLE_ROUTES'),(self.base.gbp_disabled_probe(),b'EXACT_GBP_DISABLED_UNCONFIGURED_NO_NETWORK'),(self.w.Release.meta_disabled_probe(self),b'EXACT_META_ABSENT_DISABLED_NO_NETWORK')]
            for code,marker in checks:need(marker in m.run(['docker','exec',self.offline_name,'python','-B','-c',code],'OFFLINE_SOURCE_OR_ROUTES_PROBE_FAILED'),'EXACT_OFFLINE_PROBE_MARKER_REQUIRED')
        finally:m.run(['docker','stop','--time','20',self.offline_name],'OFFLINE_STOP_FAILED',45)
        need(self.rows(data/'crm_prod.db')==rows and self.metadata(data/'crm_prod.db')==metadata and self.w.objects(data/'crm_prod.db')==objects and m.schema_signature(data/'crm_prod.db',REVISION)==self.proof['schema_sha256'],'OFFLINE_STARTUP_CHANGED_DATABASE')
        self.current();result={'stage':'META_OAUTH_DIAGNOSTICS_PREPARED','source_sha':SOURCE_SHA,'frontend_version':FRONTEND,'schema_revision':REVISION,'schema_sha256':self.proof['schema_sha256'],'old_crm':self.proof['crm'],'candidate_image':image,'preflight_sha256':a.preflight_sha256,'manifest_sha256':a.manifest_sha256,'payload_sha256':a.payload_sha256,'before_inventory_sha256':before_sha,'after_inventory_sha256':after_sha,'table_count':141,'backend_only':True,'all_current_rows_schema_metadata_preserved':True,'existing_meta_rows_preserved':True,'offline_credentials_absent':True,'offline_network_none':True,'offline_workers_off':True,'python310_and_exact_routes_verified':True,'frontend_static_nginx_csp_unchanged':True,'original_inspect_credentials_persisted':False,'provider_requests':False,'production_database_written':False,'runtime_environment_changed':False};sha=self.record('prepared.json',result);return {**result,'receipt_sha256':sha}

    def reviewed(self,*,recovery=False):
        m,a=self.m,self.args;need(re.fullmatch('[a-f0-9]{64}',a.review_sha256 or ''),'ACTUAL_PREPARED_REVIEW_REQUIRED');r=json.loads(m.read(a.release/'prepared.json',a.review_sha256))
        need(r['stage']=='META_OAUTH_DIAGNOSTICS_PREPARED' and r['source_sha']==SOURCE_SHA and r['frontend_version']==FRONTEND and r['schema_revision']==REVISION and r['schema_sha256']==self.proof['schema_sha256'] and r['old_crm']==self.proof['crm'] and r['table_count']==141,'EXACT_PREPARED_DIAGNOSTIC_SCOPE_REQUIRED')
        need(r['manifest_sha256']==a.manifest_sha256 and r['payload_sha256']==a.payload_sha256 and r['preflight_sha256']==a.preflight_sha256,'EXACT_PREPARED_PINS_REQUIRED')
        need(all(r[k] is True for k in ('backend_only','all_current_rows_schema_metadata_preserved','existing_meta_rows_preserved','offline_credentials_absent','offline_network_none','offline_workers_off','python310_and_exact_routes_verified','frontend_static_nginx_csp_unchanged')) and all(r[k] is False for k in ('original_inspect_credentials_persisted','provider_requests','production_database_written','runtime_environment_changed')),'EXACT_OFFLINE_ACCEPTANCE_REQUIRED')
        before=json.loads(m.read(a.release/'backend-before.json',r['before_inventory_sha256']));expected=json.loads(m.read(a.release/'backend-after.json',r['after_inventory_sha256']));need(digest(before)==self.proof['backend_inventory_sha256'] and expected=={**before,**self.manifest['backend_after']},'EXACT_PREPARED_SOURCE_INVENTORIES_REQUIRED')
        if recovery:return r,None,before,expected
        old=m.inspect(self.proof['crm']['id']);need(old['Image']==self.proof['crm']['image'] and m.runtime(old)['config']==self.proof['crm']['config'] and m.image_id(r['candidate_image'])==r['candidate_image'],'EXACT_ORIGINAL_CONFIG_AND_PATCH_IMAGE_REQUIRED');return r,old,before,expected

    def state(self,r):
        value=json.loads(self.m.read(self.args.release/'candidate-created.json'));need(value=={'source_sha':SOURCE_SHA,'candidate_id':value['candidate_id'],'candidate_image':r['candidate_image'],'original_id':self.proof['crm']['id'],'review_sha256':self.args.review_sha256} and re.fullmatch('[a-f0-9]{64}',value['candidate_id']) and value['candidate_id']!=value['original_id'],'EXACT_DURABLE_PATCH_CANDIDATE_REQUIRED');return value

    def identities(self,state):
        m=self.m;old=m.inspect(state['original_id']);candidate=m.inspect(state['candidate_id']);need(old['Image']==self.proof['crm']['image'] and old['Name'] in {'/t24-crm','/'+self.old_name},'KNOWN_ORIGINAL_REQUIRED');need(candidate['Image']==state['candidate_image'] and candidate['Name'] in {'/t24-crm','/'+self.candidate_name},'KNOWN_PATCH_CANDIDATE_REQUIRED')
        for name,identity in (('t24-crm',None),(self.old_name,old['Id']),(self.candidate_name,candidate['Id'])):
            found=m.inspect_optional(name);need(not found or found['Id'] in ({old['Id'],candidate['Id']} if identity is None else {identity}),'UNKNOWN_PRIMARY_OR_RESERVED_CONTAINER')
        return old,candidate

    def fresh(self,r,before,expected,state,*,live=False,recovery=False):
        self.boundaries(recovery=recovery);old,candidate=self.identities(state);compare(candidate,old,r['candidate_image'],self.m);self.environment(old);self.environment(candidate);self.source_boundary(old,before);self.source_boundary(candidate,expected)
        if not recovery:need(self.m.runtime(old)==self.proof['crm'],'ORIGINAL_RUNTIME_PROVENANCE_DRIFT')
        need(type(candidate['RestartCount']) is int and (candidate['RestartCount']>=0 if recovery else candidate['RestartCount']==0),'PATCH_CANDIDATE_RESTARTED')
        if live:need(candidate['State']['Running'] is True and old['State']['Running'] is False and self.m.inspect('t24-crm')['Id']==candidate['Id'],'EXACT_SINGLE_LIVE_PATCH_REQUIRED');self.helper.validation_window(candidate)
        else:need(candidate['State']['Running'] is False,'STOPPED_PATCH_CANDIDATE_REQUIRED')
        return old,candidate

    def public_check(self,r,before,expected,state):
        old,candidate=self.fresh(r,before,expected,state,live=True)
        probe=types.SimpleNamespace(m=self.m,proof=self.proof,nginx=lambda **_:self.nginx(),rows=lambda:self.m.sql_snapshot(self.m.BUSINESS),pf=types.SimpleNamespace(meta_environment=self.environment,security_headers=self.ctx.pf.security_headers))
        probe.delivery_sentinel=lambda identity:self.w.Release.delivery_sentinel(probe,identity);probe.meta_callback_sentinel=lambda identity:self.w.Release.meta_callback_sentinel(probe,identity)
        result=self.w.Release.public_check(probe,candidate['Id']);self.fresh(r,before,expected,state,live=True);return result

    def activate(self):
        m,a=self.m,self.args;r,old,before,expected=self.reviewed();self.current();need(not (a.release/'activation-started.json').exists() and not m.inspect_optional(self.old_name) and not m.inspect_optional(self.candidate_name),'FRESH_DIAGNOSTIC_SWITCH_REQUIRED')
        self.record('activation-started.json',{'source_sha':SOURCE_SHA,'review_sha256':a.review_sha256,'original_id':old['Id'],'candidate_image':r['candidate_image']})
        config=copy.deepcopy(old['Config']);config.update(Image=r['candidate_image'],Hostname='');config['HostConfig']=copy.deepcopy(old['HostConfig']);networks=m.retained().clone_networks(old);need(networks or old['HostConfig']['NetworkMode'] in {'host','none'},'ORIGINAL_NETWORKS_REQUIRED');config['NetworkingConfig']={'EndpointsConfig':networks}
        status,raw=m.retained().docker_request('POST','/containers/create?name='+self.candidate_name,config);need(status==201,'PATCH_CANDIDATE_CREATE_FAILED');identity=json.loads(raw)['Id'];need(re.fullmatch('[a-f0-9]{64}',identity),'EXACT_CREATED_PATCH_ID_REQUIRED')
        self.record('candidate-created.json',{'source_sha':SOURCE_SHA,'candidate_id':identity,'candidate_image':r['candidate_image'],'original_id':old['Id'],'review_sha256':a.review_sha256});state=self.state(r)
        try:
            _,candidate=self.fresh(r,before,expected,state);need(candidate['State']['Status']=='created' and candidate['State'].get('StartedAt') in {'','0001-01-01T00:00:00Z','0001-01-01T00:00:00.000000000Z'},'NEVER_STARTED_PATCH_REQUIRED')
            m.run(['docker','stop','--time','30',old['Id']],'ORIGINAL_STOP_FAILED',60);retained,_=self.fresh(r,before,expected,state);need(retained['State']['Running'] is False,'ORIGINAL_STOPPED_REQUIRED')
            m.run(['docker','rename',old['Id'],self.old_name],'ORIGINAL_RENAME_FAILED');m.run(['docker','rename',identity,'t24-crm'],'PATCH_RENAME_FAILED');self.fresh(r,before,expected,state)
            m.run(['docker','start',identity],'PATCH_START_FAILED');m.ready(identity);self.fresh(r,before,expected,state,live=True)
            need(m.run(['docker','exec',identity,'python','-B','-c',self.activation._configured_probe()],'META_AND_GOOGLE_CONFIGURATION_PROBE_FAILED').strip()==b'EXACT_META_CONFIGURED_GOOGLE_ON_NO_NETWORK','EXACT_CONFIGURED_PROBE_MARKER_REQUIRED')
            privacy=self.public_check(r,before,expected,state);_,candidate=self.fresh(r,before,expected,state,live=True)
            result={'stage':'META_OAUTH_DIAGNOSTICS_DEPLOYED','source_sha':SOURCE_SHA,'frontend_version':FRONTEND,'schema_revision':REVISION,'crm':m.runtime(candidate),'preflight_sha256':a.preflight_sha256,'prepared_sha256':a.review_sha256,'candidate_inventory_sha256':r['after_inventory_sha256'],'two_backend_runtime_files_only':True,'all_141_current_business_rows_schema_and_private_preserved':True,'existing_meta_nine_env_and_key_preserved':True,'google_on_cutoff_preserved':True,'frontend_static_nginx_csp_unchanged':True,'schema_migrated':False,'business_writes':False,'provider_requests_by_tool':False,'database_restored':False,'containers_deleted':False,'inspect_credentials_persisted':False,**privacy};sha=self.record('deployed.json',result);return {**result,'receipt_sha256':sha}
        except BaseException:self.recover_internal(r,before,expected);raise

    def recover_internal(self,r,before,expected):
        m=self.m;state=self.state(r);candidate=m.inspect(state['candidate_id']);need(candidate['Id']==state['candidate_id'] and candidate['Image']==r['candidate_image'],'KNOWN_DURABLE_PATCH_FOR_CONTAINMENT_REQUIRED')
        if candidate['State']['Running']:m.run(['docker','stop','--time','30',candidate['Id']],'PATCH_CONTAINMENT_FAILED',60)
        need(m.inspect(candidate['Id'])['State']['Running'] is False,'PATCH_CONTAINED_REQUIRED');old,candidate=self.fresh(r,before,expected,state,recovery=True)
        need(m.runtime(old)['config']==self.proof['crm']['config'],'ORIGINAL_CONFIG_CHANGED')
        if candidate['Name']=='/t24-crm':m.run(['docker','rename',candidate['Id'],self.candidate_name],'RETAIN_PATCH_NAME_FAILED')
        if old['Name']!='/t24-crm':m.run(['docker','rename',old['Id'],'t24-crm'],'RESTORE_ORIGINAL_NAME_FAILED')
        if not old['State']['Running']:m.run(['docker','start',old['Id']],'ORIGINAL_RESUME_FAILED')
        m.ready(old['Id']);restored=m.inspect('t24-crm');need(restored['Id']==self.proof['crm']['id'] and restored['State']['Running'] is True and m.runtime(restored)['config']==self.proof['crm']['config'],'EXACT_ORIGINAL_NOT_RESTORED');self.environment(restored);self.source_boundary(restored,before);self.boundaries(recovery=True)
        result={'stage':'META_OAUTH_DIAGNOSTICS_ORIGINAL_RESUMED','source_sha':BASE_SOURCE,'original_id':restored['Id'],'candidate_retained_stopped':True,'independent_rows_preserved':True,'database_restored':False,'business_writes':False,'provider_requests':False,'frontend_static_nginx_unchanged':True};self.record('recovery-'+str(time.time_ns())+'.json',result);return result

    def recover(self):
        need(not (self.args.release/'deployed.json').exists(),'SUCCESSFUL_PATCH_REQUIRES_SEPARATE_RECOVERY_REVIEW');r,_,before,expected=self.reviewed(recovery=True);started=json.loads(self.m.read(self.args.release/'activation-started.json'));need(started=={'source_sha':SOURCE_SHA,'review_sha256':self.args.review_sha256,'original_id':self.proof['crm']['id'],'candidate_image':r['candidate_image']},'EXACT_RECOVERY_INTENT_REQUIRED')
        if not (self.args.release/'candidate-created.json').exists():self.current();return {'stage':'META_OAUTH_DIAGNOSTICS_ORIGINAL_UNCHANGED','manual_orphan_review_required':True,'database_restored':False}
        return self.recover_internal(r,before,expected)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--phase',choices=['prepare','activate','recover'],required=True);parser.add_argument('--release',type=Path,required=True);parser.add_argument('--manifest-sha256',required=True);parser.add_argument('--payload-sha256',required=True);parser.add_argument('--preflight',type=Path,required=True);parser.add_argument('--preflight-sha256',required=True);parser.add_argument('--review-sha256');a=parser.parse_args();pins_ready()
    need(os.geteuid()==0 and socket.gethostname()==HOST,'EXACT_ROOT_SERVER_REQUIRED');resource.setrlimit(resource.RLIMIT_CORE,(0,0));os.umask(0o077);sys.dont_write_bytecode=True
    need(a.release.resolve()==a.release and a.release.parent==Path('/opt/t24-crm/releases'),'EXACT_RELEASE_PARENT_REQUIRED')
    for parent in (a.release,*a.release.parents):
        row=parent.lstat();need(parent.resolve()==parent and stat.S_ISDIR(row.st_mode) and row.st_uid==0 and not row.st_mode&0o022,'PROTECTED_RELEASE_DIRECTORY_REQUIRED')
    need(stat.S_IMODE(a.release.lstat().st_mode)==0o700,'PRIVATE_RELEASE_REQUIRED');need(all(re.fullmatch('[a-f0-9]{64}',value) for value in (a.manifest_sha256,a.payload_sha256,a.preflight_sha256)),'EXACT_REVIEWED_FILE_PINS_REQUIRED')
    need(a.preflight==Path('/opt/t24-crm/releases/meta-oauth-diagnostics-preflight-'+a.preflight_sha256[:12]+'.json') and (a.phase!='prepare' or a.review_sha256 is None),'EXACT_PROOF_AND_PREPARE_REVIEW_REQUIRED')
    fd=os.open('/opt/t24-crm/releases/.meta-oauth-diagnostics-release.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        row=os.fstat(fd);need(stat.S_ISREG(row.st_mode) and row.st_uid==0 and row.st_nlink==1 and stat.S_IMODE(row.st_mode)==0o600,'PROTECTED_RELEASE_LOCK_REQUIRED');fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);print(json.dumps(getattr(Release(a),a.phase)(),sort_keys=True))
    finally:os.close(fd)

if __name__=='__main__':
    try:main()
    except BaseException as error:
        value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',value) else 'META_DIAGNOSTIC_RELEASE_REJECTED';print(json.dumps({'stage':'META_OAUTH_DIAGNOSTICS_RELEASE_REJECTED','code':code,'database_restored':False}));sys.exit(1)
