"""Read-only, self-contained static-release boundary; never execute old helpers.

Only metadata/schema, public static files and runtime source hashes are read.
No application table rows, credentials, provider requests or runtime lifecycle calls.
"""
import copy
import hashlib
import itertools
import json
import os
import re
import socket
import sqlite3
import stat
import subprocess
import time
from pathlib import Path

HOST = 'iZj6c4cj7edgnhdimts4l7Z'
BASE_SOURCE = 'f405a3079a184469d71924ca4950c41900dd922b'
BASE_VERSION = '75e008e44e70'
BASE_PUBLIC = '/var/www/t24-crm-public/crm-mobile-focus-f405a3079a18-20261112'
# The prior deployed receipt pins the complete path/hash map, including every
# retained asset. Its exact digest implies the complete file/byte inventory;
# retain the independently enforced tree count and byte upper bounds below.
MAX_STATIC_FILES = 8192
MAX_STATIC_BYTES = 536870912
SCHEMA = 'j65bc789b025'
SCHEMA_SHA = 'ca15d3cb51c5cb99a68865c6a0c0d5aadd32ee1c5a5cfbc70dee7bfbbf4baa6a'
DATABASE_IDENTITY = [64515, 262854]
DB = Path('/opt/t24-crm/app/data/crm_prod.db')
NGINX = Path('/etc/nginx/sites-enabled/t24-crm')
HELPERS = {'/opt/t24-crm/releases/crm-order-list-7ff2deff1ed3-20261111/release.py': '5a702dc034f95392fdd7372014cba7db41b86880182ad909a6f983b7cf6cb270', '/opt/t24-crm/releases/crm-order-list-contact-guard-eae1018a1da1-20261111/release.py': 'e072b611d8a2c6f558d1f666de25caeed4e223e6cc94e3a8183e833f751474cc', '/opt/t24-crm/releases/crm-order-mobile-fix-a753b28fadb0-20261111/release.py': 'cc22fcaa76d4c6f4f69d0bb29f56ec9a216c3d8c806bed1bbde687c90871899e', '/opt/t24-crm/releases/crm-order-system-86fbb228e176-20261111/release.py': '6c05c3ea9840719e92e0b87e418a17541a5fc85a8d1b181a0854149a5c1d1672', '/opt/t24-crm/releases/crm-theme-details-596687a9b9e7-20261111/release.py': 'd70cf13f0b06335c2339d2dd05fc08054bcfdafc84fd49020ce94c63b8ab2262', '/opt/t24-crm/releases/crm-theme-performance-ced537b14f9e-20261111/release.py': '9fc7979eac14d6616894a96d6f9d0270a8318b47bb313026d81841ac039315ce', '/opt/t24-crm/releases/crm-ui-refinement-34917180e0d8-20261111/release.py': '54baac38f4c95977890d3bf31d6d549d7649eae2f37781ed345bc842bfb26ef4', '/opt/t24-crm/releases/ringcentral-team-18240e28774a-20261109/release.py': '922e0ed7d3fbde5d2985a5ea2a02b90b9622262f1969c8146535665133589f85', '/opt/t24-crm/releases/crm-mobile-focus-f405a3079a18-20261112/release.py': '3a49e896b8716b4d3b6a47097bc56d98e445acf268d27b6c8f69678ff7fbe91c'}
RUNTIME = {'config': 'a0343fa6afc0a90d553a5cbe5535709b0a22350c96013a696aa9b1b65ce4e5cf', 'id': 'a781614d942f9e44bc9a590e4538d6cb0a278f29ec1e5a6ee161542d2a112f91', 'image': 'sha256:ee0ec78aefb57df0ac03beb015e7ea4cfb91be92d32207ff00a3b3128d298e32', 'started': '2026-11-10T17:39:56.698664937Z'}
PRIVATE = {'t24-private-api': {'config': '04160cf058e2e8b47b719e731a813af4bdb12144850680b50ed2ec00dd5491e2', 'id': 'f8644b043b7f9d8e57190a8e7f411291ccb0814871428891e00e77cb74974d6b', 'image': 'sha256:a82266de5af9ff84a957854f8dc7971415718278f0cf7342d037dde74dd518c5', 'started': '2026-10-11T23:58:43.773320701Z'}, 't24-private-worker': {'config': '7dba014c965ef1c4618a0a33546a5089edb27095a3c06ce05ab06d01a8ceb061', 'id': '7f7930d5ea468765c404a163ecb0cb4d2935b793ad4435efc8ca8aa782772cab', 'image': 'sha256:a82266de5af9ff84a957854f8dc7971415718278f0cf7342d037dde74dd518c5', 'started': '2026-10-11T23:58:58.055948866Z'}}
BASE_INVENTORY_SHA = '283eae77666cee3f3572781ab9ea353ec6e43646f0c00620738c8755c880dfc5'
BASE_PUBLIC_INVENTORY_SHA = 'ca66d962163e0cff001b06105adb8ed8c259e83efe9a1bd0fa1766f62f004d28'
EXPECTED_BACKEND = {'routers/sales_leads.py': '5842cd67af54eb71c974718e636877a1ed556e40e5ddcbad1996f53659efdac8', 'services/sales_contact_protection.py': 'c8cc5a04e895155067efa13e4656f4e4bf380a5354931cb5fa37a2ebb163cb0f'}

