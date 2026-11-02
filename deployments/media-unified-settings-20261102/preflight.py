"""Read-only current427 / active auto-prep / h43-165 baseline capture.

Loads the authenticated legacy chain once. Does not call its old sample(),
construct the worker helper, request a provider or freeze live business rows.
"""
import copy,hashlib,json,os,re,resource,socket,sqlite3,stat,types
from pathlib import Path
HOST='iZj6c4cj7edgnhdimts4l7Z'
ROOT=Path('/opt/t24-crm/releases')
OLD=ROOT/'media-automation-c78b50a11e02-20261102'
HELPER='9cc1abc634f927fc0f3b54c1d8d6f8ede2fe5573eb4c730236f756015a97eefe'
CONTROLLER='8727edc4ae5ef1a99ef1276f7f337412ec1de67526d3eeb5a5baf9664853cd78'
WORKER='c5acd2d20de6ef07e1f417849b07ff6a0a28b6934cb6a590d08913207f5e66f9'
PREPARED='29ae8e354c8555a9aca186f5ef0b2368d17bd7f6007f73e57e6195e62558a47d'
DEPLOYED='bea765503d909b4ad5f7b1899cb040016ff44fdbe07970da3d82b0b4fbf1f212'
ENABLED='067d8e6f15b801f8a7a7736d2c8772820d2cf5b8208aae19b3d57ec34481804a'
MANIFEST='96f1baa987eeea40115fb8408ddb28d1a39b8a1dbbb254098f2da2ae554e44f8'
PAYLOAD='7054749c962d4cf5bd88b1ba040e6efd8ab85cca904675fb00aeb32340554c45'
OLD_PREFLIGHT='b130a39759f3638b4428fd974913e1b1cf6b964f757f010ec7b76364baa2d8c0'
SOURCE='c78b50a11e020674ad53b34fbbfb5b1badd4a9a5'
FRONTEND='569fa342f1c3'
HEAD='h43fe567f803'
SCHEMA='7bccbd8ff34d0d10d102b5fe3510470ee6b7817be7f168921f2887e7f6bf3872'
NGINX='fa702dcd4c3be4cae9faaff0462ef4a6fb70b3e955d724857bbe0c68c5ebd74b'
ACTIVE_NGINX='7dcd909a106c3e2096624d9bc7e6b4fe77bc22d10c9ae6586204a9fdd55c1730'
CSP='ead64b09efe8c4f35648aa8eafe8855c5268ecf0999e0918b3642dd9dfbfe7a6'
PUBLIC='/var/www/t24-crm-public/media-automation-c78b50a11e02-20261102'
STATIC='10d2f885a116c76600fe4d5c3282e6c3b70832e2a07f1604ec9c6cf4da2b3819'
RUNTIME={'config':'b01627120f6ade88898d49db1301837104817ec67c66f211dd99a0f0ed368529','id':'0e33ad4fcfb91258d37206ff66473cb95e6a033fb15b572e8cbc89a8a56849b2','image':'sha256:f456f7aaca2452db96c9df796f3c01efda9a2f23403bdd5e3b755b409c6de8f1','restart':0,'started':'2026-11-02T04:19:00.366678579Z'}
KEY='T24_MEDIA_MONTHLY_AUTOPREP_ENABLED'
H=lambda b:hashlib.sha256(b).hexdigest()
_CACHE=None
def need(ok,code):
    if not ok:raise RuntimeError(code)
def encoded(v):return (json.dumps(v,sort_keys=True,indent=2)+'\n').encode()
def digest(v):return H(json.dumps(v,sort_keys=True,separators=(',',':')).encode())
def identity(r):return (r.st_dev,r.st_ino,r.st_uid,r.st_mode,r.st_nlink,r.st_size,r.st_mtime_ns,r.st_ctime_ns)
def read(path,sha,maximum=16777216):
    need(path.is_absolute() and path.resolve()==path,'CANONICAL_ROOT_PRIVATE_PATH_REQUIRED')
    for p in path.parents:
        r=p.lstat();need(stat.S_ISDIR(r.st_mode) and r.st_uid==0 and not r.st_mode&0o022,'ROOT_PROTECTED_PARENT_REQUIRED')
    r=path.lstat();need(stat.S_ISREG(r.st_mode) and r.st_uid==0 and stat.S_IMODE(r.st_mode)==0o600 and r.st_nlink==1 and 0<r.st_size<=maximum,'ROOT600_FROZEN_FILE_REQUIRED')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as f:o=os.fstat(f.fileno());body=f.read(maximum+1);a=os.fstat(f.fileno())
    need(identity(r)==identity(o)==identity(a)==identity(path.lstat()) and len(body)==r.st_size and H(body)==sha,'EXACT_STABLE_FROZEN_BYTES_REQUIRED');return body
