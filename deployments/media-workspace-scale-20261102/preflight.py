"""Two stable read-only samples of the actual R3 backend/mobile static release.

This captures current rows, including completed explicitly requested discovery
reads. It neither refreshes credentials nor changes business/provider state.
"""
import hashlib,json,os,re,resource,socket,sqlite3,stat,types
from pathlib import Path
from types import SimpleNamespace

HOST='iZj6c4cj7edgnhdimts4l7Z'
ROOT=Path('/opt/t24-crm/releases')
OLD=ROOT/'google-business-onboarding-mobile-adb948da237f-20261102'
HELPER='fb017adf5eaa00e7c873bc26471693cb54030494631390c7a85ad24891171b0c'
MANIFEST='a08a1c922981b0fe0fa91436b4061e5143f6769bfd9e0e03b89f6c852444a51b'
PAYLOAD='ff601095511c4e1573c49360b4e6833f46c0aa4a15ecb5c49b98fa5e6330e9f4'
PREFLIGHT='b847750a7e816361fa13a166f4f24e4f23a97008e108f33da486d54239bece5b'
PREPARED='648f59c27576e06164b9a2db4d295606ed340e710591965d12b201db24e86cd8'
DEPLOYED='2a863c960b22d1392ede19a39ace1af18e1526508cf711e778d05fa763290947'
SOURCE='8b429dad8a2f144ea27527717d4811fb7ddc9b3c'
STATIC_SOURCE='adb948da237f2056bf37e53c9e5ec25c42cb8f78'
FRONTEND='c814db9f574f'
REVISION='g32ed456e792'
SCHEMA='c111f3fc3154eab704a25536280bf02dfd00d120867da7ed9727ec2c85ac4a7f'
CSP='ead64b09efe8c4f35648aa8eafe8855c5268ecf0999e0918b3642dd9dfbfe7a6'
PUBLIC=Path('/var/www/t24-crm-public/'+OLD.name)
RUNTIME={'id':'9b247014d54e57e5f671d3f8378c6b387c5301a87471b823e790b0d4965d072b','config':'eeed0663f81bffa9cc9926afde7d203ac84ced2725e0fba0fc7342c136531728','image':'sha256:ed057407d8866958a2966043ddc2457488d77cc00dd7bbabb608bcedc7c0bb09','restart':0,'started':'2026-11-01T19:00:56.90391494Z'}
BACKEND_FILES=frozenset({'services/media_workspace.py','routers/media_workspace.py'})
H=lambda b:hashlib.sha256(b).hexdigest()
_CACHE=None

def need(ok,code):
    if not ok:raise RuntimeError(code)
