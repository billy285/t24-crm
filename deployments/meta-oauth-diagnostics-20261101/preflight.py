"""Fresh active-Meta backend-only baseline. No credentials, rows or tokens exported."""
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import socket
import stat
import sys
import types

H=lambda body:hashlib.sha256(body).hexdigest()
HOST='iZj6c4cj7edgnhdimts4l7Z'
BASE_SOURCE='6cf69fbe4cbe8f13eb359df0fbae7f4fb7180729'
FRONTEND='58d2c585210f'
REVISION='bde8da01f247'
ACTIVATION_FROM='2026-10-30T19:42:04Z'
ORIGINAL_ID='f6dad7697bee46f2bfaae6afe651db5ce38e8c88ed86b24c1bb3200ca00b4333'
IMAGE='sha256:98ae650db11bc425d35204442e0444f2d421a56594507ec75f8aae97853cf084'
ACTIVATION_ROOT=Path('/opt/t24-crm/releases/meta-business-activation-6cf69fbe4cbe-20261101')
TOOLS=ACTIVATION_ROOT/'tools-activation-v1'
CORE_SHA='4df1106fd1bbcafeb895896ace72b7d285b92a955d618b11ed88ef05da108576'
BASELINE_SHA='0884eca1646e0891b9d2106282688bcb1fa9186807f470d8754f7f0fbf5655fb'
ACTIVATION_SHA='5bd8f623fb149cfec60c2c65e3f68468f02329db93501009f9a8182835dd5963'
ACTIVATED_SHA='f2a877800a85dcd08994dc726d5eb1248352121fe86ea5c3caf05bf2b5581a61'
CREDENTIAL_RECEIPT_SHA='c4814e82750849bd13f85747a2fe0e9b92ada0f5f610aa4311b78b3811a43dc7'
ENV_SHA='66d9d6664aea6e82397b63678ca1b1ec167afc458df2b76446febf58749fc520'
BACKEND_FILES=frozenset({'services/meta_business_provider.py','routers/meta_business.py'})
_CACHE=None


def need(ok,code):
    if not ok:raise RuntimeError(code)


def digest(value):return H(json.dumps(value,sort_keys=True,separators=(',',':')).encode())


def read(path,sha=None,maximum=1048576):
    row=path.lstat();need(path.resolve()==path and stat.S_ISREG(row.st_mode) and row.st_uid==0 and row.st_nlink==1 and stat.S_IMODE(row.st_mode)==0o600,'PROTECTED_SOURCE_OR_RECEIPT_REQUIRED')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as stream:opened=os.fstat(stream.fileno());body=stream.read(maximum+1)
    after=path.lstat();fields=lambda x:(x.st_dev,x.st_ino,x.st_size,x.st_mtime_ns,x.st_ctime_ns,x.st_uid,x.st_mode,x.st_nlink)
    need(fields(row)==fields(opened)==fields(after) and len(body)<=maximum and (sha is None or H(body)==sha),'EXACT_SOURCE_OR_RECEIPT_HASH_REQUIRED');return body


def load(path,sha,name):
    module=types.ModuleType(name);module.__file__=str(path)
    exec(compile(read(path,sha),str(path),'exec'),module.__dict__);return module


def dependencies():
    global _CACHE
    for name,sha in (('core.py',CORE_SHA),('baseline.py',BASELINE_SHA),('activation.py',ACTIVATION_SHA)):read(TOOLS/name,sha)
    if _CACHE is None:
        core=load(TOOLS/'core.py',CORE_SHA,'_meta_diagnostic_retained_core')
        baseline=load(TOOLS/'baseline.py',BASELINE_SHA,'_meta_diagnostic_retained_baseline');baseline.configure(core)
        activation=load(TOOLS/'activation.py',ACTIVATION_SHA,'_meta_diagnostic_retained_activation');activation.configure(core,baseline)
        ctx=baseline.dependencies();_CACHE=(core,baseline,activation,ctx)
    return _CACHE


def meta_environment(core,info):
    env=info['Config']['Env'];values={}
    for row in env:
        need(isinstance(row,str) and '=' in row and not any(char in row for char in '\r\n\0'),'STRICT_CURRENT_ENVIRONMENT_REQUIRED')
        key,value=row.split('=',1);need(key not in values,'DUPLICATE_CURRENT_ENV_KEY');values[key]=value
    meta=[row for row in env if row.split('=',1)[0].startswith('T24_META_')]
    parsed=core.validate_meta_env(meta)
    need(all(parsed['T24_META_TOKEN_KEY']!=values.get(key) for key in ('T24_GBP_TOKEN_KEY','MASK_KEY','PRIVATE_WORKSPACE_ENCRYPTION_KEY')),'CURRENT_META_KEY_MUST_REMAIN_INDEPENDENT')
    return digest(meta)


