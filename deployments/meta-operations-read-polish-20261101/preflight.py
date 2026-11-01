"""Current configured Publisher read-only baseline; preserve every populated table.

This is a UI/read-parser followup, with no schema or environment change. It
does not reuse the original new-table-empty release checks or any key rotation.
"""
import hashlib
import json
from pathlib import Path
import re
import resource
import os
import socket
import stat
from types import ModuleType

HOST = 'iZj6c4cj7edgnhdimts4l7Z'
SOURCE = '95588aa2e630784a419704bb4ce3da89965586e6'
FRONTEND = 'd2dbd67fa15d'
REVISION = 'cefa9b12a358'
ACTIVATION_ROOT = Path('/opt/t24-crm/releases/meta-operations-activation-20261101')
TOOLS = ACTIVATION_ROOT/'tools-activation-v1'
CORE_SHA = '72e5e12b6bf6b1415ffc35d5f8c43676972964338f889c3b4fcfe102ad95539e'
BASELINE_SHA = '82f015a1c49798c8659f72c12a639518e358c150c0a6234133dd8c7d918a1941'
ACTIVATED_SHA = '00309f7c36fb6111ca41eff91009bfa47570eec14650c0de9aab085a6cc10933'
CREDENTIAL_RECEIPT_SHA = 'ffb023fdd68ae490cad33b42a525ec13debedd91c9c3944afbc90607b97b4241'
PREPARED_SHA = 'e2c7846fa5b497320860494751cb3907d1a54fbedf8d0b6b60681c4f8837ac05'
RUNTIME = {'id':'b9f7e2f4ee0c86fe6d40018b76eaa96ca8e63774250137575a9484cdd3cc1961',
    'config':'e6e375f809b35b4d3e60445f0e2e945489a15bdb31cadad3c20c6ff0b15f7d95',
    'image':'sha256:4797556daa7b98dbeeae6c31364d4f3411645c324902e0f8b922cf1180a7af53',
    'restart':0,'started':'2026-11-01T00:59:30.956352607Z'}
FULL_ENV_SHA = '3d414fb4b9b5b1ae9bb5ecc1ce503be3c788f8bee27d0806de9d72fd3df0e223'
OPS_ENV_FILE_SHA = '29244a8656a6228947e88500671f37b48dfebf4f01237135a6ea60ab0123b342'
ROOT = Path('/opt/t24-crm/releases')
H = lambda body:hashlib.sha256(body).hexdigest()
_CACHE = None


def need(value, code):
    if not value:raise RuntimeError(code)


def digest(value):return H(json.dumps(value,sort_keys=True,separators=(',',':')).encode())


def read_bootstrap(path,sha):
    for parent in path.parents:
        row=parent.lstat();need(parent.resolve()==parent and stat.S_ISDIR(row.st_mode) and row.st_uid==0 and not row.st_mode&0o022,'PROTECTED_BOOTSTRAP_PARENT_REQUIRED')
    before=path.lstat();need(path.resolve()==path and stat.S_ISREG(before.st_mode) and before.st_uid==0 and before.st_nlink==1 and stat.S_IMODE(before.st_mode)==0o600,'PROTECTED_BOOTSTRAP_REQUIRED')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as stream:opened=os.fstat(stream.fileno());body=stream.read(131073)
    after=path.lstat();fields=lambda row:(row.st_dev,row.st_ino,row.st_size,row.st_mtime_ns,row.st_ctime_ns,row.st_uid,row.st_mode,row.st_nlink)
    need(fields(before)==fields(opened)==fields(after) and len(body)<=131072 and H(body)==sha,'EXACT_BOOTSTRAP_BYTES_REQUIRED');return body


