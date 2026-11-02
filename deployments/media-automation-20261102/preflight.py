"""Capture current immutable runtime and two fresh read-only business samples.

Historical deployment receipts authenticate the helper chain, never today's rows.
No provider call, business write, schema change or container mutation is made.
"""
import hashlib,json,os,re,resource,socket,sqlite3,stat,types
from pathlib import Path
from types import SimpleNamespace

HOST='iZj6c4cj7edgnhdimts4l7Z'
ROOT=Path('/opt/t24-crm/releases')
OLD=ROOT/'media-meta-monthly-static-eec3d1d02a97-20261102'
HELPER='cd277633fd751576d85ec8d9bd49685df7e4bb98ddfffebbf8ceae508d3e4284'
PREPARED='eedb0a0bd08bd7d46cf2bf206b9c50aae8d2487dcf93a5619b23a8eb6b44f285'
DEPLOYED='2354bb6e48c86423250df592434cc5d020020ac397b44f92cd7fef31df836c4d'
MANIFEST='ef228b776044f74651d8c397283b70ea8eaf3a5443a829eb11fe5048ce52c632'
PAYLOAD='8a3a4b1be14c2d508a9c57aef3206e52a4a1008abaa750f65fce0c940e71601e'
PREFLIGHT='78bb1249abca9506a9158c88fcbc31edf36c0eef6926c07ddc07f6235e0a9143'
SOURCE='5fd379d625d6c18abdec1b98d388494d0900c780'
FRONTEND='8c3b5e1302ac'
HEAD='g32ed456e792'
SCHEMA='c111f3fc3154eab704a25536280bf02dfd00d120867da7ed9727ec2c85ac4a7f'
NGINX='0184a613c95d04fb74f6d674213b1d787c000af33c5add5c90eb02637302ba40'
CSP='ead64b09efe8c4f35648aa8eafe8855c5268ecf0999e0918b3642dd9dfbfe7a6'
PUBLIC='/var/www/t24-crm-public/media-meta-monthly-static-eec3d1d02a97-20261102'
STATIC='a8def10330366b13cabcb1fe1155f681f849a70a590252d1e7eafb8b18f58a3e'
RUNTIME={'config':'5038d2dcddb9b0215926f5d45411c25b56542c678a082a8b05774054b1d9c94e','id':'1ee579193b73048fb1120f516d53d2400191c2499cfad5284184ca0506ed698e','image':'sha256:05dc7e8e8ce620e0d92e07e95d304537250d17beb14dbeb63713e06d2319bf41','restart':0,'started':'2026-11-01T22:06:12.469255563Z'}
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
    body=read(OLD/'release.py',HELPER,131072)
    if _CACHE is None:
        mod=types.ModuleType('_automation_current_static');mod.__file__=str(OLD/'release.py');exec(compile(body,mod.__file__,'exec'),mod.__dict__)
        need(mod.SOURCE_SHA=='eec3d1d02a97a5b52a1483e0c93f094242aade56' and mod.BASE_SOURCE==SOURCE and mod.FRONTEND==FRONTEND and mod.HEAD==HEAD,'EXACT_CURRENT_HELPER_REQUIRED')
        a=SimpleNamespace(phase='recover',release=OLD,manifest_sha256=MANIFEST,payload_sha256=PAYLOAD,preflight=ROOT/('media-meta-monthly-static-preflight-'+PREFLIGHT[:12]+'.json'),preflight_sha256=PREFLIGHT,review_sha256=PREPARED)
        current=mod.Release(a);prepared=json.loads(read(OLD/'prepared.json',PREPARED));deployed=json.loads(read(OLD/'deployed.json',DEPLOYED))
        mod.validate_prepared(prepared,MANIFEST,PAYLOAD,PREFLIGHT)
        need(deployed['stage']=='MEDIA_META_MONTHLY_UI_STATIC_DEPLOYED' and deployed['runtime']==RUNTIME and deployed['public_root']==PUBLIC and deployed['public_inventory_sha256']==STATIC and deployed['prepared_sha256']==PREPARED,'EXACT_CURRENT_DEPLOYED_RECEIPT_REQUIRED')
        need(deployed['all162_rows_preserved'] is True and all(deployed[k] is False for k in ('database_writes','schema_changes','container_restarts','permissions_changes','environment_changes','provider_or_publication_actions')),'EXACT_EXISTING_PROTECTION_RECEIPT_REQUIRED')
        _CACHE=(mod,current,current.inventory)
    return _CACHE

