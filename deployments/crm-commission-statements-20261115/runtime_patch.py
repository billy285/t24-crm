"""Exact one-file image patch and exact runtime cloning. No migration or DB restore."""
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

SCOPE = 'crm-commission-statements'
PATCH_FILES = ('alembic/versions/k76cd890c136_monthly_commission_statements.py', 'main.py', 'models/commissions.py', 'routers/commissions.py', 'services/commission_statement_worker.py', 'services/commission_statements.py')
BASE_IMAGE = 'sha256:92776eff8ecd9fffd7031c6e8db58b94b8027e86ffbdea792ee1fb2d285cb7ed'
BASE_FILE_HASHES = {'alembic/versions/k76cd890c136_monthly_commission_statements.py': None, 'main.py': '9edae4fae9ecaedf8466176d61f51e7fda09ef2ab1aafb04496ddc95576f8203', 'models/commissions.py': '7f8c6229e568c5a14943db2e664be7bed960ae6ecd405d72b2bcbb9994d74f19', 'routers/commissions.py': '2eab5f5ababd75f64a2f4098e44e6ecfd481299fbb94bc19d2557201c1ed0316', 'services/commission_statement_worker.py': None, 'services/commission_statements.py': None}
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
    need(isinstance(before, dict) and len(before) == 448 and all(before.get(name) == expected for name, expected in BASE_FILE_HASHES.items()), 'EXACT_445_BASE_SOURCE_INVENTORY_REQUIRED')
    need(isinstance(patch_hashes, dict) and set(patch_hashes) == set(PATCH_FILES) and all(isinstance(value, str) and re.fullmatch('[a-f0-9]{64}', value) and value != BASE_FILE_HASHES[name] for name, value in patch_hashes.items()), 'EXACT_PATCH_HASHES_REQUIRED')
    result = {**before, **patch_hashes}
    need(len(result) == 451, 'EXACT_446_CANDIDATE_REQUIRED')
    return result



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


def offline_validation(image, clone, schema_head, schema_sha, feature=True):
    # No original environment or credential mount is exposed to this process.
    script = 'import sys,sqlite3,json,hashlib,pathlib\nsys.path.insert(0,\'/app/backend\')\nfrom services.database import _load_all_models,_alembic_heads\nfrom core.database import Base\nfrom services.schema_readiness import RUNTIME_REQUIRED_TABLE_COLUMNS\n_load_all_models()\nassert _alembic_heads()=={HEAD}\nc=sqlite3.connect(\'file:/validation/crm_prod.db?mode=ro&immutable=1\',uri=True)\nc.execute(\'pragma query_only=on\')\nassert c.execute(\'select version_num from alembic_version\').fetchall()==[(HEAD,)]\nschema=[list(r) for r in c.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE \'sqlite_%\' ORDER BY type,name")]\nassert hashlib.sha256(json.dumps(schema,sort_keys=True,separators=(\',\',\':\'),ensure_ascii=True).encode()).hexdigest()==SCHEMA\nneeded={t.name:{col.name for col in t.columns} for t in Base.metadata.tables.values()}\nneeded.update({name:set(cols) for name,cols in RUNTIME_REQUIRED_TABLE_COLUMNS.items()})\nfor name,cols in needed.items():\n    assert cols<={r[1] for r in c.execute(\'pragma table_info("\'+name.replace(\'"\',\'""\')+\'")\')}\nc.close()\nif FEATURE:\n    from routers.commissions import router\n    from services.commission_statement_worker import start_worker,stop_worker,run_due_cycle\n    assert all(callable(x) for x in (start_worker,stop_worker,run_due_cycle))\n    routes=[r for r in router.routes if \'/statements\' in r.path]\n    assert len(routes)>=4\n    assert all(any(getattr(d.call,\'__name__\',\'\')==\'get_finance_user\' for d in r.dependant.dependencies) for r in routes)\nprint(json.dumps(dict(schema_and_orm_verified=True,feature_routes_verified=FEATURE)))\n'
    prefix = 'FEATURE=' + repr(feature) + ';HEAD=' + repr(schema_head) + ';SCHEMA=' + repr(schema_sha) + '\n'
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
# Methods appended to the pinned runtime helper.
import contextlib

OLD_REVISION = 'j65bc789b025'
NEW_REVISION = 'k76cd890c136'
MIGRATION_FILE = 'alembic/versions/k76cd890c136_monthly_commission_statements.py'
NEW_TABLES = frozenset({'commission_statements','commission_statement_lines','commission_statement_cycles'})