def encoded(value):return (json.dumps(value,sort_keys=True,indent=2)+'\n').encode()
def digest(value):return H(json.dumps(value,sort_keys=True,separators=(',',':')).encode())
def identity(s):return(s.st_dev,s.st_ino,s.st_uid,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
def read(path,sha,maximum=16777216):
    need(path.is_absolute() and path.resolve()==path,'CANONICAL_ROOT_PRIVATE_PATH_REQUIRED')
    for p in path.parents:
        s=p.lstat();need(stat.S_ISDIR(s.st_mode) and s.st_uid==0 and not s.st_mode&0o022 and not p.is_symlink(),'ROOT_PROTECTED_PARENT_REQUIRED')
    s=path.lstat();need(stat.S_ISREG(s.st_mode) and s.st_uid==0 and s.st_nlink==1 and stat.S_IMODE(s.st_mode)==0o600 and 0<s.st_size<=maximum,'ROOT600_FROZEN_FILE_REQUIRED')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as f:a=os.fstat(f.fileno());body=f.read(maximum+1);b=os.fstat(f.fileno())
    need(identity(s)==identity(a)==identity(b)==identity(path.lstat()) and len(body)==s.st_size and H(body)==sha,'EXACT_FROZEN_FILE_BYTES_REQUIRED');return body

def dependencies():
    global _CACHE
    need(os.geteuid()==0 and socket.gethostname()==HOST,'EXACT_ROOT_SERVER_REQUIRED')
    code=read(OLD/'release.py',HELPER,131072)
    if _CACHE is None:
        mobile=types.ModuleType('_scale_mobile_release');mobile.__file__=str(OLD/'release.py');exec(compile(code,mobile.__file__,'exec'),mobile.__dict__)
        need(mobile.SOURCE_SHA==STATIC_SOURCE and mobile.BASE_SOURCE==SOURCE and mobile.FRONTEND==FRONTEND and mobile.HEAD==REVISION,'EXACT_MOBILE_AND_BACKEND_SOURCE_REQUIRED')
        args=SimpleNamespace(release=OLD,manifest_sha256=MANIFEST,payload_sha256=PAYLOAD,preflight=ROOT/('google-business-onboarding-mobile-preflight-'+PREFLIGHT[:12]+'.json'),preflight_sha256=PREFLIGHT,review_sha256=PREPARED)
        wrapper=mobile.Release(args);prepared=json.loads(read(OLD/'prepared.json',PREPARED));deployed=json.loads(read(OLD/'deployed.json',DEPLOYED));mobile.validate_prepared(prepared,MANIFEST,PAYLOAD,PREFLIGHT)
        need(deployed['stage']=='GOOGLE_ONBOARDING_MOBILE_STATIC_DEPLOYED' and deployed['source_sha']==STATIC_SOURCE and deployed['backend_source_sha']==SOURCE and deployed['frontend_version']==FRONTEND and deployed['runtime']==RUNTIME and deployed['public_root']==str(PUBLIC) and deployed['prepared_sha256']==PREPARED,'EXACT_COMPLETED_MOBILE_DEPLOYMENT_REQUIRED')
        need(all(deployed[x] is True for x in ('all162_rows_preserved','static_only','content_security_policy_unchanged','old_hashed_assets_preserved')) and all(deployed[x] is False for x in ('database_writes','schema_changes','container_restarts','permissions_changes','environment_changes','provider_or_publication_actions')),'EXACT_PRESERVED_DATA_AND_AUTHORITY_REQUIRED')
        module,flow,inventory=wrapper.pf.dependencies()
        need(len(inventory)==419 and flow.m.inventory(RUNTIME['id'])==inventory and all(name in inventory for name in BACKEND_FILES),'EXACT_CURRENT419_BACKEND_SOURCE_REQUIRED')
        _CACHE=(module,flow,inventory,wrapper,deployed)
    return _CACHE[:3]

def markers(path):
    con=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True,timeout=3)
    try:
        con.execute('PRAGMA query_only=ON');con.execute('BEGIN')
        names=('customers','google_business_bindings','google_business_onboarding_catalogs','google_business_onboarding_requests','google_business_onboarding_batches','google_business_onboarding_items')
        values={name:con.execute('SELECT count(*) FROM '+name).fetchone()[0] for name in names}
        values['active_google_bindings']=con.execute('SELECT count(*) FROM google_business_bindings WHERE active=1').fetchone()[0]
        return values
    finally:con.close()