def dependencies():
    global _CACHE
    need(os.geteuid()==0 and socket.gethostname()==HOST,'EXACT_ROOT_SERVER_REQUIRED');resource.setrlimit(resource.RLIMIT_CORE,(0,0));os.umask(0o077)
    core_body=read_bootstrap(TOOLS/'core.py',CORE_SHA);baseline_body=read_bootstrap(TOOLS/'baseline.py',BASELINE_SHA)
    if _CACHE is None:
        c=ModuleType('_read_polish_existing_publisher_core');c.__file__=str(TOOLS/'core.py');exec(compile(core_body,c.__file__,'exec'),c.__dict__)
        b=ModuleType('_read_polish_existing_publisher_baseline');b.__file__=str(TOOLS/'baseline.py');exec(compile(baseline_body,b.__file__,'exec'),b.__dict__);b.configure(c)
        ctx=b.dependencies()
        activated=c.strict_json(c.read(ACTIVATION_ROOT/'activated.json',sha=ACTIVATED_SHA))
        prepared=c.strict_json(c.read(ACTIVATION_ROOT/'prepared.json',sha=PREPARED_SHA))
        credential=c.strict_json(c.read(ACTIVATION_ROOT/'credential-receipt.json',sha=CREDENTIAL_RECEIPT_SHA))
        need(activated['stage']=='META_OPERATIONS_PUBLISHER_RUNTIME_ACTIVATED' and activated['source_sha']==SOURCE and activated['frontend_version']==FRONTEND and activated['crm']==RUNTIME and
             activated['operations_execution_enabled'] is False and activated['operations_scheduler_enabled'] is False and activated['same_application_image'] is True,'EXACT_CONFIGURED_PUBLISHER_ACTIVATION_REQUIRED')
        need(prepared['expected_full_environment_sha256']==FULL_ENV_SHA and prepared['env_sha256']==credential['env_sha256']==OPS_ENV_FILE_SHA and credential['env_path']==str(c.ENV_FILE) and
             credential['independent_fernet_key_generated'] is True and credential['existing_read_credentials_preserved'] is True,'EXACT_INDEPENDENT_CREDENTIAL_RECEIPTS_REQUIRED')
        _CACHE=(c,b,ctx)
    return _CACHE


def environment(c,ctx,info):
    rows=info['Config']['Env'];values={}
    need(isinstance(rows,list),'EXACT_CURRENT_ENVIRONMENT_REQUIRED')
    for row in rows:
        need(isinstance(row,str) and '=' in row and not any(ch in row for ch in '\r\n\0'),'STRICT_ENVIRONMENT_ROW_REQUIRED')
        key,value=row.split('=',1);need(key not in values,'DUPLICATE_ENVIRONMENT_KEY_REJECTED');values[key]=value
    ops=[row for row in rows if row.split('=',1)[0].startswith('T24_META_OPS_')]
    old=[row for row in rows if not row.split('=',1)[0].startswith('T24_META_OPS_')]
    c.validate_ops_env(ops);old_values=c.old_environment(old)
    need(digest(rows)==FULL_ENV_SHA and digest(old)==ctx.workflow.proof['environment_sha256'],'ALL_CURRENT_ENVIRONMENT_VALUES_AND_ORDER_DRIFT')
    need(H(('\n'.join(ops)+'\n').encode('ascii'))==OPS_ENV_FILE_SHA,'EXACT_CURRENT_OPS_CREDENTIAL_VALUES_REQUIRED')
    need(values['T24_META_OPS_APP_SECRET']!=old_values['T24_META_APP_SECRET'] and all(values['T24_META_OPS_TOKEN_KEY']!=old_values.get(key) for key in ('T24_META_TOKEN_KEY','T24_GBP_TOKEN_KEY','MASK_KEY','PRIVATE_WORKSPACE_ENCRYPTION_KEY')),'INDEPENDENT_OPS_KEY_OR_APP_SECRET_DRIFT')
    return digest(rows),digest(ops)


