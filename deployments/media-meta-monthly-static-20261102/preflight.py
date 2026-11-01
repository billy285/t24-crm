"""Two stable read-only samples of the exact completed Meta monthly release."""
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
SOURCE='5fd379d625d6c18abdec1b98d388494d0900c780'
FRONTEND='1d94d63752de'
HEAD='g32ed456e792'
ROOT=Path('/opt/t24-crm/releases')
OLD=ROOT/'media-meta-monthly-5fd379d625d6-20261102'
HELPER='b11362093b66d5bbefc62d0907f8217f389735b7ffa5da7d091ad4e132bc2247'
PREPARED='09ec24d26f267137bf5dcc6e5e9e563224da99fe553a4d7b9b986804afae2ac3'
DEPLOYED='41ab8e9a87761901e16cce56102de6040d80476aa1b9e43c9f422cea1e3d3aa0'
MANIFEST='7a94c774a72a8402559b97d49e3693c8e7a6e72b20d45da10b4389b6ef5e3abc'
PAYLOAD='55a2d2e5c6447c15cc33f83bb1a9af69f0bcb14f39bca5fa821d707f94b7b704'
PREFLIGHT='6199dc87be59bb86693f2e1b0a06278624b1faac112db5598e43aee78464a7d2'
SCHEMA='c111f3fc3154eab704a25536280bf02dfd00d120867da7ed9727ec2c85ac4a7f'
CSP='ead64b09efe8c4f35648aa8eafe8855c5268ecf0999e0918b3642dd9dfbfe7a6'
NGINX='67ac1c2f5d3cee61a393aab0c875a75a09c799d1e2e8a64d11d5043825a4e9d6'
PUBLIC='/var/www/t24-crm-public/media-meta-monthly-5fd379d625d6-20261102'
RUNTIME={'config': '5038d2dcddb9b0215926f5d45411c25b56542c678a082a8b05774054b1d9c94e', 'id': '1ee579193b73048fb1120f516d53d2400191c2499cfad5284184ca0506ed698e', 'image': 'sha256:05dc7e8e8ce620e0d92e07e95d304537250d17beb14dbeb63713e06d2319bf41', 'restart': 0, 'started': '2026-11-01T22:06:12.469255563Z'}
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
        module=ModuleType('_priority_current_scale');module.__file__=str(OLD/'release.py');exec(compile(body,module.__file__,'exec'),module.__dict__)
        need(module.SOURCE_SHA==SOURCE and module.FRONTEND==FRONTEND and module.SCHEMA_REVISION==HEAD and module.SCOPE=='media-meta-monthly','EXACT_DEPLOYED_SCALE_SOURCE_REQUIRED')
        args=SimpleNamespace(phase='recover',release=OLD,manifest_sha256=MANIFEST,payload_sha256=PAYLOAD,preflight=ROOT/('media-meta-monthly-preflight-'+PREFLIGHT[:12]+'.json'),preflight_sha256=PREFLIGHT,review_sha256=PREPARED)
        ctx=module.Release(args);prepared=json.loads(read(OLD/'prepared.json',PREPARED));deployed=json.loads(read(OLD/'deployed.json',DEPLOYED))
        module.validate_prepared(prepared,MANIFEST,PAYLOAD,PREFLIGHT)
        need(deployed['stage']=='MEDIA_META_MONTHLY_DEPLOYED' and deployed['source_sha']==SOURCE and deployed['frontend_version']==FRONTEND and deployed['schema_revision']==HEAD and deployed['table_count']==162 and deployed['crm']==RUNTIME and deployed['prepared_sha256']==PREPARED,'EXACT_CURRENT_SCALE_DEPLOYMENT_REQUIRED')
        need(deployed['privacy']['content_security_policy_sha256']==CSP and all(deployed[x] is True for x in ('all162_rows_schema_preserved','existing_full_environment_preserved','existing_ops_credentials_preserved','private_boundary_preserved','old_meta_google_cutoff_preserved')) and all(deployed[x] is False for x in ('provider_requests','database_restored','operations_execution_enabled','operations_scheduler_enabled','credentials_journaled')),'EXACT_EXISTING_PROTECTION_PROOF_REQUIRED')
        inventory=json.loads(read(OLD/'backend-candidate-inventory.json',prepared['candidate_inventory_sha256']))
        need(len(inventory)==420,'EXACT420_BACKEND_SOURCE_FILES_REQUIRED');_CACHE=(module,ctx,inventory)
    return _CACHE

def markers(path):
    con=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True,timeout=3)
    try:
        con.execute('PRAGMA query_only=ON');con.execute('BEGIN')
        return {name:con.execute('SELECT count(*) FROM '+name).fetchone()[0] for name in ('customers','google_business_bindings','google_business_onboarding_catalogs','google_business_onboarding_requests','google_business_onboarding_batches','google_business_onboarding_items')}
    finally:con.close()

