"""Read-only immutable boundary for a static-only navigation release.

Loads the exact published unified-settings graph once. No legacy sample(),
business-row hash, worker action, database write, provider or credential export.
"""
import hashlib,json,os,re,resource,socket,stat,types
from pathlib import Path
HOST='iZj6c4cj7edgnhdimts4l7Z'
ROOT=Path('/opt/t24-crm/releases')
OLD=ROOT/'media-unified-settings-54e027aad00e-20261102'
HELPER='b9d954130b99802bf444fe1ce99b73ba869c21ca95d1387ebb6d124d06ea109e'
PREPARED='c96bb2707cfd7c1c83a0bc01e7e17671a5997b20f09d27b44bbb42801ab91482'
DEPLOYED='b5d270391535704c36a756a8d1a3b8f0cf0c1e7e312ceb64ba64fd842b09d68d'
MANIFEST='0292d5bf251f16b03bfb0692942715c0cd304f998fe644211b95e780433341e3'
PAYLOAD='64537d65fbdf9b8f249d004f6639e9d2d7b5c28ac14bf43f256cee3cdf442439'
OLD_BASELINE='0dd43fefcf43ee7c925cbf825b3d88fb125abe1168f3adde9478ba603205dc83'
SOURCE='54e027aad00e81a4ebb747ada1299e7a10e1ec52'
FRONTEND='32a580644502'
HEAD='i54af678a914'
SCHEMA='7eb5fb2bee9bc5523e20bddca16542b2f465a715c073c20c8551d40aa63ec2b4'
NGINX='e03166467fa1e953847b0d9bb9a16f9e34e5784367363d35e63886554c42ee7e'
CSP='ead64b09efe8c4f35648aa8eafe8855c5268ecf0999e0918b3642dd9dfbfe7a6'
PUBLIC='/var/www/t24-crm-public/media-unified-settings-54e027aad00e-20261102'
STATIC='3466c4ca6dda8f946d13586c5cf64815809892abaf9fb5901779a8db096df274'
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
        module=types.ModuleType('_navigation_published_unified_once');module.__file__=str(OLD/'release.py');exec(compile(read(OLD/'release.py',HELPER,131072),module.__file__,'exec'),module.__dict__)
        need(module.SOURCE_SHA==SOURCE and module.FRONTEND==FRONTEND and module.NEW_REVISION==HEAD,'EXACT_PUBLISHED_UNIFIED_SOURCE_REQUIRED')
        args=types.SimpleNamespace(phase='recover',release=OLD,manifest_sha256=MANIFEST,payload_sha256=PAYLOAD,preflight=ROOT/('media-unified-settings-baseline-'+OLD_BASELINE[:12]+'.json'),preflight_sha256=OLD_BASELINE,review_sha256=PREPARED)
        ctx=module.Release(args);prepared,old=ctx.reviewed(recovery=True);deployed=module.strict_json(read(OLD/'deployed.json',DEPLOYED))
        need(deployed['stage']=='MEDIA_UNIFIED_SETTINGS_DEPLOYED' and deployed['source_sha']==SOURCE and deployed['frontend_version']==FRONTEND and deployed['schema_revision']==HEAD and deployed['table_count']==169 and deployed['crm']==RUNTIME and deployed['prepared_sha256']==PREPARED and deployed['all_worker_flags_environment_credentials_private_preserved'] is True,'EXACT_DEPLOYED_UNIFIED_PROOF_REQUIRED')
        inventory={**ctx.inventory,**module.BACKEND_AFTER};need(len(inventory)==432,'EXACT432_BACKEND_SOURCE_REQUIRED');_CACHE=(module,ctx,inventory,deployed)
    return _CACHE
def credential_metadata(ctx):
    c=ctx.base.c
    return {'ops':c.safe.protected_metadata(c.c.ENV_FILE),'google':c.safe.protected_metadata(c.safe.GBP_ENV),'meta_read':c.safe.protected_metadata(c.ctx.workflow.core.ENV_FILE),'meta_legacy':c.safe.protected_metadata(c.ctx.workflow.core.LEGACY_ENV_FILE)}
