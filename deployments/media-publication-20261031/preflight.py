"""Capture the enabled scheduler baseline without reading private content or credentials."""
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

H = lambda body: hashlib.sha256(body).hexdigest()
HOST = 'iZj6c4cj7edgnhdimts4l7Z'
BASE_SOURCE = '5a52cdcf8e9560fcf5ec6e2b27f264f6f0fe1087'
BASE_FRONTEND = '50347ba2c9da'
REVISION = 'd9e4f6a7b803'
OLD = Path('/opt/t24-crm/releases/media-ops-review-refresh-retry-5a52cdcf8e95-20261031')
OLD_PREFLIGHT_SHA = '8f22bbc8929a675ef51ca85061d2ffad4f94cc5eec1cad4a794498e5a64dc32d'
DEPLOYED_SHA = 'e9790ac0c05b14a79f0e72d7a6d11d2547d5bf9d8892c29b3d9703295f866c80'
ENABLED = Path('/opt/t24-crm/releases/media-ops-scheduler-refresh-retry-5a52cdcf8e95-20261031/67363ee8-9604-4e23-80ab-8d331218259a/enabled.json')
ENABLED_SHA = 'b7b1f50e0d5b306bc46ea415f4a160ab8cbeccfae879d6604a6d8607b9f83f29'
ORIGINAL_ID = '213d3b7a490d2208d6a4329d1569355ceb1caf41527ea76d735ff0ae31d314bd'
IMAGE = 'sha256:f6a39af2ecad2ae561595560313a95ff1d87de38141880e2340bbfbe6c8c7ecb'
ACTIVATION_FROM = '2026-10-30T19:42:04Z'
BACKEND_FILES = frozenset({'models/media_operations.py', 'routers/media_operations.py', 'services/media_operations.py',
    'services/google_business.py', 'alembic/versions/eaf5a7b8c914_media_publication_specs.py'})


def need(ok, code):
    if not ok:
        raise RuntimeError(code)


def digest(value):
    return H(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())


def read(path, sha=None):
    row = path.lstat()
    need(path.resolve() == path and stat.S_ISREG(row.st_mode) and row.st_uid == 0 and row.st_nlink == 1 and stat.S_IMODE(row.st_mode) == 0o600, 'PROTECTED_TOOL_REQUIRED')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        body = stream.read(1048577)
    need(len(body) <= 1048576 and (sha is None or H(body) == sha), 'PINNED_TOOL_HASH_REQUIRED')
    return body


def load(path, sha, name):
    module = types.ModuleType(name)
    module.__file__ = str(path)
    exec(compile(read(path, sha), str(path), 'exec'), module.__dict__)
    return module


def dependencies():
    helper = load(OLD / 'preflight.py', OLD_PREFLIGHT_SHA, '_publication_retained_preflight')
    m, base, safe = helper.dependencies()
    return helper, m, base, safe


def google_environment(info):
    values = {}
    for value in info['Config']['Env']:
        need(isinstance(value, str) and '=' in value and not any(c in value for c in '\r\n\0'), 'EXACT_ENVIRONMENT_FORMAT_REQUIRED')
        key, val = value.split('=', 1)
        need(key not in values, 'DUPLICATE_ENVIRONMENT_KEY')
        values[key] = val
    expected = {'T24_GBP_ENABLED', 'T24_GBP_API_APPROVED', 'T24_GBP_CLIENT_ID', 'T24_GBP_CLIENT_SECRET',
        'T24_GBP_TOKEN_KEY', 'T24_GBP_PUBLIC_URL', 'T24_GBP_SCHEDULER_ENABLED', 'T24_GBP_SCHEDULER_ACTIVATION_FROM'}
    need({key for key in values if key.startswith('T24_GBP_')} == expected, 'EXACT_EXISTING_GOOGLE_ENVIRONMENT_REQUIRED')
    need(values['T24_GBP_ENABLED'] == values['T24_GBP_API_APPROVED'] == values['T24_GBP_SCHEDULER_ENABLED'] == 'true', 'EXISTING_GOOGLE_WORKER_MUST_REMAIN_ENABLED')
    need(values['T24_GBP_PUBLIC_URL'] == 'https://t24-crm.com' and values['T24_GBP_SCHEDULER_ACTIVATION_FROM'] == ACTIVATION_FROM, 'EXACT_EXISTING_GOOGLE_CUTOFF_REQUIRED')


