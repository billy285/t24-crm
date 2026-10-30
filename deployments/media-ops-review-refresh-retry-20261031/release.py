"""Exact authoritative-review hotfix. No schema migration, seeds or provider actions."""
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

H=lambda value:hashlib.sha256(value).hexdigest()
SOURCE_SHA='5a52cdcf8e9560fcf5ec6e2b27f264f6f0fe1087'
FRONTEND='50347ba2c9da'
BASE_SOURCE='6b47aefa201fb5e4963e4cfa522b7a5776e5a2c4'
BASE_FRONTEND='b06112728ac2'
BASE_DEPLOYED_SHA='17858808bd0ac0f825e8a51931bdf49cde6253f431a0ab7e8280b301fe3b9f37'
RECOVERED_SHA='9544b445b850c4265a3953e1ffd561c548ac142cb89f84527c807cb944584fe3'
REVISION='d9e4f6a7b803'
SCOPE='media-ops-review-refresh-retry'
PREFLIGHT_SHA='8f22bbc8929a675ef51ca85061d2ffad4f94cc5eec1cad4a794498e5a64dc32d'
BACKEND_FILES={'services/google_business.py','routers/google_business.py'}
SOURCE_FILES={'app/backend/'+n for n in BACKEND_FILES}|{'app/frontend/src/components/GoogleBusinessWorkspace.tsx','app/backend/tests/test_google_business_review_refresh.py'}
HOST='iZj6c4cj7edgnhdimts4l7Z'


def need(ok,code):
    if not ok:raise RuntimeError(code)


def digest(value):return H(json.dumps(value,sort_keys=True,separators=(',',':')).encode())


def compare(candidate,original,m):
    need(candidate['Config']['Env']==original['Config']['Env'],'EXACT_EXISTING_ENVIRONMENT_REQUIRED')
    need(candidate['Config'].get('Labels')==m.expected_labels(original),'EXACT_RELEASE_LABELS_REQUIRED')
    for info in (candidate,original):
        need('OomKillDisable' in info['HostConfig'] and (info['HostConfig']['OomKillDisable'] is None or info['HostConfig']['OomKillDisable'] is False),'EXACT_OOM_DEFAULT_REQUIRED')
        for endpoint in info.get('NetworkSettings',{}).get('Networks',{}).values():need(endpoint.get('IPAMConfig') is None or endpoint.get('IPAMConfig')=={},'EXPLICIT_IPAM_UNSUPPORTED')
    normalized=copy.deepcopy(candidate)
    for key in ('Image','Hostname','Labels'):normalized['Config'][key]=copy.deepcopy(original['Config'].get(key))
    left,right=original['HostConfig']['OomKillDisable'],candidate['HostConfig']['OomKillDisable']
    need(left is right or left is None and right is False,'UNPROVEN_OOM_DEFAULT_DIRECTION')
    normalized['HostConfig']['OomKillDisable']=left
    need(m.runtime(normalized)['config']==m.runtime(original)['config'],'EXACT_RUNTIME_CONFIGURATION_REQUIRED')


def sequence_boundary(before,current,*,forward=False,recovery=False):
    # Protected proof stores values only to compare counters in memory; never
    # print the map or write any counter/database value back.
    for value in (before,current):
        need(set(value)=={'pragma_sha256','sequence_exists','sequence_sha256','sequence_values'},'EXACT_SEQUENCE_VALUES_REQUIRED')
        rows=value['sequence_values']
        need(type(value['sequence_exists']) is bool and isinstance(rows,dict) and all(isinstance(name,str) and type(number) is int and number>=0 for name,number in rows.items()),'EXACT_VALID_SEQUENCE_MAP_REQUIRED')
        need(value['sequence_exists'] or not rows,'SEQUENCE_EXISTENCE_MAP_CONFLICT')
        need(value['sequence_sha256']==digest(sorted(rows.items())),'SEQUENCE_PROOF_HASH_VALUES_CONFLICT')
    need(before['pragma_sha256']==current['pragma_sha256'] and before['sequence_exists'] is current['sequence_exists'],'EXACT_SCHEMA_PRAGMA_METADATA_REQUIRED')
    if recovery:return  # Preserve valid current independent business counters.
    if forward:
        need(set(before['sequence_values'])==set(current['sequence_values']),'SEQUENCE_KEYSET_CHANGED')
        need(all(current['sequence_values'][name]>=number for name,number in before['sequence_values'].items()),'SEQUENCE_COUNTER_REGRESSED')
    else:need(before==current,'EXACT_UNCHANGED_SCHEMA_METADATA_REQUIRED')


