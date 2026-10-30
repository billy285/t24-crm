"""Fresh read-only CRM proof; no provider calls or private/credential file content reads."""
import base64
import hashlib
import json
import os
import re
import resource
import socket
import stat
import subprocess
import sys
import types
import zlib
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True
H = lambda body: hashlib.sha256(body).hexdigest()
HOST = 'iZj6c4cj7edgnhdimts4l7Z'
BASE_SOURCE = '7431d1986b81328fcc822e3e13641e4d03b6b9bf'
BASE_FRONTEND = 'c648c284143e'
BASE_REVISION = 'c8d3e5f6a702'
BASE_DATABASE_IDENTITY = (64515, 262854)
BASE_IMAGE = 'sha256:0a058c4927abd5c2216fe65a8f36a42705d7064ad91248339ca997aa3d019ccb'
BASE_RUNTIME = {'id': 'e180fc81030f77f09c411495b2c3b2dc27c464ddedf55bd02d2bbb7098ff2838',
    'image': BASE_IMAGE, 'started': '2026-10-30T05:27:22.107967031Z', 'restart': 0,
    'config': '08698adcbb9f1724737f5d26e47386fdb8f7f504e71f2edfe536e0e45e11c19b'}
LEGACY = Path('/opt/t24-crm/releases/stripe-history-daily-scan-285c3377e6d0-20261019/release.py')
LEGACY_SHA = 'bd5f1af9c67b6e268d7d1b4d91ae4b122895480b10bb6ef777b79770ca2392c0'
PINS = Path('/opt/t24-crm/releases/commission-service-month-preflight-20261013.json')
PINS_SHA = 'af9028f405deed4486628b8c709fe0157100a00a515e00840bdf760eec11f161'
PRIOR_RELEASE = Path('/opt/t24-crm/releases/google-business-7431d1986b81-20261030')
PRIOR_DEPLOYED_SHA = '16fbbcf5ef322684256fff82af3b25146a5efaff48f7947a398c480020895cab'
ACTIVATION = Path('/opt/t24-crm/releases/google-business-activation-7431d1986b81-20261030/attempt-v3')
ENABLED_RECEIPT = ACTIVATION / 'completion-oom-default/enabled.json'
ENABLED_RECEIPT_SHA = 'fc1fb80477a00839246dab0ef818abe766285f99db905adca12d8f84298e341d'
LOGGING_RECEIPT = ACTIVATION / 'logging-protected.json'
LOGGING_RECEIPT_SHA = '43e6f45db4fdcb6e907c622eb081e023659e7538ff97bf45cb6adbc0eefd6c50'
NGINX_SHA = '1884a40eec391a3b113d28e11c904270d1c485b01ecc7f89a2cf8b99aededd7e'
ACTIVE_NGINX_SHA = '972b069dd659c9cdc18ac32c9e78a96cbe387b633fa6fe87de676f5047772e48'
GBP_ENV = Path('/opt/t24-crm/secrets/google-business/runtime.env')
GBP_NAMES = frozenset('T24_GBP_' + key for key in ('ENABLED', 'API_APPROVED', 'CLIENT_ID', 'CLIENT_SECRET', 'TOKEN_KEY', 'PUBLIC_URL'))
SCHEDULER_NAMES = frozenset({'T24_GBP_SCHEDULER_ENABLED', 'T24_GBP_SCHEDULER_ACTIVATION_FROM'})
BACKEND_FILES = frozenset({'main.py', 'models/google_business.py', 'routers/google_business.py',
    'services/google_business.py', 'services/google_business_management.py', 'services/google_business_scheduler.py',
    'services/google_business_ai.py', 'alembic/versions/d9e4f6a7b803_google_business_management.py'})
NEW_TABLES = frozenset('google_business_' + key for key in ('management_requests', 'assignment_previews', 'schedules', 'ai_consents', 'ai_drafts'))
GOOGLE_TABLES = frozenset('google_business_' + key for key in ('connections', 'oauth_states', 'bindings', 'grants', 'actions'))


def need(ok, code):
    if not ok:
        raise RuntimeError(code)


def safe_error(error):
    value = str(error)
    return value if isinstance(error, RuntimeError) and re.fullmatch('[A-Z0-9_]{1,100}', value) else 'READONLY_PREFLIGHT_FAILED'