def dependencies():
    global _CACHE
    need(os.geteuid()==0 and socket.gethostname()==HOST,'EXACT_ROOT_SERVER_REQUIRED')
    body=read(OLD/'release.py',HELPER,131072);read(OLD/'at_write_release.py',CONTROLLER,131072);read(OLD/'worker_enable.py',WORKER,131072)
    if _CACHE is None:
        module=types.ModuleType('_unified_current_r2_once');module.__file__=str(OLD/'release.py');exec(compile(body,module.__file__,'exec'),module.__dict__)
        need(module.SOURCE_SHA==SOURCE and module.FRONTEND==FRONTEND and module.NEW_REVISION==HEAD,'EXACT_DEPLOYED_APPLICATION_REQUIRED')
        args=types.SimpleNamespace(phase='recover',release=OLD,manifest_sha256=MANIFEST,payload_sha256=PAYLOAD,preflight=ROOT/('media-automation-preflight-'+OLD_PREFLIGHT[:12]+'.json'),preflight_sha256=OLD_PREFLIGHT,review_sha256=PREPARED)
        ctx=module.Release(args);prepared=json.loads(read(OLD/'prepared.json',PREPARED));main=json.loads(read(OLD/'deployed.json',DEPLOYED));enabled=json.loads(read(OLD/'worker-enabled.json',ENABLED));module.validate_prepared(prepared,MANIFEST,PAYLOAD,OLD_PREFLIGHT)
        need(main['stage']=='MEDIA_AUTOMATION_DEPLOYED' and main['protocol']=='media-automation-at-write-v1' and main['source_sha']==SOURCE and main['frontend_version']==FRONTEND and main['schema_revision']==HEAD and main['table_count']==165 and main['prepared_sha256']==PREPARED and main['quiescent_baseline_sha256']=='2df9b0f4268f50cae490d65abb08cb05c1eaa796e6caec6175067213aba865bc','EXACT_DEPLOYED_AT_WRITE_PROOF_REQUIRED')
        need(enabled['stage']=='MEDIA_AUTOMATION_WORKER_ENABLED' and enabled['main_deployed_sha256']==DEPLOYED and enabled['source_sha']==SOURCE and enabled['crm']==RUNTIME and enabled['only_new_runtime_flag_added'] is True and enabled['existing_environment_files_flags_credentials_static_acl_preserved'] is True and all(enabled[k] is False for k in ('ai_calls_requested','publications_requested','database_written','policies_created')),'EXACT_CURRENT_ACTIVE_WORKER_PROOF_REQUIRED')
        inventory={**ctx.original_inventory,**module.BACKEND_AFTER};need(len(inventory)==427,'EXACT427_CURRENT_BACKEND_FILES_REQUIRED');_CACHE=(module,ctx,inventory)
    return _CACHE