def baseline(helper, m, base, safe):
    receipt = json.loads(read(OLD / 'deployed.json', DEPLOYED_SHA))
    enabled = json.loads(read(ENABLED, ENABLED_SHA))
    need(receipt['stage'] == 'MEDIA_OPS_REVIEW_REFRESH_RETRY_DEPLOYED_VERIFIED' and receipt['source_sha'] == BASE_SOURCE and receipt['frontend_version'] == BASE_FRONTEND and receipt['schema_revision'] == REVISION, 'EXACT_DEPLOYED_SOURCE_REQUIRED')
    need(enabled['stage'] == 'SCHEDULER_CONFIG_ENABLED_VERIFIED' and enabled['source_sha'] == BASE_SOURCE and enabled['frontend_version'] == BASE_FRONTEND and enabled['schema_revision'] == REVISION and enabled['activation_from'] == ACTIVATION_FROM and enabled['deployed_sha256'] == DEPLOYED_SHA, 'EXACT_ENABLED_SCHEDULER_RECEIPT_REQUIRED')
    need(enabled['crm']['id'] == ORIGINAL_ID and enabled['crm']['image'] == IMAGE, 'EXACT_CURRENT_CONTAINER_REQUIRED')
    need(all(enabled[key] is True for key in ('same_image', 'exact_two_scheduler_keys_only', 'all_existing_env_mounts_network_unchanged', 'all_business_rows_unchanged')), 'EXACT_SCHEDULER_ENABLE_BOUNDARIES_REQUIRED')
    crm = m.inspect('t24-crm')
    need(crm['State']['Running'] is True and m.runtime(crm) == enabled['crm'], 'ENABLED_RUNTIME_DRIFT')
    google_environment(crm)
    m.verify_secret_mount(crm)
    m.verify_production_worker_enabled(crm)
    m.retained().require_safe_original_restart(crm)
    inventory = m.inventory(crm['Id'])
    need(H((json.dumps(inventory, sort_keys=True, indent=2) + '\n').encode()) == receipt['candidate_inventory_sha256'], 'EXACT_DEPLOYED_BACKEND_REQUIRED')
    need(m.schema_signature(m.BUSINESS, REVISION) == receipt['schema_sha256'], 'DEPLOYED_SCHEMA_DRIFT')
    static = Path(receipt['public_root'])
    need(m.digest(m.tree(static)) == receipt['public_inventory_sha256'] and json.loads((static / 'app-version.json').read_bytes())['version'] == BASE_FRONTEND, 'DEPLOYED_STATIC_DRIFT')
    oldproof = json.loads(read(Path('/opt/t24-crm/releases/media-ops-review-refresh-retry-preflight-' + receipt['preflight_sha256'][:12] + '.json'), receipt['preflight_sha256']))
    body = m.NGINX.read_bytes()
    active = m.run(['nginx', '-T'], 'ACTIVE_NGINX_REQUIRED')
    new, old = os.fsencode(receipt['public_root']), os.fsencode(oldproof['public_root'])
    need(H(body) == receipt['nginx_sha256'] and active.count(new) == 1 and H(active.replace(new, old, 1)) == oldproof['active_nginx_config_sha256'], 'CALLBACK_PROTECTED_NGINX_DRIFT')
    pins = json.loads(m.read(base.PRIVATE_PINS, base.PRIVATE_PINS_SHA))
    private = safe.safe_private_boundary(m, pins)
    identity = m.BUSINESS.stat()
    snapshot = m.sql_snapshot(m.BUSINESS)
    rows = {name: {'count': value['count'], 'rows_sha256': value['rows_sha256'], 'shape_sha256': digest({k: value[k] for k in ('columns', 'schema', 'indexes')})} for name, value in snapshot.items()}
    need(len(rows) == 129 and 'media_operation_publication_specs' not in rows and all(name in inventory for name in BACKEND_FILES if not name.startswith('alembic/')), 'EXACT_EXISTING_TABLE_AND_SOURCE_SET_REQUIRED')
    return {'stage': 'MEDIA_PUBLICATION_READONLY_PREFLIGHT', 'host': HOST, 'source_sha': BASE_SOURCE, 'frontend_version': BASE_FRONTEND,
        'schema_revision': REVISION, 'schema_sha256': receipt['schema_sha256'], 'deployed_sha256': DEPLOYED_SHA, 'scheduler_enabled_receipt_sha256': ENABLED_SHA,
        'host_docker_timestamp_parser_verified': True, 'crm': m.runtime(crm), 'database_identity': [identity.st_dev, identity.st_ino],
        'database_metadata': helper.db_metadata(m.BUSINESS), 'rows': rows, 'original_columns': {name: value['columns'] for name, value in snapshot.items()},
        'backend_inventory_sha256': digest(inventory), 'backend_file_count': len(inventory), 'backend_changed_before': {name: inventory.get(name) for name in sorted(BACKEND_FILES)},
        'public_root': str(static), 'public_inventory_sha256': receipt['public_inventory_sha256'], 'nginx_sha256': H(body), 'active_nginx_config_sha256': H(active),
        'credential_boundary': m.credential_boundary(), 'google_credential_metadata': safe.protected_metadata(safe.GBP_ENV), 'private_boundary': private,
        'environment_sha256': digest(sorted(crm['Config']['Env'])), 'scheduler_enabled': True, 'scheduler_activation_from': ACTIVATION_FROM,
        'gbp_feature_enabled': True, 'callback_logging_protection_retained': True, 'provider_requests': False, 'business_writes': False,
        'private_content_read': False, 'credential_content_read': False, 'container_or_configuration_changed': False}


