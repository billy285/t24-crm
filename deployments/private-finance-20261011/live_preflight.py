#!/usr/bin/env python3
"""Readonly, receipt-pinned live baseline for the joint private finance release.

No application imports, HTTP, credential decryption, commands other than Docker
inspect, files written, service changes or private record values are permitted.
Only a root release operator on the exact verified host may execute this file.
"""
import argparse
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import stat
import subprocess

HOST = 'iZj6c4cj7edgnhdimts4l7Z'
BASE_SOURCE = 'dd8061ca30b91554f3f431446616dffc12c81b7a'
CRM_ID = 'ca45180be18981a7c3727a9c7a031690946f2c4c77f0cd96608fc65da3a3fb26'
CRM_IMAGE = 'sha256:7a1b09bbb04899e7c6459491d32c45c25d789801a51b4a95e9b77b7dafcbb4ab'
CRM_STARTED = '2026-10-10T17:19:07.948520307Z'
CRM_CONFIG = '2e5c793eae3c192963037652717f91b402d351372378350f44dc2294fa85bdc0'
PRIVATE_IMAGE = 'sha256:2ed347b29ba8f29ffeaab26df75e8c5d75c7479b477a1e45e80bdf2b19d098db'
PRIVATE_IDS = {'api': '31b4553486ac7955733877db576655648ed9cc778a153dc5591958831298020f',
               'worker': 'bbbb2c880eb7246fc98f9704d7cdb306541bb989b297cbf1e6381c22229095da'}
ENV_SHA = '180f945729234df79c45f5148663f8407c75be55aa8d4e79107305c03c00f82d'
PRIVATE_RECEIPT = Path('/opt/t24-crm/releases/ads-health-dd8061c-20261011/switch-state-a088ede4998048548b8877407f7a8ca5.json')
PRIVATE_RECEIPT_SHA = '87bc0280ed6759321d3762268f31a9ed440c1ed53e1b2944d62cbb321b4e4388'
STATIC_RECEIPT = Path('/opt/t24-crm/releases/ads-health-responsive-30d9748-20261011/static-state-98b2cce3141a4e8a8cbc17ca58695839.json')
STATIC_RECEIPT_SHA = '81bf3ec698201300da4472df092daa1c0d64462e64e49075b0c1417b75236ea3'
PUBLIC = Path('/var/www/t24-crm-public/ads-health-responsive-30d9748-20261011')
FRONTEND_VERSION = '54da68143ed2'
ENV = Path('/opt/t24-crm/private-workspace/config/runtime.env')
NGINX = Path('/etc/nginx/sites-enabled/t24-crm')
BUSINESS = Path('/opt/t24-crm/app/data/crm_prod.db')
PRIVATE_DB = Path('/opt/t24-crm/private-workspace/data/workspace.db')
PRIVATE_TABLES = {'private_connections', 'private_items', 'private_preferences', 'private_sync_runs'}
PRIVATE_DEVICE_INODE = (64515, 282885)


class PreflightError(RuntimeError):
    pass


def need(condition, code):
    if not condition: raise PreflightError(code)


def sha(blob): return hashlib.sha256(blob).hexdigest()


def digest(value): return sha(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())


def safe_file(path, *, protected=False, maximum=2 * 1024 * 1024):
    need(path.is_absolute() and path.resolve() == path, 'CANONICAL_PATH_REQUIRED')
    info = path.lstat()
    need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == 0 and
         not info.st_mode & 0o022 and info.st_size <= maximum, 'FILE_PROTECTION_DRIFT')
    if protected:
        need(stat.S_IMODE(info.st_mode) == 0o600 and path.parent.stat().st_uid == 0 and
             not path.parent.stat().st_mode & 0o077, 'PROTECTED_FILE_OR_DIRECTORY_DRIFT')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        actual = os.fstat(stream.fileno())
        need((info.st_dev, info.st_ino) == (actual.st_dev, actual.st_ino), 'FILE_IDENTITY_CHANGED')
        blob = stream.read(maximum + 1)
    need(len(blob) <= maximum and path.stat().st_ino == info.st_ino, 'FILE_CHANGED_DURING_READ')
    return blob


def receipt(path, expected):
    blob = safe_file(path, protected=True)
    need(sha(blob) == expected, 'PRIOR_RECEIPT_HASH_DRIFT')
    value = json.loads(blob)
    need(isinstance(value, dict), 'PRIOR_RECEIPT_FORMAT_DRIFT')
    return value


