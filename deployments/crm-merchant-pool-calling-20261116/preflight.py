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
BASE_SOURCE = '25c1aea5c979d33addcc65a75b0a7f8f653e541f'
BASE_VERSION = '82125934f19c'
BASE_PUBLIC = '/var/www/t24-crm-public/crm-commission-statements-25c1aea5c979-20261115'
# The prior deployed receipt pins the complete path/hash map, including every
# retained asset. Its exact digest implies the complete file/byte inventory;
# retain the independently enforced tree count and byte upper bounds below.
MAX_STATIC_FILES = 8192
MAX_STATIC_BYTES = 536870912
SCHEMA = 'k76cd890c136'
SCHEMA_SHA = '53e7124afef8d6bd6dc65127bc7811db1fae289bde8364ccfb23b2028769cd46'
DATABASE_IDENTITY = [64515, 262854]
DB = Path('/opt/t24-crm/app/data/crm_prod.db')
NGINX = Path('/etc/nginx/sites-enabled/t24-crm')
HELPERS = {'/opt/t24-crm/releases/crm-customer-business-b8744b9b1f5f-20261115/release.py': 'bcb4be10f55fa8ea0d351a7261d999d3ee922b62080aac0c44bc02f4d7b8cec1', '/opt/t24-crm/releases/crm-customer-business-b8744b9b1f5f-20261115/runtime_patch.py': '03fd545f1b9f6e695927857ef2d4f4171606a78d8087b1d89b487d4be4d8e0c1', '/opt/t24-crm/releases/crm-customer-classification-c833347b4212-20261115/release.py': '77a1e3d858407388a20e4d946f566647f32859d13a2b6e7880eeda6511728199', '/opt/t24-crm/releases/crm-customer-classification-c833347b4212-20261115/runtime_patch.py': '82f73b44a37215167f8c3c61a2eda5cbbf8c5c8d97fc86d2b2ba92d05a3f1af6', '/opt/t24-crm/releases/crm-customer-followup-refresh-313bc88af3d9-20261113/release.py': '2d2a0709add360088651024c9432969d86554e6d85a11b503869b9bbefe3929f', '/opt/t24-crm/releases/crm-customer-intake-f89c9d0d07b7-20261114/release.py': '1ed518cc3b2cc27e603ef931174bede3cca698915b2d47e06e401207a135a826', '/opt/t24-crm/releases/crm-customer-mobile-layout-c8fcbdf92047-20261113/release.py': '8916ade45f9748ffac9c0a5650604c9e741dda31ec7d35ac155152efa5c954f0', '/opt/t24-crm/releases/crm-customer-operations-73959dcf5791-20261113/release.py': '8871325ee42da9a3549b6f84717da147a97866dc30e83c1834df48336d9b60cd', '/opt/t24-crm/releases/crm-deal-handoff-38c63158b7af-20261114/release.py': '4edcd942f59ee920ab6beb021a4496a6fec56d77a258abc731becc0b7d4ced51', '/opt/t24-crm/releases/crm-final-ui-polish-3e53c8a37386-20261113/release.py': '5434231235bf0167c46b6f45784426f72cd59ed60da96f68496fa368317e0c01', '/opt/t24-crm/releases/crm-finance-spacing-1ca9767b2ed8-20261114/release.py': 'cf3773e5c0be84b4b87b755ca3529bff97ec813aab37f0ef7ad80be77b3c8445', '/opt/t24-crm/releases/crm-hierarchy-refine-7bba253c20f0-20261114/release.py': 'b7765e02e97d18086156cd109cbb15366e1371cf3ea930d3ad0372844b95fec9', '/opt/t24-crm/releases/crm-metric-repair-f58a4abcfeaa-20261114/release.py': '91271f4cc6d5b0cd42d7ec59af14f3ed3d9f470320eca4c11d39bbbe3d6a66f4', '/opt/t24-crm/releases/crm-mobile-focus-f405a3079a18-20261112/release.py': '3a49e896b8716b4d3b6a47097bc56d98e445acf268d27b6c8f69678ff7fbe91c', '/opt/t24-crm/releases/crm-mobile-reading-ad22dac20e6f-20261114/release.py': 'd57244988059b0684c5f81a164032c73c7babc3ec3582d6bee001374b77f37a8', '/opt/t24-crm/releases/crm-order-list-7ff2deff1ed3-20261111/release.py': '5a702dc034f95392fdd7372014cba7db41b86880182ad909a6f983b7cf6cb270', '/opt/t24-crm/releases/crm-order-list-contact-guard-eae1018a1da1-20261111/release.py': 'e072b611d8a2c6f558d1f666de25caeed4e223e6cc94e3a8183e833f751474cc', '/opt/t24-crm/releases/crm-order-mobile-fix-a753b28fadb0-20261111/release.py': 'cc22fcaa76d4c6f4f69d0bb29f56ec9a216c3d8c806bed1bbde687c90871899e', '/opt/t24-crm/releases/crm-order-system-86fbb228e176-20261111/release.py': '6c05c3ea9840719e92e0b87e418a17541a5fc85a8d1b181a0854149a5c1d1672', '/opt/t24-crm/releases/crm-owner-detail-theme-c32757eb1db9-20261114/release.py': '7be46485b36206944930e62f95800104616e2c7b81e616a9fb8fe84887a1cf17', '/opt/t24-crm/releases/crm-owner-priorities-ca97f4b8ce9a-20261114/release.py': '00f8a3d28d87a764a5f09e03bd6076baf4c891b8659eb3bf485159a72a610032', '/opt/t24-crm/releases/crm-refresh-stability-094292520997-20261113/release.py': '80449876aac1ef316f16738208bef3d72cac2ca2b09a52205ebf9a901573adcc', '/opt/t24-crm/releases/crm-stripe-accounting-c7fec53771fa-20261114/release.py': '748cbc705bbdc0a4b27500160b715e94b19ba46dec2481f82c84e17a6335c13a', '/opt/t24-crm/releases/crm-stripe-bank-batches-12b2b3ad6b0c-20261114/release.py': '8d434aed5a4bf029f604709ca888cd25b398b1b11208132bc97027f295c81bb4', '/opt/t24-crm/releases/crm-stripe-payout-reader-de25cc8d9036-20261114/release.py': 'f1d90807222e1f4a4d6d3f72315e63f1a7446ef8cadc1f714efff9a0a4d12daf', '/opt/t24-crm/releases/crm-system-ui-audit-4f1770c9b830-20261113/release.py': '18f17de04d7582d184f23ba7dba1d2a1375dc2c367400041d958aca07c69ba6a', '/opt/t24-crm/releases/crm-theme-details-596687a9b9e7-20261111/release.py': 'd70cf13f0b06335c2339d2dd05fc08054bcfdafc84fd49020ce94c63b8ab2262', '/opt/t24-crm/releases/crm-theme-performance-ced537b14f9e-20261111/release.py': '9fc7979eac14d6616894a96d6f9d0270a8318b47bb313026d81841ac039315ce', '/opt/t24-crm/releases/crm-ui-refinement-34917180e0d8-20261111/release.py': '54baac38f4c95977890d3bf31d6d549d7649eae2f37781ed345bc842bfb26ef4', '/opt/t24-crm/releases/ringcentral-team-18240e28774a-20261109/release.py': '922e0ed7d3fbde5d2985a5ea2a02b90b9622262f1969c8146535665133589f85', '/opt/t24-crm/releases/crm-commission-statements-25c1aea5c979-20261115/release.py': '3afd9f085ce93e363cd98c27a6db78a9b381ea36556ff73d9d34cdd00871dbca', '/opt/t24-crm/releases/crm-commission-statements-25c1aea5c979-20261115/runtime_patch.py': 'a784ec6ea0655c5f9f9a678855d9938308a2cc650c1c73dfd9def57dcdb0efbb', '/opt/t24-crm/releases/crm-commission-statements-25c1aea5c979-20261115/preflight.py': 'e915c50d07ae094607d518d3e19dac044136451585091aee0ebb29ebc9455981'}
RUNTIME = {'config': 'f8199f6a6a4e08d2579c9459fb085a485c39c4c3ca88d5de497b45cfaafb7b9a', 'id': '1ab068b3fa6989f7f86a181892f996d6ba366144669a022281655396b8ee46b5', 'image': 'sha256:c85d2b5f7468f7d32db7f43579603f3b9bfbde95cd30921b9faff00c90f8dd0c', 'started': '2026-11-15T13:29:42.752816329Z'}
PRIVATE = {'t24-private-api': {'config': '04160cf058e2e8b47b719e731a813af4bdb12144850680b50ed2ec00dd5491e2', 'id': 'f8644b043b7f9d8e57190a8e7f411291ccb0814871428891e00e77cb74974d6b', 'image': 'sha256:a82266de5af9ff84a957854f8dc7971415718278f0cf7342d037dde74dd518c5', 'started': '2026-10-11T23:58:43.773320701Z'}, 't24-private-worker': {'config': '7dba014c965ef1c4618a0a33546a5089edb27095a3c06ce05ab06d01a8ceb061', 'id': '7f7930d5ea468765c404a163ecb0cb4d2935b793ad4435efc8ca8aa782772cab', 'image': 'sha256:a82266de5af9ff84a957854f8dc7971415718278f0cf7342d037dde74dd518c5', 'started': '2026-10-11T23:58:58.055948866Z'}}
BASE_INVENTORY_SHA = '79dd9ef64e93cdc3680e25fe41b1a3d601c49ac7d8cacc2f582884c959d8524f'
BASE_PUBLIC_INVENTORY_SHA = '04136e533121cf089d0329b4ba9c16638fc01aa57de2c0a8195e96113588e2e7'
EXPECTED_BACKEND = {'routers/sales_leads.py': 'fc47f18d2f53275210792bfed35ad66aa2c692f903bf24b8a3121a7a6ee77bf3', 'services/sales_contact_protection.py': 'c8cc5a04e895155067efa13e4656f4e4bf380a5354931cb5fa37a2ebb163cb0f', 'routers/app_config.py': '0f5a399a8b713d507d9aa4f5a222c10e7c98d9873b9ece54cdc794696d3111d0', 'routers/opportunities.py': 'f498d50fe5499802701891f5443c2b12ce51a15ef1498e3cc44d0c84d91e3200', 'services/commissions.py': 'e9ef220656c7a9d24e43c1b4d453fe883ba1dd676bbde1968ff1a0570646fb76', 'services/stripe_bank_reconciliation.py': '22e83c43f222ef2a8c9505b4d6a44bfbc07caf09871d226537363f4b4b9dfda6', 'services/business_intelligence.py': 'd378647df4db1b6a15250f98c7ad934fa7435248099c45822173463306bcb2ef', 'services/customers.py': '90aa546f526902539983171f890e8310d86e88dccb05a152457bed2c196dc122', 'services/management_decision_preview.py': '329240f38d3d5bacf0dc295709fe31d46509e435fcb96b4cf1c7ff29d80a5982', 'services/management_decision_workflow.py': '1694a0c2cca2bf0dde19365866d60bb66c3e402b82046a5b92f3621c35572ecf', 'services/sales_deal_handoffs.py': 'c3517a3f1c86a20d60920c02430ea3895f35bba7d725948675130fa2cee9dd48', 'services/customer_codes.py': 'e413a7981c98aa16421cbef881c542d5fc29973071419b47d525b3994c651823', 'routers/sales_intelligence.py': '22c313e610ba22701fa480fedf560dbc638b5cf53c0d17a5eaf2f4509fde60b2', 'routers/service_progresses.py': '5fbec577f5ecfa7f61ed818e8d4b74206f13e3669292dced5cff05ab24d334fd', 'services/media_operations.py': '25e7b025a8f734f2ca3c764ba1e12b8efad449c3741bd3e1999e365e669b20d4', 'services/sales_conversion_reporting.py': 'c79beaa62b0903ee9a4fd6ddf19d070ae98bd7b8b3436166a80b30b39414e9d2', 'services/service_weekly_evidence.py': 'e560cdc3dde2a59ce0213d22ff2f4ce95b6e61419f95028da2faca922fe04b73', 'routers/customers.py': '9d9bb7302922b5f84ec9587b1784ed7cec6b104210d1abf4b717f2274c0adf07', 'alembic/versions/k76cd890c136_monthly_commission_statements.py': 'dac05c33db0fddeca53d6487ea296428498acdb08811bf122a97668ab6cfb808', 'main.py': '7a5f7c754df44e2d999785cf80ef2eecc1cafbf538c91b5a992250e02197425c', 'models/commissions.py': '0afdb213d637295664e53ffc2dd82c5774fa00dd2856f82c6ce8be39c14966a8', 'routers/commissions.py': '407416d1c3219ae79cd597b331cfc586053b6142eab4534e3d53c599cd617005', 'services/commission_statement_worker.py': '0cfba0553f56932edb7d7a66a78af594a171e2d953a1235f93c8d531a9c70f1a', 'services/commission_statements.py': 'f5054953da3c3df9a9db720b4cb9fc5959021ecd5a7e89ca1e30b3e1d07e7514', 'routers/merchant_pool.py': '9d966de2497b26399d53a4739f23d07ecbb2df4acab6fe27ddb9af1c7c288fab', 'routers/prospect_verification.py': '14e03f9fb1645d77c87d664302df5a80aec427d3f0fa464adfa99bec7e714330', 'services/prospect_verification.py': '602bfc15763b742fff3cd3f8796298a400d9bd3bf920d7078a313977051cefda', 'services/sales_task_assignment.py': 'bece9ba0441150d168425f0ab8911ee7b800a39ba10093335da219ab865dcf78', 'services/sales_lead_cycle.py': '5c04c70a5911d1018924864570a402840f72f236abd990435c514a9e1917e5b6'}

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
    need(len(value) == 451 and all(value.get(k) == v for k, v in EXPECTED_BACKEND.items()), 'CURRENT451_BACKEND_PIN_REQUIRED')
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
    return {'runtime': crm, 'private_runtimes': private, 'schema_revision': SCHEMA, 'schema_sha256': SCHEMA_SHA, 'table_count': table_count, 'database_identity': DATABASE_IDENTITY, 'backend_inventory_sha256': backend_inventory(crm['id']), 'backend_file_count': 451, 'public_root': root, 'frontend_version': expected_version, 'public_inventory_sha256': digest(inventory), 'nginx_path': str(path), 'nginx_sha256': sha(body), 'active_nginx_sha256': sha(active), 'content_security_policy_sha256': public(expected_version), 'helper_hashes': helper_hashes}