def table_definitions(path):
    con=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True,timeout=3)
    try:
        con.execute('PRAGMA query_only=ON');con.execute('BEGIN');return [list(r) for r in con.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name,tbl_name")]
    finally:con.close()
def environment(ctx,info):
    rows=info['Config']['Env'];need(isinstance(rows,list) and [v for v in rows if v.split('=',1)[0]==KEY]==[KEY+'=true'],'EXISTING_MONTHLY_AUTOPREP_TRUE_REQUIRED')
    projected=copy.deepcopy(info);projected['Config']['Env']=[v for v in rows if v.split('=',1)[0]!=KEY];ctx.environment(projected)
    return digest(sorted(rows)),digest(rows)
def sample():
    _,ctx,inventory=dependencies();m=ctx.m;p=ctx.proof;c=ctx.c;info=m.inspect('t24-crm');need(info['State']['Running'] is True and m.runtime(info)==RUNTIME and m.inventory(info['Id'])==inventory,'EXACT_CURRENT427_RUNTIME_SOURCE_REQUIRED');env,ordered=environment(ctx,info)
    need(ctx.c.safe.safe_private_boundary(m,ctx.c.pins)==p['private_boundary'],'PRIVATE_BOUNDARY_CHANGED')
    credentials={'ops':ctx.c.safe.protected_metadata(ctx.c.c.ENV_FILE),'google':ctx.c.safe.protected_metadata(ctx.c.safe.GBP_ENV),'meta_read':ctx.c.safe.protected_metadata(ctx.c.ctx.workflow.core.ENV_FILE),'meta_legacy':ctx.c.safe.protected_metadata(ctx.c.ctx.workflow.core.LEGACY_ENV_FILE)}
    need(credentials==p['credential_metadata'] and m.credential_boundary()==p['credential_boundary'],'CREDENTIAL_METADATA_CHANGED');need([m.BUSINESS.stat().st_dev,m.BUSINESS.stat().st_ino]==p['database_identity'] and m.schema_signature(m.BUSINESS,HEAD)==SCHEMA,'CURRENT165_DATABASE_IDENTITY_SCHEMA_CHANGED')
    rows=ctx.rows();need(len(rows)==165,'EXACT165_CURRENT_TABLES_REQUIRED');need(str(ctx.public)==PUBLIC and m.verify_public(ctx.public,ctx.manifest)==STATIC and H(m.NGINX.read_bytes())==NGINX,'CURRENT_STATIC_BYTES_CHANGED');need(ctx.nginx(updated=True)==ACTIVE_NGINX,'CURRENT_ACTIVE_NGINX_CHANGED');ctx.staticmod.public_security_policy(m,CSP)
    return {'stage':'MEDIA_UNIFIED_SETTINGS_READONLY_BASELINE','source_sha':SOURCE,'frontend_version':FRONTEND,'schema_revision':HEAD,'crm':RUNTIME,'backend_inventory':inventory,'backend_inventory_sha256':digest(inventory),'backend_file_count':427,'rows':rows,'database_metadata':ctx.c.metadata(m.BUSINESS),'database_identity':p['database_identity'],'schema_sha256':SCHEMA,'table_definitions':table_definitions(m.BUSINESS),'environment_sha256':env,'ordered_environment_sha256':ordered,'ops_environment_sha256':p['ops_environment_sha256'],'credential_boundary':p['credential_boundary'],'credential_metadata':credentials,'private_boundary':p['private_boundary'],'public_root':PUBLIC,'public_inventory_sha256':STATIC,'nginx_sha256':NGINX,'active_nginx_sha256':ACTIVE_NGINX,'content_security_policy_sha256':CSP,'monthly_auto_prep_enabled':True,'google_scheduler_enabled':True,'google_scheduler_activation_from':'2026-10-30T19:42:04Z','meta_execution_enabled':False,'meta_scheduler_enabled':False,'old_flags_preserved':True,'rows_are_historical_until_writer_stop':True,'business_writes':False,'provider_requests':False,'private_content_exported':False,'credentials_exported':False,'runtime_changed':False,'schema_changed':False}
def capture():
    first=sample();second=sample();mutable=('rows','database_metadata')
    need({k:v for k,v in first.items() if k not in mutable}=={k:v for k,v in second.items() if k not in mutable},'IMMUTABLE_CURRENT_BOUNDARIES_CHANGED')
    body=encoded(second);sha=H(body);path=ROOT/('media-unified-settings-baseline-'+sha[:12]+'.json')
    if path.exists():read(path,sha)
    else:
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as f:f.write(body);f.flush();os.fsync(f.fileno())
    keys=('source_sha','frontend_version','schema_revision','crm','backend_inventory_sha256','backend_file_count','database_identity','schema_sha256','environment_sha256','ordered_environment_sha256','ops_environment_sha256','public_root','public_inventory_sha256','nginx_sha256','active_nginx_sha256','content_security_policy_sha256','monthly_auto_prep_enabled','google_scheduler_enabled','google_scheduler_activation_from','meta_execution_enabled','meta_scheduler_enabled','old_flags_preserved')
    result={'stage':'MEDIA_UNIFIED_SETTINGS_BASELINE_CAPTURED','sha256':sha,'path':str(path),'bytes':len(body),'table_count':165,'historical_rows_sha256':digest(second['rows']),'immutable_two_samples_verified':True,'live_rows_may_advance_before_stop':True,**{k:second[k] for k in keys},'business_writes':False,'provider_requests':False,'runtime_changed':False,'schema_changed':False,'credentials_exported':False,'private_content_exported':False};need(len(json.dumps(result).encode())<12000,'BOUNDED_AGGREGATE_CAPTURE_REQUIRED');return result
def main():
    resource.setrlimit(resource.RLIMIT_CORE,(0,0));os.umask(0o077);print(json.dumps(capture(),sort_keys=True))
if __name__=='__main__':
    try:main()
    except BaseException as e:
        v=str(e);code=v if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',v) else 'MEDIA_UNIFIED_SETTINGS_CAPTURE_REJECTED';print(json.dumps({'stage':'MEDIA_UNIFIED_SETTINGS_CAPTURE_REJECTED','code':code,'business_writes':False},sort_keys=True));raise SystemExit(1)