class Release:
    def __init__(self,args):
        self.args=args
        helper=args.release/'preflight.py';row=helper.lstat()
        need(helper.resolve()==helper and stat.S_ISREG(row.st_mode) and row.st_uid==0 and row.st_nlink==1 and stat.S_IMODE(row.st_mode)==0o600,'PROTECTED_PREFLIGHT_TOOL_REQUIRED')
        body=helper.read_bytes();need(H(body)==PREFLIGHT_SHA,'FROZEN_PREFLIGHT_TOOL_REQUIRED')
        self.pf=types.ModuleType('_review_refresh_preflight');self.pf.__file__=str(args.release/'preflight.py');exec(compile(body,self.pf.__file__,'exec'),self.pf.__dict__)
        self.m,self.base,self.safe=self.pf.dependencies();m=self.m
        self.manifest=json.loads(m.read(args.release/'manifest.json',args.manifest_sha256));m.read(args.release/'payload.tar.gz',args.payload_sha256)
        self.proof=json.loads(m.read(args.preflight,args.preflight_sha256));self.validate()
        self.pins=json.loads(m.read(self.base.PRIVATE_PINS,self.base.PRIVATE_PINS_SHA))
        self.public=Path('/var/www/t24-crm-public/'+SCOPE+'-'+SOURCE_SHA[:12]+'-20261031')
        need(args.release==Path('/opt/t24-crm/releases/'+SCOPE+'-'+SOURCE_SHA[:12]+'-20261031'),'EXACT_RELEASE_PATH_REQUIRED')
        self.source=SOURCE_SHA;self.version=FRONTEND
        m.SOURCE,m.SCOPE=SOURCE_SHA,SCOPE;m.BASELINE_FRONTEND,m.FRONTEND_VERSION=BASE_FRONTEND,FRONTEND
        m.PUBLIC,m.NGINX_SHA,m.STATIC_SHA=Path(self.proof['public_root']),self.proof['nginx_sha256'],self.proof['public_inventory_sha256']
        m.OLD_ID,m.BASE_IMAGE,m.OLD_CONFIG=(self.proof['crm'][k] for k in ('id','image','config'))
        m.BACKEND=BACKEND_FILES;m.public_root=lambda:self.public
        self.offline_name='t24-'+SCOPE+'-probe-'+SOURCE_SHA[:12]
        self.old_name='t24-crm-before-'+SCOPE+'-'+SOURCE_SHA[:12]
        self.candidate_name='t24-crm-candidate-'+SCOPE+'-'+SOURCE_SHA[:12]

    def validate(self):
        p,v,a=self.proof,self.manifest,self.args
        need(p.get('recovered_sha256')==self.pf.RECOVERED_SHA and p.get('host_docker_timestamp_parser_verified') is True,'EXACT_RECOVERED_HOST_PROBE_REQUIRED')
        need(p['stage']=='MEDIA_OPS_REVIEW_REFRESH_RETRY_READONLY_PREFLIGHT' and p['host']==HOST and p['source_sha']==BASE_SOURCE and p['frontend_version']==BASE_FRONTEND and p['schema_revision']==REVISION,'EXACT_FRESH_BASELINE_REQUIRED')
        need(p['deployed_sha256']==self.pf.DEPLOYED_SHA and p['crm']['id']==self.pf.ORIGINAL_ID and p['crm']['image']==self.pf.IMAGE,'EXACT_DEPLOYED_RUNTIME_REQUIRED')
        need(p['scheduler_disabled'] is True and p['gbp_feature_enabled'] is True and p['callback_logging_protection_retained'] is True and len(p['rows'])==129,'EXACT_ENABLED_OFF_SCHEMA_REQUIRED')
        need(all(p[k] is False for k in ('provider_requests','business_writes','private_content_read','credential_content_read','container_or_configuration_changed')),'READONLY_FACTS_REQUIRED')
        need(v['source_sha']==SOURCE_SHA and v['frontend_version']==FRONTEND and v['baseline_source_sha']==BASE_SOURCE and v['baseline_frontend_version']==BASE_FRONTEND,'EXACT_SOURCE_FRONTEND_REQUIRED')
        need(v['schema_revision']==REVISION and v['database_migration'] is False and v['production_seed_rows'] is False and v['credentials_included'] is False,'NO_DATABASE_OR_SECRET_PAYLOAD_ALLOWED')
        need(set(v['changed_source_files'])==SOURCE_FILES and len(v['changed_source_files'])==len(SOURCE_FILES),'EXACT_FOUR_SOURCE_FILES_REQUIRED')
        need(v['preflight_sha256']==a.preflight_sha256 and v['payload_sha256']==a.payload_sha256,'EXACT_PAYLOAD_BASELINE_REQUIRED')
        need(set(v['backend_before'])==set(v['backend_after'])==BACKEND_FILES and v['backend_before']==p['backend_changed_before'],'EXACT_TWO_BACKEND_BASELINES_REQUIRED')
        need({n[8:] for n in v['files'] if n.startswith('backend/')}==BACKEND_FILES,'EXACT_TWO_BACKEND_PATCHES_REQUIRED')
        need({'static/index.html','static/app-version.json'}<=set(v['files']) and all(n in {'backend/'+p for p in BACKEND_FILES} or n.startswith('static/') and self.m.static_path(n[7:]) for n in v['files']),'EXACT_PATCH_STATIC_SCOPE_REQUIRED')
        need(all(re.fullmatch('[a-f0-9]{64}',s) for s in [*v['files'].values(),*v['backend_before'].values(),*v['backend_after'].values()]),'EXACT_SOURCE_HASHES_REQUIRED')
        need(all(v['files']['backend/'+n]==v['backend_after'][n] for n in BACKEND_FILES),'BACKEND_HASH_IDENTITY_REQUIRED')

    def private_boundary(self):
        need(self.safe.safe_private_boundary(self.m,self.pins)==self.proof['private_boundary'],'PRIVATE_METADATA_OR_RUNTIME_DRIFT')

    def nginx(self,updated=False):return self.base.Release.nginx_boundary(self,updated=updated)

    def protections(self,*,updated=False,recovery=False):
        m,p=self.m,self.proof
        self.private_boundary();need(m.credential_boundary()==p['credential_boundary'] and self.safe.protected_metadata(self.safe.GBP_ENV)==p['google_credential_metadata'],'CREDENTIAL_METADATA_DRIFT')
        row=m.BUSINESS.stat();need([row.st_dev,row.st_ino]==p['database_identity'],'DATABASE_INODE_DRIFT')
        metadata=self.pf.db_metadata(m.BUSINESS);expected=p['database_metadata']
        sequence_boundary(expected,metadata,forward=not recovery,recovery=recovery)
        need(m.schema_signature(m.BUSINESS,REVISION)==p['schema_sha256'],'EXACT_UNCHANGED_SCHEMA_METADATA_REQUIRED')
        need(digest(m.tree(m.PUBLIC))==p['public_inventory_sha256'],'ORIGINAL_STATIC_FILES_DRIFT');self.nginx(updated)

    def rows(self):return self.pf.row_evidence(self.m)
    def source_boundary(self,info,inventory):return self.base.Release.source_overlay_boundary(self,info,inventory)

    def current(self,*,rows=True):
        m,p=self.m,self.proof;self.protections();old=m.inspect('t24-crm')
        need(old['State']['Running'] is True and m.runtime(old)==p['crm'],'CURRENT_RUNTIME_DRIFT')
        self.base.verify_gbp_environment_enabled(old);m.verify_secret_mount(old);m.verify_production_worker_enabled(old);m.retained().require_safe_original_restart(old)
        need(digest(sorted(old['Config']['Env']))==p['environment_sha256'],'CURRENT_ENVIRONMENT_DRIFT')
        inventory=m.inventory(old['Id']);need(digest(inventory)==p['backend_inventory_sha256'] and len(inventory)==p['backend_file_count'],'CURRENT_SOURCE_DRIFT')
        if rows:need(self.rows()==p['rows'],'CURRENT_ROWS_CHANGED_REFRESH_PREFLIGHT')
        m.ready(old['Id']);return old,inventory

    def image(self):
        m=self.m;need(m.image_id(m.BASE_IMAGE)==m.BASE_IMAGE,'EXACT_LOCAL_BASE_IMAGE_REQUIRED')
        base='t24-crm:'+SCOPE+'-base-'+SOURCE_SHA[:12];prior=m.image_id(base)
        need(prior is None or prior==m.BASE_IMAGE,'BASE_TAG_DRIFT')
        if prior is None:m.run(['docker','image','tag',m.BASE_IMAGE,base],'BASE_TAG_CREATE_FAILED')
        m.write(self.args.release/'Dockerfile',('FROM '+base+'\n'+''.join('COPY backend/'+n+' /app/backend/'+n+'\n' for n in sorted(BACKEND_FILES))).encode())
        m.write(self.args.release/'.dockerignore',m.dockerignore());tag='t24-crm:'+SCOPE+'-'+SOURCE_SHA[:12]
        m.run(['docker','build','--network=none','--pull=false','-t',tag,str(self.args.release)],'PATCH_BUILD_FAILED',300)
        need(m.image_id(base)==m.BASE_IMAGE,'BASE_IMAGE_TAG_DRIFT');image=m.image_id(tag)
        need(re.fullmatch('sha256:[a-f0-9]{64}',image or ''),'EXACT_BUILT_IMAGE_REQUIRED');return image

    def route_probe(self):
        base=self.base
        expected=base.GBP_ROUTES|{('/api/v1/google-business/bindings/{binding_id}/review','GET')}
        # Fixed review route is additive; no original route may disappear.
        return "from main import app\nimport fastapi.routing\nschema=app.openapi()\nexpected="+repr(expected)+"\nactual={(p,m.upper()) for p,v in schema['paths'].items() if p.startswith('/api/v1/google-business') for m in v if m.lower() in {'get','post','put','patch','delete','options','head'}}\nassert actual==expected\ncontexts=list(fastapi.routing.iter_route_contexts(app.routes)) if hasattr(fastapi.routing,'iter_route_contexts') else app.routes\nregistered=[(x.path,m) for x in contexts if getattr(x,'path','').startswith('/api/v1/google-business') for m in (getattr(x,'methods',set()) or set())]\nassert len(registered)==len(expected) and set(registered)==expected\nprint('EXACT_AUTHORITATIVE_REVIEW_ROUTE_REGISTERED')\n"

    def prepare(self):
        self.pf.docker_timestamp_probe()
        m,a,v=self.m,self.args,self.manifest;old,before=self.current()
        need({p.name for p in a.release.iterdir()}=={'release.py','preflight.py','manifest.json','payload.tar.gz'},'FRESH_PATCH_STAGING_REQUIRED')
        m.extract(a.release,v);expected={**before,**v['backend_after']}
        original_sha=m.write(a.release/'original-container.json',old);before_sha=m.write(a.release/'backend-original-inventory.json',before);after_sha=m.write(a.release/'backend-candidate-inventory.json',expected)
        image=self.image();data=a.release/'probe-data';data.mkdir(mode=0o700);(a.release/'probe-logs').mkdir(mode=0o700)
        m.backup(m.BUSINESS,data/'crm_prod.db');before_rows=self.pf.row_evidence(type('M',(),{'BUSINESS':data/'crm_prod.db','sql_snapshot':staticmethod(m.sql_snapshot)}))
        offline_metadata=self.pf.db_metadata(data/'crm_prod.db');sequence_boundary(self.proof['database_metadata'],offline_metadata,forward=True)
        need(before_rows==self.proof['rows'] and m.schema_signature(data/'crm_prod.db',REVISION)==self.proof['schema_sha256'],'OFFLINE_COPY_EXACT_REQUIRED')
        need(not m.inspect_optional(self.offline_name),'FRESH_OFFLINE_PROBE_NAME_REQUIRED')
        command=self.base.Release.offline_args(self,data,image);command[2:2]=['--name',self.offline_name,'-d']
        m.run(command,'OFFLINE_START_FAILED')
        try:
            m.ready(self.offline_name);self.base.verify_disabled_environment(m.inspect(self.offline_name))
            need(m.inventory(self.offline_name)==expected,'OFFLINE_PATCH_SOURCE_DRIFT')
            checks=[("import sys;assert sys.version_info[:2]==(3,10);print('EXACT_PYTHON310')",b'EXACT_PYTHON310'),(self.route_probe(),b'EXACT_AUTHORITATIVE_REVIEW_ROUTE_REGISTERED'),(self.base.gbp_disabled_probe(),b'EXACT_GBP_DISABLED_UNCONFIGURED_NO_NETWORK')]
            for code,marker in checks:
                output=m.run(['docker','exec',self.offline_name,'python','-B','-c',code],'OFFLINE_EXACT_PROBE_FAILED');need(marker in output,'OFFLINE_PROBE_MARKER_REQUIRED')
        finally:m.run(['docker','stop','--time','20',self.offline_name],'OFFLINE_STOP_FAILED',45)
        copy_module=type('M',(),{'BUSINESS':data/'crm_prod.db','sql_snapshot':staticmethod(m.sql_snapshot)})
        need(self.pf.row_evidence(copy_module)==before_rows and m.schema_signature(data/'crm_prod.db',REVISION)==self.proof['schema_sha256'] and self.pf.db_metadata(data/'crm_prod.db')==offline_metadata,'OFFLINE_STARTUP_CHANGED_DATABASE')
        root,static=m.stage_public(a.release,v);next_sha=H(m.next_nginx(m.NGINX.read_bytes()));self.current()
        result={'stage':'MEDIA_OPS_REVIEW_REFRESH_RETRY_PREPARED_OFFLINE_VERIFIED','source_sha':SOURCE_SHA,'frontend_version':FRONTEND,'schema_revision':REVISION,'schema_sha256':self.proof['schema_sha256'],'old_crm':m.runtime(old),'candidate_image':image,'preflight_sha256':a.preflight_sha256,'manifest_sha256':a.manifest_sha256,'payload_sha256':a.payload_sha256,'original_container_sha256':original_sha,'original_inventory_sha256':before_sha,'candidate_inventory_sha256':after_sha,'public_root':str(root),'public_inventory_sha256':static,'nginx_next_sha256':next_sha,'offline_rows_unchanged':True,'offline_schema_metadata_unchanged':True,'actual_python310_verified':True,'offline_network_none':True,'offline_credentials_absent':True,'offline_workers_off':True,'authoritative_route_registered':True,'database_migrated':False,'provider_requests':False,'original_table_count':129,'sequence_monotonic_progress_preserved':True,'sequence_written_by_tool':False,'offline_own_sequence_exact_before_after':True,'host_docker_timestamp_parser_verified':True}
        sha=m.write(a.release/'prepared.json',result);return {**result,'receipt_sha256':sha}

    def reviewed(self):
        m,a=self.m,self.args;need(re.fullmatch('[a-f0-9]{64}',a.review_sha256 or ''),'PREPARED_INDEPENDENT_REVIEW_REQUIRED')
        r=json.loads(m.read(a.release/'prepared.json',a.review_sha256))
        need(r['stage']=='MEDIA_OPS_REVIEW_REFRESH_RETRY_PREPARED_OFFLINE_VERIFIED' and r['source_sha']==SOURCE_SHA and r['frontend_version']==FRONTEND and r['schema_revision']==REVISION and r['schema_sha256']==self.proof['schema_sha256'] and r['original_table_count']==129,'EXACT_PREPARED_SCOPE_REQUIRED')
        need(r['manifest_sha256']==a.manifest_sha256 and r['payload_sha256']==a.payload_sha256 and r['preflight_sha256']==a.preflight_sha256,'PREPARED_IDENTITIES_DRIFT')
        need(all(r[k] is True for k in ('offline_rows_unchanged','offline_schema_metadata_unchanged','actual_python310_verified','offline_network_none','offline_credentials_absent','offline_workers_off','authoritative_route_registered','sequence_monotonic_progress_preserved','offline_own_sequence_exact_before_after','host_docker_timestamp_parser_verified')) and r['database_migrated'] is False and r['provider_requests'] is False and r['sequence_written_by_tool'] is False,'EXACT_OFFLINE_PROOF_REQUIRED')
        old=json.loads(m.read(a.release/'original-container.json',r['original_container_sha256']));before=json.loads(m.read(a.release/'backend-original-inventory.json',r['original_inventory_sha256']));expected=json.loads(m.read(a.release/'backend-candidate-inventory.json',r['candidate_inventory_sha256']))
        need(m.runtime(old)==r['old_crm']==self.proof['crm'] and digest(before)==self.proof['backend_inventory_sha256'] and expected=={**before,**self.manifest['backend_after']},'PREPARED_ORIGINAL_SOURCE_DRIFT')
        need(m.image_id(r['candidate_image'])==r['candidate_image'] and m.verify_public(self.public,self.manifest)==r['public_inventory_sha256'],'PREPARED_IMAGE_OR_STATIC_DRIFT')
        return r,old,before,expected

    def state(self,receipt,old):
        state=json.loads(self.m.read(self.args.release/'candidate-created.json'))
        need(state=={'source_sha':SOURCE_SHA,'candidate_id':state['candidate_id'],'candidate_image':receipt['candidate_image'],'original_id':old['Id'],'review_sha256':self.args.review_sha256} and re.fullmatch('[a-f0-9]{64}',state['candidate_id']) and state['candidate_id']!=old['Id'],'EXACT_DURABLE_CANDIDATE_ID_REQUIRED');return state

    def identities(self,state,old):
        m=self.m;retained=m.inspect(old['Id']);candidate=m.inspect(state['candidate_id'])
        need(retained['Id']==old['Id'] and retained['Image']==old['Image'] and m.runtime(retained)['config']==m.runtime(old)['config'],'RETAINED_ORIGINAL_DRIFT')
        need(candidate['Id']==state['candidate_id'] and candidate['Image']==state['candidate_image'] and candidate['Name'] in {'/t24-crm','/'+self.candidate_name},'OWNED_CANDIDATE_ID_IMAGE_ROLE_REQUIRED')
        need(retained['Name'] in {'/t24-crm','/'+self.old_name},'ORIGINAL_ROLE_DRIFT')
        active=m.inspect_optional('t24-crm');need(not active or active['Id'] in {old['Id'],candidate['Id']},'UNKNOWN_PRIMARY_CONTAINER')
        for name,key in ((self.old_name,old['Id']),(self.candidate_name,candidate['Id'])):
            found=m.inspect_optional(name);need(not found or found['Id']==key,'UNKNOWN_RESERVED_CONTAINER')
        return retained,candidate

    def fresh(self,receipt,old,before,expected,state,*,live=False,updated=False,rows=True):
        self.protections(updated=updated);retained,candidate=self.identities(state,old)
        need(self.m.runtime(retained)==self.m.runtime(old),'ORIGINAL_RESTART_PROVENANCE_DRIFT')
        need(type(candidate['RestartCount']) is int and candidate['RestartCount']==0,'CANDIDATE_RESTARTED')
        compare(candidate,old,self.m)
        self.base.verify_gbp_environment_enabled(candidate);self.m.verify_secret_mount(candidate);self.m.verify_production_worker_enabled(candidate)
        self.source_boundary(retained,before);self.source_boundary(candidate,expected)
        if live:
            need(candidate['State']['Running'] is True and retained['State']['Running'] is False and self.m.inspect('t24-crm')['Id']==candidate['Id'],'EXACT_LIVE_CANDIDATE_REQUIRED')
            self.pf.validation_window(candidate)
        if rows:need(self.rows()==self.proof['rows'],'PRODUCTION_ROWS_CHANGED')
        return retained,candidate

    def public_check(self,version):
        # Only two fixed no-query loopback paths, with no curl config/proxy/auth.
        prefix=['curl','-q','--silent','--show-error','--fail','--noproxy','*','--resolve','t24-crm.com:443:127.0.0.1','--max-time','3']
        for attempt in range(5):
            try:
                value=json.loads(self.m.run([*prefix,'https://t24-crm.com/app-version.json'],'PUBLIC_LOOPBACK_VERSION_FAILED',5))
                need(value.get('version')==version,'PUBLIC_LOOPBACK_FRONTEND_DRIFT')
                self.m.run([*prefix,'https://t24-crm.com/ready'],'PUBLIC_LOOPBACK_READY_FAILED',5);return
            except Exception:
                if attempt==4:raise RuntimeError('PUBLIC_LOOPBACK_ACCEPTANCE_FAILED')
                time.sleep(0.2)

    def record(self,name,value):
        sha=self.m.write(self.args.release/name,value);fd=os.open(self.args.release,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:os.fsync(fd)
        finally:os.close(fd)
        return sha

    def activate(self):
        m,a=self.m,self.args;r,old,before,expected=self.reviewed();self.current()
        need(not (a.release/'activation-started.json').exists() and not m.inspect_optional(self.old_name) and not m.inspect_optional(self.candidate_name),'FRESH_SWITCH_REQUIRED')
        self.record('activation-started.json',{'source_sha':SOURCE_SHA,'review_sha256':a.review_sha256,'original_id':old['Id'],'candidate_image':r['candidate_image']})
        config=m.clone_config(r['candidate_image'],old)
        status,body=m.retained().docker_request('POST','/containers/create?name='+self.candidate_name,config);need(status==201,'CANDIDATE_CREATE_FAILED')
        identity=json.loads(body)['Id'];need(re.fullmatch('[a-f0-9]{64}',identity),'EXACT_CREATED_ID_REQUIRED')
        self.record('candidate-created.json',{'source_sha':SOURCE_SHA,'candidate_id':identity,'candidate_image':r['candidate_image'],'original_id':old['Id'],'review_sha256':a.review_sha256});state=self.state(r,old)
        try:
            retained,candidate=self.fresh(r,old,before,expected,state)
            need(candidate['State']['Status']=='created' and candidate['State']['Running'] is False and type(candidate['RestartCount']) is int and candidate['RestartCount']==0,'NEVER_STARTED_CANDIDATE_REQUIRED')
            m.run(['docker','stop','--time','30',old['Id']],'ORIGINAL_STOP_FAILED',60)
            retained,candidate=self.fresh(r,old,before,expected,state);need(retained['State']['Running'] is False and candidate['State']['Running'] is False,'BOTH_CONTAINERS_STOPPED_REQUIRED')
            m.run(['docker','rename',old['Id'],self.old_name],'ORIGINAL_RENAME_FAILED');m.run(['docker','rename',identity,'t24-crm'],'CANDIDATE_RENAME_FAILED')
            self.fresh(r,old,before,expected,state);m.run(['docker','start',identity],'CANDIDATE_START_FAILED');m.ready(identity)
            self.fresh(r,old,before,expected,state,live=True)
            output=m.run(['docker','exec',identity,'python','-B','-c',self.base.active_configuration_probe()],'ACTIVE_GOOGLE_PRESERVATION_FAILED');need(b'EXACT_GBP_PRESERVED_SCHEDULER_OFF_NO_NETWORK' in output,'EXACT_ACTIVE_CONFIG_REQUIRED')
            original_nginx=m.NGINX.read_bytes();updated=m.next_nginx(original_nginx);need(H(updated)==r['nginx_next_sha256'],'REVIEWED_NGINX_ROOT_REQUIRED')
            self.nginx();m.replace_nginx(original_nginx,updated);m.retained().reload_nginx()
            _,candidate=self.fresh(r,old,before,expected,state,live=True,updated=True)
            need(m.verify_public(self.public,self.manifest)==r['public_inventory_sha256'],'FINAL_PUBLIC_DRIFT')
            self.public_check(FRONTEND)
            _,candidate=self.fresh(r,old,before,expected,state,live=True,updated=True)
            result={'stage':'MEDIA_OPS_REVIEW_REFRESH_RETRY_DEPLOYED_VERIFIED','deployed':True,'source_sha':SOURCE_SHA,'frontend_version':FRONTEND,'schema_revision':REVISION,'schema_sha256':self.proof['schema_sha256'],'crm':m.runtime(candidate),'original_id':old['Id'],'candidate_inventory_sha256':r['candidate_inventory_sha256'],'public_root':str(self.public),'public_inventory_sha256':r['public_inventory_sha256'],'nginx_sha256':H(m.NGINX.read_bytes()),'preflight_sha256':a.preflight_sha256,'prepared_sha256':a.review_sha256,'all_129_table_rows_unchanged':True,'database_migrated':False,'database_restored':False,'original_env_mounts_network_unchanged':True,'existing_google_environment_preserved':True,'scheduler_disabled':True,'private_runtime_unchanged':True,'nginx_only_public_root_changed':True,'provider_requests_by_deployment':False,'public_loopback_ready_and_version_verified':True,'sequence_monotonic_progress_preserved':True,'sequence_written_by_tool':False}
            sha=m.write(a.release/'deployed.json',result);return {**result,'receipt_sha256':sha}
        except BaseException:
            self.recover_internal(r,old,before,expected);raise

    def recover_internal(self,r,old,before,expected):
        m,a=self.m,self.args;state=self.state(r,old);candidate=m.inspect(state['candidate_id'])
        need(candidate['Id']==state['candidate_id'] and candidate['Image']==r['candidate_image'] and candidate['Name'] in {'/t24-crm','/'+self.candidate_name},'OWNED_RECOVERY_CANDIDATE_REQUIRED')
        if candidate['State']['Running']:m.run(['docker','stop','--time','30',candidate['Id']],'RECOVERY_CONTAINMENT_FAILED',60)
        need(m.inspect(candidate['Id'])['State']['Running'] is False,'RECOVERY_EXECUTOR_STOPPED_REQUIRED')
        # Protect fresh metadata/schema/old source before starting retained code.
        # Rows may have evolved independently; recovery never restores old data.
        body=m.NGINX.read_bytes();updated=H(body)==r['nginx_next_sha256'];self.protections(updated=updated,recovery=True)
        retained,candidate=self.identities(state,old);self.source_boundary(retained,before);m.verify_secret_mount(retained)
        if updated:
            previous=body.replace(os.fsencode(str(self.public)),os.fsencode(self.proof['public_root']),1)
            need(H(previous)==self.proof['nginx_sha256'],'EXACT_ORIGINAL_NGINX_REQUIRED');m.replace_nginx(body,previous)
        # Repeat reload even when a prior reload failed after restoring bytes.
        m.retained().reload_nginx()
        if candidate['Name']=='/t24-crm':m.run(['docker','rename',candidate['Id'],self.candidate_name],'RETAIN_FAILED_CANDIDATE_FAILED')
        retained=m.inspect(old['Id'])
        if retained['Name']!='/t24-crm':m.run(['docker','rename',retained['Id'],'t24-crm'],'RESTORE_ORIGINAL_NAME_FAILED')
        if not retained['State']['Running']:m.run(['docker','start',retained['Id']],'RESTORE_ORIGINAL_START_FAILED')
        m.ready(old['Id']);retained=m.inspect('t24-crm');need(retained['Id']==old['Id'] and retained['State']['Running'] is True and m.runtime(retained)['config']==m.runtime(old)['config'],'ORIGINAL_NOT_RESTORED')
        self.source_boundary(retained,before);self.protections(recovery=True);self.base.verify_gbp_environment_enabled(retained);self.public_check(BASE_FRONTEND)
        kept=m.inspect(state['candidate_id']);need(kept['State']['Running'] is False and kept['Name']=='/'+self.candidate_name,'FAILED_CANDIDATE_NOT_CONTAINED')
        result={'stage':'MEDIA_OPS_REVIEW_REFRESH_RETRY_ORIGINAL_RESTORED','source_sha':BASE_SOURCE,'frontend_version':BASE_FRONTEND,'schema_revision':REVISION,'crm':m.runtime(retained),'candidate_retained_stopped':True,'database_migrated':False,'database_restored':False,'business_rows_written_by_tool':False,'scheduler_disabled':True,'private_runtime_unchanged':True,'provider_requests_by_tool':False}
        path=a.release/'recovered.json'
        if path.exists() and json.loads(m.read(path))!=result:path=a.release/('recovered-'+digest(result)[:12]+'.json')
        if path.exists():need(json.loads(m.read(path))==result,'RECOVERY_RESULT_RECEIPT_DRIFT')
        else:m.write(path,result)
        return {**result,'receipt_sha256':H(m.read(path)),'receipt_file':path.name}

    def recover(self):
        r,old,before,expected=self.reviewed();need(not (self.args.release/'deployed.json').exists(),'SUCCESSFUL_RELEASE_REQUIRES_SEPARATE_RECOVERY_REVIEW')
        started=json.loads(self.m.read(self.args.release/'activation-started.json'));need(started=={'source_sha':SOURCE_SHA,'review_sha256':self.args.review_sha256,'original_id':old['Id'],'candidate_image':r['candidate_image']},'RECOVERY_SWITCH_IDENTITY_DRIFT')
        if not (self.args.release/'candidate-created.json').exists():
            # A create/ID-save interruption happens before we stop or rename the
            # original. Never infer ownership or delete a container by its name.
            self.protections(recovery=True);active=self.m.inspect('t24-crm')
            need(active['Id']==old['Id'] and active['State']['Running'] is True and self.m.runtime(active)==self.proof['crm'],'UNRECORDED_CANDIDATE_REQUIRES_MANUAL_RECOVERY')
            self.source_boundary(active,before);self.base.verify_gbp_environment_enabled(active)
            return {'stage':'MEDIA_OPS_REVIEW_REFRESH_RETRY_ABORTED_BEFORE_SWITCH','original_running_unchanged':True,'candidate_identity_not_recorded':True,'candidate_not_touched':True,'manual_orphan_review_required':True,'database_restored':False,'provider_requests_by_tool':False}
        return self.recover_internal(r,old,before,expected)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--phase',choices=['prepare','activate','recover'],required=True);parser.add_argument('--release',type=Path,required=True);parser.add_argument('--manifest-sha256',required=True);parser.add_argument('--payload-sha256',required=True);parser.add_argument('--preflight',type=Path,required=True);parser.add_argument('--preflight-sha256',required=True);parser.add_argument('--review-sha256');args=parser.parse_args()
    need(os.geteuid()==0 and socket.gethostname()==HOST,'EXACT_ROOT_SERVER_REQUIRED');resource.setrlimit(resource.RLIMIT_CORE,(0,0));os.umask(0o077);sys.dont_write_bytecode=True
    need(args.release.resolve()==args.release and args.release.parent==Path('/opt/t24-crm/releases'),'EXACT_RELEASE_PARENT_REQUIRED')
    row=args.release.lstat();need(stat.S_ISDIR(row.st_mode) and row.st_uid==0 and stat.S_IMODE(row.st_mode)==0o700,'PROTECTED_RELEASE_REQUIRED')
    need(all(re.fullmatch('[a-f0-9]{64}',s) for s in (args.manifest_sha256,args.payload_sha256,args.preflight_sha256)),'EXACT_PUBLIC_PINS_REQUIRED')
    lock=os.open('/opt/t24-crm/releases/.media-ops-review-refresh-release.lock',os.O_RDWR|os.O_NONBLOCK|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        row=os.fstat(lock);need(stat.S_ISREG(row.st_mode) and row.st_uid==0 and row.st_nlink==1 and stat.S_IMODE(row.st_mode)==0o600,'PROTECTED_LOCK_REQUIRED');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        result=getattr(Release(args),args.phase)();print(json.dumps(result,sort_keys=True))
    finally:os.close(lock)


if __name__=='__main__':
    try:main()
    except BaseException as error:
        code=str(error) if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',str(error)) else 'REVIEW_REFRESH_REJECTED'
        print(json.dumps({'stage':'MEDIA_OPS_REVIEW_REFRESH_RETRY_RELEASE_REJECTED','code':code,'database_restored':False}));sys.exit(1)