def sample():
    module,flow,inventory=dependencies();_,_,_,wrapper,deployed=_CACHE;m=flow.m;current=m.inspect('t24-crm')
    need(current['State']['Running'] is True and m.runtime(current)==RUNTIME,'EXACT_CURRENT_CONFIGURED_RUNTIME_REQUIRED')
    environment,ops=flow.environment(current);flow.ctx.workflow.pf.google_environment(current);m.verify_secret_mount(current);m.verify_production_worker_enabled(current);m.retained().require_safe_original_restart(current)
    need(m.inventory(RUNTIME['id'])==inventory,'CURRENT419_BACKEND_SOURCE_DRIFT')
    need(m.schema_signature(m.BUSINESS,REVISION)==SCHEMA,'EXACT_CURRENT162_SCHEMA_REQUIRED')
    need(flow.safe.safe_private_boundary(m,flow.pins)==wrapper.proof['private_boundary'],'PRIVATE_BOUNDARY_DRIFT')
    credentials={'ops':flow.safe.protected_metadata(flow.c.ENV_FILE),'google':flow.safe.protected_metadata(flow.safe.GBP_ENV),'meta_read':flow.safe.protected_metadata(flow.ctx.workflow.core.ENV_FILE),'meta_legacy':flow.safe.protected_metadata(flow.ctx.workflow.core.LEGACY_ENV_FILE)}
    need(credentials==wrapper.proof['credential_metadata'] and m.credential_boundary()==wrapper.proof['credential_boundary'],'EXISTING_CREDENTIAL_METADATA_DRIFT')
    wrapper.nginx(True);rows=flow.retained.evidence(flow.rows());need(len(rows)==162,'EXACT_ALL162_TABLES_REQUIRED')
    public=m.verify_public(PUBLIC,wrapper.manifest);need(public==deployed['public_inventory_sha256'],'EXACT_CURRENT_MOBILE_STATIC_REQUIRED')
    row=m.BUSINESS.stat();need([row.st_dev,row.st_ino]==wrapper.proof['database_identity'],'EXACT_CURRENT_DATABASE_IDENTITY_REQUIRED')
    return {'stage':'MEDIA_WORKSPACE_SCALE_READONLY_PREFLIGHT','host':HOST,'source_sha':SOURCE,'static_source_sha':STATIC_SOURCE,'frontend_version':FRONTEND,'schema_revision':REVISION,'deployed_receipt_sha256':DEPLOYED,'crm':m.runtime(current),'environment_sha256':environment,'ops_environment_sha256':ops,'schema_sha256':SCHEMA,'rows':rows,'database_identity':[row.st_dev,row.st_ino],'database_metadata':flow.metadata(m.BUSINESS),'business_markers':markers(m.BUSINESS),'backend_inventory':inventory,'backend_inventory_sha256':digest(inventory),'backend_file_count':len(inventory),'backend_changed_before':{name:inventory[name] for name in sorted(BACKEND_FILES)},'credential_boundary':wrapper.proof['credential_boundary'],'credential_metadata':credentials,'private_boundary':wrapper.proof['private_boundary'],'public_root':str(PUBLIC),'public_inventory_sha256':public,'nginx_sha256':H(m.NGINX.read_bytes()),'active_nginx_sha256':H(m.run(['nginx','-T'],'ACTIVE_NGINX_REQUIRED')),'content_security_policy_sha256':CSP,'all162_current_tables_preserved':True,'google_scheduler_enabled':True,'google_scheduler_activation_from':'2026-10-30T19:42:04Z','ops_execution_enabled':False,'ops_scheduler_enabled':False,'existing_asset_worker_enabled':True,'onboarding_worker_default_enabled':True,'business_writes':False,'provider_requests':False,'credential_file_content_read':False,'private_content_read':False,'runtime_changed':False,'schema_changed':False,'permissions_changed':False}

def stable(first,second,retained):
    retained.live_sequence_boundary(first['database_metadata'],second['database_metadata'])
    need({**second,'database_metadata':first['database_metadata']}==first,'CURRENT162_BOUNDARIES_CHANGED_DURING_CAPTURE')

def capture():
    first=sample();second=sample();_,flow,_=dependencies();stable(first,second,flow.retained)
    body=encoded(second);sha=H(body);path=ROOT/('media-workspace-scale-preflight-'+sha[:12]+'.json')
    if path.exists():read(path,sha)
    else:
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as f:f.write(body);f.flush();os.fsync(f.fileno())
    keep=('host','source_sha','static_source_sha','frontend_version','schema_revision','deployed_receipt_sha256','crm','environment_sha256','ops_environment_sha256','schema_sha256','database_identity','business_markers','backend_inventory_sha256','backend_file_count','backend_changed_before','public_root','public_inventory_sha256','nginx_sha256','active_nginx_sha256','content_security_policy_sha256','all162_current_tables_preserved','google_scheduler_enabled','google_scheduler_activation_from','ops_execution_enabled','ops_scheduler_enabled','existing_asset_worker_enabled','onboarding_worker_default_enabled')
    result={'stage':'MEDIA_WORKSPACE_SCALE_PREFLIGHT_CAPTURED','sha256':sha,'path':str(path),'bytes':len(body),'table_count':162,'rows_sha256':digest(second['rows']),**{key:second[key] for key in keep},'two_stable_samples_verified':True,'schema_changed':False,'permissions_changed':False,'business_writes':False,'provider_requests':False,'credential_file_content_read':False,'private_content_read':False,'runtime_changed':False}
    need(len(json.dumps(result).encode())<10000,'BOUNDED_AGGREGATE_CAPTURE_REQUIRED');return result

def main():
    resource.setrlimit(resource.RLIMIT_CORE,(0,0));os.umask(0o077)
    need(os.geteuid()==0 and socket.gethostname()==HOST,'EXACT_ROOT_SERVER_REQUIRED');print(json.dumps(capture(),sort_keys=True))
if __name__=='__main__':
    try:main()
    except Exception as error:
        value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',value) else 'MEDIA_WORKSPACE_SCALE_CAPTURE_REJECTED'
        print(json.dumps({'stage':'MEDIA_WORKSPACE_SCALE_CAPTURE_REJECTED','code':code},sort_keys=True));raise SystemExit(1)
