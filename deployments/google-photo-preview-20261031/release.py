"""Static-only private PNG preview repair; keep CRM runtime, API, data and CSP exact."""
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
import sys
import time
import types

H = lambda body: hashlib.sha256(body).hexdigest()
HOST = 'iZj6c4cj7edgnhdimts4l7Z'
SOURCE_SHA = '04a42942ce128f74c77db9250f2e7a28485b5c32'
FRONTEND = 'f3e9e6f7bfa0'
APPLICATION_FREEZE_SHA = '8928e4e59b3a65ac48731e39019fcf6f36bd33a912d1bf771fd0315616c6b2a5'
PREFLIGHT_SHA = 'a37a2a742ab97fac3194fb902b0e687bd847d2166ec82b09608947d437eccfbb'
BASE_SOURCE = '5931e430e629fb633f846ebc068a8fc12d4b9a0a'
BASE_FRONTEND = '8cc54170ca26'
BASE_DEPLOYED_SHA = 'c05397479169846fd2c5c62eccffb3880d4cb6d2b90c60e929ce9b9370340d4a'
REVISION = 'acd7c9d0e136'
SCOPE = 'google-photo-preview'
ACTIVATION_FROM = '2026-10-30T19:42:04Z'
BACKEND_FILES = frozenset()
FRONTEND_FILES = frozenset({'app/frontend/src/lib/media-publication-images.ts', 'app/frontend/src/components/MediaPublicationImage.tsx'})
TEST_FILES = frozenset({'app/frontend/tests/media-publication-images.test.mjs'})
SOURCE_FILES = FRONTEND_FILES | TEST_FILES


def need(ok, code):
    if not ok: raise RuntimeError(code)


def digest(value): return H(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())
def encoded(value): return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def pins_ready():
    need(all(isinstance(v, str) and re.fullmatch(pattern, v) and set(v) != {'0'} for v, pattern in ((SOURCE_SHA, '[a-f0-9]{40}'), (FRONTEND, '[a-f0-9]{12}'), (APPLICATION_FREEZE_SHA, '[a-f0-9]{64}'))), 'ACTUAL_REVIEWED_SOURCE_FRONTEND_AND_FREEZE_REQUIRED')


def local_bytes(path, maximum=16 * 1024 ** 2):
    path = Path(path); row = path.lstat(); need(path.resolve() == path.absolute() and stat.S_ISREG(row.st_mode) and row.st_nlink == 1, 'REGULAR_CANONICAL_LOCAL_INPUT_REQUIRED')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream: opened = os.fstat(stream.fileno()); body = stream.read(maximum + 1)
    after = path.lstat(); fields = lambda v: (v.st_dev, v.st_ino, v.st_size, v.st_mtime_ns, v.st_ctime_ns, v.st_nlink)
    need(fields(row) == fields(opened) == fields(after) and len(body) <= maximum, 'LOCAL_INPUT_READ_DRIFT'); return body


def protected_read(path, sha):
    row = path.lstat(); need(row.st_uid == 0 and stat.S_IMODE(row.st_mode) == 0o600, 'PROTECTED_TOOL_REQUIRED'); body = local_bytes(path, 1048576); need(H(body) == sha, 'EXACT_REVIEWED_TOOL_BYTES_REQUIRED'); return body


def validate_summary(p):
    need(p['stage'] == 'GOOGLE_PHOTO_PREVIEW_PREFLIGHT_CAPTURED' and p['source_sha'] == BASE_SOURCE and p['frontend_version'] == BASE_FRONTEND and p['schema_revision'] == REVISION and p['table_count'] == 136 and p['deployed_sha256'] == BASE_DEPLOYED_SHA, 'EXACT_ACTUAL_STATIC_PREFLIGHT_REQUIRED')
    need(p['scheduler_enabled'] is True and p['scheduler_activation_from'] == ACTIVATION_FROM and all(p[k] is True for k in ('gbp_feature_enabled', 'callback_logging_protection_retained', 'image_delivery_logging_protection_retained', 'existing_image_policies_and_data_preserved', 'private_boundary_verified', 'host_docker_timestamp_parser_verified')), 'EXACT_EXISTING_RUNTIME_BOUNDARIES_REQUIRED')
    need(all(p[k] is False for k in ('credential_content_read', 'private_content_read', 'executed_business_writes')) and re.fullmatch('[a-f0-9]{64}', p['content_security_policy_sha256']), 'READONLY_CSP_SUMMARY_REQUIRED')
    sha=p['sha256']; need(re.fullmatch('[a-f0-9]{64}',sha) and p['path']=='/opt/t24-crm/releases/google-photo-preview-preflight-'+sha[:12]+'.json','EXACT_SERVER_PROOF_PATH_REQUIRED')


