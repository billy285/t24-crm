"""Read-only fresh Meta-disabled baseline; no provider, configuration or business writes."""
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
BASE_SOURCE = '04a42942ce128f74c77db9250f2e7a28485b5c32'
BACKEND_SOURCE = '5931e430e629fb633f846ebc068a8fc12d4b9a0a'
BASE_FRONTEND = 'f3e9e6f7bfa0'
REVISION = 'acd7c9d0e136'
OLD = Path('/opt/t24-crm/releases/google-photo-preview-retry-04a42942ce12-20261031')
OLD_PREFLIGHT_SHA = 'a37a2a742ab97fac3194fb902b0e687bd847d2166ec82b09608947d437eccfbb'
OLD_RELEASE_SHA = '2b6213b00960ce4b8ec55baf2cb3d92eb029584bc49006a18441dfaa89552312'
DEPLOYED_SHA = 'ece3827fd84049525823e672ad9b76288b929894d01b8f900c3e0c722c711200'
ORIGINAL_ID = '987ff7a2f5dffcc72efdedc58e915c5efd75ef46c1b80266ede7c6f805aca153'
IMAGE = 'sha256:222b2dd5e48e358ec4ec80a4caf8acc05209d9f6b16ab1a09150622b88864b70'
ACTIVATION_FROM = '2026-10-30T19:42:04Z'
BACKEND_FILES = frozenset({'models/meta_business.py', 'services/meta_business_provider.py', 'services/meta_business.py', 'routers/meta_business.py', 'alembic/versions/bde8da01f247_meta_business_connections.py'})
META_TABLES = frozenset({'meta_business_connections', 'meta_business_oauth_states', 'meta_business_assets', 'meta_business_bindings', 'meta_business_requests'})
META_CALLBACK = '/api/v1/meta-business/oauth/callback'
DELIVERY_PREFIX = '/api/v1/media-publication-images/delivery/'
CALLBACK = '/api/v1/google-business/oauth/callback'


def need(ok, code):
    if not ok: raise RuntimeError(code)


def digest(value): return H(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())


def read(path, sha=None):
    row = path.lstat()
    need(path.resolve() == path and stat.S_ISREG(row.st_mode) and row.st_uid == 0 and row.st_nlink == 1 and stat.S_IMODE(row.st_mode) == 0o600, 'PROTECTED_TOOL_REQUIRED')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        opened = os.fstat(stream.fileno()); body = stream.read(1048577)
    after = path.lstat()
    fields = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns, value.st_nlink)
    need(fields(row) == fields(opened) == fields(after) and len(body) <= 1048576 and (sha is None or H(body) == sha), 'PINNED_TOOL_HASH_REQUIRED')
    return body


def load(path, sha, name):
    module = types.ModuleType(name); module.__file__ = str(path)
    exec(compile(read(path, sha), str(path), 'exec'), module.__dict__)
    return module


def dependencies():
    previous = load(OLD / 'preflight.py', OLD_PREFLIGHT_SHA, '_meta_retained_static_preflight')
    values = previous.dependencies()
    need(isinstance(values, tuple) and len(values) == 6, 'RETAINED_DEPENDENCY_ARITY_REQUIRED')
    helper, m, base, safe, workflow, _ = values
    static = load(OLD / 'release.py', OLD_RELEASE_SHA, '_meta_retained_static_release')
    return helper, m, base, safe, workflow, static, previous


