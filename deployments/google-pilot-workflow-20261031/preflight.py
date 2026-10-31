"""Read-only 136-table baseline; retain existing image policies and Google worker."""
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
BASE_SOURCE = 'c114242205af98c33a7c2ad435409e0c84ebd085'
BASE_FRONTEND = '33047aa593a2'
REVISION = 'acd7c9d0e136'
OLD = Path('/opt/t24-crm/releases/media-workflow-c114242205af-20261031')
OLD_PREFLIGHT_SHA = 'a776108b6c877d8909fe0e41a5b0fb112d663acc9189e0db7f88883a97c39164'
OLD_RELEASE_SHA = '0ca6e6af5a32769740cc6bef4d51c6cf20aa6157d0ef8757f3ba84a9975d9eb3'
DEPLOYED_SHA = '5639019ef95f88523eea7dc0548a74c0d7705871d7af834bb0b3b33d24ebd3bc'
ORIGINAL_ID = 'e46b65eeb94bf09412841c2bd6a71408d9920def8eb2e33a1a02c3becdf5f45b'
IMAGE = 'sha256:7d894afd3c3f19a0976a54a0bfd31b05f204cf71c41b2990fd8f0fb5f07558e8'
ACTIVATION_FROM = '2026-10-30T19:42:04Z'
BACKEND_FILES = frozenset({'routers/google_business.py', 'services/google_business_readiness.py'})
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
    previous = load(OLD / 'preflight.py', OLD_PREFLIGHT_SHA, '_pilot_retained_preflight')
    values = previous.dependencies()
    need(isinstance(values, tuple) and len(values) == 4, 'RETAINED_DEPENDENCY_ARITY_REQUIRED')
    helper, m, base, safe = values
    workflow = load(OLD / 'release.py', OLD_RELEASE_SHA, '_pilot_retained_workflow')
    return helper, m, base, safe, workflow, previous


def google_environment(info):
    values = {}
    for value in info['Config']['Env']:
        need(isinstance(value, str) and '=' in value and not any(c in value for c in '\r\n\0'), 'EXACT_ENVIRONMENT_FORMAT_REQUIRED')
        key, val = value.split('=', 1); need(key not in values, 'DUPLICATE_ENVIRONMENT_KEY'); values[key] = val
    expected = {'T24_GBP_ENABLED', 'T24_GBP_API_APPROVED', 'T24_GBP_CLIENT_ID', 'T24_GBP_CLIENT_SECRET', 'T24_GBP_TOKEN_KEY', 'T24_GBP_PUBLIC_URL', 'T24_GBP_SCHEDULER_ENABLED', 'T24_GBP_SCHEDULER_ACTIVATION_FROM'}
    need({key for key in values if key.startswith('T24_GBP_')} == expected, 'EXACT_EXISTING_GOOGLE_ENVIRONMENT_REQUIRED')
    need(values['T24_GBP_ENABLED'] == values['T24_GBP_API_APPROVED'] == values['T24_GBP_SCHEDULER_ENABLED'] == 'true', 'EXISTING_GOOGLE_WORKER_MUST_REMAIN_ENABLED')
    need(values['T24_GBP_PUBLIC_URL'] == 'https://t24-crm.com' and values['T24_GBP_SCHEDULER_ACTIVATION_FROM'] == ACTIVATION_FROM, 'EXACT_EXISTING_GOOGLE_CUTOFF_REQUIRED')


def privacy_blocks(workflow, active):
    _, blocks = workflow.nginx_blocks(active)
    servers = [row for row in blocks if row['header'] == ['server'] and any(d[0] == 'server_name' and 't24-crm.com' in d[1:] for d in row['directives']) and any(d[0] == 'listen' and any(v == '443' or v.endswith(':443') for v in d[1:]) for d in row['directives'])]
    need(len(servers) == 1, 'EXACT_CRM_HTTPS_SERVER_REQUIRED'); server = servers[0]
    for header in (['location', '=', CALLBACK], ['location', '^~', DELIVERY_PREFIX]):
        rows = [row for row in blocks if row['parent'] is server and row['header'] == header]
        need(len(rows) == 1 and ['access_log', 'off'] in rows[0]['directives'] and ['error_log', '/dev/null', 'crit'] in rows[0]['directives'], 'EXISTING_CALLBACK_AND_DELIVERY_PRIVACY_REQUIRED')
    workflow.delivery_log_paths(active)