def sample(core,baseline,activation,ctx):
    m=ctx.m;receipt=core.strict_json(read(ACTIVATION_ROOT/'activated.json',ACTIVATED_SHA))
    need(receipt['stage']=='META_USER_CONNECTION_RUNTIME_ACTIVATED' and receipt['source_sha']==BASE_SOURCE and receipt['frontend_version']==FRONTEND and receipt['meta_configured'] is True and receipt['crm']['id']==ORIGINAL_ID and receipt['crm']['image']==IMAGE,'EXACT_ACTIVATED_META_RECEIPT_REQUIRED')
    need(all(receipt[key] is True for key in ('same_application_image','exact_nine_meta_environment_keys_added','old_environment_options_mounts_network_labels_preserved','all_141_business_rows_schema_and_private_boundaries_unchanged','google_on_cutoff_preserved')),'EXACT_META_ACTIVATION_BOUNDARIES_REQUIRED')
    need(all(receipt[key] is False for key in ('database_restored','business_writes','provider_requests','nginx_changed','credential_values_exported','production_containers_deleted')),'EXACT_NO_BUSINESS_ACTIVATION_RECEIPT_REQUIRED')
    old=m.inspect('t24-crm');need(old['State']['Running'] is True and m.runtime(old)==receipt['crm'],'EXACT_CURRENT_ACTIVATED_RUNTIME_REQUIRED')
    core.pins_ready();ctx.pf.google_environment(old);meta_sha=meta_environment(core,old)
    m.verify_secret_mount(old);m.verify_production_worker_enabled(old);m.retained().require_safe_original_restart(old)
    inventory=m.inventory(old['Id']);need(inventory==ctx.inventory and set(BACKEND_FILES)<=set(inventory),'EXACT_CURRENT_BACKEND_SOURCE_REQUIRED')
    # This helper fingerprints current legitimate Meta flows along with all
    # other tables. Its default mode imposes no empty-table or OFF-policy rule.
    protected=baseline.protected_sample(ctx)
    cred=core.strict_json(read(ACTIVATION_ROOT/'credential-receipt.json',CREDENTIAL_RECEIPT_SHA))
    need(cred['env_sha256']==ENV_SHA and cred['env_path']==str(core.ENV_FILE) and cred['app_id']==core.APP_ID and cred['config_id']==core.CONFIG_ID and cred['configuration_freeze_sha256']==core.CONFIG_FREEZE_SHA and cred['independent_fernet_key_generated'] is True,'EXACT_EXISTING_META_CREDENTIAL_RECEIPT_REQUIRED')
    need(all(cred[key] is False for key in ('runtime_changed','business_writes','provider_requests','credential_values_exported')),'CREDENTIAL_RECEIPT_SCOPE_REQUIRED')
    core.directory(core.ENV_FILE.parent)
    return {**protected,'stage':'META_OAUTH_DIAGNOSTICS_READONLY_PREFLIGHT','host':HOST,'source_sha':BASE_SOURCE,'frontend_version':FRONTEND,'schema_revision':REVISION,'activated_receipt_sha256':ACTIVATED_SHA,
        'crm':m.runtime(old),'environment_sha256':digest(old['Config']['Env']),'meta_environment_sha256':meta_sha,
        'backend_inventory_sha256':digest(inventory),'backend_file_count':len(inventory),'backend_changed_before':{name:inventory[name] for name in sorted(BACKEND_FILES)},
        'meta_credential_metadata':ctx.safe.protected_metadata(core.ENV_FILE),'meta_credential_receipt_sha256':CREDENTIAL_RECEIPT_SHA,'meta_credential_env_sha256':ENV_SHA,
        'meta_enabled_configured':True,'exact_nine_meta_environment_keys_preserved':True,'meta_existing_rows_preserved':True,'google_scheduler_enabled':True,'google_scheduler_activation_from':ACTIVATION_FROM,
        'provider_requests':False,'business_writes':False,'private_content_read':False,'credential_file_content_read':False,'container_or_configuration_changed':False}


def collect():
    need(os.geteuid()==0 and socket.gethostname()==HOST,'EXACT_ROOT_SERVER_REQUIRED');resource.setrlimit(resource.RLIMIT_CORE,(0,0));os.umask(0o077);sys.dont_write_bytecode=True
    values=dependencies();values[3].helper.docker_timestamp_probe();first=sample(*values);current=sample(*values)
    values[3].release.live_sequence_boundary(first['database_metadata'],current['database_metadata'])
    need({**current,'database_metadata':first['database_metadata']}==first,'PREFLIGHT_CHANGED_DURING_READ');return current


def capture():
    proof=collect();body=(json.dumps(proof,sort_keys=True,indent=2)+'\n').encode();sha=H(body);path=Path('/opt/t24-crm/releases/meta-oauth-diagnostics-preflight-'+sha[:12]+'.json')
    core=dependencies()[0]
    if path.exists():need(read(path,sha)==body,'EXISTING_PROOF_DRIFT')
    else:core.write(path,body)
    keys=('source_sha','frontend_version','schema_revision','schema_sha256','activated_receipt_sha256','crm','environment_sha256','meta_environment_sha256','backend_inventory_sha256','backend_changed_before','meta_credential_metadata','meta_credential_receipt_sha256','meta_credential_env_sha256','nginx_sha256','active_nginx_sha256','public_root','public_inventory_sha256','content_security_policy_sha256','meta_enabled_configured','exact_nine_meta_environment_keys_preserved','meta_existing_rows_preserved','google_scheduler_enabled','google_scheduler_activation_from')
    print(json.dumps({'stage':'META_OAUTH_DIAGNOSTICS_PREFLIGHT_CAPTURED','path':str(path),'sha256':sha,'bytes':len(body),**{key:proof[key] for key in keys},'table_count':len(proof['rows']),'rows_sha256':digest(proof['rows']),'credential_file_content_read':False,'private_content_read':False,'business_writes':False,'provider_requests':False,'runtime_changed':False},sort_keys=True))


if __name__=='__main__':
    try:capture()
    except BaseException as error:
        message=str(error);code=message if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',message) else 'META_DIAGNOSTIC_PREFLIGHT_REJECTED'
        print(json.dumps({'stage':'META_OAUTH_DIAGNOSTICS_PREFLIGHT_REJECTED','code':code}));sys.exit(1)