def google_environment(info):
    values = {}
    for value in info['Config']['Env']:
        need(isinstance(value, str) and '=' in value and not any(c in value for c in '\r\n\0'), 'EXACT_ENVIRONMENT_FORMAT_REQUIRED')
        key, val = value.split('=', 1); need(key not in values, 'DUPLICATE_ENVIRONMENT_KEY'); values[key] = val
    expected = {'T24_GBP_ENABLED', 'T24_GBP_API_APPROVED', 'T24_GBP_CLIENT_ID', 'T24_GBP_CLIENT_SECRET', 'T24_GBP_TOKEN_KEY', 'T24_GBP_PUBLIC_URL', 'T24_GBP_SCHEDULER_ENABLED', 'T24_GBP_SCHEDULER_ACTIVATION_FROM'}
    need({key for key in values if key.startswith('T24_GBP_')} == expected, 'EXACT_EXISTING_GOOGLE_ENVIRONMENT_REQUIRED')
    need(values['T24_GBP_ENABLED'] == values['T24_GBP_API_APPROVED'] == values['T24_GBP_SCHEDULER_ENABLED'] == 'true', 'EXISTING_GOOGLE_WORKER_MUST_REMAIN_ENABLED')
    need(values['T24_GBP_PUBLIC_URL'] == 'https://t24-crm.com' and values['T24_GBP_SCHEDULER_ACTIVATION_FROM'] == ACTIVATION_FROM, 'EXACT_EXISTING_GOOGLE_CUTOFF_REQUIRED')


def meta_environment(info):
    need(not any(value.split('=', 1)[0].startswith('T24_META_') for value in info['Config']['Env']), 'NEW_META_ENVIRONMENT_MUST_START_ABSENT_DISABLED')


def privacy_blocks(workflow, active):
    _, blocks = workflow.nginx_blocks(active)
    servers = [row for row in blocks if row['header'] == ['server'] and any(d[0] == 'server_name' and 't24-crm.com' in d[1:] for d in row['directives']) and any(d[0] == 'listen' and any(v == '443' or v.endswith(':443') for v in d[1:]) for d in row['directives'])]
    need(len(servers) == 1, 'EXACT_CRM_HTTPS_SERVER_REQUIRED'); server = servers[0]
    for header in (['location', '=', CALLBACK], ['location', '^~', DELIVERY_PREFIX]):
        rows = [row for row in blocks if row['parent'] is server and row['header'] == header]
        need(len(rows) == 1 and ['access_log', 'off'] in rows[0]['directives'] and ['error_log', '/dev/null', 'crit'] in rows[0]['directives'], 'EXISTING_CALLBACK_AND_DELIVERY_PRIVACY_REQUIRED')
    workflow.delivery_log_paths(active)


def security_headers(m):
    argv = ['curl', '-q', '--silent', '--show-error', '--noproxy', '*', '--http1.1', '--max-time', '5', '--max-redirs', '0', '--resolve', 't24-crm.com:443:127.0.0.1', '-D', '-', '-o', '/dev/null', 'https://t24-crm.com/media-ops']
    body = m.run(argv, 'LOCAL_CSP_HEADER_READ_FAILED', 10)
    need(isinstance(body, bytes) and len(body) < 16384, 'BOUNDED_CSP_HEADERS_REQUIRED')
    lines = body.decode('iso-8859-1').splitlines()
    need(lines and re.fullmatch(r'HTTP/1[.]1 200(?: .*)?', lines[0]), 'EXACT_PUBLIC_SPA_200_REQUIRED')
    values = [line.split(':', 1)[1].strip() for line in lines[1:] if ':' in line and line.split(':',1)[0].lower() == 'content-security-policy']
    need(len(values) == 1 and bool(values[0]) and len(values[0]) < 8192 and 'img-src' in values[0], 'EXACT_EXISTING_CSP_HEADER_REQUIRED')
    return {'content_security_policy_sha256': H(values[0].encode())}