BASE_NGINX_SHA = 'b57782d971994bc625a0f20f0e6a444a1e0e2ead3895ee085c0e1a74d3e412f8'
BASE_ACTIVE_NGINX_SHA = 'b1c548904275da1489b4c786cd42aa6f7fd294390daa8f05a27d7b3b36c882f7'
BASE_CSP_SHA = 'ead64b09efe8c4f35648aa8eafe8855c5268ecf0999e0918b3642dd9dfbfe7a6'

EXPECTED_BOUNDARY = {'active_nginx_sha256': 'b1c548904275da1489b4c786cd42aa6f7fd294390daa8f05a27d7b3b36c882f7', 'backend_file_count': 451, 'backend_inventory_sha256': '79dd9ef64e93cdc3680e25fe41b1a3d601c49ac7d8cacc2f582884c959d8524f', 'content_security_policy_sha256': 'ead64b09efe8c4f35648aa8eafe8855c5268ecf0999e0918b3642dd9dfbfe7a6', 'database_identity': [64515, 262854], 'frontend_version': '82125934f19c', 'helper_hashes': {'/opt/t24-crm/releases/crm-customer-business-b8744b9b1f5f-20261115/release.py': 'bcb4be10f55fa8ea0d351a7261d999d3ee922b62080aac0c44bc02f4d7b8cec1', '/opt/t24-crm/releases/crm-customer-business-b8744b9b1f5f-20261115/runtime_patch.py': '03fd545f1b9f6e695927857ef2d4f4171606a78d8087b1d89b487d4be4d8e0c1', '/opt/t24-crm/releases/crm-customer-classification-c833347b4212-20261115/release.py': '77a1e3d858407388a20e4d946f566647f32859d13a2b6e7880eeda6511728199', '/opt/t24-crm/releases/crm-customer-classification-c833347b4212-20261115/runtime_patch.py': '82f73b44a37215167f8c3c61a2eda5cbbf8c5c8d97fc86d2b2ba92d05a3f1af6', '/opt/t24-crm/releases/crm-customer-followup-refresh-313bc88af3d9-20261113/release.py': '2d2a0709add360088651024c9432969d86554e6d85a11b503869b9bbefe3929f', '/opt/t24-crm/releases/crm-customer-intake-f89c9d0d07b7-20261114/release.py': '1ed518cc3b2cc27e603ef931174bede3cca698915b2d47e06e401207a135a826', '/opt/t24-crm/releases/crm-customer-mobile-layout-c8fcbdf92047-20261113/release.py': '8916ade45f9748ffac9c0a5650604c9e741dda31ec7d35ac155152efa5c954f0', '/opt/t24-crm/releases/crm-customer-operations-73959dcf5791-20261113/release.py': '8871325ee42da9a3549b6f84717da147a97866dc30e83c1834df48336d9b60cd', '/opt/t24-crm/releases/crm-deal-handoff-38c63158b7af-20261114/release.py': '4edcd942f59ee920ab6beb021a4496a6fec56d77a258abc731becc0b7d4ced51', '/opt/t24-crm/releases/crm-final-ui-polish-3e53c8a37386-20261113/release.py': '5434231235bf0167c46b6f45784426f72cd59ed60da96f68496fa368317e0c01', '/opt/t24-crm/releases/crm-finance-spacing-1ca9767b2ed8-20261114/release.py': 'cf3773e5c0be84b4b87b755ca3529bff97ec813aab37f0ef7ad80be77b3c8445', '/opt/t24-crm/releases/crm-hierarchy-refine-7bba253c20f0-20261114/release.py': 'b7765e02e97d18086156cd109cbb15366e1371cf3ea930d3ad0372844b95fec9', '/opt/t24-crm/releases/crm-metric-repair-f58a4abcfeaa-20261114/release.py': '91271f4cc6d5b0cd42d7ec59af14f3ed3d9f470320eca4c11d39bbbe3d6a66f4', '/opt/t24-crm/releases/crm-mobile-focus-f405a3079a18-20261112/release.py': '3a49e896b8716b4d3b6a47097bc56d98e445acf268d27b6c8f69678ff7fbe91c', '/opt/t24-crm/releases/crm-mobile-reading-ad22dac20e6f-20261114/release.py': 'd57244988059b0684c5f81a164032c73c7babc3ec3582d6bee001374b77f37a8', '/opt/t24-crm/releases/crm-order-list-7ff2deff1ed3-20261111/release.py': '5a702dc034f95392fdd7372014cba7db41b86880182ad909a6f983b7cf6cb270', '/opt/t24-crm/releases/crm-order-list-contact-guard-eae1018a1da1-20261111/release.py': 'e072b611d8a2c6f558d1f666de25caeed4e223e6cc94e3a8183e833f751474cc', '/opt/t24-crm/releases/crm-order-mobile-fix-a753b28fadb0-20261111/release.py': 'cc22fcaa76d4c6f4f69d0bb29f56ec9a216c3d8c806bed1bbde687c90871899e', '/opt/t24-crm/releases/crm-order-system-86fbb228e176-20261111/release.py': '6c05c3ea9840719e92e0b87e418a17541a5fc85a8d1b181a0854149a5c1d1672', '/opt/t24-crm/releases/crm-owner-detail-theme-c32757eb1db9-20261114/release.py': '7be46485b36206944930e62f95800104616e2c7b81e616a9fb8fe84887a1cf17', '/opt/t24-crm/releases/crm-owner-priorities-ca97f4b8ce9a-20261114/release.py': '00f8a3d28d87a764a5f09e03bd6076baf4c891b8659eb3bf485159a72a610032', '/opt/t24-crm/releases/crm-refresh-stability-094292520997-20261113/release.py': '80449876aac1ef316f16738208bef3d72cac2ca2b09a52205ebf9a901573adcc', '/opt/t24-crm/releases/crm-stripe-accounting-c7fec53771fa-20261114/release.py': '748cbc705bbdc0a4b27500160b715e94b19ba46dec2481f82c84e17a6335c13a', '/opt/t24-crm/releases/crm-stripe-bank-batches-12b2b3ad6b0c-20261114/release.py': '8d434aed5a4bf029f604709ca888cd25b398b1b11208132bc97027f295c81bb4', '/opt/t24-crm/releases/crm-stripe-payout-reader-de25cc8d9036-20261114/release.py': 'f1d90807222e1f4a4d6d3f72315e63f1a7446ef8cadc1f714efff9a0a4d12daf', '/opt/t24-crm/releases/crm-system-ui-audit-4f1770c9b830-20261113/release.py': '18f17de04d7582d184f23ba7dba1d2a1375dc2c367400041d958aca07c69ba6a', '/opt/t24-crm/releases/crm-theme-details-596687a9b9e7-20261111/release.py': 'd70cf13f0b06335c2339d2dd05fc08054bcfdafc84fd49020ce94c63b8ab2262', '/opt/t24-crm/releases/crm-theme-performance-ced537b14f9e-20261111/release.py': '9fc7979eac14d6616894a96d6f9d0270a8318b47bb313026d81841ac039315ce', '/opt/t24-crm/releases/crm-ui-refinement-34917180e0d8-20261111/release.py': '54baac38f4c95977890d3bf31d6d549d7649eae2f37781ed345bc842bfb26ef4', '/opt/t24-crm/releases/ringcentral-team-18240e28774a-20261109/release.py': '922e0ed7d3fbde5d2985a5ea2a02b90b9622262f1969c8146535665133589f85', '/opt/t24-crm/releases/crm-commission-statements-25c1aea5c979-20261115/release.py': '3afd9f085ce93e363cd98c27a6db78a9b381ea36556ff73d9d34cdd00871dbca', '/opt/t24-crm/releases/crm-commission-statements-25c1aea5c979-20261115/runtime_patch.py': 'a784ec6ea0655c5f9f9a678855d9938308a2cc650c1c73dfd9def57dcdb0efbb', '/opt/t24-crm/releases/crm-commission-statements-25c1aea5c979-20261115/preflight.py': 'e915c50d07ae094607d518d3e19dac044136451585091aee0ebb29ebc9455981'}, 'nginx_path': '/etc/nginx/sites-enabled/t24-crm', 'nginx_sha256': 'b57782d971994bc625a0f20f0e6a444a1e0e2ead3895ee085c0e1a74d3e412f8', 'private_runtimes': {'t24-private-api': {'canonical_mounts_sha256': 'f8e9b5779213f483cfc512cec1e32b82156b12c704b7d41c4417288c0aafa962', 'config': '04160cf058e2e8b47b719e731a813af4bdb12144850680b50ed2ec00dd5491e2', 'environment_sha256': '52ec4efc6528bca46e7b31d1eeeacb426f3ffea4373acb54746a4437eb3e8732', 'id': 'f8644b043b7f9d8e57190a8e7f411291ccb0814871428891e00e77cb74974d6b', 'image': 'sha256:a82266de5af9ff84a957854f8dc7971415718278f0cf7342d037dde74dd518c5', 'restart_count': 0, 'started': '2026-10-11T23:58:43.773320701Z'}, 't24-private-worker': {'canonical_mounts_sha256': 'f8e9b5779213f483cfc512cec1e32b82156b12c704b7d41c4417288c0aafa962', 'config': '7dba014c965ef1c4618a0a33546a5089edb27095a3c06ce05ab06d01a8ceb061', 'environment_sha256': 'b412bc27ec885bca443730ceb68fedc63649ef21d1cec65f8e5ce6f8dd02cc48', 'id': '7f7930d5ea468765c404a163ecb0cb4d2935b793ad4435efc8ca8aa782772cab', 'image': 'sha256:a82266de5af9ff84a957854f8dc7971415718278f0cf7342d037dde74dd518c5', 'restart_count': 0, 'started': '2026-10-11T23:58:58.055948866Z'}}, 'public_inventory_sha256': '04136e533121cf089d0329b4ba9c16638fc01aa57de2c0a8195e96113588e2e7', 'public_root': '/var/www/t24-crm-public/crm-commission-statements-25c1aea5c979-20261115', 'runtime': {'canonical_mounts_sha256': '9d359d0d20b3a8422e7e97658fed117b35befa79a84e3947e3db2fe199cf2b6f', 'config': 'f8199f6a6a4e08d2579c9459fb085a485c39c4c3ca88d5de497b45cfaafb7b9a', 'environment_sha256': '9ecc4a543dc193736e08a8526f691722e68ecae9f8e0a206beb8d4f61d4329d0', 'id': '1ab068b3fa6989f7f86a181892f996d6ba366144669a022281655396b8ee46b5', 'image': 'sha256:c85d2b5f7468f7d32db7f43579603f3b9bfbde95cd30921b9faff00c90f8dd0c', 'restart_count': 0, 'started': '2026-11-15T13:29:42.752816329Z'}, 'schema_revision': 'k76cd890c136', 'schema_sha256': '53e7124afef8d6bd6dc65127bc7811db1fae289bde8364ccfb23b2028769cd46', 'table_count': 172}

def main():
    first = capture()
    need(first['nginx_sha256'] == BASE_NGINX_SHA and first['active_nginx_sha256'] == BASE_ACTIVE_NGINX_SHA and first['content_security_policy_sha256'] == BASE_CSP_SHA, 'EXACT_DEPLOYED_NGINX_CSP_BASELINE_REQUIRED')
    need(first == EXPECTED_BOUNDARY, 'EXACT_DEPLOYED_FULL_BASELINE_REQUIRED')
    need(capture() == first, 'READONLY_BOUNDARY_NOT_STABLE')
    print(json.dumps({'stage': 'CRM_MERCHANT_POOL_CALLING_READONLY_BASELINE', 'captured_at_unix': int(time.time()), 'baseline_source_sha': BASE_SOURCE, **first, 'static_only': False, 'business_rows_read': False, 'database_writes': False, 'runtime_restarts': False, 'old_helpers_executed': False}, sort_keys=True))

if __name__ == '__main__':
    main()