def sample():
    module,ctx,inventory=dependencies();m=ctx.m;current=m.inspect('t24-crm')
    need(current['State']['Running'] is True and m.runtime(current)==RUNTIME,'EXACT_CURRENT_SCALE_RUNTIME_REQUIRED')
    env,ops=ctx.environment(current);ctx.ctx.workflow.pf.google_environment(current);m.verify_secret_mount(current);m.verify_production_worker_enabled(current);m.retained().require_safe_original_restart(current)
    ctx.protections(updated=True,recovery=True)
    need(m.inventory(RUNTIME['id'])==inventory,'CURRENT420_BACKEND_SOURCE_DRIFT')
    need(H(m.NGINX.read_bytes())==NGINX and str(ctx.public)==PUBLIC,'EXACT_CURRENT_SCALE_NGINX_ROOT_REQUIRED')
    active_nginx=ctx.nginx(updated=True)
    rows=ctx.retained.evidence(ctx.rows());need(len(rows)==162,'EXACT162_ROW_EVIDENCE_REQUIRED')
    evidence=markers(m.BUSINESS)
    need(all(rows[name]['count']==value for name,value in evidence.items() if type(value)is int and name in rows),'CONSISTENT_DISCOVERY_AND_ROW_EVIDENCE_REQUIRED')
    return {'stage':'MEDIA_META_MONTHLY_STATIC_READONLY_PREFLIGHT','source_sha':SOURCE,'frontend_version':FRONTEND,'schema_revision':HEAD,'deployed_receipt_sha256':DEPLOYED,'prepared_receipt_sha256':PREPARED,'crm':m.runtime(current),'environment_sha256':env,'ops_environment_sha256':ops,'schema_sha256':m.schema_signature(m.BUSINESS,HEAD),'rows':rows,'database_metadata':ctx.metadata(m.BUSINESS),'database_identity':ctx.proof['database_identity'],'business_markers':evidence,'backend_inventory':inventory,'backend_inventory_sha256':digest(inventory),'backend_file_count':420,'credential_boundary':ctx.proof['credential_boundary'],'credential_metadata':ctx.proof['credential_metadata'],'private_boundary':ctx.proof['private_boundary'],'public_root':PUBLIC,'public_inventory_sha256':m.verify_public(ctx.public,ctx.manifest),'nginx_sha256':NGINX,'active_nginx_sha256':active_nginx,'content_security_policy_sha256':CSP,'all162_current_tables_preserved':True,'google_scheduler_enabled':True,'google_scheduler_activation_from':'2026-10-30T19:42:04Z','ops_execution_enabled':False,'ops_scheduler_enabled':False,'existing_asset_worker_enabled':True,'onboarding_worker_default_enabled':True,'business_writes':False,'provider_requests':False,'credential_file_content_read':False,'private_content_read':False,'runtime_changed':False,'schema_changed':False,'permissions_changed':False}

def stable(first,second,retained):
    retained.live_sequence_boundary(first['database_metadata'],second['database_metadata'])
    need({**second,'database_metadata':first['database_metadata']}==first,'CURRENT162_BOUNDARIES_CHANGED_DURING_CAPTURE')

def capture():
    first=sample();second=sample();_,ctx,_=dependencies();stable(first,second,ctx.retained)
    body=encoded(second);sha=H(body);path=ROOT/('media-meta-monthly-static-preflight-'+sha[:12]+'.json')
    if path.exists():read(path,sha)
    else:
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(body);stream.flush();os.fsync(stream.fileno())
    keep=('source_sha','frontend_version','schema_revision','deployed_receipt_sha256','prepared_receipt_sha256','crm','environment_sha256','ops_environment_sha256','schema_sha256','database_identity','business_markers','backend_inventory_sha256','backend_file_count','public_root','public_inventory_sha256','nginx_sha256','active_nginx_sha256','content_security_policy_sha256','all162_current_tables_preserved','google_scheduler_enabled','google_scheduler_activation_from','ops_execution_enabled','ops_scheduler_enabled','existing_asset_worker_enabled','onboarding_worker_default_enabled')
    result={'stage':'MEDIA_META_MONTHLY_STATIC_PREFLIGHT_CAPTURED','sha256':sha,'path':str(path),'bytes':len(body),'table_count':162,'rows_sha256':digest(second['rows']),**{key:second[key] for key in keep},'two_stable_samples_verified':True,'existing_monthly_rate_counter_forward_only':True,'schema_changed':False,'permissions_changed':False,'business_writes':False,'provider_requests':False,'credential_file_content_read':False,'private_content_read':False,'runtime_changed':False}
    need(len(json.dumps(result).encode())<10000,'BOUNDED_AGGREGATE_CAPTURE_REQUIRED');return result

def main():
    resource.setrlimit(resource.RLIMIT_CORE,(0,0));os.umask(0o077)
    need(os.geteuid()==0 and socket.gethostname()==HOST,'EXACT_ROOT_SERVER_REQUIRED')
    print(json.dumps(capture(),sort_keys=True))

if __name__=='__main__':
    try:main()
    except Exception as error:
        value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',value) else 'MEDIA_META_MONTHLY_STATIC_CAPTURE_REJECTED'
        print(json.dumps({'stage':'MEDIA_META_MONTHLY_STATIC_CAPTURE_REJECTED','code':code},sort_keys=True));raise SystemExit(1)