def prior_receipts():
    private = receipt(PRIVATE_RECEIPT, PRIVATE_RECEIPT_SHA)
    static = receipt(STATIC_RECEIPT, STATIC_RECEIPT_SHA)
    need(private.get('phase') == 'ADS_HEALTH_UPGRADE_SERVER_VERIFIED' and
         private.get('new_ids') == PRIVATE_IDS and
         private.get('candidate_image') == PRIVATE_IMAGE and private.get('env_sha256') == ENV_SHA and
         private.get('business_tables_verified') == 83, 'PRIVATE_RECEIPT_SCOPE_DRIFT')
    need(static.get('phase') == 'RESPONSIVE_STATIC_UPGRADE_VERIFIED' and
         static.get('frontend_version') == FRONTEND_VERSION and static.get('backend_services_modified') is False and
         static.get('databases_restored') is False and static.get('business_tables_verified') == 83 and
         re.fullmatch('[a-f0-9]{64}', static.get('new_nginx_sha256', '')), 'STATIC_RECEIPT_SCOPE_DRIFT')
    need(all(static['private_and_crm_runtime']['private'][role]['id'] == PRIVATE_IDS[role] and
             static['private_and_crm_runtime']['private'][role]['image'] == PRIVATE_IMAGE and
             static['private_and_crm_runtime']['private'][role]['configuration_sha256'] ==
                private['new_private'][role]['configuration_sha256'] and
             static['private_and_crm_runtime']['private'][role]['started_at'] == private['new_private'][role]['started_at']
             for role in PRIVATE_IDS), 'RECEIPT_RUNTIME_CHAIN_DRIFT')
    return private, static


def inspect(name):
    need(name in {'t24-crm', 't24-private-api', 't24-private-worker'}, 'INSPECT_TARGET_REJECTED')
    result = subprocess.run(['docker', 'inspect', name], capture_output=True, timeout=30, check=False)
    need(result.returncode == 0, 'CONTAINER_INSPECT_FAILED')
    value = json.loads(result.stdout)
    need(isinstance(value, list) and len(value) == 1, 'SINGLE_CONTAINER_REQUIRED')
    return value[0]


def config_hash(info):
    return digest({'Config': info['Config'], 'HostConfig': info['HostConfig'],
                   'Mounts': sorted(info['Mounts'], key=digest)})


def healthy(info, *, api=False):
    need(info['State']['Running'] and not info['State'].get('Dead') and
         not info['State'].get('Restarting'), 'CONTAINER_NOT_RUNNING')
    if api: need(info['State'].get('Health', {}).get('Status') == 'healthy', 'API_NOT_HEALTHY')


def crm_snapshot():
    info = inspect('t24-crm'); healthy(info, api=True)
    need(info['Id'] == CRM_ID and info['Image'] == CRM_IMAGE and
         info['State']['StartedAt'] == CRM_STARTED, 'CRM_RUNTIME_DRIFT')
    need(len(info['Mounts']) == 2, 'CRM_MOUNT_COUNT_DRIFT')
    variants = [digest({'Config': info['Config'], 'HostConfig': info['HostConfig'], 'Mounts': list(order)})
                for order in itertools.permutations(info['Mounts'])]
    need(CRM_CONFIG in variants, 'CRM_CONFIGURATION_DRIFT')
    need(info['HostConfig']['PortBindings'].get('8000/tcp') == [{'HostIp': '127.0.0.1', 'HostPort': '8000'}], 'CRM_PORT_DRIFT')
    return {'id': CRM_ID, 'image': CRM_IMAGE, 'started_at': CRM_STARTED, 'configuration_sha256': CRM_CONFIG}


def parse_env(blob):
    need(blob and len(blob) <= 65536 and blob.endswith(b'\n') and b'\r' not in blob and b'\0' not in blob, 'ENV_FORMAT_DRIFT')
    values = {}
    for row in blob.decode().splitlines():
        need('=' in row, 'ENV_ROW_DRIFT'); name, value = row.split('=', 1)
        need(re.fullmatch('[A-Z][A-Z0-9_]*', name) and name not in values, 'ENV_KEY_DRIFT')
        values[name] = value
    required = {'PRIVATE_WORKSPACE_OWNER_IDS': '4', 'PRIVATE_WORKSPACE_PUBLIC_URL': 'https://t24-crm.com',
        'PRIVATE_WORKSPACE_DATABASE_URL': 'sqlite+aiosqlite:////private-data/workspace.db',
        'DATABASE_URL': 'sqlite:///./data/crm_prod.db', 'DATABASE_SCHEMA_MODE': 'verify_only',
        'ENFORCE_EMPLOYEE_STATUS': 'true', 'ENFORCE_EMPLOYEE_SESSIONS': 'true'}
    need(all(values.get(key) == value for key, value in required.items()), 'ENV_BOUNDARY_DRIFT')
    return values


