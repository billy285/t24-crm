"""Exact two-file image patch and exact runtime cloning. No migration or DB restore."""
import copy
import hashlib
import http.client
import itertools
import json
import os
from pathlib import Path, PurePosixPath
import re
import socket
import sqlite3
import stat
import subprocess
import time
from urllib.parse import quote

SCOPE = 'crm-customer-operations'
PATCH_FILES = ('routers/opportunities.py', 'services/commissions.py')
BASE_IMAGE = 'sha256:6f206710585b94f9b3cde35b8fa1b39407609bdb5625bd5ff800e9cc804fb334'
BASE_FILE_HASHES = {'routers/opportunities.py': 'c4ece534a2a68a8f9af75cf8ecee92f528844640f35399acd9b1064fbbcf3649', 'services/commissions.py': '58ae21b8818cf9e5f92ad790d95bc61f27c2815adb5606f2cbc80016530df13a'}
INVENTORY_SCRIPT = """import pathlib,hashlib,json
r=pathlib.Path('/app/backend');excluded={'data','logs','__pycache__','.git','.pytest_cache','.venv','node_modules','work'}
print(json.dumps({str(p.relative_to(r)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(r.rglob('*')) if p.is_file() and not p.is_symlink() and not any(x in excluded or x.startswith('.') for x in p.relative_to(r).parts) and p.suffix not in {'.pyc','.db','.log','.pem','.key'}}))
"""