def baseline(helper, m, base, safe, workflow, previous):
    need(bool(BACKEND_FILES), 'EXACT_REVIEWED_PATCH_SCOPE_REQUIRED')
    receipt = json.loads(read(OLD / 'deployed.json', DEPLOYED_SHA))
    need(receipt['stage'] == 'MEDIA_WORKFLOW_DEPLOYED_VERIFIED' and receipt['deployed'] is True and receipt['source_sha'] == BASE_SOURCE and receipt['frontend_version'] == BASE_FRONTEND and receipt['schema_revision'] == REVISION, 'EXACT_DEPLOYED_SOURCE_REQUIRED')
    need(receipt['scheduler_enabled'] is True and receipt['scheduler_activation_from'] == ACTIVATION_FROM and receipt['crm']['id'] == ORIGINAL_ID and receipt['crm']['image'] == IMAGE, 'EXACT_ENABLED_RUNTIME_RECEIPT_REQUIRED')
    need(all(receipt[key] is True for key in ('original_env_mounts_network_unchanged', 'existing_google_environment_preserved', 'private_runtime_unchanged', 'delivery_prefix_logging_protected')), 'EXACT_PRIOR_DEPLOYMENT_BOUNDARIES_REQUIRED')
    crm = m.inspect('t24-crm'); need(crm['State']['Running'] is True and m.runtime(crm) == receipt['crm'], 'ENABLED_RUNTIME_DRIFT')
    google_environment(crm); m.verify_secret_mount(crm); m.verify_production_worker_enabled(crm); m.retained().require_safe_original_restart(crm)
    inventory = m.inventory(crm['Id'])
    need(H((json.dumps(inventory, sort_keys=True, indent=2) + '\n').encode()) == receipt['candidate_inventory_sha256'], 'EXACT_DEPLOYED_BACKEND_REQUIRED')
    need(m.schema_signature(m.BUSINESS, REVISION) == receipt['schema_sha256'], 'DEPLOYED_SCHEMA_DRIFT')
    static = Path(receipt['public_root']); need(m.digest(m.tree(static)) == receipt['public_inventory_sha256'] and json.loads((static / 'app-version.json').read_bytes())['version'] == BASE_FRONTEND, 'DEPLOYED_STATIC_DRIFT')
    body = m.NGINX.read_bytes(); active = m.run(['nginx', '-T'], 'ACTIVE_NGINX_REQUIRED')
    need(H(body) == receipt['nginx_sha256'] and H(active) == receipt['sentinel_active_nginx_sha256'] and active.count(os.fsencode(receipt['public_root'])) == 1, 'EXACT_DEPLOYED_NGINX_REQUIRED'); privacy_blocks(workflow, active)
    pins = json.loads(m.read(base.PRIVATE_PINS, base.PRIVATE_PINS_SHA)); private = safe.safe_private_boundary(m, pins)
    identity = m.BUSINESS.stat(); snapshot = m.sql_snapshot(m.BUSINESS); rows = workflow.evidence(snapshot)
    need(len(rows) == 136 and workflow.NEW_TABLES <= set(rows), 'EXACT_EXISTING_136_TABLES_REQUIRED')
    return {'stage': 'GOOGLE_PILOT_WORKFLOW_READONLY_PREFLIGHT', 'host': HOST, 'source_sha': BASE_SOURCE, 'frontend_version': BASE_FRONTEND, 'schema_revision': REVISION, 'schema_sha256': receipt['schema_sha256'], 'deployed_sha256': DEPLOYED_SHA, 'host_docker_timestamp_parser_verified': True, 'crm': m.runtime(crm), 'database_identity': [identity.st_dev, identity.st_ino], 'database_metadata': helper.db_metadata(m.BUSINESS), 'rows': rows, 'backend_inventory_sha256': digest(inventory), 'backend_file_count': len(inventory), 'backend_changed_before': {name: inventory.get(name) for name in sorted(BACKEND_FILES)}, 'public_root': str(static), 'public_inventory_sha256': receipt['public_inventory_sha256'], 'nginx_sha256': H(body), 'active_nginx_config_sha256': H(active), 'credential_boundary': m.credential_boundary(), 'google_credential_metadata': safe.protected_metadata(safe.GBP_ENV), 'private_boundary': private, 'environment_sha256': digest(sorted(crm['Config']['Env'])), 'scheduler_enabled': True, 'scheduler_activation_from': ACTIVATION_FROM, 'gbp_feature_enabled': True, 'callback_logging_protection_retained': True, 'image_delivery_logging_protection_retained': True, 'existing_image_policies_and_data_preserved': True, 'provider_requests': False, 'business_writes': False, 'private_content_read': False, 'credential_content_read': False, 'container_or_configuration_changed': False}


def collect():
    need(os.geteuid() == 0 and socket.gethostname() == HOST, 'EXACT_ROOT_SERVER_REQUIRED'); resource.setrlimit(resource.RLIMIT_CORE, (0, 0)); os.umask(0o077); sys.dont_write_bytecode = True
    values = dependencies(); values[0].docker_timestamp_probe(); proof = baseline(*values)
    need(proof == baseline(*values), 'PREFLIGHT_CHANGED_DURING_READ'); return proof


def capture():
    proof = collect(); body = (json.dumps(proof, sort_keys=True, indent=2) + '\n').encode(); sha = H(body); path = Path('/opt/t24-crm/releases/google-pilot-workflow-preflight-' + sha[:12] + '.json')
    if path.exists(): need(read(path, sha) == body, 'EXISTING_PREFLIGHT_DRIFT')
    else:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream: stream.write(body); stream.flush(); os.fsync(stream.fileno())
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try: os.fsync(directory)
        finally: os.close(directory)
    keys = ('source_sha', 'frontend_version', 'schema_revision', 'schema_sha256', 'deployed_sha256', 'crm', 'backend_changed_before', 'backend_inventory_sha256', 'environment_sha256', 'nginx_sha256', 'active_nginx_config_sha256', 'scheduler_enabled', 'scheduler_activation_from', 'gbp_feature_enabled', 'callback_logging_protection_retained', 'image_delivery_logging_protection_retained', 'existing_image_policies_and_data_preserved')
    print(json.dumps({'stage': 'GOOGLE_PILOT_WORKFLOW_PREFLIGHT_CAPTURED', 'sha256': sha, 'bytes': len(body), 'path': str(path), **{key: proof[key] for key in keys}, 'rows_sha256': digest(proof['rows']), 'table_count': len(proof['rows']), 'private_boundary_verified': True, 'executed_business_writes': False, 'credential_content_read': False, 'private_content_read': False, 'host_docker_timestamp_parser_verified': True}, sort_keys=True))


if __name__ == '__main__':
    try: capture()
    except BaseException as error:
        value = str(error); code = value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}', value) else 'PREFLIGHT_REJECTED'
        print(json.dumps({'stage': 'GOOGLE_PILOT_WORKFLOW_PREFLIGHT_REJECTED', 'code': code})); sys.exit(1)