def private_runtime(previous, environment):
    result = {}
    for role, expected_id in PRIVATE_IDS.items():
        info = inspect('t24-private-' + role); pinned = previous['new_private'][role]
        healthy(info, api=role == 'api')
        need(info['Id'] == expected_id and info['Image'] == PRIVATE_IMAGE and
             config_hash(info) == pinned['configuration_sha256'] and
             info['State']['StartedAt'] == pinned['started_at'] and
             info['RestartCount'] == pinned['restart_count'], 'PRIVATE_RUNTIME_CONFIGURATION_DRIFT')
        need(info['Config'].get('Labels', {}).get('t24.private.source.sha') == BASE_SOURCE and
             info['Config'].get('Labels', {}).get('t24.private.role') == role, 'PRIVATE_SOURCE_LABEL_DRIFT')
        host = info['HostConfig']
        need(host['ReadonlyRootfs'] and host['CapDrop'] == ['ALL'] and host['SecurityOpt'] == ['no-new-privileges'] and
             not host.get('Privileged') and not host.get('CapAdd') and not host.get('Binds') and
             not host.get('Devices') and not host.get('DeviceRequests') and host.get('NetworkMode') in {'default', 'bridge'},
             'PRIVATE_ISOLATION_DRIFT')
        binds = [entry for entry in info['Mounts'] if entry['Type'] == 'bind']
        need(len(binds) == 2 and {(m['Source'], m['Destination'], m['RW']) for m in binds} == {
            ('/opt/t24-crm/app/data', '/app/backend/data', False),
            ('/opt/t24-crm/private-workspace/data', '/private-data', True)} and len(info['Mounts']) <= 3 and
            all(m['Type'] == 'bind' or m['Type'] == 'tmpfs' and m['Destination'] == '/tmp' for m in info['Mounts']),
            'PRIVATE_MOUNT_DRIFT')
        env = dict(row.split('=', 1) for row in info['Config']['Env'])
        need(all(env.get(key) == value for key, value in environment.items()), 'PRIVATE_ENV_CONFIG_DRIFT')
        if role == 'api':
            need(info['Config']['Entrypoint'] == ['uvicorn'] and info['Config']['Cmd'] ==
                 ['services.private_workspace_app:app', '--host', '0.0.0.0', '--port', '8001', '--no-access-log'] and
                 host['PortBindings'] == {'8001/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '8001'}]}, 'PRIVATE_API_LAUNCH_DRIFT')
        else:
            need(info['Config']['Entrypoint'] == ['python'] and info['Config']['Cmd'] ==
                 ['-m', 'services.private_workspace_worker'] and not host['PortBindings'], 'PRIVATE_WORKER_LAUNCH_DRIFT')
        result[role] = {'id': expected_id, 'image': PRIVATE_IMAGE, 'configuration_sha256': config_hash(info),
            'started_at': pinned['started_at'], 'restart_count': pinned['restart_count'],
            'environment_names': sorted(env), 'source_sha': BASE_SOURCE, 'launch_mount_port_verified': True}
    return result


def database_snapshots(previous):
    need(BUSINESS.is_file() and BUSINESS.resolve() == BUSINESS and not BUSINESS.is_symlink(), 'BUSINESS_PATH_DRIFT')
    with sqlite3.connect(BUSINESS.as_uri() + '?mode=ro', uri=True, timeout=15) as db:
        db.execute('PRAGMA query_only=ON'); db.execute('BEGIN')
        need(db.execute('PRAGMA integrity_check').fetchall() == [('ok',)], 'BUSINESS_INTEGRITY_DRIFT')
        schema = list(db.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name'))
        tables = sorted(row[1] for row in schema if row[0] == 'table')
        need(len(tables) == 83 and not any(name.startswith('private_') for name in tables), 'BUSINESS_TABLE_SCOPE_DRIFT')
        need(db.execute('SELECT version_num FROM alembic_version').fetchall() == [('ab6d8e2f0411',)], 'BUSINESS_HEAD_DRIFT')
        need(db.execute('SELECT role,status FROM employees WHERE id=4').fetchall() == [('super_admin', 'active')], 'OWNER_IDENTITY_DRIFT')
        fingerprints = {}
        for table in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            rows = db.execute('SELECT * FROM ' + quoted).fetchall()
            encoded = sorted(json.dumps(list(row), ensure_ascii=False, default=lambda v: {'hex': v.hex()},
                                        sort_keys=True, separators=(',', ':')) for row in rows)
            fingerprints[table] = {'count': len(rows), 'sha256': sha('\n'.join(encoded).encode())}
        business = {'table_count': 83, 'schema_head': 'ab6d8e2f0411', 'schema_sha256': digest(schema),
                    'table_fingerprints': fingerprints, 'owner_4_active_super_admin_verified': True}
    info = PRIVATE_DB.lstat()
    need(PRIVATE_DB.resolve() == PRIVATE_DB and stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and
         info.st_uid == 0 and stat.S_IMODE(info.st_mode) == 0o600 and not os.path.samefile(PRIVATE_DB, BUSINESS) and
         (info.st_dev, info.st_ino) == PRIVATE_DEVICE_INODE, 'PRIVATE_FILE_IDENTITY_DRIFT')
    with sqlite3.connect(PRIVATE_DB.as_uri() + '?mode=ro', uri=True, timeout=15) as db:
        db.execute('PRAGMA query_only=ON'); db.execute('BEGIN')
        need(db.execute('PRAGMA integrity_check').fetchall() == [('ok',)], 'PRIVATE_INTEGRITY_DRIFT')
        schema = list(db.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name'))
        tables = {row[1] for row in schema if row[0] == 'table'}
        need(tables == PRIVATE_TABLES and digest(schema) == previous['private_database']['schema_sha256'], 'PRIVATE_SCHEMA_DRIFT')
        for table in sorted(tables):
            quoted = '"' + table + '"'
            need(db.execute('SELECT 1 FROM ' + quoted + ' WHERE owner_id IS NULL OR owner_id <> ? LIMIT 1', ('4',)).fetchone() is None,
                 'PRIVATE_OWNER_SCOPE_DRIFT')
    need((PRIVATE_DB.stat().st_dev, PRIVATE_DB.stat().st_ino) == (info.st_dev, info.st_ino), 'PRIVATE_FILE_CHANGED')
    return business, {'device': info.st_dev, 'inode': info.st_ino, 'schema_sha256': digest(schema),
                      'table_inventory': sorted(tables), 'owner_scope_verified': True}


def compare_baseline(current, baseline):
    need(baseline.get('stage') == 'PRIVATE_FINANCE_LIVE_READONLY_BASELINE' and
         baseline.get('format_version') == 1 and baseline.get('mutation_performed') is False,
         'FROZEN_BASELINE_FORMAT_DRIFT')
    need(current == baseline, 'FROZEN_BASELINE_DRIFT')


def preflight():
    need(os.geteuid() == 0 and socket.gethostname() == HOST, 'VERIFIED_ROOT_SERVER_REQUIRED')
    previous, static = prior_receipts()
    blob = safe_file(ENV, protected=True, maximum=65536)
    need(sha(blob) == ENV_SHA, 'ENVIRONMENT_HASH_DRIFT')
    environment = parse_env(blob)
    crm = crm_snapshot(); private = private_runtime(previous, environment)
    nginx = safe_file(NGINX, maximum=65536)
    need(sha(nginx) == static['new_nginx_sha256'] and nginx.count(str(PUBLIC).encode()) == 1 and
         b'127.0.0.1:8000' in nginx and b'127.0.0.1:8001' in nginx, 'NGINX_BASELINE_DRIFT')
    need(json.loads(safe_file(PUBLIC / 'app-version.json', maximum=4096)) == {'version': FRONTEND_VERSION}, 'STATIC_VERSION_DRIFT')
    business, database = database_snapshots(previous)
    need(all(database[key] == previous['private_database'][key] for key in ('device', 'inode', 'schema_sha256')),
         'PRIVATE_RECEIPT_DATABASE_DRIFT')
    return {'format_version': 1, 'stage': 'PRIVATE_FINANCE_LIVE_READONLY_BASELINE', 'mutation_performed': False,
        'hostname': HOST, 'crm': crm, 'private': private, 'business': business, 'private_database': database,
        'environment_sha256': ENV_SHA, 'environment_presence': {name: bool(value) for name, value in sorted(environment.items())},
        'nginx_sha256': sha(nginx), 'static_root': str(PUBLIC), 'frontend_version': FRONTEND_VERSION,
        'private_receipt_sha256': PRIVATE_RECEIPT_SHA, 'static_receipt_sha256': STATIC_RECEIPT_SHA}


def main(args):
    need(bool(args.compare_baseline) == bool(args.baseline_sha256), 'BASELINE_FILE_AND_HASH_REQUIRED_TOGETHER')
    current = preflight()
    if args.compare_baseline:
        need(re.fullmatch('[a-f0-9]{64}', args.baseline_sha256), 'FROZEN_BASELINE_HASH_REQUIRED')
        compare_baseline(current, receipt(args.compare_baseline, args.baseline_sha256))
    print(json.dumps(current, sort_keys=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--compare-baseline', type=Path)
    parser.add_argument('--baseline-sha256')
    try: main(parser.parse_args())
    except Exception as error:
        code = str(error) if isinstance(error, PreflightError) and re.fullmatch('[A-Z0-9_]+', str(error)) else 'PREFLIGHT_FAILED'
        print('PRIVATE_FINANCE_PREFLIGHT_ERROR ' + code)
        raise SystemExit(1) from None