def need(value, code):
    if not value:
        raise RuntimeError(code)

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()

def sha(body):
    return hashlib.sha256(body).hexdigest()

def digest(value):
    return sha(canonical(value))

def strict_json(body):
    def pairs(rows):
        result = {}
        for key, value in rows:
            need(key not in result, 'DUPLICATE_JSON_KEY')
            result[key] = value
        return result
    def constant(_):
        raise RuntimeError('NONFINITE_JSON')
    return json.loads(body, object_pairs_hook=pairs, parse_constant=constant)

def protected(path, expected=None, maximum=16777216, private=False):
    path = Path(path)
    need(path.is_absolute() and path.resolve() == path, 'CANONICAL_FILE_REQUIRED')
    for parent in path.parents:
        row = parent.lstat()
        need(stat.S_ISDIR(row.st_mode) and row.st_uid == 0 and not row.st_mode & 0o022, 'PROTECTED_PARENT_REQUIRED')
    row = path.lstat()
    need(stat.S_ISREG(row.st_mode) and row.st_uid == 0 and row.st_nlink == 1 and not row.st_mode & (0o077 if private else 0o022), 'PROTECTED_REGULAR_FILE_REQUIRED')
    identity = lambda v: (v.st_dev, v.st_ino, v.st_mode, v.st_uid, v.st_size, v.st_nlink, v.st_mtime_ns, v.st_ctime_ns)
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as stream:
        opened = os.fstat(stream.fileno())
        body = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    need(identity(row) == identity(opened) == identity(after) == identity(path.lstat()) and len(body) == row.st_size <= maximum, 'STABLE_BOUNDED_FILE_REQUIRED')
    need(expected is None or sha(body) == expected, 'EXACT_FILE_HASH_REQUIRED')
    return body

def run(args, code, timeout=40):
    result = subprocess.run(args, capture_output=True, timeout=timeout)
    need(result.returncode == 0 and len(result.stdout) <= 8388608, code)
    return result.stdout

def inspect(name):
    rows = strict_json(run(['docker', 'inspect', name], 'CONTAINER_INSPECT_FAILED'))
    need(len(rows) == 1, 'EXACT_SINGLE_CONTAINER_REQUIRED')
    return rows[0]

def networks(info):
    result = {}
    for name, value in info.get('NetworkSettings', {}).get('Networks', {}).items():
        result[name] = {key: copy.deepcopy(value[key]) for key in ('Aliases', 'Links', 'DriverOpts', 'GwPriority') if value.get(key) is not None}
        if 'Aliases' in result[name]:
            result[name]['Aliases'] = [v for v in result[name]['Aliases'] if v not in (info['Id'], info['Id'][:12])]
    return result

def runtime_hash(info, mounts):
    return digest({'Config': info['Config'], 'HostConfig': info['HostConfig'], 'Mounts': mounts, 'networks': networks(info)})

def runtime(info, expected):
    need(info['State']['Running'] is True and all(info[key] == expected[field] for key, field in [('Id', 'id'), ('Image', 'image')]) and info['State']['StartedAt'] == expected['started'], 'EXACT_RUNNING_RUNTIME_REQUIRED')
    mounts = info['Mounts']
    need(len(mounts) <= 6, 'BOUNDED_MOUNT_PERMUTATION_REQUIRED')
    # Full dictionaries, no removed fields; Docker may reorder Mounts only.
    need(any(runtime_hash(info, list(order)) == expected['config'] for order in itertools.permutations(mounts)), 'COMPLETE_RUNTIME_CONFIG_CHANGED')
    return {**expected, 'restart_count': info['RestartCount'], 'canonical_mounts_sha256': digest(sorted(mounts, key=canonical)), 'environment_sha256': digest(info['Config'].get('Env', []))}

