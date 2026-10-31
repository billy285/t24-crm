"""Capture the phase-one deployed baseline; do not read private content or credentials."""
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
BASE_SOURCE = '6a7c0f7ee8d1b5eb9e24a5f0027cce24930d0667'
BASE_FRONTEND = '5af8aec0193c'
REVISION = 'eaf5a7b8c914'
OLD = Path('/opt/t24-crm/releases/media-publication-6a7c0f7ee8d1-20261031')
OLD_PREFLIGHT_SHA = '7d1452c8bdd1f493f23ce6fcec6cbd702f3dc0495bc19adca53aca051dd8411a'
DEPLOYED_SHA = 'c4d66c9cd2ae3fc3cf18543138ce7f28c1764d31e28ed89668960ec8838cf35c'
ENABLED_SHA = 'b7b1f50e0d5b306bc46ea415f4a160ab8cbeccfae879d6604a6d8607b9f83f29'
ORIGINAL_ID = '85037c222afa2d59be3a272083ffd12e8996524ceee6daf1378be8779126a3ef'
IMAGE = 'sha256:1363c9a6fb528bf7f97f4d92570a60116a29e1b2f7c34ff00825a4aa348e0874'
ACTIVATION_FROM = '2026-10-30T19:42:04Z'
BACKEND_FILES = frozenset({'main.py', 'alembic/versions/fbc6b8c9d025_media_publication_images.py',
    'alembic/versions/acd7c9d0e136_media_content_plans.py', 'models/media_publication_images.py', 'models/media_planning.py',
    'routers/media_operations.py', 'routers/media_publication_images.py', 'routers/media_planning.py',
    'services/google_business.py', 'services/google_business_management.py', 'services/media_operations.py',
    'services/media_publication_images.py', 'services/media_planning.py'})
