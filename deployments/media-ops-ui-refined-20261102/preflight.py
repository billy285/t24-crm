"""Read-only immutable boundary for a static-only navigation release.

Loads the exact published navigation-static graph once. No legacy sample(),
business-row hash, worker action, database write, provider or credential export.
"""
import hashlib,json,os,re,resource,socket,stat,types
from pathlib import Path
HOST='iZj6c4cj7edgnhdimts4l7Z'
ROOT=Path('/opt/t24-crm/releases')
OLD=ROOT/'media-navigation-sticky-68fa8589101f-20261102'
HELPER='eba0044e3ab176be9cd7235da48cb41d67d2940c617e226f30c80d6eeb756181'
PREPARED='1958c97791a8785ed95e65f6548486f761a09b8c9fddd561ec432e7571e31e4d'
DEPLOYED='a921c62e832ed0ede42409f3dab590303bfb5547af06addf7d30c2468c5bd5e4'
MANIFEST='b4139c1fb240c7a6d1bfe913be1b78aabba3457c1fa9543304dbe29b3dade0bf'
PAYLOAD='7b5b12340dcedcaf52260db4296e15e75c6043d7a36f028389ed752ff747c73f'
OLD_BASELINE='6c8dcf5954a5ccac79b323dc40a67e001034e232d27505a55d101c451a103216'
SOURCE='68fa8589101f4a3075141c910ec51fd86b9ec9ed'
FRONTEND='6f71217e47f1'
BACKEND_SOURCE='54e027aad00e81a4ebb747ada1299e7a10e1ec52'
HEAD='i54af678a914'
SCHEMA='7eb5fb2bee9bc5523e20bddca16542b2f465a715c073c20c8551d40aa63ec2b4'
NGINX='a8cbd5556d10436ef38351c075d87c1a98253ed766f5289f911aec703b8c007d'
CSP='ead64b09efe8c4f35648aa8eafe8855c5268ecf0999e0918b3642dd9dfbfe7a6'
PUBLIC='/var/www/t24-crm-public/media-navigation-sticky-68fa8589101f-20261102'
STATIC='23de6e842828ec137b75abbdf36663b77f1c3f2a69f59970c5dbbacb2a5caa30'
RUNTIME={'config':'e910c0852b1a2dbe12474ed55040544feb85dc3dfd037ef603c94d86bea5b84a','id':'6f826ade371a37fbf405c2e90ee405abb4e7d5ad5c9344139cb65a46596e5757','image':'sha256:1b6caabf90c809def8e180811336ebdc12e49305ad0f11bf4126730790d09bee','restart':0,'started':'2026-11-02T07:13:16.110095163Z'}
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
    if _CACHE is None:
        module=types.ModuleType('_refined_published_static_once');module.__file__=str(OLD/'release.py');exec(compile(read(OLD/'release.py',HELPER,131072),module.__file__,'exec'),module.__dict__)
        need(module.SOURCE_SHA==SOURCE and module.FRONTEND==FRONTEND and module.BASE_SOURCE==BACKEND_SOURCE and module.HEAD==HEAD,'EXACT_PUBLISHED_STATIC_SOURCE_REQUIRED')
        args=types.SimpleNamespace(phase='recover',release=OLD,manifest_sha256=MANIFEST,payload_sha256=PAYLOAD,preflight=ROOT/('media-navigation-sticky-baseline-'+OLD_BASELINE[:12]+'.json'),preflight_sha256=OLD_BASELINE,review_sha256=PREPARED)
        previous=module.Release(args);prepared=previous.reviewed();deployed=module.strict_json(read(OLD/'deployed.json',DEPLOYED))
        need(deployed['stage']=='MEDIA_NAVIGATION_STICKY_STATIC_DEPLOYED' and deployed['source_sha']==SOURCE and deployed['backend_source_sha']==BACKEND_SOURCE and deployed['frontend_version']==FRONTEND and deployed['runtime']==RUNTIME and deployed['prepared_sha256']==PREPARED and deployed['static_only'] is True and all(deployed[k] is False for k in ('database_writes','schema_changes','container_restarts','environment_changes','permissions_changes','provider_or_publication_actions')),'EXACT_PREVIOUS_STATIC_DEPLOYMENT_REQUIRED')
        ctx=previous.ctx;inventory=previous.inventory;need(len(inventory)==432,'EXACT432_BACKEND_SOURCE_REQUIRED');_CACHE=(module,ctx,inventory,deployed,previous)
    return _CACHE[:4]
def credential_metadata(ctx):
    c=ctx.base.c
    return {'ops':c.safe.protected_metadata(c.c.ENV_FILE),'google':c.safe.protected_metadata(c.safe.GBP_ENV),'meta_read':c.safe.protected_metadata(c.ctx.workflow.core.ENV_FILE),'meta_legacy':c.safe.protected_metadata(c.ctx.workflow.core.LEGACY_ENV_FILE)}