def table_definitions(path):
    con=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True,timeout=3)
    try:
        con.execute('PRAGMA query_only=ON');con.execute('BEGIN')
        return [list(r) for r in con.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name,tbl_name")]
    finally:con.close()

def sample():
    mod,s,inventory=dependencies();c=s.ctx;m=s.m;p=s.proof;info=m.inspect('t24-crm')
    need(info['State']['Running'] is True and m.runtime(info)==RUNTIME and m.inventory(RUNTIME['id'])==inventory and len(inventory)==420,'EXACT_CURRENT420_RUNTIME_REQUIRED')
    env,ops=c.environment(info);c.ctx.workflow.pf.google_environment(info);m.verify_secret_mount(info);m.verify_production_worker_enabled(info);m.retained().require_safe_original_restart(info)
    need(c.safe.safe_private_boundary(m,c.pins)==p['private_boundary'],'PRIVATE_BOUNDARY_CHANGED')
    credentials={'ops':c.safe.protected_metadata(c.c.ENV_FILE),'google':c.safe.protected_metadata(c.safe.GBP_ENV),'meta_read':c.safe.protected_metadata(c.ctx.workflow.core.ENV_FILE),'meta_legacy':c.safe.protected_metadata(c.ctx.workflow.core.LEGACY_ENV_FILE)}
    need(credentials==p['credential_metadata'] and m.credential_boundary()==p['credential_boundary'],'CREDENTIAL_METADATA_CHANGED')
    need([m.BUSINESS.stat().st_dev,m.BUSINESS.stat().st_ino]==p['database_identity'] and m.schema_signature(m.BUSINESS,HEAD)==SCHEMA,'DATABASE_IDENTITY_OR_SCHEMA_CHANGED')
    rows=c.retained.evidence(c.rows());need(len(rows)==162,'EXACT162_CURRENT_TABLES_REQUIRED')
    c.retained.live_sequence_boundary(p['database_metadata'],c.metadata(m.BUSINESS))
    need(H(m.NGINX.read_bytes())==NGINX and str(s.public)==PUBLIC and m.verify_public(s.public,s.manifest)==STATIC,'CURRENT_STATIC_BYTES_CHANGED')
    s.nginx(updated=True);active=H(m.run(['nginx','-T'],'NGINX_READ_FAILED'));mod.public_security_policy(m,CSP)
    return {'stage':'MEDIA_AUTOMATION_READONLY_PREFLIGHT','source_sha':SOURCE,'frontend_version':FRONTEND,'schema_revision':HEAD,'crm':RUNTIME,'environment_sha256':env,'ops_environment_sha256':ops,'schema_sha256':SCHEMA,'rows':rows,'database_metadata':c.metadata(m.BUSINESS),'database_identity':p['database_identity'],'table_definitions':table_definitions(m.BUSINESS),'backend_inventory':inventory,'backend_inventory_sha256':digest(inventory),'backend_file_count':420,'credential_boundary':p['credential_boundary'],'credential_metadata':credentials,'private_boundary':p['private_boundary'],'public_root':PUBLIC,'public_inventory_sha256':STATIC,'nginx_sha256':NGINX,'active_nginx_sha256':active,'content_security_policy_sha256':CSP,'google_scheduler_enabled':True,'google_scheduler_activation_from':'2026-10-30T19:42:04Z','ops_execution_enabled':False,'ops_scheduler_enabled':False,'new_automation_worker_enabled':False,'existing_asset_worker_enabled':True,'onboarding_worker_default_enabled':True,'business_writes':False,'provider_requests':False,'credential_file_content_read':False,'private_content_read':False,'runtime_changed':False,'schema_changed':False,'permissions_changed':False}

def capture():
    first=sample();second=sample();_,s,_=dependencies();s.ctx.retained.live_sequence_boundary(first['database_metadata'],second['database_metadata'])
    need({**second,'database_metadata':first['database_metadata']}==first,'FRESH_CURRENT_BOUNDARIES_CHANGED_DURING_CAPTURE')
    body=encoded(second);sha=H(body);path=ROOT/('media-automation-preflight-'+sha[:12]+'.json')
    if path.exists():read(path,sha)
    else:
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as f:f.write(body);f.flush();os.fsync(f.fileno())
    keys=('source_sha','frontend_version','schema_revision','crm','environment_sha256','ops_environment_sha256','schema_sha256','database_identity','backend_inventory_sha256','backend_file_count','public_root','public_inventory_sha256','nginx_sha256','active_nginx_sha256','content_security_policy_sha256','google_scheduler_enabled','google_scheduler_activation_from','ops_execution_enabled','ops_scheduler_enabled','new_automation_worker_enabled','existing_asset_worker_enabled','onboarding_worker_default_enabled')
    result={'stage':'MEDIA_AUTOMATION_PREFLIGHT_CAPTURED','sha256':sha,'path':str(path),'bytes':len(body),'table_count':162,'rows_sha256':digest(second['rows']),'table_definitions_sha256':digest(second['table_definitions']),**{k:second[k] for k in keys},'two_fresh_stable_samples_verified':True,'schema_changed':False,'business_writes':False,'provider_requests':False,'private_content_read':False,'credential_file_content_read':False,'runtime_changed':False,'permissions_changed':False}
    need(len(json.dumps(result).encode())<10000,'BOUNDED_AGGREGATE_RESULT_REQUIRED');return result

def main():
    resource.setrlimit(resource.RLIMIT_CORE,(0,0));os.umask(0o077);print(json.dumps(capture(),sort_keys=True))
if __name__=='__main__':
    try:main()
    except Exception as e:
        v=str(e);code=v if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',v) else 'MEDIA_AUTOMATION_PREFLIGHT_REJECTED'
        print(json.dumps({'stage':'MEDIA_AUTOMATION_PREFLIGHT_REJECTED','code':code},sort_keys=True));raise SystemExit(1)