def need(value, code):
    if not value:
        raise RuntimeError(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def run(args, code='RUNTIME_COMMAND_FAILED', timeout=90):
    result = subprocess.run(args, capture_output=True, timeout=timeout)
    need(result.returncode == 0 and len(result.stdout) <= 8388608, code)
    return result.stdout


def inspect(name):
    rows = json.loads(run(['docker', 'inspect', name], 'RUNTIME_INSPECT_FAILED'))
    need(isinstance(rows, list) and len(rows) == 1, 'SINGLE_RUNTIME_REQUIRED')
    return rows[0]


def missing_requested(result, name):
    if result.returncode != 1 or result.stdout.strip() != b'[]':
        return False
    pattern = rb'(?i:(?:error: |error response from daemon: )?no such (?:object|container): )' + re.escape(name.encode('utf-8')) + rb'\r?\n?'
    return re.fullmatch(pattern, result.stderr) is not None


def optional(name):
    result = subprocess.run(['docker', 'inspect', name], capture_output=True, timeout=30)
    if result.returncode:
        need(missing_requested(result, name), 'RUNTIME_LOOKUP_FAILED')
        return None
    rows = json.loads(result.stdout)
    need(isinstance(rows, list) and len(rows) == 1, 'SINGLE_OPTIONAL_RUNTIME_REQUIRED')
    return rows[0]


def networks(info):
    result = {}
    for name, value in info.get('NetworkSettings', {}).get('Networks', {}).items():
        need(not value.get('IPAMConfig'), 'STATIC_IP_REQUIRES_SEPARATE_REVIEW')
        result[name] = {key: copy.deepcopy(value[key]) for key in ('Aliases', 'Links', 'DriverOpts', 'GwPriority') if value.get(key) is not None}
        if 'Aliases' in result[name]:
            result[name]['Aliases'] = [v for v in result[name]['Aliases'] if v not in (info['Id'], info['Id'][:12])]
    need(bool(result), 'EXISTING_NETWORK_REQUIRED')
    return result


def sorted_mounts(info):
    return sorted(info['Mounts'], key=canonical)


def validate_layout(info, database):
    need(info['Image'] == BASE_IMAGE and info['HostConfig'].get('AutoRemove') is False, 'PRESERVED_BASE_RUNTIME_REQUIRED')
    need(info['HostConfig'].get('NetworkMode') == 'app_default', 'EXACT_EXISTING_NETWORK_MODE_REQUIRED')
    need(info['HostConfig'].get('RestartPolicy', {}).get('Name') in {'no', 'unless-stopped'}, 'ROLLBACK_RETENTION_RESTART_POLICY_REQUIRED')
    need(len(info['Mounts']) == 3, 'EXACT_THREE_EXISTING_MOUNTS_REQUIRED')
    expected = {'/app/backend/data': True, '/app/backend/logs': True, '/run/secrets/t24_crm_stripe_history_readonly': False}
    need({row['Destination']: row['RW'] for row in info['Mounts']} == expected and all(row['Type'] == 'bind' for row in info['Mounts']), 'EXACT_BIND_DESTINATIONS_AND_MODES_REQUIRED')
    need(any(row['Source'] == str(database.parent) and row['Destination'] == '/app/backend/data' for row in info['Mounts']), 'EXACT_PRODUCTION_DATABASE_MOUNT_REQUIRED')
    networks(info)


def validate_writable_layer(info, lines):
    parents = set()
    for row in info['Mounts']:
        path = PurePosixPath(row['Destination'])
        parents.add(str(path))
        parents.update(map(str, path.parents))
    for line in lines:
        need(len(line) > 2 and line[:2] in ('A ', 'C ', 'D '), 'VALID_WRITABLE_LAYER_DIFF_REQUIRED')
        name = line[2:]
        need(name.startswith('/') and '..' not in PurePosixPath(name).parts, 'CANONICAL_WRITABLE_LAYER_PATH_REQUIRED')
        cache = '__pycache__' in PurePosixPath(name).parts and (name.startswith('/app/backend/') or re.match(r'^/usr/(?:local/)?lib/python3\.\d+/', name))
        benign = name in parents or name in {'/tmp', '/run', '/var', '/var/tmp', '/root', '/root/.cache'} or name.startswith(('/tmp/', '/var/tmp/', '/root/.cache/')) or cache
        need(benign, 'UNREVIEWED_WRITABLE_LAYER_STATE')


def inventory(container):
    return json.loads(run(['docker', 'exec', container, 'python', '-I', '-S', '-B', '-c', INVENTORY_SCRIPT], 'LIVE_INVENTORY_FAILED'))


def cold_inventory(image):
    need(re.fullmatch(r'sha256:[a-f0-9]{64}', image), 'IMMUTABLE_LOCAL_IMAGE_REQUIRED')
    return json.loads(run(['docker', 'run', '--rm', '--network=none', '--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges', '--pids-limit=64', '--memory=256m', '--entrypoint=python', image, '-I', '-S', '-B', '-c', INVENTORY_SCRIPT], 'COLD_IMAGE_INVENTORY_FAILED'))


def expected_inventory(before, patch_hashes):
    need(isinstance(before, dict) and len(before) == 443 and all(before.get(name) == BASE_FILE_HASHES[name] for name in PATCH_FILES), 'EXACT_443_BASE_TWO_FILE_INVENTORY_REQUIRED')
    need(isinstance(patch_hashes, dict) and set(patch_hashes) == set(PATCH_FILES) and all(re.fullmatch('[a-f0-9]{64}', value) and value != BASE_FILE_HASHES[name] for name, value in patch_hashes.items()), 'EXACT_TWO_NEW_BACKEND_HASHES_REQUIRED')
    return {**before, **patch_hashes}



def clone_payload(original, image, source):
    need(re.fullmatch(r'sha256:[a-f0-9]{64}', image) and image != BASE_IMAGE and re.fullmatch('[a-f0-9]{40}', source), 'EXACT_NEW_IMAGE_AND_SOURCE_REQUIRED')
    need(original['HostConfig'].get('AutoRemove') is False, 'NO_AUTO_REMOVE_FOR_ROLLBACK_REQUIRED')
    config = copy.deepcopy(original['Config'])
    config['Image'] = image
    config['Hostname'] = ''
    config['Labels'] = {**(config.get('Labels') or {}), 't24.release.scope': SCOPE, 't24.release.source': source}
    config['HostConfig'] = copy.deepcopy(original['HostConfig'])
    config['NetworkingConfig'] = {'EndpointsConfig': networks(original)}
    return config


def configuration_equal(current, original, image, source, *, original_runtime=False, retained_name=None):
    expected = copy.deepcopy(original['Config'])
    if not original_runtime:
        expected['Image'] = image
        expected['Hostname'] = current['Id'][:12]
        expected['Labels'] = {**(expected.get('Labels') or {}), 't24.release.scope': SCOPE, 't24.release.source': source}
    need(current['Config'] == expected and current['Image'] == image, 'EXACT_RUNTIME_CONFIG_REQUIRED')
    host = dict(current['HostConfig'])
    # Docker29 serializes candidate OomKillDisable's explicit null default as false.
    if not original_runtime and 'OomKillDisable' in original['HostConfig'] and original['HostConfig']['OomKillDisable'] is None and host.get('OomKillDisable') is False:
        host['OomKillDisable'] = None
    need(host == original['HostConfig'], 'EXACT_HOST_SECURITY_AND_MOUNTS_REQUIRED')
    need(current['Config'].get('Env') == original['Config'].get('Env'), 'EXACT_RUNTIME_ENVIRONMENT_REQUIRED')
    need(sorted_mounts(current) == sorted_mounts(original), 'EXACT_ALL_MOUNT_FIELDS_REQUIRED')
    actual_networks, prior_networks = networks(current), networks(original)
    if original_runtime and retained_name:
        for row in actual_networks.values():
            if 'Aliases' in row:
                row['Aliases'] = ['t24-crm' if value == retained_name else value for value in row['Aliases']]
    need(actual_networks == prior_networks, 'EXACT_RUNTIME_NETWORK_ALIASES_REQUIRED')


class DockerConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect('/var/run/docker.sock')


def create_candidate(original, image, source):
    payload = clone_payload(original, image, source)
    connection = DockerConnection('localhost', timeout=45)
    try:
        connection.request('POST', '/containers/create?name=' + quote('t24-crm'), json.dumps(payload), {'Content-Type': 'application/json'})
        response = connection.getresponse()
        body = response.read(1048577)
        need(response.status == 201 and len(body) <= 1048576, 'CANDIDATE_CREATE_FAILED')
        ident = json.loads(body).get('Id', '')
        need(re.fullmatch('[a-f0-9]{64}', ident), 'EXACT_CANDIDATE_ID_REQUIRED')
        return ident
    finally:
        connection.close()


def ready(ident, timeout=65):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        result = subprocess.run(['docker', 'exec', ident, 'curl', '-q', '-fsS', '--max-time', '3', '--noproxy', '*', 'http://127.0.0.1:8000/ready'], capture_output=True, timeout=6)
        if result.returncode == 0:
            return
        need(inspect(ident)['State']['Running'], 'CANDIDATE_EXITED_BEFORE_READY')
        time.sleep(0.5)
    raise RuntimeError('CANDIDATE_READINESS_TIMEOUT')


def schema_metadata(database):
    connection = sqlite3.connect('file:' + str(database) + '?mode=ro', uri=True)
    try:
        connection.execute('PRAGMA query_only=ON')
        connection.execute('BEGIN')
        revision = connection.execute('SELECT version_num FROM alembic_version').fetchall()
        definitions = [list(row) for row in connection.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name")]
        return {'revision': revision, 'sha256': digest(definitions), 'table_count': sum(row[0] == 'table' for row in definitions)}
    finally:
        connection.close()


def backup_clone(source, target):
    need(not target.exists(), 'FRESH_PRIVATE_CLONE_REQUIRED')
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    os.close(fd)
    old = sqlite3.connect('file:' + str(source) + '?mode=ro', uri=True)
    clone = sqlite3.connect(target)
    try:
        old.execute('PRAGMA query_only=ON')
        old.backup(clone)
    finally:
        old.close()
        clone.close()
    need(stat.S_IMODE(target.stat().st_mode) == 0o600, 'ROOT_PRIVATE_DB_CLONE_REQUIRED')


def offline_validation(image, clone, schema_head, schema_sha):
    # No original environment or credential mount is exposed to this process.
    script = """import sys,pathlib,sqlite3,json,hashlib
sys.path.insert(0,'/app/backend')
for name in ('routers/opportunities.py','services/commissions.py'):
 p=pathlib.Path('/app/backend')/name;compile(p.read_bytes(),str(p),'exec')
from routers.opportunities import router as opportunity_router,convert_opportunity
from services.commissions import _resolve_payment_scope
assert callable(convert_opportunity) and callable(_resolve_payment_scope)
assert any(r.path=='/api/v1/opportunities/{opportunity_id}/convert' and 'POST' in r.methods for r in opportunity_router.routes)
from routers.app_config import router,DEFAULT_CUSTOMER_FOLLOWUP_STATUSES,customer_followup_result
assert len(DEFAULT_CUSTOMER_FOLLOWUP_STATUSES.split(','))==8
assert {r.path for r in router.routes if r.path.endswith('/customer-followup-statuses')}=={'/api/v1/app-config/dict_config/customer-followup-statuses'}
assert {'GET','PATCH'} <= {m for r in router.routes if r.path.endswith('/customer-followup-statuses') for m in r.methods}
c=sqlite3.connect('file:/validation/crm_prod.db?mode=ro&immutable=1',uri=True);c.execute('PRAGMA query_only=ON')
assert c.execute('SELECT version_num FROM alembic_version').fetchall()==[(HEAD,)]
definitions=[list(r) for r in c.execute(\"SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name\")]
assert hashlib.sha256(json.dumps(definitions,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()==SCHEMA
assert len(customer_followup_result({})['active'].split(','))==8
c.close();print(json.dumps({'offline_import_and_project_linkage_valid':True,'service_dictionary_defaults_preserved':True,'schema_unchanged':True,'business_rows_read':False,'database_writes':False,'provider_network':False}))
"""
    prefix = 'HEAD=' + repr(schema_head) + ';SCHEMA=' + repr(schema_sha) + '\n'
    images = json.loads(run(['docker', 'image', 'inspect', image], 'OFFLINE_IMAGE_METADATA_READ_FAILED'))
    need(len(images) == 1 and images[0]['Id'] == image, 'EXACT_OFFLINE_IMAGE_REQUIRED')
    inherited = images[0].get('Config', {}).get('Env') or []
    need(isinstance(inherited, list) and all(isinstance(value, str) and re.fullmatch('[A-Za-z_][A-Za-z0-9_]*', value.split('=', 1)[0]) for value in inherited), 'BOUNDED_OFFLINE_ENVIRONMENT_REQUIRED')
    env = {value.split('=', 1)[0]: '' for value in inherited}
    env.update({'PATH': '/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C.UTF-8', 'PORT': '8000', 'LOG_LEVEL': 'INFO',
        'APP_ENV': 'test', 'ENVIRONMENT': 'test', 'ENV': 'test', 'DATABASE_SCHEMA_MODE': 'verify_only',
        'JWT_SECRET_KEY': 'offline-synthetic-jwt-012345678901234567890123456789',
        'MASK_KEY': 'offline-synthetic-mask-012345678901234567890123456789',
        'DATABASE_URL': 'sqlite+aiosqlite:////validation/crm_prod.db',
        'AUTOMATION_SCAN_ENABLED': 'false', 'STRIPE_HISTORY_DAILY_SCAN_ENABLED': 'false', 'STRIPE_AUTO_POSTING_ENABLED': 'false',
        'T24_GBP_SCHEDULER_ENABLED': 'false', 'T24_GBP_ENABLED': 'false', 'T24_GBP_API_APPROVED': 'false',
        'T24_META_OPS_SCHEDULER_ENABLED': 'false', 'T24_META_EXECUTION_ENABLED': 'false',
        'T24_MEDIA_MONTHLY_AUTOPREP_ENABLED': 'false', 'T24_MEDIA_ASSET_WORKER_ENABLED': 'false',
        'T24_GBP_ONBOARDING_WORKER_ENABLED': 'false', 'APP_AI_KEY': '', 'OPENAI_API_KEY': '',
        'ENABLE_MOCK_DATA': 'false', 'MGX_LOAD_INIT_DATA': 'false', 'PYTHONDONTWRITEBYTECODE': '1'})
    args = ['docker', 'run', '--rm', '--network=none', '--read-only', '--user=0:0', '--cap-drop=ALL', '--security-opt=no-new-privileges', '--pids-limit=128', '--memory=512m', '--tmpfs', '/tmp:rw,nosuid,noexec', '--mount', 'type=bind,src=' + str(clone) + ',dst=/validation/crm_prod.db,readonly', '--entrypoint=python']
    args += [part for key, value in env.items() for part in ('-e', key + '=' + value)]
    args += [image, '-I', '-B', '-c', prefix + script]
    return json.loads(run(args, 'OFFLINE_READONLY_VALIDATION_FAILED', timeout=120))