def sample():
    _,ctx,inventory,deployed=dependencies();previous=_CACHE[4];m=ctx.m;p=previous.proof;info=m.inspect('t24-crm');previous.boundary(updated=True);previous.public_check()
    need(info['State']['Running'] is True and m.runtime(info)==RUNTIME,'EXACT_CURRENT_RUNTIME_REQUIRED')
    private=ctx.base.c.safe.safe_private_boundary(m,ctx.base.c.pins);credentials=credential_metadata(ctx)
    need(private==p['private_boundary'] and credentials==p['credential_metadata'] and m.credential_boundary()==p['credential_boundary'],'EXACT_PRIVATE_CREDENTIAL_BOUNDARY_REQUIRED')
    need(str(previous.public)==PUBLIC and m.verify_public(previous.public,previous.manifest)==STATIC and H(m.NGINX.read_bytes())==NGINX,'EXACT_CURRENT_STATIC_NGINX_REQUIRED')
    definitions=ctx.definitions();need(len([v for v in definitions if v[0]=='table'])==169 and m.schema_signature(m.BUSINESS,HEAD)==SCHEMA,'EXACT169_SCHEMA_REQUIRED')
    meta=ctx.metadata();active=H(m.run(['nginx','-T'],'ACTIVE_NGINX_READ_FAILED'))
    return {'stage':'MEDIA_OPS_UI_REFINED_READONLY_BASELINE','source_sha':SOURCE,'backend_source_sha':BACKEND_SOURCE,'frontend_version':FRONTEND,'schema_revision':HEAD,'crm':RUNTIME,'backend_inventory':inventory,'backend_inventory_sha256':digest(inventory),'backend_file_count':432,'table_count':169,'table_definitions':definitions,'schema_sha256':SCHEMA,'database_identity':p['database_identity'],'database_pragmas_sha256':meta['pragma_sha256'],'sequence_table_exists':meta['sequence_exists'],'environment_sha256':p['environment_sha256'],'ordered_environment_sha256':p['ordered_environment_sha256'],'ops_environment_sha256':p['ops_environment_sha256'],'credential_boundary':p['credential_boundary'],'credential_metadata':credentials,'private_boundary':private,'public_root':PUBLIC,'public_inventory_sha256':STATIC,'nginx_sha256':NGINX,'active_nginx_sha256':active,'content_security_policy_sha256':CSP,'monthly_auto_prep_enabled':True,'google_scheduler_enabled':True,'google_scheduler_activation_from':'2026-10-30T19:42:04Z','meta_execution_enabled':False,'meta_scheduler_enabled':False,'old_flags_preserved':True,'business_rows_read_or_frozen':False,'business_writes':False,'provider_requests':False,'credentials_exported':False,'private_content_exported':False,'runtime_changed':False,'schema_changed':False}
def stable(first,second):need(first==second,'IMMUTABLE_STATIC_BOUNDARIES_CHANGED')
def capture():
    first=sample();second=sample();stable(first,second);body=encoded(second);sha=H(body);path=ROOT/('media-ops-ui-refined-baseline-'+sha[:12]+'.json')
    if path.exists():read(path,sha)
    else:
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as f:f.write(body);f.flush();os.fsync(f.fileno())
    keys=('source_sha','backend_source_sha','frontend_version','schema_revision','crm','backend_inventory_sha256','backend_file_count','table_count','schema_sha256','database_identity','database_pragmas_sha256','environment_sha256','ordered_environment_sha256','ops_environment_sha256','public_root','public_inventory_sha256','nginx_sha256','active_nginx_sha256','content_security_policy_sha256','monthly_auto_prep_enabled','google_scheduler_enabled','google_scheduler_activation_from','meta_execution_enabled','meta_scheduler_enabled','old_flags_preserved')
    result={'stage':'MEDIA_OPS_UI_REFINED_BASELINE_CAPTURED','sha256':sha,'path':str(path),'bytes':len(body),'immutable_two_samples_verified':True,**{k:second[k] for k in keys},'business_rows_read_or_frozen':False,'business_writes':False,'provider_requests':False,'credentials_exported':False,'private_content_exported':False,'runtime_changed':False,'schema_changed':False};need(len(json.dumps(result).encode())<12000,'BOUNDED_AGGREGATE_CAPTURE_REQUIRED');return result
def main():
    resource.setrlimit(resource.RLIMIT_CORE,(0,0));os.umask(0o077);print(json.dumps(capture(),sort_keys=True))
if __name__=='__main__':
    try:main()
    except BaseException as e:
        v=str(e);code=v if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',v) else 'MEDIA_OPS_UI_REFINED_CAPTURE_REJECTED';print(json.dumps({'stage':'MEDIA_OPS_UI_REFINED_CAPTURE_REJECTED','code':code,'business_writes':False},sort_keys=True));raise SystemExit(1)