def sample():
    module,ctx,inventory,deployed=dependencies();m=ctx.m;p=ctx.proof;c=ctx.base.c;info=m.inspect('t24-crm')
    need(info['State']['Running'] is True and m.runtime(info)==RUNTIME and m.inventory(info['Id'])==inventory,'EXACT_CURRENT432_RUNTIME_SOURCE_REQUIRED');ctx.environment(info);env,ordered=ctx.pf.environment(ctx.base,info)
    private=c.safe.safe_private_boundary(m,c.pins);credentials=credential_metadata(ctx)
    need(private==p['private_boundary'] and credentials==p['credential_metadata'] and m.credential_boundary()==p['credential_boundary'],'EXACT_PRIVATE_CREDENTIAL_BOUNDARY_REQUIRED')
    ctx.immutable(migrated=True,updated=True,recovery=True);ctx.writer_census((info['Id'],))
    need(str(ctx.public)==PUBLIC and m.verify_public(ctx.public,ctx.manifest)==STATIC and H(m.NGINX.read_bytes())==NGINX,'EXACT_CURRENT_STATIC_NGINX_REQUIRED')
    active=ctx.nginx(updated=True);ctx.base.staticmod.public_security_policy(m,CSP)
    definitions=ctx.definitions();need(len([v for v in definitions if v[0]=='table'])==169 and m.schema_signature(m.BUSINESS,HEAD)==SCHEMA,'EXACT169_SCHEMA_REQUIRED')
    meta=ctx.metadata();return {'stage':'MEDIA_NAVIGATION_STICKY_READONLY_BASELINE','source_sha':SOURCE,'frontend_version':FRONTEND,'schema_revision':HEAD,'crm':RUNTIME,'backend_inventory':inventory,'backend_inventory_sha256':digest(inventory),'backend_file_count':432,'table_count':169,'table_definitions':definitions,'schema_sha256':SCHEMA,'database_identity':p['database_identity'],'database_pragmas_sha256':meta['pragma_sha256'],'sequence_table_exists':meta['sequence_exists'],'environment_sha256':env,'ordered_environment_sha256':ordered,'ops_environment_sha256':p['ops_environment_sha256'],'credential_boundary':p['credential_boundary'],'credential_metadata':credentials,'private_boundary':private,'public_root':PUBLIC,'public_inventory_sha256':STATIC,'nginx_sha256':NGINX,'active_nginx_sha256':active,'content_security_policy_sha256':CSP,'monthly_auto_prep_enabled':True,'google_scheduler_enabled':True,'google_scheduler_activation_from':'2026-10-30T19:42:04Z','meta_execution_enabled':False,'meta_scheduler_enabled':False,'old_flags_preserved':True,'business_rows_read_or_frozen':False,'business_writes':False,'provider_requests':False,'credentials_exported':False,'private_content_exported':False,'runtime_changed':False,'schema_changed':False}
def stable(first,second):need(first==second,'IMMUTABLE_STATIC_BOUNDARIES_CHANGED')
def capture():
    first=sample();second=sample();stable(first,second);body=encoded(second);sha=H(body);path=ROOT/('media-navigation-sticky-baseline-'+sha[:12]+'.json')
    if path.exists():read(path,sha)
    else:
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as f:f.write(body);f.flush();os.fsync(f.fileno())
    keys=('source_sha','frontend_version','schema_revision','crm','backend_inventory_sha256','backend_file_count','table_count','schema_sha256','database_identity','database_pragmas_sha256','environment_sha256','ordered_environment_sha256','ops_environment_sha256','public_root','public_inventory_sha256','nginx_sha256','active_nginx_sha256','content_security_policy_sha256','monthly_auto_prep_enabled','google_scheduler_enabled','google_scheduler_activation_from','meta_execution_enabled','meta_scheduler_enabled','old_flags_preserved')
    result={'stage':'MEDIA_NAVIGATION_STICKY_BASELINE_CAPTURED','sha256':sha,'path':str(path),'bytes':len(body),'immutable_two_samples_verified':True,**{k:second[k] for k in keys},'business_rows_read_or_frozen':False,'business_writes':False,'provider_requests':False,'credentials_exported':False,'private_content_exported':False,'runtime_changed':False,'schema_changed':False};need(len(json.dumps(result).encode())<12000,'BOUNDED_AGGREGATE_CAPTURE_REQUIRED');return result
def main():
    resource.setrlimit(resource.RLIMIT_CORE,(0,0));os.umask(0o077);print(json.dumps(capture(),sort_keys=True))
if __name__=='__main__':
    try:main()
    except BaseException as e:
        v=str(e);code=v if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',v) else 'MEDIA_NAVIGATION_STICKY_CAPTURE_REJECTED';print(json.dumps({'stage':'MEDIA_NAVIGATION_STICKY_CAPTURE_REJECTED','code':code,'business_writes':False},sort_keys=True));raise SystemExit(1)
