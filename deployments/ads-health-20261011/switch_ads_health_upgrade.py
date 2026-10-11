#!/usr/bin/env python3
"""Reviewed private-service/static switch; never modifies the running CRM or DB.

All credentials and raw docker inspection remain in memory. Receipts contain
only hashes, counts, IDs and controlled failure codes. Rollback never restores a
database or deletes retained old containers.
"""
import argparse
import fcntl
import hashlib
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
import urllib.error
import urllib.request
from uuid import uuid4

SOURCE = 'dd8061ca30b91554f3f431446616dffc12c81b7a'
VERSION = 'dc6e92e22ef7'
HOST = 'iZj6c4cj7edgnhdimts4l7Z'
CRM_ID = 'ca45180be18981a7c3727a9c7a031690946f2c4c77f0cd96608fc65da3a3fb26'
CRM_IMAGE = 'sha256:7a1b09bbb04899e7c6459491d32c45c25d789801a51b4a95e9b77b7dafcbb4ab'
CRM_STARTED = '2026-10-10T17:19:07.948520307Z'
CRM_CONFIG = '2e5c793eae3c192963037652717f91b402d351372378350f44dc2294fa85bdc0'
BASE_IMAGE = 'sha256:ce90e93f5420d940fce431cd23cdc8f9e95a6d18d41167fe46a4ebf2738862a8'
OLD_IDS = {'api': '627de60395d238990245c8a3958255508896ecd31aa0218b5c63283e8500a443',
           'worker': 'a1ae1e9b72c48439495da120e51d1148fc145f2d2592c5301404e8c8a4b353b1'}
CURRENT_ENV_SHA = '180f945729234df79c45f5148663f8407c75be55aa8d4e79107305c03c00f82d'
NGINX_SHA = '3d1789e13931fa5de24ec693ca069e134733e9961154bd1c0e77fa7a004c1ed2'
BASELINE_SHA = '0b545f9b16f886d93e346102429feee7f87639dfd3ab23c387aab2da5f75aa9e'
PRIVATE_PROOFS = {
    'api': {'configuration_sha256': 'e451a271d097e71d9dd44d895d89507b3ac01cedd14db68035cc6c30be933b52', 'started_at': '2026-10-11T07:22:27.377186902Z'},
    'worker': {'configuration_sha256': '9d769daf19fa9ccaaeb6b6e9ca2b2e603b309a14837f404bd3f79310a5afbb4d', 'started_at': '2026-10-11T07:22:33.381758285Z'},
}
RELEASE = Path('/opt/t24-crm/releases/ads-health-dd8061c-20261011')
PUBLIC = Path('/var/www/t24-crm-public/ads-health-dd8061c-20261011')
OLD_PUBLIC = Path('/var/www/t24-crm-public/google-ads-d6fce13-20261011')
NGINX = Path('/etc/nginx/sites-enabled/t24-crm')
CONFIG = Path('/opt/t24-crm/private-workspace/config')
ENV = CONFIG / 'runtime.env'
BUSINESS = Path('/opt/t24-crm/app/data/crm_prod.db')
PRIVATE_DB = Path('/opt/t24-crm/private-workspace/data/workspace.db')
PREFIX = '/api/v1/private-workspace'
TARGET_KEY = 'PRIVATE_WORKSPACE_GOOGLE_ADS_CUSTOMER_ID'
TARGET_CUSTOMER = '7539806760'
ADDED_KEYS = {'GOOGLE_WORKSPACE_CLIENT_ID', 'GOOGLE_WORKSPACE_CLIENT_SECRET', 'PRIVATE_WORKSPACE_GMAIL_EXPECTED_ACCOUNT'}
BACKEND = ('services/private_workspace.py', 'services/private_workspace_providers.py', 'services/private_ads_health.py')
MIN_TESTS = 248
TABLES = {'private_connections', 'private_items', 'private_preferences', 'private_sync_runs'}
HEADERS = {
    'X-Frame-Options': 'SAMEORIGIN',
    'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self' data:; connect-src 'self' https: wss:; frame-ancestors 'self'; base-uri 'self'; form-action 'self'",
    'Strict-Transport-Security': 'max-age=31536000; includeSubDomains',
    'Referrer-Policy': 'strict-origin-when-cross-origin',
    'Permissions-Policy': 'camera=(), geolocation=(), microphone=(self)',
    'X-Content-Type-Options': 'nosniff',
}


class SwitchError(RuntimeError):
    pass


def need(condition, code):
    if not condition:
        raise SwitchError(code)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def digest(value):
    return sha(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())


def secure(path, directory=False, mode=None):
    info = path.lstat()
    need(path.resolve() == path and not stat.S_ISLNK(info.st_mode), 'PATH_ALIAS_REJECTED')
    need(info.st_uid == 0 and not stat.S_IMODE(info.st_mode) & 0o077, 'PROTECTED_PATH_REQUIRED')
    need(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
         'PROTECTED_TYPE_REQUIRED')
    if mode is not None:
        need(stat.S_IMODE(info.st_mode) == mode, 'PROTECTED_MODE_REQUIRED')
    return info


def read_protected(path, maximum=65536):
    before = secure(path, mode=0o600)
    need(before.st_size <= maximum, 'PROTECTED_FILE_SIZE_REJECTED')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        observed = os.fstat(stream.fileno())
        need((before.st_ino, before.st_dev) == (observed.st_ino, observed.st_dev), 'PROTECTED_FILE_CHANGED')
        data = stream.read(maximum + 1)
    need(len(data) <= maximum, 'PROTECTED_FILE_SIZE_REJECTED')
    return data