INVENTORY_SCRIPT = """import pathlib,hashlib,json
r=pathlib.Path('/app/backend');excluded={'data','logs','__pycache__','.git','.pytest_cache','.venv','node_modules','work'}
print(json.dumps({str(p.relative_to(r)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(r.rglob('*')) if p.is_file() and not p.is_symlink() and not any(x in excluded or x.startswith('.') for x in p.relative_to(r).parts) and p.suffix not in {'.pyc','.db','.log','.pem','.key'}}))
"""

def backend_inventory(container):
    value = strict_json(run(['docker', 'exec', container, 'python', '-B', '-c', INVENTORY_SCRIPT], 'BACKEND_SOURCE_INVENTORY_FAILED'))
    need(len(value) == 443 and all(value.get(k) == v for k, v in EXPECTED_BACKEND.items()), 'CURRENT443_BACKEND_PIN_REQUIRED')
    need(digest(value) == BASE_INVENTORY_SHA, 'EXACT_FULL_BACKEND_INVENTORY_REQUIRED')
    return digest(value)

def static_path(name):
    parts = name.split('/')
    return bool(parts and not name.startswith('/') and '\\' not in name and all(re.fullmatch(r'[A-Za-z0-9_@][A-Za-z0-9_.@+-]*', part) and part not in ('.', '..') for part in parts))

def tree(root):
    root = Path(root)
    need(root.is_absolute() and root.resolve() == root and root.is_dir(), 'CANONICAL_STATIC_ROOT_REQUIRED')
    result = {}
    total = 0
    for path in sorted(root.rglob('*')):
        row = path.lstat()
        need(not stat.S_ISLNK(row.st_mode) and row.st_uid == 0 and not row.st_mode & 0o022, 'PROTECTED_STATIC_TREE_REQUIRED')
        if stat.S_ISDIR(row.st_mode):
            continue
        relative = str(path.relative_to(root))
        need(stat.S_ISREG(row.st_mode) and static_path(relative), 'REGULAR_STATIC_FILE_REQUIRED')
        body = protected(path)
        total += len(body)
        need(total <= MAX_STATIC_BYTES and len(result) < MAX_STATIC_FILES, 'BOUNDED_STATIC_TREE_REQUIRED')
        result[relative] = sha(body)
    need({'index.html', 'app-version.json'} <= set(result), 'SPA_VERSION_REQUIRED')
    if str(root) == BASE_PUBLIC:
        need(digest(result) == BASE_PUBLIC_INVENTORY_SHA, 'EXACT_DEPLOYED_BASE_STATIC_INVENTORY_REQUIRED')
    return result

def nginx():
    path = NGINX.resolve()
    body = protected(path)
    matches = re.findall(rb'^\s*root\s+(/var/www/t24-crm-public/[^;\s]+);', body, re.M)
    need(len(matches) == 1, 'EXACT_PUBLIC_ROOT_REQUIRED')
    active = run(['nginx', '-T'], 'ACTIVE_NGINX_READ_FAILED')
    need(active.count(matches[0]) == 1, 'EXACT_ACTIVE_ROOT_REQUIRED')
    return path, body, active, matches[0].decode()

def public(version):
    args = ['curl', '-q', '--silent', '--show-error', '--fail', '--noproxy', '*', '--http1.1', '--max-time', '5', '--max-redirs', '0', '--resolve', 't24-crm.com:443:127.0.0.1']
    value = run(args + ['-H', 'Cache-Control: no-cache', 'https://t24-crm.com/app-version.json?refresh-stability-readonly=' + str(time.time_ns())], 'PUBLIC_VERSION_READ_FAILED', 10)
    need(len(value) <= 1024 and strict_json(value) == {'version': version}, 'EXACT_PUBLIC_VERSION_REQUIRED')
    headers = run(args + ['-D', '-', '-o', '/dev/null', 'https://t24-crm.com/sales-workbench'], 'PUBLIC_HEADERS_READ_FAILED', 10)
    need(len(headers) < 16384, 'BOUNDED_PUBLIC_HEADERS_REQUIRED')
    lines = headers.decode('iso-8859-1').splitlines()
    need(lines and re.fullmatch(r'HTTP/1[.]1 200(?: .*)?', lines[0]), 'PUBLIC_SPA_200_REQUIRED')
    csp = [line.split(':', 1)[1].strip() for line in lines[1:] if ':' in line and line.split(':', 1)[0].lower() == 'content-security-policy']
    need(len(csp) == 1 and 0 < len(csp[0]) < 8192, 'EXACT_SINGLE_CSP_REQUIRED')
    return sha(csp[0].encode())

