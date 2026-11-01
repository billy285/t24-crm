"""Capture current live owner Meta/Google without exporting credentials or rows."""
import hashlib
import json
from pathlib import Path
from types import ModuleType

HOST = 'iZj6c4cj7edgnhdimts4l7Z'
SOURCE = 'a03766539ef3430f350f467652511a43ee3c4abf'
FRONTEND = '58d2c585210f'
REVISION = 'bde8da01f247'
ACTIVATION_ROOT = Path('/opt/t24-crm/releases/meta-business-crm-activation-a03766539ef3-20261101')
CORE_SHA = 'ae765a08c76438a3416ee67f78e3c0d77c71e5240bd77c938aa2476a328d3dc8'
BASELINE_SHA = 'fc7af7f4d91440c9ec9b621c3d9086d3d679dcb94beb52b5b151e32b7ef50362'
ACTIVATED_SHA = '4e40cdd7de39fee3eb898c3b9f98059df586e59062326ae288b856241f67aba6'
CREDENTIAL_SHA = 'df306941af84cc6f31905092c23d6f7a7c4182b6b9f595ddde433f42931e698c'
ENV_SHA = '9c7e30e80b7550b5b7a62a189059046e14dd215c56c601749d34d1bdc2d76a51'
ORIGINAL_ID = '4c4085ff201a88ad685ab69d7a85c8615567acdcb2225d529e23b95858997811'
IMAGE = 'sha256:e136fbc267e7bb81d069c597eb2c4ddab7e5f39bf183bbe6cd6cbccc7a19919d'
CONFIG = '81ae2c6ccb2074531929aae8812a5d48806a19a185e515e7ed62b48148b01834'
ROOT = Path('/opt/t24-crm/releases')
H = lambda body: hashlib.sha256(body).hexdigest()
_CACHE = None


def need(value, code):
    if not value: raise RuntimeError(code)


def digest(value):
    return H(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())


def dependencies():
    global _CACHE
    # Bootstrap needs the already reviewed private core reader before any
    # transitive helper is loaded. No provider, SQL or runtime writes here.
    import os, stat, socket, resource
    need(os.geteuid() == 0 and socket.gethostname() == HOST, 'EXACT_ROOT_SERVER_REQUIRED')
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0)); os.umask(0o077)
    def read(path, sha):
        for parent in path.parents:
            row = parent.lstat()
            need(parent.resolve() == parent and stat.S_ISDIR(row.st_mode) and row.st_uid == 0 and not row.st_mode & 0o022, 'PROTECTED_SOURCE_PARENT_REQUIRED')
        prior = path.lstat()
        need(path.resolve() == path and stat.S_ISREG(prior.st_mode) and prior.st_uid == 0 and prior.st_nlink == 1 and stat.S_IMODE(prior.st_mode) == 0o600, 'PROTECTED_CORE_REQUIRED')
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb') as stream:
            opened = os.fstat(stream.fileno()); body = stream.read(1048577)
        after = path.lstat(); identity = lambda r: (r.st_dev,r.st_ino,r.st_size,r.st_mtime_ns,r.st_ctime_ns,r.st_mode,r.st_uid,r.st_nlink)
        need(identity(prior) == identity(opened) == identity(after) and len(body) <= 1048576 and H(body) == sha, 'EXACT_CORE_BYTES_REQUIRED')
        return body
    tools = ACTIVATION_ROOT / 'tools-activation-v1'
    core_body = read(tools / 'core.py', CORE_SHA)
    baseline_body = read(tools / 'baseline.py', BASELINE_SHA)
    if _CACHE is None:
        c = ModuleType('_meta_operations_preflight_core'); c.__file__ = str(tools / 'core.py'); exec(compile(core_body,c.__file__,'exec'),c.__dict__)
        b = ModuleType('_meta_operations_preflight_baseline'); b.__file__ = str(tools / 'baseline.py'); exec(compile(baseline_body,b.__file__,'exec'),b.__dict__); b.configure(c)
        ctx = b.dependencies(); _CACHE = (c,b,ctx)
    return _CACHE