def write_new(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def fsync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def save(path, value, replace=False):
    data = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
    if replace:
        secure(path, mode=0o600)
        temporary = path.parent / ('.' + path.name + '-' + uuid4().hex)
        write_new(temporary, data)
        os.replace(temporary, path)
        fsync_directory(path.parent)
    else:
        write_new(path, data)


def run(command, code, timeout=30):
    # No raw output is logged: docker inspect/env and errors may contain secrets.
    result = subprocess.run(command, capture_output=True, timeout=timeout, check=False)
    need(result.returncode == 0, code)
    return result.stdout


def inspect(identity, optional=False):
    result = subprocess.run(['docker', 'inspect', identity], capture_output=True, timeout=30, check=False)
    if optional and result.returncode:
        return None
    need(result.returncode == 0, 'CONTAINER_INSPECT_FAILED')
    value = json.loads(result.stdout)
    need(len(value) == 1, 'SINGLE_CONTAINER_REQUIRED')
    return value[0]


def config_hash(value):
    return digest({'Config': value['Config'], 'HostConfig': value['HostConfig'],
                   'Mounts': sorted(value['Mounts'], key=digest)})


def crm_check(require_healthy=True):
    info = inspect('t24-crm')
    need(info['Id'] == CRM_ID and info['Image'] == CRM_IMAGE and info['State']['StartedAt'] == CRM_STARTED,
         'CRM_RUNTIME_DRIFT')
    if require_healthy:
        need(info['State']['Running'] and info['State'].get('Health', {}).get('Status') == 'healthy', 'CRM_HEALTH_DRIFT')
    need(len(info['Mounts']) == 2, 'CRM_MOUNT_COUNT_DRIFT')
    variants = [digest({'Config': info['Config'], 'HostConfig': info['HostConfig'], 'Mounts': list(order)})
                for order in itertools.permutations(info['Mounts'])]
    need(CRM_CONFIG in variants, 'CRM_CONFIGURATION_DRIFT')
    need(info['HostConfig']['PortBindings'].get('8000/tcp') == [{'HostIp': '127.0.0.1', 'HostPort': '8000'}],
         'CRM_PORT_DRIFT')
    return {'id': CRM_ID, 'image': CRM_IMAGE, 'started_at': CRM_STARTED, 'configuration_sha256': CRM_CONFIG}


def parse_env(data):
    need(data and len(data) <= 65536 and data.endswith(b'\n') and b'\r' not in data and b'\x00' not in data,
         'ENV_FORMAT_REJECTED')
    result = {}
    for row in data.decode('utf-8').splitlines():
        need('=' in row, 'ENV_ROW_REJECTED')
        name, value = row.split('=', 1)
        need(re.fullmatch('[A-Z][A-Z0-9_]*', name) and name not in result, 'ENV_KEY_REJECTED')
        result[name] = value
    return result


def env_check(old_bytes, new_bytes, expected_email):
    need(sha(old_bytes) == CURRENT_ENV_SHA and new_bytes == old_bytes, 'CURRENT_ENV_BYTES_CHANGED')
    values=parse_env(new_bytes)
    need(values.get(TARGET_KEY)==TARGET_CUSTOMER and not values.get('GOOGLE_ADS_LOGIN_CUSTOMER_ID','').strip() and
         (not values.get('GOOGLE_ADS_CUSTOMER_ID','').strip() or values['GOOGLE_ADS_CUSTOMER_ID'].strip().replace('-','')==TARGET_CUSTOMER),
         'DIRECT_TARGET_ENVIRONMENT_DRIFT')
    old, new = parse_env(old_bytes), parse_env(new_bytes)
    need(ADDED_KEYS <= set(new), 'CONNECTED_GMAIL_CONFIGURATION_REQUIRED')
    need(re.fullmatch(r'[A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z0-9-]+', expected_email) and
         new['PRIVATE_WORKSPACE_GMAIL_EXPECTED_ACCOUNT'].casefold() == expected_email.casefold(), 'EXPECTED_EMAIL_MISMATCH')
    need(re.fullmatch(r'\d{6,24}-[A-Za-z0-9_-]{10,128}\.apps\.googleusercontent\.com', new['GOOGLE_WORKSPACE_CLIENT_ID']) and
         re.fullmatch('[!-~]{16,256}', new['GOOGLE_WORKSPACE_CLIENT_SECRET']), 'GOOGLE_CONFIGURATION_INVALID')
    required = {'PRIVATE_WORKSPACE_OWNER_IDS': '4', 'PRIVATE_WORKSPACE_PUBLIC_URL': 'https://t24-crm.com',
                'PRIVATE_WORKSPACE_DATABASE_URL': 'sqlite+aiosqlite:////private-data/workspace.db',
                'DATABASE_URL': 'sqlite:///./data/crm_prod.db', 'DATABASE_SCHEMA_MODE': 'verify_only',
                'ENFORCE_EMPLOYEE_STATUS': 'true', 'ENFORCE_EMPLOYEE_SESSIONS': 'true'}
    need(all(new.get(k) == v for k, v in required.items()) and
         len(new.get('JWT_SECRET_KEY', '')) >= 32 and len(new.get('PRIVATE_WORKSPACE_ENCRYPTION_KEY', '')) >= 32,
         'PRIVATE_CONFIGURATION_DRIFT')
    return old, new


def docker_env(info):
    entries = info['Config']['Env']
    result = {}
    for row in entries:
        need('=' in row, 'CONTAINER_ENV_INVALID')
        name, value = row.split('=', 1)
        need(name not in result, 'CONTAINER_ENV_DUPLICATE')
        result[name] = value
    return result


def business_fingerprints(path=BUSINESS):
    need(path.is_file() and not path.is_symlink() and path.resolve() == path, 'BUSINESS_PATH_DRIFT')
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=15) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        need(db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'BUSINESS_INTEGRITY_FAILED')
        tables = sorted(row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'"))
        need(len(tables) == 83 and not any(t.startswith('private_') for t in tables), 'BUSINESS_SCHEMA_DRIFT')
        need(db.execute('SELECT version_num FROM alembic_version').fetchall() == [('ab6d8e2f0411',)], 'BUSINESS_SCHEMA_HEAD_DRIFT')
        need(db.execute('SELECT role,status FROM employees WHERE id=4').fetchall() == [('super_admin', 'active')], 'OWNER_IDENTITY_DRIFT')
        result = {}
        for table in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            rows = db.execute('SELECT * FROM ' + quoted).fetchall()
            encoded = sorted(json.dumps(list(row), ensure_ascii=False, sort_keys=True,
                             default=lambda value: {'hex': value.hex()}, separators=(',', ':')) for row in rows)
            result[table] = {'count': len(rows), 'sha256': sha(('\n'.join(encoded)).encode())}
        schema = list(db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"))
        return {'schema_sha256': digest(schema), 'tables': result}


def private_snapshot(path=PRIVATE_DB, full=False):
    info = secure(path, mode=0o600)
    need((info.st_dev, info.st_ino) == (64515, 282885), 'PRIVATE_DATABASE_IDENTITY_DRIFT')
    need(not os.path.samefile(path, BUSINESS), 'DATABASES_ALIASED')
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=15) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        need(db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'PRIVATE_INTEGRITY_FAILED')
        names = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        need(names == TABLES, 'PRIVATE_TABLE_SCOPE_DRIFT')
        schema = list(db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"))
        # Full content hashes are computed only while the old worker is frozen;
        # no mail, ciphertext or preferences are returned in release receipts.
        rows = {}
        if full:
            for table in sorted(TABLES):
                encoded = sorted(json.dumps(list(row), sort_keys=True, separators=(',', ':'),
                                 default=lambda value: {'hex': value.hex()}) for row in db.execute('SELECT * FROM ' + table))
                rows[table] = sha(('\n'.join(encoded)).encode())
        # After the candidate worker starts, sync may change provider data,
        # priorities, timestamps, access tokens and sync-run rows. Preserve user
        # overrides and stable record keys rather than reading full mail again.
        items = {row[0]: digest(list(row)) for row in db.execute(
            'SELECT id,owner_id,source_id,external_id,local_title,local_summary,action_status,snoozed_until,created_at FROM private_items')}
        preferences = {row[0]: digest(list(row)) for row in db.execute('SELECT owner_id,preferences_json FROM private_preferences')}
        connections = {}
        for identity, owner, source, status, generation, metadata in db.execute(
                'SELECT id,owner_id,source_id,status,generation,metadata_json FROM private_connections'):
            metadata = json.loads(metadata or '{}')
            connections[identity] = {'owner_id': owner, 'source_id': source, 'status': status, 'generation': generation,
                                     'account_label': metadata.get('account_label'), 'scope': metadata.get('scope'),
                                     'connection_mode': metadata.get('connection_mode'), 'ads_customer_id': metadata.get('ads_customer_id')}
    return {'device': info.st_dev, 'inode': info.st_ino, 'schema_sha256': digest(schema), 'items': items,
            'preferences': preferences, 'connections': connections, 'frozen_rows': rows}


def check_private_preserved(before, after):
    need(all(after.get(key) == before.get(key) for key in ('device', 'inode', 'schema_sha256')),
         'PRIVATE_DATABASE_SCHEMA_OR_INODE_DRIFT')
    need(all(after['items'].get(key) == value for key, value in before['items'].items()), 'PRIVATE_EXISTING_KEYS_OR_OVERRIDES_CHANGED')
    need(before['preferences'] == after['preferences'], 'PRIVATE_PREFERENCES_CHANGED')
    need(before['connections'] == after['connections'], 'PRIVATE_CONNECTION_IDENTITY_OR_STATUS_CHANGED')


def check_private_frozen(before, after):
    check_private_preserved(before, after)
    need(set(before['frozen_rows']) == TABLES and before['frozen_rows'] == after['frozen_rows'],
         'PRIVATE_ROWS_CHANGED_BEFORE_NEW_WORKER')


def connected_gmail_check(snapshot, expected_email):
    matches = [row for row in snapshot['connections'].values() if row['source_id'] == 'gmail' and row['owner_id'] == '4']
    need(len(matches) == 1 and matches[0]['status'] == 'connected' and
         isinstance(matches[0]['account_label'], str) and matches[0]['account_label'].casefold() == expected_email.casefold() and
         matches[0]['scope'] == 'https://www.googleapis.com/auth/gmail.readonly' and matches[0]['connection_mode'] == 'oauth',
         'CONNECTED_GMAIL_BASELINE_REQUIRED')


def connected_ads_check(snapshot):
    connected=[row for row in snapshot['connections'].values() if row['source_id']=='google_ads' and row['owner_id']=='4']
    need(len(connected)==1 and connected[0]['status']=='connected' and connected[0]['connection_mode']=='oauth' and
         connected[0]['ads_customer_id']==TARGET_CUSTOMER and
         'https://www.googleapis.com/auth/adwords' in (connected[0]['scope'] or '').split(),
         'CONNECTED_ADS_BASELINE_REQUIRED')


def credentials_readable(api_identity):
    # Use already-tested candidate libraries and its existing env in memory.
    # This command imports no application module, opens private SQLite read-only,
    # and prints only a boolean/count, never credential/profile/mail values.
    code = """import base64,hashlib,json,os,sqlite3
from cryptography.fernet import Fernet
key=os.environ['PRIVATE_WORKSPACE_ENCRYPTION_KEY'].strip()
cipher=Fernet(base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest()))
count=0
with sqlite3.connect('file:/private-data/workspace.db?mode=ro',uri=True) as db:
 db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
 for status,encrypted in db.execute('SELECT status,encrypted_credentials FROM private_connections'):
  if status=='connected':
   assert encrypted
   value=json.loads(cipher.decrypt(encrypted.encode()))
   assert isinstance(value,dict) and value
   count+=1
assert count>=1
print(json.dumps({'connected_credentials_readable':True,'connected_count':count}))
"""
    report = json.loads(run(['docker', 'exec', api_identity, 'python', '-c', code], 'CONNECTED_CREDENTIALS_UNREADABLE'))
    need(report.get('connected_credentials_readable') is True and report.get('connected_count', 0) >= 1,
         'CONNECTED_CREDENTIALS_UNREADABLE')
    return report


def public_manifest(candidate):
    meta = candidate['public']
    need(meta['path'] == str(PUBLIC) and meta['worker_user'] == 'www-data' and
         meta['actual_worker_read_verified'] is True and meta['prior_assets_preserved'] is True, 'PUBLIC_PREPARATION_PROOF_REQUIRED')
    manifest_path = RELEASE / 'public-manifest.json'
    data = read_protected(manifest_path, 2 * 1024**2)
    need(sha(data) == meta['manifest_sha256'], 'PUBLIC_MANIFEST_DRIFT')
    manifest = json.loads(data)
    need(isinstance(manifest, dict) and len(manifest) == meta['files'] and 'index.html' in manifest and 'app-version.json' in manifest,
         'PUBLIC_MANIFEST_INCOMPLETE')
    actual = {}
    for path in sorted(PUBLIC.rglob('*')):
        need(path.resolve() == path and not path.is_symlink() and path.stat().st_uid == 0 and
             not path.stat().st_mode & 0o022, 'PUBLIC_PATH_UNTRUSTED')
        if path.is_dir():
            continue
        relative = path.relative_to(PUBLIC).as_posix()
        need(path.is_file() and relative in manifest and path.stat().st_nlink == 1 and
             re.fullmatch('[a-f0-9]{64}', manifest[relative]), 'PUBLIC_FILE_SCOPE_DRIFT')
        actual[relative] = sha(path.read_bytes())
    need(actual == manifest and json.loads((PUBLIC / 'app-version.json').read_bytes()) == {'version': VERSION}, 'PUBLIC_BYTES_DRIFT')
    proof = "import pathlib,hashlib,json;r=pathlib.Path(" + repr(str(PUBLIC)) + ");print(json.dumps({p.relative_to(r).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(r.rglob('*')) if p.is_file()},sort_keys=True))"
    need(json.loads(run(['runuser', '-u', 'www-data', '--', 'python3', '-c', proof], 'PUBLIC_WORKER_READ_FAILED')) == manifest,
         'PUBLIC_WORKER_BYTES_DRIFT')
    return manifest


def candidate_check(args):
    data = read_protected(RELEASE / 'candidate.json', 2 * 1024**2)
    need(sha(data) == args.candidate_sha256, 'CANDIDATE_RECEIPT_DRIFT')
    value = json.loads(data)
    need(value['stage'] == 'ADS_HEALTH_CANDIDATE_VERIFIED' and value['source_sha'] == SOURCE and
         value['frontend_version'] == VERSION and value['base_image_id'] == BASE_IMAGE and
         value['readonly_baseline_sha256'] == BASELINE_SHA and
         value['backend_runtime_changed_files'] == list(BACKEND) and
         value['all_other_backend_bytes_identical'] is True and value['all_package_bytes_identical'] is True and
         value['production_services_modified'] is False and value['production_environment_loaded_in_tests'] is False and
         value['production_database_mounted_in_tests'] is False and value['deployed'] is False, 'VERIFIED_CANDIDATE_REQUIRED')
    tests = value['candidate_tests']
    need(tests['tests'] >= MIN_TESTS and tests['network'] == 'none' and tests['production_env_loaded'] is False and
         tests['production_database_access'] is False and tests['actual_image_tested'] is True, 'ACTUAL_IMAGE_TESTS_REQUIRED')
    image = value['image_id']
    need(re.fullmatch('sha256:[a-f0-9]{64}', image) and image != BASE_IMAGE, 'CANDIDATE_IMAGE_ID_INVALID')
    observed = json.loads(run(['docker', 'image', 'inspect', image], 'CANDIDATE_IMAGE_MISSING'))[0]
    need(observed['Id'] == image and observed['Config']['Labels'].get('t24.source.sha') == SOURCE, 'CANDIDATE_IMAGE_LABEL_DRIFT')
    return value, public_manifest(value)


def nginx_bytes(original):
    need(sha(original) == NGINX_SHA, 'NGINX_BASELINE_DRIFT')
    old, new = str(OLD_PUBLIC).encode(), str(PUBLIC).encode()
    need(original.count(old) == 1 and new not in original, 'EXACT_PUBLIC_ROOT_REPLACEMENT_REQUIRED')
    changed = original.replace(old, new, 1)
    need(changed.replace(new, old, 1) == original and b'127.0.0.1:8001' in original and
         b'127.0.0.1:8000' in original and all(name.encode() in original for name in HEADERS), 'NGINX_PROXY_OR_HEADERS_DRIFT')
    return changed


def read_nginx():
    info = NGINX.lstat()
    need(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and info.st_nlink == 1 and
         NGINX.resolve() == NGINX and not info.st_mode & 0o022 and info.st_size <= 65536, 'NGINX_PATH_UNTRUSTED')
    fd = os.open(NGINX, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        observed = os.fstat(stream.fileno())
        need((observed.st_dev, observed.st_ino) == (info.st_dev, info.st_ino), 'NGINX_CHANGED_DURING_READ')
        return stream.read(65537)


def atomic_nginx(data, allowed_hashes):
    info = NGINX.lstat()
    need(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and info.st_nlink == 1 and
         NGINX.resolve() == NGINX and not info.st_mode & 0o022, 'NGINX_PATH_UNTRUSTED')
    need(sha(read_nginx()) in allowed_hashes, 'NGINX_CONCURRENT_CHANGE')
    temporary = NGINX.parent / ('.t24-ads-health-' + uuid4().hex)
    write_new(temporary, data)
    temporary.chmod(stat.S_IMODE(info.st_mode))
    need(sha(read_nginx()) in allowed_hashes and NGINX.stat().st_ino == info.st_ino, 'NGINX_CHANGED_BEFORE_REPLACE')
    os.replace(temporary, NGINX)
    fsync_directory(NGINX.parent)


def create_command(name, role, image, attempt):
    need(role in {'api', 'worker'} and name.startswith('t24-ads-health-stage-'), 'STAGED_NAME_OR_ROLE_INVALID')
    result = ['docker', 'create', '--name', name, '--restart', 'unless-stopped', '--read-only', '--cap-drop', 'ALL',
              '--security-opt', 'no-new-privileges', '--log-opt', 'max-size=5m', '--log-opt', 'max-file=3',
              '--env-file', str(ENV), '--tmpfs', '/tmp:rw,nosuid,noexec,size=128m',
              '--mount', 'type=bind,src=/opt/t24-crm/app/data,dst=/app/backend/data,readonly',
              '--mount', 'type=bind,src=/opt/t24-crm/private-workspace/data,dst=/private-data',
              '--label', 't24.private.source.sha=' + SOURCE, '--label', 't24.private.role=' + role,
              '--label', 't24.ads_health.upgrade.attempt=' + attempt]
    if role == 'api':
        result += ['--publish', '127.0.0.1:8001:8001', '--health-cmd', 'curl -fsS http://127.0.0.1:8001/ready || exit 1',
                   '--health-interval', '15s', '--health-timeout', '5s', '--health-start-period', '15s', '--health-retries', '3',
                   '--entrypoint', 'uvicorn', image, 'services.private_workspace_app:app', '--host', '0.0.0.0', '--port', '8001', '--no-access-log']
    else:
        result += ['--no-healthcheck', '--entrypoint', 'python', image, '-m', 'services.private_workspace_worker']
    return result


def staged_check(identity, role, image, attempt, env, expected_state=None):
    info = inspect(identity)
    need(info['Id'] == identity and info['Image'] == image and identity not in {*OLD_IDS.values(), CRM_ID}, 'NEW_CONTAINER_IDENTITY_DRIFT')
    labels = info['Config'].get('Labels', {})
    need(labels.get('t24.private.source.sha') == SOURCE and labels.get('t24.private.role') == role and
         labels.get('t24.ads_health.upgrade.attempt') == attempt, 'NEW_CONTAINER_LABEL_DRIFT')
    host = info['HostConfig']
    need(host['ReadonlyRootfs'] and host['CapDrop'] == ['ALL'] and
         host['SecurityOpt'] == ['no-new-privileges'] and host['RestartPolicy']['Name'] == 'unless-stopped' and
         host['LogConfig']['Config'] == {'max-size': '5m', 'max-file': '3'} and
         host['Tmpfs'] == {'/tmp': 'rw,nosuid,noexec,size=128m'}, 'NEW_CONTAINER_PROTECTIONS_DRIFT')
    need(not host.get('Privileged') and not host.get('CapAdd') and not host.get('Devices') and
         not host.get('DeviceRequests') and not host.get('Binds') and
         host.get('NetworkMode') in {'default', 'bridge'} and host.get('PidMode', '') == '' and
         host.get('IpcMode') == 'private' and host.get('UTSMode', '') == '', 'NEW_CONTAINER_ISOLATION_DRIFT')
    binds = [m for m in info['Mounts'] if m['Type'] == 'bind']
    mounts = {(m['Source'], m['Destination'], m['RW']) for m in binds}
    need(mounts == {('/opt/t24-crm/app/data', '/app/backend/data', False),
                    ('/opt/t24-crm/private-workspace/data', '/private-data', True)} and
         len(binds) == 2 and all(m['Type'] == 'bind' or
                               (m['Type'] == 'tmpfs' and m['Destination'] == '/tmp' and m['RW'])
                               for m in info['Mounts']) and len(info['Mounts']) <= 3, 'NEW_CONTAINER_MOUNTS_DRIFT')
    configured = docker_env(info)
    need(all(configured.get(name) == value for name, value in env.items()), 'NEW_CONTAINER_ENV_DRIFT')
    need(not any(name.startswith(('STRIPE_', 'OPENAI_', 'RINGCENTRAL_', 'OSS_', 'PRIVATE_GOOGLE_')) for name in configured),
         'UNAUTHORIZED_PLATFORM_SECRET_PRESENT')
    if role == 'api':
        need(info['Config']['Entrypoint'] == ['uvicorn'] and info['Config']['Cmd'] ==
             ['services.private_workspace_app:app', '--host', '0.0.0.0', '--port', '8001', '--no-access-log'], 'NEW_API_COMMAND_DRIFT')
        need(host['PortBindings'] == {'8001/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '8001'}]}, 'NEW_API_PORT_DRIFT')
        health = info['Config'].get('Healthcheck', {})
        need(health.get('Test') == ['CMD-SHELL', 'curl -fsS http://127.0.0.1:8001/ready || exit 1'] and
             health.get('Interval') == 15_000_000_000 and health.get('Timeout') == 5_000_000_000 and
             health.get('StartPeriod') == 15_000_000_000 and health.get('Retries') == 3, 'NEW_API_HEALTHCHECK_DRIFT')
    else:
        need(info['Config']['Entrypoint'] == ['python'] and info['Config']['Cmd'] == ['-m', 'services.private_workspace_worker'] and
             not host['PortBindings'] and info['Config'].get('Healthcheck', {}).get('Test') == ['NONE'], 'NEW_WORKER_COMMAND_DRIFT')
    if expected_state is not None:
        need(info['State']['Status'] == expected_state and not info['State'].get('Dead') and not info['State'].get('Restarting'),
             'NEW_CONTAINER_STATE_DRIFT')
    return {'id': identity, 'image': image, 'configuration_sha256': config_hash(info),
            'started_at': info['State']['StartedAt'], 'restart_count': info['RestartCount']}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def request(url, maximum=16 * 1024**2):
    need(url.startswith('https://t24-crm.com/') or url.startswith('http://127.0.0.1:800'), 'HTTP_TARGET_REJECTED')
    opener = urllib.request.build_opener(NoRedirect())
    try:
        response = opener.open(url, timeout=5)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        body = response.read(maximum + 1)
        need(len(body) <= maximum, 'HTTP_RESPONSE_TOO_LARGE')
        return response.code, {k.lower(): v for k, v in response.headers.items()}, body


def wait_ready():
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        try:
            code, _, body = request('http://127.0.0.1:8001/ready', 4096)
            if code == 200 and json.loads(body) == {'ready': True}:
                return
        except Exception:
            pass
        time.sleep(1)
    raise SwitchError('PRIVATE_SERVICE_NOT_READY')


def unauthenticated_check(public=False):
    origin = 'https://t24-crm.com' if public else 'http://127.0.0.1:8001'
    for suffix in ('', '/access'):
        code, headers, _ = request(origin + PREFIX + suffix, 65536)
        need(code == 401 and no_store(headers), 'PRIVATE_AUTH_OR_CACHE_DRIFT')


def no_store(headers):
    return 'no-store' in {part.strip().lower() for part in headers.get('cache-control', '').split(',')}


def wait_api_healthy(identity):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        info = inspect(identity)
        need(info['Id'] == identity and info['State']['Running'] and info['RestartCount'] == 0 and
             not info['State'].get('Restarting'), 'NEW_API_HEALTH_RUNTIME_FAILED')
        if info['State'].get('Health', {}).get('Status') == 'healthy':
            return
        time.sleep(1)
    raise SwitchError('NEW_API_NOT_HEALTHY')


def header_check(headers):
    need(all(headers.get(name.lower()) == value for name, value in HEADERS.items()), 'PUBLIC_SECURITY_HEADERS_DRIFT')


def current_assets(root, manifest):
    # Cached old assets remain readable on disk; HTTP checks follow only this
    # index's reachable JS/CSS graph so retained history cannot cause thousands
    # of serial requests during a live switch.
    index = (root / 'index.html').read_text()
    pending = [name.lstrip('/') for name in re.findall(r'(?:src|href)=["\x27](/assets/[A-Za-z0-9_.-]+\.(?:js|css))["\x27]', index)]
    need(pending and any(name.endswith('.js') for name in pending), 'CURRENT_ASSET_ENTRY_MISSING')
    pattern = re.compile(r'["\x27](?:(?:\./|/assets/|assets/))?([A-Za-z0-9_-]+\.(?:js|css))["\x27]')
    graph = {}
    while pending:
        name = pending.pop()
        if name in graph:
            continue
        need(name in manifest and re.fullmatch(r'assets/[A-Za-z0-9_.-]+\.(?:js|css)', name), 'CURRENT_ASSET_SCOPE_DRIFT')
        path = root / name
        need(path.is_file() and path.resolve() == path and not path.is_symlink() and sha(path.read_bytes()) == manifest[name],
             'CURRENT_ASSET_BYTES_DRIFT')
        graph[name] = manifest[name]
        need(len(graph) <= 256, 'CURRENT_ASSET_GRAPH_LIMIT')
        if name.endswith('.js'):
            pending += ['assets/' + referenced for referenced in pattern.findall(path.read_text())]
    return graph


def public_check(manifest, version, root=PUBLIC):
    whole_deadline = time.monotonic() + 120
    graph = current_assets(root, manifest)
    deadline = time.monotonic() + 15
    while True:
        try:
            code, headers, body = request('https://t24-crm.com/app-version.json?ads_health_upgrade=' + uuid4().hex, 4096)
            matched = code == 200 and json.loads(body) == {'version': version}
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            matched = False
        if matched:
            break
        need(time.monotonic() < deadline, 'PUBLIC_VERSION_PROPAGATION_FAILED')
        time.sleep(1)
    header_check(headers)
    need(no_store(headers), 'PUBLIC_VERSION_CACHE_DRIFT')
    code, headers, body = request('https://t24-crm.com/?ads_health_upgrade=' + uuid4().hex)
    need(code == 200 and sha(body) == manifest['index.html'], 'PUBLIC_INDEX_BYTES_DRIFT')
    header_check(headers)
    for name, expected in graph.items():
        need(time.monotonic() < whole_deadline, 'PUBLIC_ASSET_VERIFICATION_DEADLINE')
        relative = PurePosixPath(name)
        need(relative.as_posix() == name and '..' not in relative.parts and not relative.is_absolute(), 'PUBLIC_ASSET_PATH_INVALID')
        code, asset_headers, content = request('https://t24-crm.com/' + name)
        need(code == 200 and sha(content) == expected, 'PUBLIC_ASSET_BYTES_DRIFT')
    unauthenticated_check(True)
    need(request('https://t24-crm.com/ready', 4096)[0] == 200, 'PUBLIC_CRM_READY_FAILED')


def old_check(role, baseline, old_env, running=None):
    info = inspect(OLD_IDS[role])
    previous = baseline['private']['t24-private-' + role]
    need(info['Id'] == OLD_IDS[role] and info['Image'] == BASE_IMAGE and config_hash(info) == previous['configuration_sha256'],
         'OLD_PRIVATE_CONFIGURATION_DRIFT')
    if running is True:
        need(info['State']['Running'] and info['State']['StartedAt'] == previous['started_at'], 'OLD_PRIVATE_RUNTIME_DRIFT')
    if running is False:
        need(not info['State']['Running'], 'OLD_PRIVATE_MUST_BE_STOPPED')
    env = docker_env(info)
    need(all(env.get(k) == v for k, v in old_env.items()), 'OLD_PRIVATE_ENV_DRIFT')
    return info


def require_free_name(name):
    need(inspect(name, optional=True) is None, 'CONTAINER_NAME_COLLISION')


def rollback(state, original, candidate_image, env, old_env, baseline, private_before):
    # A hash/identity mismatch stops rollback rather than broadening its scope.
    crm_check(require_healthy=False)
    current = sha(read_nginx())
    approved = {NGINX_SHA, state['new_nginx_sha256']}
    need(current in approved, 'ROLLBACK_NGINX_CONCURRENT_CHANGE')
    if current != NGINX_SHA:
        atomic_nginx(original, approved)
        run(['nginx', '-t'], 'ROLLBACK_NGINX_TEST_FAILED')
        run(['systemctl', 'reload', 'nginx'], 'ROLLBACK_NGINX_RELOAD_FAILED')
    for role in ('worker', 'api'):
        identity = state['new_ids'].get(role)
        if not identity and state.get('stage_names', {}).get(role):
            # docker create may have completed before a timeout lost its stdout.
            # Discover only this attempt's planned name and prove its labels before
            # recording any CID or removing anything.
            discovered = inspect(state['stage_names'][role], optional=True)
            if discovered:
                identity = discovered['Id']
                staged_check(identity, role, candidate_image, state['attempt'], env)
                state['new_ids'][role] = identity
        if identity:
            staged_check(identity, role, candidate_image, state['attempt'], env)
            run(['docker', 'rm', '-f', identity], 'ROLLBACK_NEW_CONTAINER_REMOVE_FAILED')
    if state['old_stop_begun']:
        for role in ('api', 'worker'):
            info = old_check(role, baseline, old_env)
            name = 't24-private-' + role
            if info['Name'] != '/' + name:
                require_free_name(name)
                run(['docker', 'rename', OLD_IDS[role], name], 'ROLLBACK_OLD_RENAME_FAILED')
            if not info['State']['Running']:
                run(['docker', 'start', OLD_IDS[role]], 'ROLLBACK_OLD_START_FAILED')
            if role == 'api':
                wait_ready()
                unauthenticated_check()
    crm_check()
    check_private_preserved(private_before, private_snapshot())
    need(sha(read_nginx()) == NGINX_SHA, 'ROLLBACK_NGINX_HASH_DRIFT')
    old_manifest = {p.relative_to(OLD_PUBLIC).as_posix(): sha(p.read_bytes()) for p in OLD_PUBLIC.rglob('*') if p.is_file()}
    old_version = json.loads((OLD_PUBLIC / 'app-version.json').read_bytes())['version']
    public_check(old_manifest, old_version, OLD_PUBLIC)
    state['phase'] = 'ROLLED_BACK_PRIVATE_ONLY'


def main(args):
    need(args.execute and os.geteuid() == 0 and socket.gethostname() == HOST, 'EXPLICIT_VERIFIED_SERVER_REQUIRED')
    need(re.fullmatch('[a-f0-9]{40}', SOURCE) and re.fullmatch('[a-f0-9]{12}', VERSION) and
         re.fullmatch('[a-f0-9]{64}', NGINX_SHA) and re.fullmatch('[a-f0-9]{64}', BASELINE_SHA) and MIN_TESTS >= 159 and '__' not in str(RELEASE) and '__' not in str(PUBLIC),
         'REVIEWED_CONSTANTS_MUST_BE_STAMPED')
    need(all(re.fullmatch('[a-f0-9]{64}', value) for value in (args.candidate_sha256, args.env_sha256)),
         'REVIEWED_HASH_ARGUMENT_REQUIRED')
    os.umask(0o077)
    secure(RELEASE, True, 0o700)
    secure(CONFIG.parent, True, 0o700)
    secure(CONFIG, True, 0o700)
    lock = CONFIG / 'gmail-upgrade.lock'
    fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        secure(lock, mode=0o600)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        candidate, manifest = candidate_check(args)
        updated_env = read_protected(ENV)
        need(sha(updated_env) == args.env_sha256, 'CURRENT_ENV_HASH_DRIFT')
        old_env, new_env = env_check(updated_env, updated_env, args.expected_email)
        baseline = candidate['running_baseline']
        need(baseline['crm_container_id'] == CRM_ID and baseline['crm_image_id'] == CRM_IMAGE and
             baseline['crm_started_at'] == CRM_STARTED and baseline['crm_configuration_sha256'] == CRM_CONFIG and
             baseline['nginx_sha256'] == NGINX_SHA, 'CANDIDATE_BASELINE_DRIFT')
        crm_proof = crm_check()
        need(docker_env(inspect(CRM_ID)).get('JWT_SECRET_KEY') == new_env['JWT_SECRET_KEY'], 'CRM_JWT_IDENTITY_DRIFT')
        for role in ('api', 'worker'):
            proof = baseline['private']['t24-private-' + role]
            need(proof['id'] == OLD_IDS[role] and proof['configuration_sha256'] == PRIVATE_PROOFS[role]['configuration_sha256'] and
                 proof['started_at'] == PRIVATE_PROOFS[role]['started_at'], 'OLD_PRIVATE_ID_RECEIPT_DRIFT')
            old_check(role, baseline, old_env, True)
        original = read_nginx()
        changed = nginx_bytes(original)
        private_before = private_snapshot()
        connected_gmail_check(private_before, args.expected_email)
        connected_ads_check(private_before)
        attempt = uuid4().hex
        state_path = RELEASE / ('switch-state-' + attempt + '.json')
        state = {'phase': 'PREFLIGHT_VERIFIED', 'attempt': attempt, 'new_ids': {}, 'old_ids': OLD_IDS,
                 'stage_names': {role: 't24-ads-health-stage-' + role + '-' + attempt[:12] for role in OLD_IDS},
                 'old_stop_begun': False, 'candidate_image': candidate['image_id'], 'candidate_sha256': args.candidate_sha256,
                 'env_sha256': args.env_sha256, 'readonly_baseline_sha256': BASELINE_SHA, 'new_nginx_sha256': sha(changed), 'original_nginx_sha256': NGINX_SHA,
                 'old_backup_names': {role: 't24-private-' + role + '-rollback-' + attempt[:12] for role in OLD_IDS},
                 'crm_proof': crm_proof, 'private_database': {k: private_before[k] for k in ('device', 'inode', 'schema_sha256')}}
        write_new(RELEASE / ('nginx-before-' + attempt + '.conf'), original)
        write_new(RELEASE / ('nginx-after-' + attempt + '.conf'), changed)
        save(state_path, state)
        try:
            for role in ('api', 'worker'):
                stage_name = state['stage_names'][role]
                require_free_name(stage_name)
                require_free_name(state['old_backup_names'][role])
                identity = run(create_command(stage_name, role, candidate['image_id'], attempt), 'STAGED_CREATE_FAILED').decode().strip()
                need(re.fullmatch('[a-f0-9]{64}', identity), 'CREATED_CONTAINER_ID_INVALID')
                state['new_ids'][role] = identity
                save(state_path, state, True)
                staged_check(identity, role, candidate['image_id'], attempt, new_env, 'created')
            # Last guard immediately before stopping only the old private services.
            crm_check()
            need(sha(read_nginx()) == NGINX_SHA and sha(read_protected(ENV)) == args.env_sha256, 'LAST_PREFLIGHT_DRIFT')
            for role in ('worker', 'api'):
                old_check(role, baseline, old_env, True)
            before = business_fingerprints()
            save(RELEASE / ('business-before-' + attempt + '.json'), before)
            state['old_stop_begun'] = True
            state['phase'] = 'STOPPING_OLD_PRIVATE'
            save(state_path, state, True)
            for role in ('worker', 'api'):
                old_check(role, baseline, old_env, True)
                run(['docker', 'stop', '--time', '20', OLD_IDS[role]], 'OLD_PRIVATE_STOP_FAILED', 30)
                old_check(role, baseline, old_env, False)
                if role == 'api':
                    # Worker stops first. Let the old API finish/roll back any
                    # in-flight request, then pin all private rows while BOTH old
                    # writers are stopped, immediately before candidate startup.
                    private_before = private_snapshot(full=True)
                    connected_gmail_check(private_before, args.expected_email)
                    connected_ads_check(private_before)
                require_free_name(state['old_backup_names'][role])
                run(['docker', 'rename', OLD_IDS[role], state['old_backup_names'][role]], 'OLD_PRIVATE_RENAME_FAILED')
                save(state_path, state, True)
            for role in ('api', 'worker'):
                require_free_name('t24-private-' + role)
                staged_check(state['new_ids'][role], role, candidate['image_id'], attempt, new_env, 'created')
                run(['docker', 'rename', state['new_ids'][role], 't24-private-' + role], 'NEW_PRIVATE_RENAME_FAILED')
            run(['docker', 'start', state['new_ids']['api']], 'NEW_API_START_FAILED')
            wait_ready()
            unauthenticated_check()
            wait_api_healthy(state['new_ids']['api'])
            check_private_frozen(private_before, private_snapshot(full=True))
            credentials_proof = credentials_readable(state['new_ids']['api'])
            run(['docker', 'start', state['new_ids']['worker']], 'NEW_WORKER_START_FAILED')
            first = {role: staged_check(identity, role, candidate['image_id'], attempt, new_env, 'running')
                     for role, identity in state['new_ids'].items()}
            time.sleep(5)
            final = {role: staged_check(identity, role, candidate['image_id'], attempt, new_env, 'running')
                     for role, identity in state['new_ids'].items()}
            need(first == final and all(proof['restart_count'] == 0 for proof in final.values()), 'NEW_PRIVATE_RUNTIME_UNSTABLE')
            check_private_preserved(private_before, private_snapshot())
            credentials_readable(state['new_ids']['api'])
            crm_check()
            state['phase'] = 'NEW_PRIVATE_READY'
            save(state_path, state, True)
            atomic_nginx(changed, {NGINX_SHA})
            run(['nginx', '-t'], 'NEW_NGINX_TEST_FAILED')
            run(['systemctl', 'reload', 'nginx'], 'NEW_NGINX_RELOAD_FAILED')
            state['phase'] = 'NGINX_SWITCHED'
            save(state_path, state, True)
            public_check(manifest, VERSION)
            need(sha(read_nginx()) == sha(changed), 'NEW_NGINX_HASH_DRIFT')
            need(sha(read_protected(ENV)) == args.env_sha256, 'POST_SWITCH_ENV_HASH_DRIFT')
            public_manifest(candidate)
            crm_check()
            check_private_preserved(private_before, private_snapshot())
            credentials_readable(state['new_ids']['api'])
            after = business_fingerprints()
            save(RELEASE / ('business-after-' + attempt + '.json'), after)
            changed_tables = sorted(name for name in set(before['tables']) | set(after['tables'])
                                    if before['tables'].get(name) != after['tables'].get(name))
            state['changed_business_tables'] = changed_tables
            need(not changed_tables and before['schema_sha256'] == after['schema_sha256'], 'BUSINESS_FINGERPRINT_DRIFT_PENDING_REVIEW')
            state['phase'] = 'ADS_HEALTH_UPGRADE_SERVER_VERIFIED'
            state['new_private'] = final
            state['business_tables_verified'] = 83
            state['existing_env_values_identical'] = True
            state['jwt_and_encryption_key_preserved'] = True
            state['gmail_connected_verified'] = False
            state['crm_runtime_modified'] = False
            state['databases_restored'] = False
            state['connected_credentials_readable'] = True
            state['all_private_rows_preserved_before_new_worker'] = True
            state['documented_private_sync_updates_allowed'] = True
            save(state_path, state, True)
            print(json.dumps({'stage': state['phase'], 'receipt_basename': state_path.name, 'receipt_sha256': sha(state_path.read_bytes()),
                              'new_ids': state['new_ids'], 'new_image': candidate['image_id'], 'frontend_version': VERSION,
                              'business_tables_verified': 83, 'crm_runtime_modified': False, 'gmail_connected_verified': False}, sort_keys=True))
        except BaseException as error:
            failure = str(error) if isinstance(error, SwitchError) else type(error).__name__
            need(re.fullmatch('[A-Za-z0-9_]+', failure), 'FAILURE_CODE_INVALID')
            state['failure_code'] = failure
            state['phase'] = 'ROLLBACK_REQUIRED'
            save(state_path, state, True)
            try:
                rollback(state, original, candidate['image_id'], new_env, old_env, baseline, private_before)
                state['rollback_verified'] = True
                save(state_path, state, True)
            except BaseException as rollback_error:
                state['phase'] = 'ROLLBACK_BLOCKED_IDENTITY_OR_HEALTH_CHECK'
                state['rollback_failure_code'] = str(rollback_error) if isinstance(rollback_error, SwitchError) else type(rollback_error).__name__
                save(state_path, state, True)
                print(json.dumps({'stage': state['phase'], 'receipt_basename': state_path.name,
                                  'failure_code': failure, 'rollback_failure_code': state['rollback_failure_code']}, sort_keys=True))
                raise SwitchError('ROLLBACK_REQUIRES_OPERATOR_REVIEW') from None
            raise SwitchError('UPGRADE_REJECTED_PRIVATE_ROLLBACK_VERIFIED') from None
    finally:
        os.close(fd)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--candidate-sha256', required=True)
    parser.add_argument('--env-sha256', required=True)
    parser.add_argument('--expected-email', required=True)
    try:
        main(parser.parse_args())
    except BaseException as error:
        code = str(error) if isinstance(error, SwitchError) and re.fullmatch('[A-Z0-9_]+', str(error)) else 'SWITCH_FAILED'
        print('GOOGLE_ADS_UPGRADE_ERROR ' + code, flush=True)
        raise SystemExit(1) from None