def compile_revision_sql(image, file_hash):
    # Run the immutable candidate's actual Alembic upgrade in offline SQL-rendering mode.
    compiler = """from alembic.migration import MigrationContext
from alembic.operations import Operations
from pathlib import Path
from io import StringIO
import hashlib,json,sqlite3
f=Path('/app/backend')/PATH
body=f.read_bytes()
assert hashlib.sha256(body).hexdigest()==PIN
mod={'__name__':'reviewed_revision','__file__':str(f)}
exec(compile(body,str(f),'exec'),mod)
assert mod['revision']==NEW and mod['down_revision']==OLD
buffer=StringIO()
with Operations.context(MigrationContext.configure(url='sqlite://',opts={'as_sql':True,'output_buffer':buffer})):
 mod['upgrade']()
chunk='';statements=[]
for ch in buffer.getvalue():
 chunk+=ch
 if ch==';' and sqlite3.complete_statement(chunk):
  statements.append(chunk.strip());chunk=''
assert not chunk.strip() and statements
print(json.dumps(statements))
"""
    args=['docker','run','--rm','--network=none','--read-only','--cap-drop=ALL','--security-opt=no-new-privileges','--pids-limit=80','--memory=256m','--entrypoint=python',image,'-I','-B','-c']
    prefix='PATH='+repr(MIGRATION_FILE)+';PIN='+repr(file_hash)+';OLD='+repr(OLD_REVISION)+';NEW='+repr(NEW_REVISION)+'\n'
    sql=json.loads(run([*args,prefix+compiler],'MIGRATION_SQL_COMPILATION_FAILED'))
    need(len(sql)<32 and all(isinstance(stmt,str) and len(stmt)<32000 and re.match(r'^CREATE (?:TABLE |(?:UNIQUE )?INDEX )', stmt, re.I) for stmt in sql), 'ONLY_ADDITIVE_ALEMBIC_DDL_ALLOWED')
    return sql

def quoted(name):
    return '"'+name.replace('"','""')+'"'