def capture(expected_public=BASE_PUBLIC, expected_version=BASE_VERSION):
    need(os.geteuid() == 0 and socket.gethostname() == HOST, 'EXACT_ROOT_SERVER_REQUIRED')
    helper_hashes = {name: sha(protected(name, expected)) for name, expected in HELPERS.items()}
    crm = runtime(inspect('t24-crm'), RUNTIME)
    private = {name: runtime(inspect(name), expected) for name, expected in PRIVATE.items()}
    dbrow = DB.stat()
    need([dbrow.st_dev, dbrow.st_ino] == DATABASE_IDENTITY, 'DATABASE_IDENTITY_CHANGED')
    connection = sqlite3.connect('file:' + str(DB) + '?mode=ro', uri=True)
    try:
        connection.execute('PRAGMA query_only=ON')
        connection.execute('BEGIN')
        rows = connection.execute('SELECT version_num FROM alembic_version').fetchall()
        need(rows == [(SCHEMA,)], 'EXACT_SCHEMA_HEAD_REQUIRED')
        definitions = [list(row) for row in connection.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name")]
        need(digest(definitions) == SCHEMA_SHA, 'FULL_SCHEMA_CHANGED')
        table_count = sum(row[0] == 'table' for row in definitions)
    finally:
        connection.close()
    path, body, active, root = nginx()
    need(root == expected_public, 'PUBLIC_ROOT_CHANGED')
    inventory = tree(Path(root))
    need(strict_json(protected(Path(root) / 'app-version.json')) == {'version': expected_version}, 'STATIC_VERSION_CHANGED')
    return {'runtime': crm, 'private_runtimes': private, 'schema_revision': SCHEMA, 'schema_sha256': SCHEMA_SHA, 'table_count': table_count, 'database_identity': DATABASE_IDENTITY, 'backend_inventory_sha256': backend_inventory(crm['id']), 'backend_file_count': 443, 'public_root': root, 'frontend_version': expected_version, 'public_inventory_sha256': digest(inventory), 'nginx_path': str(path), 'nginx_sha256': sha(body), 'active_nginx_sha256': sha(active), 'content_security_policy_sha256': public(expected_version), 'helper_hashes': helper_hashes}

BASE_NGINX_SHA = '7e10012d22aa5481bc9503a42d932876df3b2f9c09b14efd4c084d173b2b1870'
BASE_ACTIVE_NGINX_SHA = 'de9d752cc054dbd1b1239f9ab4f27aa1e300ae74471565053d130ae8b5a8e4b8'
BASE_CSP_SHA = 'ead64b09efe8c4f35648aa8eafe8855c5268ecf0999e0918b3642dd9dfbfe7a6'

EXPECTED_BOUNDARY = {'active_nginx_sha256': 'de9d752cc054dbd1b1239f9ab4f27aa1e300ae74471565053d130ae8b5a8e4b8', 'backend_file_count': 443, 'backend_inventory_sha256': '283eae77666cee3f3572781ab9ea353ec6e43646f0c00620738c8755c880dfc5', 'content_security_policy_sha256': 'ead64b09efe8c4f35648aa8eafe8855c5268ecf0999e0918b3642dd9dfbfe7a6', 'database_identity': [64515, 262854], 'frontend_version': '75e008e44e70', 'helper_hashes': {'/opt/t24-crm/releases/crm-order-list-7ff2deff1ed3-20261111/release.py': '5a702dc034f95392fdd7372014cba7db41b86880182ad909a6f983b7cf6cb270', '/opt/t24-crm/releases/crm-order-list-contact-guard-eae1018a1da1-20261111/release.py': 'e072b611d8a2c6f558d1f666de25caeed4e223e6cc94e3a8183e833f751474cc', '/opt/t24-crm/releases/crm-order-mobile-fix-a753b28fadb0-20261111/release.py': 'cc22fcaa76d4c6f4f69d0bb29f56ec9a216c3d8c806bed1bbde687c90871899e', '/opt/t24-crm/releases/crm-order-system-86fbb228e176-20261111/release.py': '6c05c3ea9840719e92e0b87e418a17541a5fc85a8d1b181a0854149a5c1d1672', '/opt/t24-crm/releases/crm-theme-details-596687a9b9e7-20261111/release.py': 'd70cf13f0b06335c2339d2dd05fc08054bcfdafc84fd49020ce94c63b8ab2262', '/opt/t24-crm/releases/crm-theme-performance-ced537b14f9e-20261111/release.py': '9fc7979eac14d6616894a96d6f9d0270a8318b47bb313026d81841ac039315ce', '/opt/t24-crm/releases/crm-ui-refinement-34917180e0d8-20261111/release.py': '54baac38f4c95977890d3bf31d6d549d7649eae2f37781ed345bc842bfb26ef4', '/opt/t24-crm/releases/ringcentral-team-18240e28774a-20261109/release.py': '922e0ed7d3fbde5d2985a5ea2a02b90b9622262f1969c8146535665133589f85', '/opt/t24-crm/releases/crm-mobile-focus-f405a3079a18-20261112/release.py': '3a49e896b8716b4d3b6a47097bc56d98e445acf268d27b6c8f69678ff7fbe91c'}, 'nginx_path': '/etc/nginx/sites-enabled/t24-crm', 'nginx_sha256': '7e10012d22aa5481bc9503a42d932876df3b2f9c09b14efd4c084d173b2b1870', 'private_runtimes': {'t24-private-api': {'canonical_mounts_sha256': 'f8e9b5779213f483cfc512cec1e32b82156b12c704b7d41c4417288c0aafa962', 'config': '04160cf058e2e8b47b719e731a813af4bdb12144850680b50ed2ec00dd5491e2', 'environment_sha256': '52ec4efc6528bca46e7b31d1eeeacb426f3ffea4373acb54746a4437eb3e8732', 'id': 'f8644b043b7f9d8e57190a8e7f411291ccb0814871428891e00e77cb74974d6b', 'image': 'sha256:a82266de5af9ff84a957854f8dc7971415718278f0cf7342d037dde74dd518c5', 'restart_count': 0, 'started': '2026-10-11T23:58:43.773320701Z'}, 't24-private-worker': {'canonical_mounts_sha256': 'f8e9b5779213f483cfc512cec1e32b82156b12c704b7d41c4417288c0aafa962', 'config': '7dba014c965ef1c4618a0a33546a5089edb27095a3c06ce05ab06d01a8ceb061', 'environment_sha256': 'b412bc27ec885bca443730ceb68fedc63649ef21d1cec65f8e5ce6f8dd02cc48', 'id': '7f7930d5ea468765c404a163ecb0cb4d2935b793ad4435efc8ca8aa782772cab', 'image': 'sha256:a82266de5af9ff84a957854f8dc7971415718278f0cf7342d037dde74dd518c5', 'restart_count': 0, 'started': '2026-10-11T23:58:58.055948866Z'}}, 'public_inventory_sha256': 'ca66d962163e0cff001b06105adb8ed8c259e83efe9a1bd0fa1766f62f004d28', 'public_root': '/var/www/t24-crm-public/crm-mobile-focus-f405a3079a18-20261112', 'runtime': {'canonical_mounts_sha256': '9d359d0d20b3a8422e7e97658fed117b35befa79a84e3947e3db2fe199cf2b6f', 'config': 'a0343fa6afc0a90d553a5cbe5535709b0a22350c96013a696aa9b1b65ce4e5cf', 'environment_sha256': '9ecc4a543dc193736e08a8526f691722e68ecae9f8e0a206beb8d4f61d4329d0', 'id': 'a781614d942f9e44bc9a590e4538d6cb0a278f29ec1e5a6ee161542d2a112f91', 'image': 'sha256:ee0ec78aefb57df0ac03beb015e7ea4cfb91be92d32207ff00a3b3128d298e32', 'restart_count': 0, 'started': '2026-11-10T17:39:56.698664937Z'}, 'schema_revision': 'j65bc789b025', 'schema_sha256': 'ca15d3cb51c5cb99a68865c6a0c0d5aadd32ee1c5a5cfbc70dee7bfbbf4baa6a', 'table_count': 169}

def main():
    first = capture()
    need(first['nginx_sha256'] == BASE_NGINX_SHA and first['active_nginx_sha256'] == BASE_ACTIVE_NGINX_SHA and first['content_security_policy_sha256'] == BASE_CSP_SHA, 'EXACT_DEPLOYED_NGINX_CSP_BASELINE_REQUIRED')
    need(first == EXPECTED_BOUNDARY, 'EXACT_DEPLOYED_FULL_BASELINE_REQUIRED')
    need(capture() == first, 'READONLY_BOUNDARY_NOT_STABLE')
    print(json.dumps({'stage': 'CRM_REFRESH_STABILITY_READONLY_BASELINE', 'captured_at_unix': int(time.time()), 'baseline_source_sha': BASE_SOURCE, **first, 'static_only': True, 'business_rows_read': False, 'database_writes': False, 'runtime_restarts': False, 'old_helpers_executed': False}, sort_keys=True))

if __name__ == '__main__':
    main()