def collect():
    need(os.geteuid() == 0 and socket.gethostname() == HOST, 'EXACT_ROOT_SERVER_REQUIRED')
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.umask(0o077)
    sys.dont_write_bytecode = True
    helper, m, base, safe = dependencies()
    helper.docker_timestamp_probe()
    proof = baseline(helper, m, base, safe)
    need(proof == baseline(helper, m, base, safe), 'PREFLIGHT_CHANGED_DURING_READ')
    return proof


def capture():
    proof = collect()
    body = (json.dumps(proof, sort_keys=True, indent=2) + '\n').encode()
    sha = H(body)
    path = Path('/opt/t24-crm/releases/media-publication-preflight-' + sha[:12] + '.json')
    if path.exists():
        need(read(path, sha) == body, 'EXISTING_PREFLIGHT_DRIFT')
    else:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
    print(json.dumps({'stage': 'MEDIA_PUBLICATION_PREFLIGHT_CAPTURED', 'sha256': sha, 'bytes': len(body), 'path': str(path),
        **{key: proof[key] for key in ('source_sha', 'frontend_version', 'schema_revision', 'schema_sha256', 'deployed_sha256',
            'scheduler_enabled_receipt_sha256', 'crm', 'backend_changed_before', 'backend_inventory_sha256', 'environment_sha256', 'nginx_sha256',
            'active_nginx_config_sha256', 'scheduler_enabled', 'scheduler_activation_from', 'gbp_feature_enabled', 'callback_logging_protection_retained')},
        'rows_sha256': digest(proof['rows']), 'table_count': len(proof['rows']), 'private_boundary_verified': True,
        'executed_business_writes': False, 'credential_content_read': False, 'private_content_read': False,
        'host_docker_timestamp_parser_verified': True}, sort_keys=True))


if __name__ == '__main__':
    try:
        capture()
    except BaseException as error:
        value = str(error)
        code = value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}', value) else 'PREFLIGHT_REJECTED'
        print(json.dumps({'stage': 'MEDIA_PUBLICATION_PREFLIGHT_REJECTED', 'code': code}))
        sys.exit(1)