def baseline(helper, m, base, safe, workflow, static_release, previous):
    receipt = json.loads(read(OLD / 'deployed.json', DEPLOYED_SHA))
    need(receipt['stage'] == 'GOOGLE_PHOTO_PREVIEW_DEPLOYED_STATIC_VERIFIED' and receipt['backend_source_sha'] == BACKEND_SOURCE and receipt['deployed'] is True and receipt['source_sha'] == BASE_SOURCE and receipt['frontend_version'] == BASE_FRONTEND and receipt['schema_revision'] == REVISION, 'EXACT_DEPLOYED_SOURCE_REQUIRED')
    need(receipt['scheduler_enabled'] is True and receipt['scheduler_activation_from'] == ACTIVATION_FROM and receipt['crm']['id'] == ORIGINAL_ID and receipt['crm']['image'] == IMAGE, 'EXACT_ENABLED_RUNTIME_RECEIPT_REQUIRED')
    need(all(receipt[key] is True for key in ('runtime_and_backend_unchanged', 'all_136_rows_and_schema_unchanged', 'existing_image_policies_and_data_preserved', 'callback_and_image_privacy_configuration_preserved')), 'EXACT_PRIOR_DEPLOYMENT_BOUNDARIES_REQUIRED')
    crm = m.inspect('t24-crm'); need(crm['State']['Running'] is True and m.runtime(crm) == receipt['crm'], 'ENABLED_RUNTIME_DRIFT')
    google_environment(crm); m.verify_secret_mount(crm); m.verify_production_worker_enabled(crm); m.retained().require_safe_original_restart(crm)
    inventory = m.inventory(crm['Id'])
    core_receipt = json.loads(previous.read(previous.OLD / 'deployed.json', previous.DEPLOYED_SHA))
    need(core_receipt['source_sha'] == BACKEND_SOURCE and core_receipt['crm'] == receipt['crm'] and H((json.dumps(inventory, sort_keys=True, indent=2) + '\n').encode()) == core_receipt['candidate_inventory_sha256'], 'EXACT_DEPLOYED_BACKEND_REQUIRED')
    need(not set(BACKEND_FILES).intersection(inventory), 'META_RUNTIME_PATCHES_MUST_NOT_ALREADY_EXIST')
    meta_environment(crm)
    need(m.schema_signature(m.BUSINESS, REVISION) == receipt['schema_sha256'], 'DEPLOYED_SCHEMA_DRIFT')
    static = Path(receipt['public_root']); need(m.digest(m.tree(static)) == receipt['public_inventory_sha256'] and json.loads((static / 'app-version.json').read_bytes())['version'] == BASE_FRONTEND, 'DEPLOYED_STATIC_DRIFT')
    body = m.NGINX.read_bytes(); active = m.run(['nginx', '-T'], 'ACTIVE_NGINX_REQUIRED')
    prior_proof = json.loads(previous.read(Path('/opt/t24-crm/releases/google-photo-preview-preflight-' + receipt['preflight_sha256'][:12] + '.json'), receipt['preflight_sha256']))
    new, old = os.fsencode(receipt['public_root']), os.fsencode(prior_proof['public_root'])
    need(H(body) == receipt['nginx_sha256'] and active.count(new) == 1 and H(active.replace(new, old, 1)) == prior_proof['active_nginx_config_sha256'], 'EXACT_DEPLOYED_NGINX_REQUIRED'); privacy_blocks(workflow, active)
    need(META_CALLBACK.encode() not in active, 'META_CALLBACK_LOCATION_MUST_NOT_ALREADY_EXIST')
    pins = json.loads(m.read(base.PRIVATE_PINS, base.PRIVATE_PINS_SHA)); private = safe.safe_private_boundary(m, pins)
    headers = security_headers(m)
    identity = m.BUSINESS.stat(); snapshot = m.sql_snapshot(m.BUSINESS); rows = workflow.evidence(snapshot)
    need(len(rows) == 136 and workflow.NEW_TABLES <= set(rows) and not META_TABLES.intersection(rows), 'EXACT_EXISTING_136_TABLES_REQUIRED')
    return {'stage': 'META_BUSINESS_READONLY_PREFLIGHT', 'host': HOST, 'source_sha': BASE_SOURCE, 'backend_source_sha': BACKEND_SOURCE, 'frontend_version': BASE_FRONTEND, 'schema_revision': REVISION, 'schema_sha256': receipt['schema_sha256'], 'deployed_sha256': DEPLOYED_SHA, 'host_docker_timestamp_parser_verified': True, 'crm': m.runtime(crm), 'database_identity': [identity.st_dev, identity.st_ino], 'database_metadata': helper.db_metadata(m.BUSINESS), 'rows': rows, 'backend_inventory_sha256': digest(inventory), 'backend_file_count': len(inventory), 'backend_changed_before': {name: inventory.get(name) for name in sorted(BACKEND_FILES)}, 'public_root': str(static), 'public_inventory_sha256': receipt['public_inventory_sha256'], 'nginx_sha256': H(body), 'active_nginx_config_sha256': H(active), 'credential_boundary': m.credential_boundary(), 'google_credential_metadata': safe.protected_metadata(safe.GBP_ENV), 'private_boundary': private, 'environment_sha256': digest(sorted(crm['Config']['Env'])), 'content_security_policy_sha256': headers['content_security_policy_sha256'], 'scheduler_enabled': True, 'scheduler_activation_from': ACTIVATION_FROM, 'gbp_feature_enabled': True, 'meta_feature_enabled': False, 'meta_environment_keys_absent': True, 'meta_credentials_present': False, 'meta_callback_location_absent': True, 'callback_logging_protection_retained': True, 'image_delivery_logging_protection_retained': True, 'existing_image_policies_and_data_preserved': True, 'provider_requests': False, 'business_writes': False, 'private_content_read': False, 'credential_content_read': False, 'container_or_configuration_changed': False}


