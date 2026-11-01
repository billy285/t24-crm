"""Two stable read-only R3 samples before a static-only mobile refinement."""
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import socket
import sqlite3
import stat
from types import ModuleType,SimpleNamespace

HOST='iZj6c4cj7edgnhdimts4l7Z'
SOURCE='8b429dad8a2f144ea27527717d4811fb7ddc9b3c'
FRONTEND='b0e161d74fe5'
HEAD='g32ed456e792'
ROOT=Path('/opt/t24-crm/releases')
OLD=ROOT/'google-business-onboarding-r3-8b429dad8a2f-20261102'
HELPER='0ac3a706567118506831853d425983f119d469451aea32c31f07d6f23a4b69a8'
PREPARED='ef9ea86c6f12c59c18fc508aaa5028f476ba0187a74f19e06df23b06a188d4ff'
DEPLOYED='d114e977100f7269816579f5eab96a46fd4efde9b113936a263ca2c4c363ae00'
MANIFEST='3c714aba0a597b1c46d66d8979bf43ec6464d0d5ff9c219dd0e47dd0ba816ad0'
PAYLOAD='61cdb231e54302f44a13c59c42ee488f97e892c45bfbee50c2cfcced72db4bb1'
PREFLIGHT='2b1a9dde5020023ef33136b45bc54384745aeed30ab5f2c2e3312a59a8ebd485'
SCHEMA='c111f3fc3154eab704a25536280bf02dfd00d120867da7ed9727ec2c85ac4a7f'
CSP='ead64b09efe8c4f35648aa8eafe8855c5268ecf0999e0918b3642dd9dfbfe7a6'
NGINX='8b04ec3f5a775121e6a84471027a94c1bdf985133101564ca574bf44a2120471'
PUBLIC='/var/www/t24-crm-public/google-business-onboarding-r3-8b429dad8a2f-20261102'
RUNTIME={'id':'9b247014d54e57e5f671d3f8378c6b387c5301a87471b823e790b0d4965d072b','config':'eeed0663f81bffa9cc9926afde7d203ac84ced2725e0fba0fc7342c136531728','image':'sha256:ed057407d8866958a2966043ddc2457488d77cc00dd7bbabb608bcedc7c0bb09','restart':0,'started':'2026-11-01T19:00:56.90391494Z'}
H=lambda body:hashlib.sha256(body).hexdigest()
_CACHE=None

def need(ok,code):
    if not ok:raise RuntimeError(code)
def digest(value):return H(json.dumps(value,sort_keys=True,separators=(',',':')).encode())
def encoded(value):return (json.dumps(value,sort_keys=True,indent=2)+'\n').encode()
def identity(row):return (row.st_dev,row.st_ino,row.st_uid,row.st_mode,row.st_nlink,row.st_size,row.st_mtime_ns,row.st_ctime_ns)

def read(path,sha,maximum=16777216):
    need(path.resolve()==path and path.is_absolute(),'CANONICAL_ROOT_PRIVATE_PATH_REQUIRED')
    for parent in path.parents:
        row=parent.lstat();need(stat.S_ISDIR(row.st_mode) and row.st_uid==0 and not row.st_mode&0o022 and not parent.is_symlink(),'ROOT_PROTECTED_PARENT_REQUIRED')
    row=path.lstat();need(stat.S_ISREG(row.st_mode) and row.st_uid==0 and row.st_nlink==1 and stat.S_IMODE(row.st_mode)==0o600 and 0<row.st_size<=maximum,'ROOT600_FROZEN_FILE_REQUIRED')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as stream:opened=os.fstat(stream.fileno());body=stream.read(maximum+1);after=os.fstat(stream.fileno())
    need(identity(row)==identity(opened)==identity(after)==identity(path.lstat()) and len(body)==row.st_size and H(body)==sha,'EXACT_FROZEN_FILE_BYTES_REQUIRED');return body