def digest(value):
    return H(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def protected_metadata(path):
    """lstat only: never open the database, environment or credential file."""
    path = Path(path)
    need(path.is_absolute() and path.resolve() == path, 'PROTECTED_METADATA_PATH_REQUIRED')
    for parent in path.parents:
        info = parent.lstat()
        need(stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022,
            'PROTECTED_METADATA_PARENT_REQUIRED')
    info = path.lstat()
    need(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and info.st_nlink == 1 and
        stat.S_IMODE(info.st_mode) == 0o600, 'PROTECTED_METADATA_FILE_REQUIRED')
    return {'device': info.st_dev, 'inode': info.st_ino, 'path_sha256': digest(str(path)),
        'uid': info.st_uid, 'mode': stat.S_IMODE(info.st_mode), 'size': info.st_size,
        'mtime_ns': info.st_mtime_ns, 'ctime_ns': info.st_ctime_ns}


def load_legacy():
    # The only module executed by this loader is an already-reviewed retained tool.
    before = LEGACY.lstat()
    need(LEGACY.resolve() == LEGACY and stat.S_ISREG(before.st_mode) and before.st_uid == 0 and
        before.st_nlink == 1 and not before.st_mode & 0o077, 'PROTECTED_RETAINED_HELPER_REQUIRED')
    fd = os.open(LEGACY, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        need((before.st_dev, before.st_ino) == (opened.st_dev, opened.st_ino), 'RETAINED_HELPER_OPEN_DRIFT')
        body = stream.read(1024 * 1024 + 1)
    after = LEGACY.lstat()
    need(len(body) <= 1024 * 1024 and H(body) == LEGACY_SHA and
        (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) ==
        (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns), 'IMMUTABLE_RETAINED_HELPER_REQUIRED')
    module = types.ModuleType('_media_ops_management_preflight_legacy')
    module.__file__ = str(LEGACY)
    exec(compile(body, str(LEGACY), 'exec'), module.__dict__)
    return module


def environment_proof(crm):
    values = {}
    for item in crm['Config']['Env']:
        need(isinstance(item, str) and '=' in item and not any(char in item for char in '\r\n\0'), 'ENVIRONMENT_FORMAT_REJECTED')
        key, value = item.split('=', 1)
        need(re.fullmatch('[A-Za-z_][A-Za-z0-9_]*', key) and key not in values, 'DUPLICATE_ENVIRONMENT_KEY')
        values[key] = value
    scheduler = {key for key in values if key.startswith('T24_GBP_SCHEDULER_')}
    need(scheduler <= SCHEDULER_NAMES and values.get('T24_GBP_SCHEDULER_ENABLED', 'false') == 'false' and
        not values.get('T24_GBP_SCHEDULER_ACTIVATION_FROM', ''), 'GBP_SCHEDULER_MUST_REMAIN_DISABLED')
    google = {key for key in values if key.startswith('T24_GBP_')} - scheduler
    need(google == GBP_NAMES and values['T24_GBP_ENABLED'] == 'true' and
        values['T24_GBP_API_APPROVED'] == 'true' and values['T24_GBP_PUBLIC_URL'] == 'https://t24-crm.com',
        'EXACT_EXISTING_GOOGLE_CONFIG_REQUIRED')
    return {'environment_sha256': digest(sorted(crm['Config']['Env'])), 'environment_key_count': len(values),
        'gbp_feature_enabled': True, 'scheduler_disabled': True, 'environment_values_exported': False}


def private_metadata_boundary(m, pins):
    # Use the retained role configuration checks, NOT private_boundary(), which
    # reads private ENV/DB content. This proof deliberately opens neither file.
    _, upgrade, base, _, switch = m.retained().tools()
    need(base.PRIVATE_DB == Path('/opt/t24-crm/private-workspace/data/workspace.db') and
        base.ENV == Path('/opt/t24-crm/private-workspace/config/runtime.env'), 'EXACT_PRIVATE_METADATA_PATHS_REQUIRED')
    private_db = protected_metadata(base.PRIVATE_DB)
    expected_identity = pins['databases']['private']['identity']
    need({key: private_db[key] for key in ('device', 'inode', 'path_sha256', 'uid', 'mode')} == expected_identity,
        'PRIVATE_DATABASE_IDENTITY_DRIFT')
    private_env = protected_metadata(base.ENV)
    runtime = {}
    for role in ('api', 'worker'):
        expected = pins['roles'][role]
        info = m.inspect('t24-private-' + role)
        actual = upgrade.own_role(base, switch, expected['id'], role, expected['image'], expected['attempt'],
            expected['source'], switch.environment(info), True)
        need(actual == expected['runtime'], 'PRIVATE_RUNTIME_CONFIGURATION_DRIFT')
        runtime[role] = actual
    return {'private_runtime': runtime, 'private_database_identity': expected_identity,
        'private_environment_metadata': private_env, 'private_boundary_verified': True,
        'private_boundary_scope': 'pinned_runtime_and_file_metadata_only',
        'private_file_content_read': False}


# Reused by the reviewed publisher without invoking legacy private DB readers.
safe_private_boundary = private_metadata_boundary


def snapshot_evidence(rows):
    return {name: {'count': row['count'], 'rows_sha256': row['rows_sha256'],
        'shape_sha256': digest({key: row[key] for key in ('columns', 'schema', 'indexes')})}
        for name, row in rows.items()}


def proof():
    need(os.geteuid() == 0 and socket.gethostname() == HOST, 'EXACT_SERVER_ROOT_REQUIRED')
    os.umask(0o077)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    m = load_legacy()
    pins = json.loads(m.read(PINS, PINS_SHA))
    prior = json.loads(m.read(PRIOR_RELEASE / 'deployed.json', PRIOR_DEPLOYED_SHA))
    enabled = json.loads(m.read(ENABLED_RECEIPT, ENABLED_RECEIPT_SHA))
    logging = json.loads(m.read(LOGGING_RECEIPT, LOGGING_RECEIPT_SHA))
    need(prior['stage'] == 'GOOGLE_BUSINESS_DEPLOYED_VERIFIED' and prior['deployed'] is True and
        prior['source_sha'] == BASE_SOURCE and prior['frontend_version'] == BASE_FRONTEND and
        prior['schema_revision'] == BASE_REVISION, 'EXACT_PRIOR_RELEASE_REQUIRED')
    need(enabled['stage'] == 'GBP_CONFIG_ENABLED_EXISTING_CANDIDATE_VERIFIED' and enabled['enabled'] is True and
        enabled['source_sha'] == BASE_SOURCE and enabled['frontend_version'] == BASE_FRONTEND and
        enabled['schema_revision'] == BASE_REVISION and enabled['crm'] == BASE_RUNTIME and
        enabled['active_nginx_config_sha256'] == ACTIVE_NGINX_SHA and enabled['callback_sentinel_verified'] is True,
        'EXACT_ENABLED_RECEIPT_REQUIRED')
    need(logging['active_nginx_config_sha256'] == ACTIVE_NGINX_SHA and logging['callback_sentinel_verified'] is True,
        'EXACT_CALLBACK_PROTECTION_RECEIPT_REQUIRED')
    crm = m.inspect('t24-crm')
    need(crm['State']['Running'] is True and crm['Image'] == BASE_IMAGE and m.runtime(crm) == BASE_RUNTIME,
        'CURRENT_ENABLED_RUNTIME_DRIFT')
    environment = environment_proof(crm)
    m.retained().require_safe_original_restart(crm)
    m.verify_secret_mount(crm)
    m.verify_production_worker_enabled(crm)
    private = private_metadata_boundary(m, pins)
    credential = m.credential_boundary()  # Stripe credential lstat + hash-pinned provisioning proof, never the key.
    gbp_credential = protected_metadata(GBP_ENV)
    inventory = m.inventory(crm['Id'])
    expected_inventory = json.loads(m.read(PRIOR_RELEASE / 'backend-candidate-inventory.json', prior['candidate_inventory_sha256']))
    need(inventory == expected_inventory, 'PRIOR_RELEASE_SOURCE_INVENTORY_DRIFT')
    schema = m.schema_signature(m.BUSINESS, BASE_REVISION)
    need(schema == prior['schema_sha256'], 'PRIOR_RELEASE_SCHEMA_DRIFT')
    identity_before = m.BUSINESS.stat()
    need((identity_before.st_dev, identity_before.st_ino) == BASE_DATABASE_IDENTITY, 'EXACT_BUSINESS_DATABASE_IDENTITY_REQUIRED')
    rows = m.sql_snapshot(m.BUSINESS)
    need(len(rows) == 124 and GOOGLE_TABLES <= rows.keys() and not NEW_TABLES & rows.keys(), 'EXACT_EXISTING_TABLE_SET_REQUIRED')
    nginx = m.NGINX.read_bytes()
    need(H(nginx) == NGINX_SHA, 'CALLBACK_PROTECTED_NGINX_DRIFT')
    active = m.run(['nginx', '-T'], 'NGINX_ACTIVE_PARSE_FAILED')
    need(H(active) == ACTIVE_NGINX_SHA and nginx.rstrip() in active and
        active.count(b'# configuration file /etc/nginx/sites-enabled/t24-crm:') == 1, 'ACTIVE_NGINX_CONFIGURATION_DRIFT')
    public = Path(prior['public_root'])
    need(public == Path('/var/www/t24-crm-public/google-business-7431d1986b81-20261030') and
        public.resolve() == public, 'EXACT_PUBLIC_ROOT_REQUIRED')
    static = m.tree(public)
    need(m.digest(static) == prior['public_inventory_sha256'] and
        json.loads((public / 'app-version.json').read_bytes())['version'] == BASE_FRONTEND, 'PRIOR_RELEASE_STATIC_DRIFT')
    m.ready(crm['Id'])
    need(rows == m.sql_snapshot(m.BUSINESS), 'ROWS_CHANGED_DURING_PREFLIGHT')
    need(m.runtime(crm) == m.runtime(m.inspect('t24-crm')) and environment == environment_proof(m.inspect('t24-crm')),
        'RUNTIME_CHANGED_DURING_PREFLIGHT')
    need(inventory == m.inventory(crm['Id']), 'SOURCE_CHANGED_DURING_PREFLIGHT')
    need(schema == m.schema_signature(m.BUSINESS, BASE_REVISION), 'SCHEMA_CHANGED_DURING_PREFLIGHT')
    need(nginx == m.NGINX.read_bytes() and active == m.run(['nginx', '-T'], 'NGINX_ACTIVE_PARSE_FAILED') and
        static == m.tree(public), 'PUBLIC_CONFIGURATION_CHANGED_DURING_PREFLIGHT')
    need(private == private_metadata_boundary(m, pins), 'PRIVATE_BOUNDARY_CHANGED_DURING_PREFLIGHT')
    need(credential == m.credential_boundary() and gbp_credential == protected_metadata(GBP_ENV), 'CREDENTIAL_METADATA_CHANGED_DURING_PREFLIGHT')
    identity = m.BUSINESS.stat()
    need((identity.st_dev, identity.st_ino) == (identity_before.st_dev, identity_before.st_ino), 'BUSINESS_DATABASE_IDENTITY_CHANGED_DURING_PREFLIGHT')
    return {'stage': 'MEDIA_OPS_MANAGEMENT_READONLY_PREFLIGHT', 'observed_at': datetime.now(timezone.utc).isoformat(),
        'host': HOST, 'source_sha': BASE_SOURCE, 'frontend_version': BASE_FRONTEND, 'schema_revision': BASE_REVISION,
        'schema_sha256': schema, 'crm': m.runtime(crm), 'backend_inventory_sha256': m.digest(inventory),
        'backend_file_count': len(inventory), 'backend_changed_before': {key: inventory.get(key) for key in sorted(BACKEND_FILES)},
        'database_identity': [identity.st_dev, identity.st_ino], 'rows': snapshot_evidence(rows),
        'original_columns': {name: row['columns'] for name, row in sorted(rows.items())},
        'google_tables_may_contain_existing_data': True, 'google_tables_preserved': True,
        'nginx_sha256': H(nginx), 'active_nginx_config_sha256': H(active), 'callback_logging_protection_retained': True,
        'callback_protection_receipt_sha256': LOGGING_RECEIPT_SHA, 'public_root': str(public),
        'public_inventory_sha256': m.digest(static), 'public_file_count': len(static),
        'prior_deployed_sha256': PRIOR_DEPLOYED_SHA, 'enabled_receipt_sha256': ENABLED_RECEIPT_SHA,
        'credential_boundary': credential, 'google_credential_metadata': gbp_credential,
        **private, **environment, 'provider_requests': False, 'business_writes': False,
        'container_or_configuration_changed': False, 'credential_content_read': False, 'customer_records_exported': False}


def main():
    value = proof()
    body = encoded(value)
    print(json.dumps({'stage': value['stage'], 'proof_bytes': len(body), 'proof_sha256': H(body),
        'proof_zlib_base64': base64.b64encode(zlib.compress(body, 9)).decode()}))


if __name__ == '__main__':
    try:
        main()
    except BaseException as error:
        print(json.dumps({'stage': 'MEDIA_OPS_MANAGEMENT_PREFLIGHT_REJECTED', 'code': safe_error(error)}))
        raise SystemExit(1)