def next_nginx(original, old, new):
    old, new = os.fsencode(str(old)), os.fsencode(str(new)); need(original.count(old)==1 and new not in original, 'EXACT_SINGLE_OLD_PUBLIC_ROOT_REQUIRED')
    updated=original.replace(old,new,1); need(updated.replace(new,old,1)==original,'NONROOT_NGINX_CHANGE_REJECTED'); return updated


class Release:
    def __init__(self,args):
        pins_ready();self.args=args;module=types.ModuleType('_google_photo_preview_preflight');module.__file__=str(args.release/'preflight.py')
        exec(compile(protected_read(Path(module.__file__),PREFLIGHT_SHA),module.__file__,'exec'),module.__dict__);self.pf=module
        self.helper,self.m,self.base,self.safe,self.w,_=module.dependencies();m=self.m
        self.manifest=json.loads(m.read(args.release/'manifest.json',args.manifest_sha256));m.read(args.release/'payload.tar.gz',args.payload_sha256)
        self.proof=json.loads(m.read(args.preflight,args.preflight_sha256));self.validate();self.pins=json.loads(m.read(self.base.PRIVATE_PINS,self.base.PRIVATE_PINS_SHA))
        self.public=Path('/var/www/t24-crm-public/'+SCOPE+'-'+SOURCE_SHA[:12]+'-20261031');need(args.release==Path('/opt/t24-crm/releases/'+SCOPE+'-'+SOURCE_SHA[:12]+'-20261031'),'EXACT_RELEASE_PATH_REQUIRED')
        m.SOURCE,m.SCOPE,m.BACKEND=SOURCE_SHA,SCOPE,set();m.BASELINE_FRONTEND,m.FRONTEND_VERSION=BASE_FRONTEND,FRONTEND
        m.PUBLIC,m.NGINX_SHA,m.STATIC_SHA=Path(self.proof['public_root']),self.proof['nginx_sha256'],self.proof['public_inventory_sha256'];m.public_root=lambda:self.public

    def validate(self):
        p,v,a=self.proof,self.manifest,self.args
        need(p['stage']=='GOOGLE_PHOTO_PREVIEW_READONLY_PREFLIGHT' and p['host']==HOST and p['source_sha']==BASE_SOURCE and p['frontend_version']==BASE_FRONTEND and p['schema_revision']==REVISION and p['deployed_sha256']==BASE_DEPLOYED_SHA,'EXACT_CURRENT_DEPLOYED_BASELINE_REQUIRED')
        need(p['crm']['id']==self.pf.ORIGINAL_ID and p['crm']['image']==self.pf.IMAGE and p['scheduler_enabled'] is True and p['scheduler_activation_from']==ACTIVATION_FROM and len(p['rows'])==136 and all(p[k] is True for k in ('callback_logging_protection_retained','image_delivery_logging_protection_retained','existing_image_policies_and_data_preserved','host_docker_timestamp_parser_verified')),'EXACT_RUNTIME_AND_136_TABLE_BASELINE_REQUIRED')
        need(all(p[k] is False for k in ('provider_requests','business_writes','private_content_read','credential_content_read','container_or_configuration_changed')),'READONLY_PREFLIGHT_REQUIRED')
        need(v['source_sha']==SOURCE_SHA and v['frontend_version']==FRONTEND and v['baseline_source_sha']==BASE_SOURCE and v['baseline_frontend_version']==BASE_FRONTEND and v['schema_revision']==REVISION and v['static_only'] is True and v['existing_image_policies_and_data_preserved'] is True and all(v[k] is False for k in ('backend_changes','database_migration','production_seed_rows','credentials_included','runtime_environment_changed','csp_changed')),'EXACT_STATIC_ONLY_SOURCE_SCOPE_REQUIRED')
        need(set(v['changed_source_files'])==SOURCE_FILES and len(v['changed_source_files'])==3 and v['application_freeze_sha256']==APPLICATION_FREEZE_SHA and v['preflight_sha256']==a.preflight_sha256 and v['payload_sha256']==a.payload_sha256,'EXACT_STATIC_PAYLOAD_FREEZE_REQUIRED')
        need({'static/index.html','static/app-version.json'}<=set(v['files']) and all(name.startswith('static/') and self.m.static_path(name[7:]) and re.fullmatch('[a-f0-9]{64}',sha) for name,sha in v['files'].items()),'STATIC_MEMBERS_ONLY_REQUIRED')

    def record(self,name,value):return self.w.Release.record(self,name,value)
    def rows(self):return self.w.snapshot(self.m,self.m.BUSINESS)

    def nginx(self,updated=False):
        body=self.m.NGINX.read_bytes();active=self.m.run(['nginx','-T'],'ACTIVE_NGINX_PARSE_FAILED');old,new=os.fsencode(self.proof['public_root']),os.fsencode(str(self.public))
        if updated:
            need(body.count(new)==active.count(new)==1,'EXACT_NEW_PUBLIC_ROOT_REQUIRED');body,active=body.replace(new,old,1),active.replace(new,old,1)
        need(H(body)==self.proof['nginx_sha256'] and H(active)==self.proof['active_nginx_config_sha256'],'CALLBACK_CSP_DELIVERY_OR_NONROOT_NGINX_DRIFT')

    def boundary(self,*,updated=False,recovery=False):
        m,p=self.m,self.proof;need(self.safe.safe_private_boundary(m,self.pins)==p['private_boundary'],'PRIVATE_RUNTIME_METADATA_DRIFT')
        need(m.credential_boundary()==p['credential_boundary'] and self.safe.protected_metadata(self.safe.GBP_ENV)==p['google_credential_metadata'],'CREDENTIAL_METADATA_DRIFT')
        row=m.BUSINESS.stat();need([row.st_dev,row.st_ino]==p['database_identity'],'DATABASE_INODE_DRIFT')
        self.w.sequence_boundary(p['database_metadata'],self.helper.db_metadata(m.BUSINESS),recovery=recovery)
        need(m.schema_signature(m.BUSINESS,REVISION)==p['schema_sha256'],'EXACT_UNCHANGED_136_TABLE_SCHEMA_REQUIRED')
        if not recovery:need(self.w.evidence(self.rows())==p['rows'],'ALL_136_BUSINESS_ROW_FINGERPRINTS_MUST_REMAIN_EXACT')
        need(digest(m.tree(m.PUBLIC))==p['public_inventory_sha256'],'ORIGINAL_STATIC_DRIFT');self.nginx(updated)
        current=m.inspect('t24-crm');need(current['State']['Running'] is True and m.runtime(current)==p['crm'],'CRM_RUNTIME_MUST_NOT_CHANGE_OR_RESTART')
        self.pf.google_environment(current);m.verify_secret_mount(current);m.verify_production_worker_enabled(current);m.retained().require_safe_original_restart(current)
        inventory=m.inventory(current['Id']);need(digest(inventory)==p['backend_inventory_sha256'] and len(inventory)==p['backend_file_count'] and digest(sorted(current['Config']['Env']))==p['environment_sha256'],'API_SOURCE_OR_ENVIRONMENT_MUST_REMAIN_EXACT')
        need(self.pf.security_headers(m)['content_security_policy_sha256']==p['content_security_policy_sha256'],'EXISTING_CSP_HEADER_MUST_REMAIN_EXACT');m.ready(current['Id']);return current

    def replace_nginx(self,before,after):
        self.m.replace_nginx(before,after);fd=os.open(self.m.NGINX.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:os.fsync(fd)
        finally:os.close(fd)

    def prepare(self):
        m,a=self.m,self.args;self.helper.docker_timestamp_probe();self.boundary()
        need({p.name for p in a.release.iterdir()}=={'release.py','preflight.py','manifest.json','payload.tar.gz'},'FRESH_STATIC_STAGING_REQUIRED')
        m.extract(a.release,self.manifest);root,static=m.stage_public(a.release,self.manifest);body=m.NGINX.read_bytes();next_sha=H(next_nginx(body,self.proof['public_root'],root));self.boundary()
        result={'stage':'GOOGLE_PHOTO_PREVIEW_PREPARED_STATIC_VERIFIED','source_sha':SOURCE_SHA,'frontend_version':FRONTEND,'schema_revision':REVISION,'table_count':136,'crm':self.proof['crm'],'preflight_sha256':a.preflight_sha256,'manifest_sha256':a.manifest_sha256,'payload_sha256':a.payload_sha256,'public_root':str(root),'public_inventory_sha256':static,'nginx_next_sha256':next_sha,'schema_sha256':self.proof['schema_sha256'],'content_security_policy_sha256':self.proof['content_security_policy_sha256'],'static_only':True,'all_136_rows_and_schema_unchanged':True,'existing_image_policies_and_data_preserved':True,'runtime_and_backend_unchanged':True,'callback_and_image_privacy_configuration_preserved':True,'database_migration':False,'container_changed_or_restarted':False,'csp_changed':False,'provider_requests':False,'business_writes':False}
        sha=self.record('prepared.json',result);return {**result,'receipt_sha256':sha}

    def reviewed(self):
        a,m=self.args,self.m;need(re.fullmatch('[a-f0-9]{64}',a.review_sha256 or ''),'PREPARED_INDEPENDENT_REVIEW_REQUIRED');r=json.loads(m.read(a.release/'prepared.json',a.review_sha256))
        need(r['stage']=='GOOGLE_PHOTO_PREVIEW_PREPARED_STATIC_VERIFIED' and r['source_sha']==SOURCE_SHA and r['frontend_version']==FRONTEND and r['schema_revision']==REVISION and r['table_count']==136 and r['crm']==self.proof['crm'] and r['schema_sha256']==self.proof['schema_sha256'] and r['content_security_policy_sha256']==self.proof['content_security_policy_sha256'],'EXACT_PREPARED_STATIC_SCOPE_REQUIRED')
        need(r['manifest_sha256']==a.manifest_sha256 and r['payload_sha256']==a.payload_sha256 and r['preflight_sha256']==a.preflight_sha256 and r['public_root']==str(self.public),'EXACT_PREPARED_IDENTITIES_REQUIRED')
        need(all(r[k] is True for k in ('static_only','all_136_rows_and_schema_unchanged','existing_image_policies_and_data_preserved','runtime_and_backend_unchanged','callback_and_image_privacy_configuration_preserved')) and all(r[k] is False for k in ('database_migration','container_changed_or_restarted','csp_changed','provider_requests','business_writes')),'EXACT_STATIC_PREPARATION_REQUIRED')
        need(m.verify_public(self.public,self.manifest)==r['public_inventory_sha256'],'PREPARED_PUBLIC_BYTES_DRIFT');return r

    def public_check(self):
        prefix=['curl','-q','--silent','--show-error','--fail','--noproxy','*','--resolve','t24-crm.com:443:127.0.0.1','--max-time','3']
        need(json.loads(self.m.run([*prefix,'https://t24-crm.com/app-version.json'],'PUBLIC_VERSION_FAILED',5)).get('version')==FRONTEND,'PUBLIC_VERSION_DRIFT')
        need(json.loads(self.m.run([*prefix,'https://t24-crm.com/ready'],'PUBLIC_READY_FAILED',5)).get('status')=='ready','PUBLIC_READY_DRIFT')

    def activate(self):
        m,a=self.m,self.args;r=self.reviewed();self.boundary();need(not (a.release/'activation-started.json').exists(),'FRESH_STATIC_SWITCH_REQUIRED')
        original=m.NGINX.read_bytes();updated=next_nginx(original,self.proof['public_root'],self.public);need(H(updated)==r['nginx_next_sha256'],'REVIEWED_NGINX_ROOT_REQUIRED')
        self.record('nginx-before.conf',original);self.record('activation-started.json',{'source_sha':SOURCE_SHA,'review_sha256':a.review_sha256,'nginx_next_sha256':r['nginx_next_sha256']})
        try:
            self.replace_nginx(original,updated);m.retained().reload_nginx();self.boundary(updated=True);self.public_check();self.boundary(updated=True)
            need(m.verify_public(self.public,self.manifest)==r['public_inventory_sha256'],'FINAL_STATIC_BYTES_DRIFT')
            result={'stage':'GOOGLE_PHOTO_PREVIEW_DEPLOYED_STATIC_VERIFIED','deployed':True,'source_sha':SOURCE_SHA,'frontend_version':FRONTEND,'backend_source_sha':BASE_SOURCE,'schema_revision':REVISION,'table_count':136,'schema_sha256':self.proof['schema_sha256'],'crm':self.proof['crm'],'preflight_sha256':a.preflight_sha256,'prepared_sha256':a.review_sha256,'public_root':str(self.public),'public_inventory_sha256':r['public_inventory_sha256'],'nginx_sha256':H(m.NGINX.read_bytes()),'content_security_policy_sha256':self.proof['content_security_policy_sha256'],'all_136_rows_and_schema_unchanged':True,'existing_image_policies_and_data_preserved':True,'runtime_and_backend_unchanged':True,'callback_and_image_privacy_configuration_preserved':True,'scheduler_enabled':True,'scheduler_activation_from':ACTIVATION_FROM,'static_only':True,'database_migration':False,'database_restored':False,'container_changed_or_restarted':False,'csp_changed':False,'provider_requests':False,'business_writes':False,'no_task_lease_schedule_or_public_post_created_by_tool':True}
            sha=self.record('deployed.json',result);return {**result,'receipt_sha256':sha}
        except BaseException:self.recover_internal(r);raise

    def recover_internal(self,r):
        m,a=self.m,self.args;body=m.NGINX.read_bytes();original=m.read(a.release/'nginx-before.conf',self.proof['nginx_sha256']);updated=next_nginx(original,self.proof['public_root'],self.public)
        need(H(updated)==r['nginx_next_sha256'] and body in (original,updated),'UNKNOWN_NGINX_STATE_REQUIRES_REVIEW');self.boundary(updated=body==updated,recovery=True)
        m.cleanup_nginx_temp(original,updated)
        if body==updated:self.replace_nginx(body,original)
        m.retained().reload_nginx();self.boundary(recovery=True)
        result={'stage':'GOOGLE_PHOTO_PREVIEW_ORIGINAL_STATIC_RESUMED','source_sha':BASE_SOURCE,'frontend_version':BASE_FRONTEND,'crm':self.proof['crm'],'independent_business_rows_preserved':True,'database_restored':False,'container_changed_or_restarted':False,'csp_changed':False,'provider_requests':False};self.record('recovery-'+str(time.time_ns())+'.json',result);return result

    def recover(self):
        r=self.reviewed();a=self.args;need(not (a.release/'deployed.json').exists(),'SUCCESSFUL_DEPLOYMENT_REQUIRES_SEPARATE_RECOVERY_REVIEW')
        started=json.loads(self.m.read(a.release/'activation-started.json'));need(started=={'source_sha':SOURCE_SHA,'review_sha256':a.review_sha256,'nginx_next_sha256':r['nginx_next_sha256']},'EXACT_RECOVERY_INTENT_REQUIRED');return self.recover_internal(r)


def main():
    p=argparse.ArgumentParser();p.add_argument('--phase',choices=['prepare','activate','recover'],required=True);p.add_argument('--release',type=Path,required=True);p.add_argument('--manifest-sha256',required=True);p.add_argument('--payload-sha256',required=True);p.add_argument('--preflight',type=Path,required=True);p.add_argument('--preflight-sha256',required=True);p.add_argument('--review-sha256');args=p.parse_args();pins_ready()
    need(os.geteuid()==0 and socket.gethostname()==HOST,'EXACT_ROOT_SERVER_REQUIRED');resource.setrlimit(resource.RLIMIT_CORE,(0,0));os.umask(0o077);sys.dont_write_bytecode=True
    need(args.release.resolve()==args.release and args.release.parent==Path('/opt/t24-crm/releases'),'EXACT_RELEASE_PARENT_REQUIRED')
    for parent in args.release.parents:
        row=parent.lstat();need(parent.resolve()==parent and stat.S_ISDIR(row.st_mode) and row.st_uid==0 and not row.st_mode&0o022,'PROTECTED_RELEASE_PARENT_REQUIRED')
    row=args.release.lstat();need(stat.S_ISDIR(row.st_mode) and row.st_uid==0 and stat.S_IMODE(row.st_mode)==0o700,'PROTECTED_RELEASE_REQUIRED')
    need(all(re.fullmatch('[a-f0-9]{64}',v) for v in (args.manifest_sha256,args.payload_sha256,args.preflight_sha256)) and args.preflight==Path('/opt/t24-crm/releases/google-photo-preview-preflight-'+args.preflight_sha256[:12]+'.json'),'EXACT_PUBLIC_PROOF_PINS_REQUIRED');need(args.phase!='prepare' or args.review_sha256 is None,'PREPARE_HAS_NO_SWITCH_REVIEW_ARGUMENT')
    lock=os.open('/opt/t24-crm/releases/.google-photo-preview-release.lock',os.O_RDWR|os.O_NONBLOCK|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        row=os.fstat(lock);need(stat.S_ISREG(row.st_mode) and row.st_uid==0 and row.st_nlink==1 and stat.S_IMODE(row.st_mode)==0o600,'PROTECTED_LOCK_REQUIRED');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);print(json.dumps(getattr(Release(args),args.phase)(),sort_keys=True))
    finally:os.close(lock)


if __name__=='__main__':
    try:main()
    except BaseException as error:
        value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',value) else 'STATIC_PREVIEW_RELEASE_REJECTED';print(json.dumps({'stage':'GOOGLE_PHOTO_PREVIEW_RELEASE_REJECTED','code':code,'database_restored':False}));sys.exit(1)