def dependencies():
    global _CACHE
    need(os.geteuid()==0 and socket.gethostname()==HOST,'EXACT_ROOT_SERVER_REQUIRED')
    body=read(OLD/'release.py',HELPER,131072)
    if _CACHE is None:
        module=ModuleType('_mobile_onboarding_r3');module.__file__=str(OLD/'release.py');exec(compile(body,module.__file__,'exec'),module.__dict__)
        need(module.SOURCE_SHA==SOURCE and module.FRONTEND==FRONTEND and module.NEW_REVISION==HEAD and module.SCOPE=='google-business-onboarding-r3','EXACT_R3_SOURCE_REQUIRED')
        args=SimpleNamespace(release=OLD,manifest_sha256=MANIFEST,payload_sha256=PAYLOAD,preflight=ROOT/('google-business-onboarding-preflight-'+PREFLIGHT[:12]+'.json'),preflight_sha256=PREFLIGHT,review_sha256=PREPARED)
        ctx=module.Release(args);prepared=json.loads(read(OLD/'prepared.json',PREPARED));deployed=json.loads(read(OLD/'deployed.json',DEPLOYED))
        module.validate_prepared(prepared,MANIFEST,PAYLOAD,PREFLIGHT)
        need(deployed['stage']=='GOOGLE_ONBOARDING_DEPLOYED' and deployed['source_sha']==SOURCE and deployed['frontend_version']==FRONTEND and deployed['schema_revision']==HEAD and deployed['table_count']==162 and deployed['schema_sha256']==SCHEMA and deployed['crm']==RUNTIME and deployed['prepared_sha256']==PREPARED,'EXACT_ACTUAL_R3_DEPLOYMENT_REQUIRED')
        need(deployed['privacy']['content_security_policy_sha256']==CSP and all(deployed[x] is True for x in ('existing_full_environment_preserved','existing_ops_credentials_preserved','private_boundary_preserved','old_meta_google_cutoff_preserved','content_security_policy_unchanged')) and all(deployed[x] is False for x in ('provider_requests','database_restored','operations_execution_enabled','operations_scheduler_enabled','credentials_journaled','publications_or_ai_generation_executed')),'EXACT_EXISTING_PROTECTION_PROOF_REQUIRED')
        inventory=json.loads(read(OLD/'backend-candidate-inventory.json',prepared['candidate_inventory_sha256']))
        need(len(inventory)==419,'EXACT419_BACKEND_SOURCE_FILES_REQUIRED');_CACHE=(module,ctx,inventory)
    return _CACHE

def markers(path):
    con=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True,timeout=3)
    try:
        con.execute('PRAGMA query_only=ON');con.execute('BEGIN')
        counts={name:con.execute('SELECT count(*) FROM '+name).fetchone()[0] for name in ('customers','google_business_bindings','google_business_onboarding_catalogs','google_business_onboarding_requests','google_business_onboarding_batches','google_business_onboarding_items')}
        need(counts=={'customers':43,'google_business_bindings':15,'google_business_onboarding_catalogs':1,'google_business_onboarding_requests':1,'google_business_onboarding_batches':0,'google_business_onboarding_items':0},'EXACT_COMPLETED_DISCOVERY_BASELINE_REQUIRED')
        active=con.execute('SELECT count(*) FROM google_business_bindings WHERE active=1').fetchone()[0];need(active==15,'EXACT15_ACTIVE_BINDINGS_REQUIRED')
        scoped=con.execute("SELECT count(*) FROM google_business_onboarding_catalogs c JOIN google_business_onboarding_requests r ON r.resource_id=c.id AND r.owner_id=c.owner_id JOIN google_business_connections g ON g.id=c.connection_id AND g.owner_id=c.owner_id JOIN employees e ON e.id=c.owner_id WHERE c.status='ready' AND c.revision=3 AND c.lease_token IS NULL AND c.error_code IS NULL AND c.customer_id IS NULL AND r.kind='discovery' AND g.active=1 AND g.needs_reconnect=0 AND e.role='super_admin' AND e.status IN ('active','probation')").fetchone()[0]
        need(scoped==1,'EXACT_SINGLE_READY_OWNER_DISCOVERY_REQUIRED')
        return {**counts,'active_google_bindings':active,'single_owner_discovery_verified':True}
    finally:con.close()