def collect():
    need(os.geteuid() == 0 and socket.gethostname() == HOST, 'EXACT_ROOT_SERVER_REQUIRED'); resource.setrlimit(resource.RLIMIT_CORE, (0, 0)); os.umask(0o077); sys.dont_write_bytecode = True
    values = dependencies(); values[0].docker_timestamp_probe(); proof = baseline(*values)
    current = baseline(*values)
    # Only the previously observed independent rate counter may move; adopt
    # the latest capture, while every row, schema and all other metadata agree.
    values[5].static_sequence_boundary(proof['database_metadata'], current['database_metadata'], values[4].sequence_boundary)
    normalized = {**current, 'database_metadata': proof['database_metadata']}
    need(proof == normalized, 'PREFLIGHT_CHANGED_DURING_READ'); return current


def capture():
    proof = collect(); body = (json.dumps(proof, sort_keys=True, indent=2) + '\n').encode(); sha = H(body); path = Path('/opt/t24-crm/releases/meta-business-preflight-' + sha[:12] + '.json')
    if path.exists(): need(read(path, sha) == body, 'EXISTING_PREFLIGHT_DRIFT')
    else:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream: stream.write(body); stream.flush(); os.fsync(stream.fileno())
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try: os.fsync(directory)
        finally: os.close(directory)
    keys = ('source_sha', 'backend_source_sha', 'frontend_version', 'schema_revision', 'schema_sha256', 'deployed_sha256', 'crm', 'backend_inventory_sha256', 'backend_changed_before', 'environment_sha256', 'content_security_policy_sha256', 'nginx_sha256', 'active_nginx_config_sha256', 'scheduler_enabled', 'scheduler_activation_from', 'gbp_feature_enabled', 'meta_feature_enabled', 'meta_environment_keys_absent', 'meta_credentials_present', 'meta_callback_location_absent', 'callback_logging_protection_retained', 'image_delivery_logging_protection_retained', 'existing_image_policies_and_data_preserved')
    print(json.dumps({'stage': 'META_BUSINESS_PREFLIGHT_CAPTURED', 'sha256': sha, 'bytes': len(body), 'path': str(path), **{key: proof[key] for key in keys}, 'rows_sha256': digest(proof['rows']), 'table_count': len(proof['rows']), 'private_boundary_verified': True, 'executed_business_writes': False, 'credential_content_read': False, 'private_content_read': False, 'host_docker_timestamp_parser_verified': True}, sort_keys=True))


if __name__ == '__main__':
    try: capture()
    except BaseException as error:
        value = str(error); code = value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}', value) else 'PREFLIGHT_REJECTED'
        print(json.dumps({'stage': 'META_BUSINESS_PREFLIGHT_REJECTED', 'code': code})); sys.exit(1)