def structure(db):
    return [list(row) for row in db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name")]

def row_evidence(db, tables):
    # Use stable all-column ordering, including duplicate rows; output only hashes.
    proofs={}
    for name in sorted(tables):
        ident=quoted(name)
        columns=[r[1] for r in db.execute('pragma table_info('+ident+')')]
        projection=','.join(quoted(col) for col in columns)
        order=','.join(str(i+1) for i in range(len(columns)))
        total=0
        h=hashlib.sha256()
        for row in db.execute('SELECT '+projection+' FROM '+ident+' ORDER BY '+order):
            values=[{'blob':v.hex()} if isinstance(v,bytes) else v for v in row]
            serialized=json.dumps(values,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()
            h.update(len(serialized).to_bytes(8,'big'))
            h.update(serialized)
            total+=1
        proofs[name]=[total,h.hexdigest()]
    return digest(proofs)

def verify_copy(dbfile, schema_sha):
    with contextlib.closing(sqlite3.connect('file:'+str(dbfile)+'?mode=ro',uri=True)) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        need(db.execute('PRAGMA quick_check').fetchall()==[('ok',)],'PRIVATE_BACKUP_INTEGRITY_FAILED')
        schema=structure(db)
        need(digest(schema)==schema_sha and db.execute('select version_num from alembic_version').fetchall()==[(OLD_REVISION,)],'BASE_BACKUP_SCHEMA_DRIFT')
        return row_evidence(db,{t[1] for t in schema if t[0]=='table' and t[1]!='alembic_version'})

def migrate_atomic(path, sql, old_schema_sha, backup_rows_sha, exact_after=None):
    # A single SQLite transaction includes the schema, head, and row-preservation checks.
    with contextlib.closing(sqlite3.connect(path,isolation_level=None,timeout=20)) as db:
        db.execute('PRAGMA foreign_keys=on')
        db.execute('BEGIN IMMEDIATE')
        try:
            before=structure(db)
            tables={v[1] for v in before if v[0]=='table' and v[1]!='alembic_version'}
            need(not tables.intersection(NEW_TABLES) and digest(before)==old_schema_sha and db.execute('SELECT version_num FROM alembic_version').fetchall()==[(OLD_REVISION,)],'EXACT_OLD_TRANSACTION_REQUIRED')
            need(row_evidence(db,tables)==backup_rows_sha,'BACKUP_AND_LOCKED_DATABASE_DIFFER')
            for stmt in sql:
                need(re.match(r'^CREATE (?:TABLE |(?:UNIQUE )?INDEX )',stmt,re.I),'ONLY_ADDITIVE_ALEMBIC_DDL_ALLOWED')
                db.execute(stmt)
            after=structure(db)
            delta=[v for v in after if v not in before]
            need(all(v in after for v in before) and {v[1] for v in delta if v[0]=='table'}==NEW_TABLES and all(v[0] in ('table','index') and v[2] in NEW_TABLES for v in delta),'REVIEWED_ADDITIVE_SCHEMA_ONLY')
            expected_indexes={'ix_commission_statement_lines_statement':('statement_id',),'ix_commission_statement_lines_origin':('origin_statement_id',)}
            actual_indexes={r[1]:tuple(col[2] for col in db.execute('pragma index_info('+quoted(r[1])+')')) for r in db.execute('pragma index_list(commission_statement_lines)')}
            need(all(actual_indexes.get(name)==cols for name,cols in expected_indexes.items()),'MISSING_STATEMENT_LINE_INDEX')
            for table, keys in [('commission_statements', {('month','partner_id','currency'),('payout_reference',)}),('commission_statement_lines',{('entry_id',)})]:
                unique={tuple(col[2] for col in db.execute('pragma index_info('+quoted(row[1])+')')) for row in db.execute('pragma index_list('+quoted(table)+')') if row[2]}
                need(keys.issubset(unique),'MISSING_STATEMENT_UNIQUENESS')
            need(all(db.execute('SELECT COUNT(*) FROM '+quoted(name)).fetchone()[0]==0 for name in NEW_TABLES),'MIGRATION_MUST_START_EMPTY')
            need(db.execute('UPDATE alembic_version SET version_num=? WHERE version_num=?',(NEW_REVISION,OLD_REVISION)).rowcount==1,'ALEMBIC_HEAD_UPDATE_FAILED')
            need(row_evidence(db,tables)==backup_rows_sha,'MIGRATION_CHANGED_PRIOR_ROWS')
            result=digest(after)
            need(not exact_after or result==exact_after,'LIVE_SCHEMA_DIFFERS_FROM_REHEARSAL')
            need(db.execute('PRAGMA quick_check').fetchall()==[('ok',)],'SQLITE_MIGRATION_INTEGRITY_FAILED')
            db.commit()
            return result
        except BaseException:
            if db.in_transaction: db.rollback()
            raise

def assert_no_other_docker_writer(database):
    # The original runtime must be stopped before the production backup/migration.
    raw=run(['docker','ps','-q','--no-trunc'],'WRITER_INVENTORY_FAILED').decode().splitlines()
    need(len(raw)<150 and all(re.fullmatch('[a-f0-9]{64}',item) for item in raw),'BOUNDED_WRITER_INVENTORY_REQUIRED')
    if not raw:return
    for container in json.loads(run(['docker','inspect',*raw],'WRITER_MOUNT_SCAN_FAILED')):
        for row in container['Mounts']:
            source=Path(row['Source']).resolve()
            need(not row['RW'] or source!=database and source not in database.parents,'UNEXPECTED_WRITABLE_DATABASE_MOUNT')

def sql_backup_and_apply(rt, source, backup, statements, old_schema_sha, expected_after=None):
    rt.backup_clone(source,backup)
    expected=verify_copy(backup,old_schema_sha)
    after=migrate_atomic(source,statements,old_schema_sha,expected,expected_after)
    return dict(schema_sha256=after,previous_rows_sha256=expected,backup_sha256=file_digest(backup))

def file_digest(path):
    h=hashlib.sha256()
    with path.open('rb') as file:
        for body in iter(lambda:file.read(1024*1024),b''): h.update(body)
    return h.hexdigest()

def cycle_status(database):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    day=datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
    with contextlib.closing(sqlite3.connect('file:'+str(database)+'?mode=ro',uri=True,timeout=5)) as db:
        db.execute('PRAGMA query_only=ON')
        row=db.execute('SELECT business_date,completed_at FROM commission_statement_cycles ORDER BY business_date DESC LIMIT 1').fetchone()
    return {'business_date':day,'last_completed_date':str(row[0]) if row else None,'current_cycle_completed':bool(row and str(row[0])==day and row[1])}

def verify_restricted_routes(ident):
    for path in ('/api/v1/commissions/statements/reminders','/api/v1/commissions/statements?month=2026-10'):
        status=run(['docker','exec',ident,'curl','-q','-sS','--noproxy','*','--max-time','8','--output','/dev/null','--write-out','%{http_code}','http://127.0.0.1:8000'+path],'COMMISSION_ROUTE_PROBE_FAILED',timeout=12)
        need(status.strip() in (b'401',b'403'),'COMMISSION_ROUTE_MUST_REQUIRE_AUTHORIZATION')