def sample():
    module,ctx,inventory=dependencies();m=ctx.m;current=m.inspect('t24-crm')
    need(current['State']['Running'] is True and m.runtime(current)==RUNTIME,'EXACT_CURRENT_R3_RUNTIME_REQUIRED')
    env,ops=ctx.environment(current);ctx.ctx.workflow.pf.google_environment(current);m.verify_secret_mount(current);m.verify_production_worker_enabled(current);m.retained().require_safe_original_restart(current)
    ctx.protections(updated=True,recovery=True,head=HEAD,schema=SCHEMA)
    need(m.inventory(RUNTIME['id'])==inventory,'CURRENT419_BACKEND_SOURCE_DRIFT')
    need(H(m.NGINX.read_bytes())==NGINX and str(ctx.public)==PUBLIC,'EXACT_CURRENT_R3_NGINX_ROOT_REQUIRED')
    active_nginx=ctx.nginx(updated=True)
    rows=ctx.retained.evidence(ctx.rows());need(len(rows)==162,'EXACT162_ROW_EVIDENCE_REQUIRED')
    evidence=markers(m.BUSINESS)
    need(all(rows[name]['count']==value for name,value in evidence.items() if type(value)is int and name in rows),'CONSISTENT_DISCOVERY_AND_ROW_EVIDENCE_REQUIRED')
    return {'stage':'GOOGLE_ONBOARDING_MOBILE_READONLY_PREFLIGHT','source_sha':SOURCE,'frontend_version':FRONTEND,'schema_revision':HEAD,'deployed_receipt_sha256':DEPLOYED,'prepared_receipt_sha256':PREPARED,'crm':m.runtime(current),'environment_sha256':env,'ops_environment_sha256':ops,'schema_sha256':m.schema_signature(m.BUSINESS,HEAD),'rows':rows,'database_metadata':ctx.metadata(m.BUSINESS),'database_identity':ctx.proof['database_identity'],'business_markers':evidence,'backend_inventory':inventory,'backend_inventory_sha256':digest(inventory),'backend_file_count':419,'credential_boundary':ctx.proof['credential_boundary'],'credential_metadata':ctx.proof['credential_metadata'],'private_boundary':ctx.proof['private_boundary'],'public_root':PUBLIC,'public_inventory_sha256':m.verify_public(ctx.public,ctx.manifest),'nginx_sha256':NGINX,'active_nginx_sha256':active_nginx,'content_security_policy_sha256':CSP,'all162_current_tables_preserved':True,'google_scheduler_enabled':True,'google_scheduler_activation_from':'2026-10-30T19:42:04Z','ops_execution_enabled':False,'ops_scheduler_enabled':False,'existing_asset_worker_enabled':True,'onboarding_worker_default_enabled':True,'business_writes':False,'provider_requests':False,'credential_file_content_read':False,'private_content_read':False,'runtime_changed':False,'schema_changed':False,'permissions_changed':False}

def stable(first,second,retained):
    retained.live_sequence_boundary(first['database_metadata'],second['database_metadata'])
    need({**second,'database_metadata':first['database_metadata']}==first,'CURRENT162_BOUNDARIES_CHANGED_DURING_CAPTURE')

def capture():
    first=sample();second=sample();_,ctx,_=dependencies();stable(first,second,ctx.retained)
    body=encoded(second);sha=H(body);path=ROOT/('google-business-onboarding-mobile-preflight-'+sha[:12]+'.json')
    if path.exists():read(path,sha)
    else:
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(body);stream.flush();os.fsync(stream.fileno())
    keep=('source_sha','frontend_version','schema_revision','deployed_receipt_sha256','prepared_receipt_sha256','crm','environment_sha256','ops_environment_sha256','schema_sha256','database_identity','business_markers','backend_inventory_sha256','backend_file_count','public_root','public_inventory_sha256','nginx_sha256','active_nginx_sha256','content_security_policy_sha256','all162_current_tables_preserved','google_scheduler_enabled','google_scheduler_activation_from','ops_execution_enabled','ops_scheduler_enabled','existing_asset_worker_enabled','onboarding_worker_default_enabled')
    result={'stage':'GOOGLE_ONBOARDING_MOBILE_PREFLIGHT_CAPTURED','sha256':sha,'path':str(path),'bytes':len(body),'table_count':162,'rows_sha256':digest(second['rows']),**{key:second[key] for key in keep},'two_stable_samples_verified':True,'existing_monthly_rate_counter_forward_only':True,'schema_changed':False,'permissions_changed':False,'business_writes':False,'provider_requests':False,'credential_file_content_read':False,'private_content_read':False,'runtime_changed':False}
    need(len(json.dumps(result).encode())<10000,'BOUNDED_AGGREGATE_CAPTURE_REQUIRED');return result

def main():
    resource.setrlimit(resource.RLIMIT_CORE,(0,0));os.umask(0o077)
    need(os.geteuid()==0 and socket.gethostname()==HOST,'EXACT_ROOT_SERVER_REQUIRED')
    print(json.dumps(capture(),sort_keys=True))

if __name__=='__main__':
    try:main()
    except Exception as error:
        value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',value) else 'GOOGLE_ONBOARDING_MOBILE_CAPTURE_REJECTED'
        print(json.dumps({'stage':'GOOGLE_ONBOARDING_MOBILE_CAPTURE_REJECTED','code':code},sort_keys=True));raise SystemExit(1)