NEW_TABLES = frozenset({'media_publication_image_policies', 'media_publication_images', 'media_publication_image_selections',
    'media_publication_image_deliveries', 'media_content_plans', 'media_content_plan_tasks'})


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
    previous = load(OLD / 'preflight.py', OLD_PREFLIGHT_SHA, '_workflow_retained_preflight')
    values = previous.dependencies()
    need(isinstance(values, tuple) and len(values) == 4, 'RETAINED_DEPENDENCY_ARITY_REQUIRED')
    helper, m, base, safe = values
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
    need(receipt['stage'] == 'MEDIA_PUBLICATION_DEPLOYED_VERIFIED' and receipt['deployed'] is True and receipt['source_sha'] == BASE_SOURCE and receipt['frontend_version'] == BASE_FRONTEND and receipt['schema_revision'] == REVISION, 'EXACT_DEPLOYED_SOURCE_REQUIRED')
    need(receipt['scheduler_enabled'] is True and receipt['scheduler_activation_from'] == ACTIVATION_FROM, 'EXACT_ENABLED_SCHEDULER_RECEIPT_REQUIRED')
    need(receipt['crm']['id'] == ORIGINAL_ID and receipt['crm']['image'] == IMAGE, 'EXACT_CURRENT_CONTAINER_REQUIRED')
    need(all(receipt[key] is True for key in ('original_env_mounts_network_unchanged', 'existing_google_environment_preserved', 'original_business_rows_unchanged', 'private_runtime_unchanged', 'no_new_policy_task_schedule_or_post')), 'EXACT_PRIOR_DEPLOYMENT_BOUNDARIES_REQUIRED')
    crm = m.inspect('t24-crm')
    need(crm['State']['Running'] is True and m.runtime(crm) == receipt['crm'], 'ENABLED_RUNTIME_DRIFT')
    google_environment(crm)
    m.verify_secret_mount(crm)
    m.verify_production_worker_enabled(crm)
    m.retained().require_safe_original_restart(crm)
    inventory = m.inventory(crm['Id'])
    need(H((json.dumps(inventory, sort_keys=True, indent=2) + '\n').encode()) == receipt['candidate_inventory_sha256'], 'EXACT_DEPLOYED_BACKEND_REQUIRED')
    need(m.schema_signature(m.BUSINESS, REVISION) == receipt['schema_sha256'], 'DEPLOYED_SCHEMA_DRIFT')
    static = Path(receipt['public_root'])
    need(m.digest(m.tree(static)) == receipt['public_inventory_sha256'] and json.loads((static / 'app-version.json').read_bytes())['version'] == BASE_FRONTEND, 'DEPLOYED_STATIC_DRIFT')
    oldproof = json.loads(read(Path('/opt/t24-crm/releases/media-publication-preflight-' + receipt['preflight_sha256'][:12] + '.json'), receipt['preflight_sha256']))
    body = m.NGINX.read_bytes()
    active = m.run(['nginx', '-T'], 'ACTIVE_NGINX_REQUIRED')
    new, old = os.fsencode(receipt['public_root']), os.fsencode(oldproof['public_root'])
    need(H(body) == receipt['nginx_sha256'] and active.count(new) == 1 and H(active.replace(new, old, 1)) == oldproof['active_nginx_config_sha256'], 'CALLBACK_PROTECTED_NGINX_DRIFT')
    need(b'/api/v1/media-publication-images/delivery/' not in active, 'DELIVERY_NGINX_PREFIX_ALREADY_PRESENT')
    pins = json.loads(m.read(base.PRIVATE_PINS, base.PRIVATE_PINS_SHA))
    private = safe.safe_private_boundary(m, pins)
    identity = m.BUSINESS.stat()
    snapshot = m.sql_snapshot(m.BUSINESS)
    rows = {name: {'count': value['count'], 'rows_sha256': value['rows_sha256'], 'shape_sha256': digest({k: value[k] for k in ('columns', 'schema', 'indexes')})} for name, value in snapshot.items()}
    need(len(rows) == 130 and 'media_operation_publication_specs' in rows and not NEW_TABLES.intersection(rows), 'EXACT_EXISTING_TABLE_SET_REQUIRED')
    expected_existing = {'main.py', 'routers/media_operations.py', 'services/google_business.py', 'services/google_business_management.py', 'services/media_operations.py'}
    need(set(BACKEND_FILES).intersection(inventory) == expected_existing, 'EXACT_EXISTING_RUNTIME_FILE_SCOPE_REQUIRED')
    return {'stage': 'MEDIA_WORKFLOW_READONLY_PREFLIGHT', 'host': HOST, 'source_sha': BASE_SOURCE, 'frontend_version': BASE_FRONTEND,
        'schema_revision': REVISION, 'schema_sha256': receipt['schema_sha256'], 'deployed_sha256': DEPLOYED_SHA, 'scheduler_enabled_receipt_sha256': ENABLED_SHA,
        'host_docker_timestamp_parser_verified': True, 'crm': m.runtime(crm), 'database_identity': [identity.st_dev, identity.st_ino],
        'database_metadata': helper.db_metadata(m.BUSINESS), 'rows': rows, 'original_columns': {name: value['columns'] for name, value in snapshot.items()},
        'backend_inventory_sha256': digest(inventory), 'backend_file_count': len(inventory), 'backend_changed_before': {name: inventory.get(name) for name in sorted(BACKEND_FILES)},
        'public_root': str(static), 'public_inventory_sha256': receipt['public_inventory_sha256'], 'nginx_sha256': H(body), 'active_nginx_config_sha256': H(active),
        'credential_boundary': m.credential_boundary(), 'google_credential_metadata': safe.protected_metadata(safe.GBP_ENV), 'private_boundary': private,
        'environment_sha256': digest(sorted(crm['Config']['Env'])), 'scheduler_enabled': True, 'scheduler_activation_from': ACTIVATION_FROM,
        'gbp_feature_enabled': True, 'callback_logging_protection_retained': True, 'image_delivery_prefix_absent': b'/api/v1/media-publication-images/delivery/' not in active, 'provider_requests': False, 'business_writes': False,
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
    path = Path('/opt/t24-crm/releases/media-workflow-preflight-' + sha[:12] + '.json')
    if path.exists():
        need(read(path, sha) == body, 'EXISTING_PREFLIGHT_DRIFT')
    else:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
    print(json.dumps({'stage': 'MEDIA_WORKFLOW_PREFLIGHT_CAPTURED', 'sha256': sha, 'bytes': len(body), 'path': str(path),
        **{key: proof[key] for key in ('source_sha', 'frontend_version', 'schema_revision', 'schema_sha256', 'deployed_sha256',
            'scheduler_enabled_receipt_sha256', 'crm', 'backend_changed_before', 'backend_inventory_sha256', 'environment_sha256', 'nginx_sha256',
            'active_nginx_config_sha256', 'scheduler_enabled', 'scheduler_activation_from', 'gbp_feature_enabled', 'callback_logging_protection_retained', 'image_delivery_prefix_absent')},
        'rows_sha256': digest(proof['rows']), 'table_count': len(proof['rows']), 'private_boundary_verified': True,
        'executed_business_writes': False, 'credential_content_read': False, 'private_content_read': False,
        'host_docker_timestamp_parser_verified': True}, sort_keys=True))


if __name__ == '__main__':
    try:
        capture()
    except BaseException as error:
        value = str(error)
        code = value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}', value) else 'PREFLIGHT_REJECTED'
        print(json.dumps({'stage': 'MEDIA_WORKFLOW_PREFLIGHT_REJECTED', 'code': code}))
        sys.exit(1)