def sample():
    c,b,ctx=dependencies();m=ctx.m;current=m.inspect('t24-crm')
    need(current['State']['Running'] is True and m.runtime(current)==RUNTIME,'EXACT_CONFIGURED_CURRENT_RUNTIME_REQUIRED')
    env_sha,ops_sha=environment(c,ctx,current)
    ctx.workflow.pf.google_environment(current);m.verify_secret_mount(current);m.verify_production_worker_enabled(current);m.retained().require_safe_original_restart(current);b.source(ctx,current)
    # _sample explicitly uses new_schema(empty=False) and recovery metadata;
    # it preserves every legitimate OAuth, grant, cache, request and draft row.
    protected=b._sample(ctx)
    need(len(protected['rows'])==150,'EXACT_ALL150_CURRENT_TABLES_REQUIRED')
    c.directory(c.SECRET_ROOT);row=c.ENV_FILE.lstat()
    need(c.ENV_FILE.resolve()==c.ENV_FILE and stat.S_ISREG(row.st_mode) and row.st_uid==0 and row.st_nlink==1 and stat.S_IMODE(row.st_mode)==0o600,'PROTECTED_EXISTING_OPS_CREDENTIAL_FILE_REQUIRED')
    return {**protected,'stage':'META_OPERATIONS_READ_POLISH_READONLY_PREFLIGHT','host':HOST,'source_sha':SOURCE,'frontend_version':FRONTEND,'schema_revision':REVISION,
        'activated_receipt_sha256':ACTIVATED_SHA,'crm':m.runtime(current),'environment_sha256':env_sha,'ops_environment_sha256':ops_sha,
        'backend_inventory_sha256':digest(ctx.inventory),'backend_file_count':len(ctx.inventory),'backend_changed_before':{'services/meta_operations_provider.py':ctx.inventory['services/meta_operations_provider.py']},
        'ops_credential_metadata':ctx.safe.protected_metadata(c.ENV_FILE),'all150_populated_tables_preserved':True,'ops_execution_enabled':False,'ops_scheduler_enabled':False,
        'credential_file_content_read':False,'private_content_read':False,'business_writes':False,'provider_requests':False,'runtime_changed':False}


def capture():
    first=sample();current=sample();c,b,ctx=dependencies()
    ctx.workflow.retained.live_sequence_boundary(first['database_metadata'],current['database_metadata'])
    need({**current,'database_metadata':first['database_metadata']}==first,'CURRENT_ALL150_BASELINE_CHANGED_DURING_CAPTURE')
    body=(json.dumps(current,sort_keys=True,indent=2)+'\n').encode();sha=H(body);path=ROOT/('meta-operations-read-polish-preflight-'+sha[:12]+'.json')
    if path.exists():c.read(path,sha=sha)
    else:c.write(path,body)
    keys=('host','source_sha','frontend_version','schema_revision','schema_sha256','activated_receipt_sha256','crm','environment_sha256','ops_environment_sha256',
        'backend_inventory_sha256','backend_file_count','backend_changed_before','nginx_sha256','active_nginx_sha256','public_root','public_inventory_sha256','content_security_policy_sha256',
        'all150_populated_tables_preserved','ops_execution_enabled','ops_scheduler_enabled')
    return {'stage':'META_OPERATIONS_READ_POLISH_PREFLIGHT_CAPTURED','path':str(path),'sha256':sha,'bytes':len(body),'table_count':150,'rows_sha256':digest(current['rows']),
        **{key:current[key] for key in keys},'credential_file_content_read':False,'private_content_read':False,'business_writes':False,'provider_requests':False,'runtime_changed':False}


if __name__=='__main__':
    try:print(json.dumps(capture(),sort_keys=True))
    except BaseException as exc:
        value=str(exc);code=value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',value) else 'META_OPERATIONS_READ_POLISH_PREFLIGHT_REJECTED'
        print(json.dumps({'stage':'META_OPERATIONS_READ_POLISH_PREFLIGHT_REJECTED','code':code}));raise SystemExit(1)