def sample():
    c,b,ctx = dependencies(); m = ctx.m
    activated = c.strict_json(c.read(ACTIVATION_ROOT / 'activated.json', sha=ACTIVATED_SHA))
    expected = {'id':ORIGINAL_ID,'config':CONFIG,'image':IMAGE,'restart':0,'started':'2026-10-31T19:34:06.907559214Z'}
    need(activated['stage'] == 'META_CRM_USER_CONNECTION_RUNTIME_ACTIVATED' and activated['crm'] == expected and activated['source_sha'] == SOURCE and activated['frontend_version'] == FRONTEND, 'EXACT_CURRENT_ACTIVATION_REQUIRED')
    current = m.inspect('t24-crm')
    need(current['State']['Running'] is True and m.runtime(current) == expected, 'EXACT_RUNNING_CURRENT_META_RUNTIME_REQUIRED')
    env = current['Config']['Env']; selected = [row for row in env if row.split('=',1)[0].startswith('T24_META_')]
    c.validate_meta_env(selected)
    need(not any(row.split('=',1)[0].startswith('T24_META_OPS_') for row in env), 'OPERATIONS_FEATURE_MUST_START_UNCONFIGURED')
    need(H(('\n'.join(sorted(selected))+'\n').encode('ascii')) == ENV_SHA, 'EXACT_CURRENT_META_CREDENTIAL_VALUES_REQUIRED')
    ctx.ctx.pf.google_environment(current); m.verify_secret_mount(current); m.verify_production_worker_enabled(current); m.retained().require_safe_original_restart(current)
    need(m.inventory(current['Id']) == ctx.inventory, 'EXACT_CURRENT_BACKEND_INVENTORY_REQUIRED')
    # Existing helpers impose no empty-table rule: all actual new Meta
    # connections, tokens, flows, assets and customer bindings are preserved.
    protected = ctx.legacy_baseline.protected_sample(ctx.ctx)
    credential = c.strict_json(c.read(ACTIVATION_ROOT / 'credential-receipt.json',sha=CREDENTIAL_SHA))
    need(credential['env_sha256'] == ENV_SHA and credential['env_path'] == str(c.ENV_FILE), 'EXACT_CURRENT_CREDENTIAL_RECEIPT_REQUIRED')
    c.directory(c.ENV_FILE.parent); c.directory(c.LEGACY_ENV_FILE.parent)
    return {**protected,'stage':'META_OPERATIONS_READONLY_PREFLIGHT','host':HOST,'source_sha':SOURCE,'frontend_version':FRONTEND,'schema_revision':REVISION,
        'activated_receipt_sha256':ACTIVATED_SHA,'crm':m.runtime(current),'environment_sha256':digest(env),'meta_environment_sha256':digest(selected),
        'backend_inventory_sha256':digest(ctx.inventory),'backend_file_count':len(ctx.inventory),
        'meta_credential_metadata':ctx.safe.protected_metadata(c.ENV_FILE),'legacy_meta_credential_metadata':ctx.safe.protected_metadata(c.LEGACY_ENV_FILE),
        'google_scheduler_enabled':True,'google_scheduler_activation_from':c.ACTIVATION_FROM,'meta_operations_environment_absent':True,
        'credential_file_content_read':False,'private_content_read':False,'business_writes':False,'provider_requests':False,'runtime_changed':False}


def capture():
    first = sample(); latest = sample(); c,b,ctx = dependencies()
    ctx.ctx.release.live_sequence_boundary(first['database_metadata'], latest['database_metadata'])
    need({**latest,'database_metadata':first['database_metadata']} == first, 'CURRENT_BASELINE_CHANGED_DURING_CAPTURE')
    body = (json.dumps(latest,sort_keys=True,indent=2)+'\n').encode(); sha = H(body)
    path = ROOT / ('meta-operations-preflight-'+sha[:12]+'.json')
    if path.exists(): c.read(path,sha=sha)
    else: c.write(path,body)
    keys = ('host','source_sha','frontend_version','schema_revision','schema_sha256','activated_receipt_sha256','crm','environment_sha256','meta_environment_sha256','backend_inventory_sha256','backend_file_count','meta_credential_metadata','legacy_meta_credential_metadata','nginx_sha256','active_nginx_sha256','public_root','public_inventory_sha256','content_security_policy_sha256','google_scheduler_enabled','google_scheduler_activation_from','meta_operations_environment_absent')
    return {'stage':'META_OPERATIONS_PREFLIGHT_CAPTURED','path':str(path),'sha256':sha,'bytes':len(body),**{k:latest[k] for k in keys},'table_count':len(latest['rows']),'rows_sha256':digest(latest['rows']),
        'credential_file_content_read':False,'private_content_read':False,'business_writes':False,'provider_requests':False,'runtime_changed':False}


if __name__ == '__main__':
    try: print(json.dumps(capture(),sort_keys=True))
    except BaseException as exc:
        import re
        message = str(exc); code = message if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',message) else 'META_OPERATIONS_PREFLIGHT_REJECTED'
        print(json.dumps({'stage':'META_OPERATIONS_PREFLIGHT_REJECTED','code':code})); raise SystemExit(1)
