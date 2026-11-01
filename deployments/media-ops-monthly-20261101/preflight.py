"""Configured monthly-content baseline: all existing data and authority preserved.

Only the new protected aggregate receipt is written. Existing credentials and
private database contents are never opened; no provider or business mutation.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import socket
import stat
from types import ModuleType, SimpleNamespace

HOST='iZj6c4cj7edgnhdimts4l7Z'
SOURCE='5a904dd925f03296c07018f83e97277f5f90dd08'
FRONTEND='42de3d4757db'
REVISION='cefa9b12a358'
OLD=Path('/opt/t24-crm/releases/media-ops-merchant-view-5a904dd925f0-20261101')
RELEASE_SHA='485ac303342b486a589697d514ee7a1b7bb237bf23b61585d4eb32197b8398c4'
DEPLOYED_SHA='48938f84d097d4938652218fe405a464d6f7dd5737e3bf8e590e8aeab74d0f16'
PREPARED_SHA='572d0848eafb8eb17d79167452ca971cfd82156de646d046a1131dd89bf20cc9'
MANIFEST_SHA='83abbc803879894490afbdc4836d19d82bd90df0580d94109619f0478a71fa8b'
PAYLOAD_SHA='3bd98d9ea2ab84f81cf4f5e48399d36fba5ceec3e2bf53ffce1e308f0edae6b9'
OLD_PREFLIGHT_SHA='1f47d56afc3c79de9b905ad5d95a0e15617a3ca53c934fb2e8a1d24327a7ead9'
RUNTIME={'id':'199e8a448aa3e93a5347f1e93cb3e98600c8433fa18098f7b546a3d63f6eaa03',
    'config':'0917719968304d79f94c6023c6b7f807bd5cfddef9a7982b7e3631a49d425b48',
    'image':'sha256:af0ba571d5b5a2dc46187c7083be17162803b4d98f8d45347c5da2b0f4378479',
    'restart':0,'started':'2026-11-01T02:31:21.827377617Z'}
ROOT=Path('/opt/t24-crm/releases')
BACKEND_OVERLAY=frozenset({'models/media_monthly.py','services/media_monthly.py','schemas/media_monthly.py','routers/media_monthly.py','alembic/versions/df0ba123b469_media_monthly.py'})
H=lambda body:hashlib.sha256(body).hexdigest()
_CACHE=None


def need(value,code):
    if not value:raise RuntimeError(code)


def digest(value):return H(json.dumps(value,sort_keys=True,separators=(',',':')).encode())


def protected(path,sha):
    for parent in path.parents:
        row=parent.lstat();need(parent.resolve()==parent and stat.S_ISDIR(row.st_mode) and row.st_uid==0 and not row.st_mode&0o022,'PROTECTED_SOURCE_PARENT_REQUIRED')
    before=path.lstat();need(path.resolve()==path and stat.S_ISREG(before.st_mode) and before.st_uid==0 and before.st_nlink==1 and stat.S_IMODE(before.st_mode)==0o600,'ROOT_PRIVATE_SOURCE_REQUIRED')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as stream:opened=os.fstat(stream.fileno());body=stream.read(131073)
    fields=lambda row:(row.st_dev,row.st_ino,row.st_size,row.st_mtime_ns,row.st_ctime_ns,row.st_uid,row.st_mode,row.st_nlink)
    need(fields(before)==fields(opened)==fields(path.lstat()) and len(body)<=131072 and H(body)==sha,'EXACT_PROTECTED_SOURCE_BYTES_REQUIRED');return body


def dependencies():
    global _CACHE
    need(os.geteuid()==0 and socket.gethostname()==HOST,'EXACT_ROOT_SERVER_REQUIRED');resource.setrlimit(resource.RLIMIT_CORE,(0,0));os.umask(0o077)
    body=protected(OLD/'release.py',RELEASE_SHA)
    if _CACHE is None:
        module=ModuleType('_monthly_content_deployed_read_polish');module.__file__=str(OLD/'release.py');exec(compile(body,module.__file__,'exec'),module.__dict__)
        need(module.SOURCE_SHA==SOURCE and module.FRONTEND==FRONTEND and module.SCHEMA_REVISION==REVISION,'EXACT_CURRENT_DEPLOYED_SOURCE_REQUIRED')
        args=SimpleNamespace(release=OLD,manifest_sha256=MANIFEST_SHA,payload_sha256=PAYLOAD_SHA,
            preflight=ROOT/('media-ops-merchant-view-preflight-'+OLD_PREFLIGHT_SHA[:12]+'.json'),preflight_sha256=OLD_PREFLIGHT_SHA,review_sha256=PREPARED_SHA)
        flow=module.Release(args);c=flow.c
        deployed=c.strict_json(c.read(OLD/'deployed.json',sha=DEPLOYED_SHA));prepared=c.strict_json(c.read(OLD/'prepared.json',sha=PREPARED_SHA))
        need(deployed['stage']=='MEDIA_OPS_MERCHANT_VIEW_DEPLOYED' and deployed['source_sha']==SOURCE and deployed['frontend_version']==FRONTEND and deployed['crm']==RUNTIME and deployed['schema_revision']==REVISION and deployed['table_count']==150,'EXACT_CONFIGURED_DEPLOYMENT_RECEIPT_REQUIRED')
        need(all(deployed[key] is True for key in ('all150_rows_schema_preserved','existing_full_environment_preserved','existing_ops_credentials_preserved','private_boundary_preserved','old_meta_google_cutoff_preserved')) and
             all(deployed[key] is False for key in ('operations_execution_enabled','operations_scheduler_enabled','schema_changed','database_restored','provider_requests','credentials_journaled')),'EXACT_PRESERVED_AUTHORITY_AND_DATA_RECEIPT_REQUIRED')
        inventory=c.strict_json(c.read(OLD/'backend-candidate-inventory.json',sha=prepared['candidate_inventory_sha256']))
        _CACHE=(module,flow,inventory)
    return _CACHE


def sample():
    module,flow,inventory=dependencies();m=flow.m;c=flow.c;current=m.inspect('t24-crm')
    need(current['State']['Running'] is True and m.runtime(current)==RUNTIME,'EXACT_CURRENT_CONFIGURED_RUNTIME_REQUIRED')
    environment_sha,ops_sha=flow.environment(current)
    flow.ctx.workflow.pf.google_environment(current);m.verify_secret_mount(current);m.verify_production_worker_enabled(current);m.retained().require_safe_original_restart(current)
    flow.source_boundary(current,inventory);flow.protections(updated=True,recovery=True)
    rows=flow.retained.evidence(flow.rows());need(len(rows)==150,'EXACT_ALL150_POPULATED_TABLES_REQUIRED')
    need(all(name not in inventory for name in BACKEND_OVERLAY),'MONTHLY_CONTENT_RUNTIME_MUST_START_ABSENT')
    # Every credential check below is metadata only. The full existing Env is
    # validated in server memory and represented outside the process by hashes.
    old=flow.ctx.workflow
    credentials={'ops':flow.safe.protected_metadata(c.ENV_FILE),'google':flow.safe.protected_metadata(flow.safe.GBP_ENV),
        'meta_read':flow.safe.protected_metadata(old.core.ENV_FILE),'meta_legacy':flow.safe.protected_metadata(old.core.LEGACY_ENV_FILE)}
    return {'stage':'MEDIA_OPS_MONTHLY_READONLY_PREFLIGHT','host':HOST,'source_sha':SOURCE,'frontend_version':FRONTEND,'schema_revision':REVISION,
        'deployed_receipt_sha256':DEPLOYED_SHA,'crm':m.runtime(current),'environment_sha256':environment_sha,'ops_environment_sha256':ops_sha,
        'schema_sha256':m.schema_signature(m.BUSINESS,REVISION),'rows':rows,'database_identity':flow.proof['database_identity'],'database_metadata':flow.metadata(m.BUSINESS),
        'backend_inventory':inventory,'backend_inventory_sha256':digest(inventory),'backend_file_count':len(inventory),'backend_changed_before':{name:inventory.get(name) for name in sorted(BACKEND_OVERLAY)},
        'credential_boundary':m.credential_boundary(),'credential_metadata':credentials,'private_boundary':flow.proof['private_boundary'],
        'public_root':str(flow.public),'public_inventory_sha256':m.verify_public(flow.public,flow.manifest),'nginx_sha256':H(m.NGINX.read_bytes()),
        'active_nginx_sha256':H(m.run(['nginx','-T'],'ACTIVE_NGINX_REQUIRED')),'content_security_policy_sha256':flow.proof['content_security_policy_sha256'],
        'all150_populated_tables_preserved':True,'ops_execution_enabled':False,'ops_scheduler_enabled':False,'google_scheduler_enabled':True,'google_scheduler_activation_from':'2026-10-30T19:42:04Z',
        'schema_changed':False,'permissions_changed':False,'credential_file_content_read':False,'private_content_read':False,'business_writes':False,'provider_requests':False,'runtime_changed':False}


def capture():
    first=sample();current=sample();module,flow,inventory=dependencies();c=flow.c
    flow.retained.live_sequence_boundary(first['database_metadata'],current['database_metadata'])
    need({**current,'database_metadata':first['database_metadata']}==first,'CURRENT_ALL150_BOUNDARIES_CHANGED_DURING_CAPTURE')
    body=(json.dumps(current,sort_keys=True,indent=2)+'\n').encode();sha=H(body);path=ROOT/('media-ops-monthly-preflight-'+sha[:12]+'.json')
    if path.exists():c.read(path,sha=sha)
    else:c.write(path,body)
    keys=('host','source_sha','frontend_version','schema_revision','deployed_receipt_sha256','crm','environment_sha256','ops_environment_sha256','schema_sha256',
        'backend_inventory_sha256','backend_file_count','backend_changed_before','public_root','public_inventory_sha256','nginx_sha256','active_nginx_sha256','content_security_policy_sha256',
        'all150_populated_tables_preserved','ops_execution_enabled','ops_scheduler_enabled','google_scheduler_enabled','google_scheduler_activation_from')
    return {'stage':'MEDIA_OPS_MONTHLY_PREFLIGHT_CAPTURED','sha256':sha,'path':str(path),'bytes':len(body),'table_count':150,'rows_sha256':digest(current['rows']),
        **{key:current[key] for key in keys},'schema_changed':False,'permissions_changed':False,'credential_file_content_read':False,'private_content_read':False,'business_writes':False,'provider_requests':False,'runtime_changed':False}


if __name__=='__main__':
    try:print(json.dumps(capture(),sort_keys=True))
    except BaseException as exc:
        value=str(exc);code=value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',value) else 'MONTHLY_CONTENT_PREFLIGHT_REJECTED';print(json.dumps({'stage':'MONTHLY_CONTENT_PREFLIGHT_REJECTED','code':code}));raise SystemExit(1)
